"""Calendrier économique (flux gratuit ForexFactory) filtré 'impact or' + pré-alertes avec scénarios."""
import re
from datetime import datetime, timedelta

from . import config
from .common import (http_get, log, cache_get, cache_set, now_utc, telegram,
                     esc, fmt_paris, already_fired, mark_fired)

GOLD_MOVERS = [
    (r"non-farm|nfp", "Emploi US (NFP) — LE gros mouvement de l'or", 10),
    (r"\bcpi\b", "Inflation (CPI) — gros impact via la Fed", 9),
    (r"fomc|federal funds|rate decision|fed chair|powell", "Fed — décision / discours", 10),
    (r"\bpce\b", "Inflation préférée de la Fed", 8),
    (r"\bppi\b", "Inflation producteurs", 6),
    (r"unemployment|jobless|claims", "Chômage", 6),
    (r"\bgdp\b", "Croissance", 6),
    (r"retail sales", "Consommation", 6),
    (r"ism|pmi", "Activité (ISM/PMI)", 5),
    (r"jolts|adp", "Emploi (indicateur avancé)", 6),
    (r"consumer sentiment|michigan|uom|inflation expectations", "Anticipations d'inflation (Michigan)", 6),
    (r"fomc minutes|meeting minutes", "Minutes de la Fed", 7),
]

# Comment lire chaque type d'annonce pour l'or
# type -> (ce que veut dire "au-dessus de la prévision", effet or si au-dessus)
PLAYBOOK = [
    (r"claims", "claims"),
    (r"unemployment rate", "unemp"),
    (r"cpi|pce|ppi|price index|hourly earnings|inflation expectations|employment cost|wage", "infl"),
    (r"fomc|federal funds|rate decision|fed |powell|minutes|speaks|testif", "fed"),
    (r"non-farm|nfp|adp|jolts|retail sales|gdp|ism|pmi|durable|confidence|sentiment|uom|housing|industrial|payroll|spending", "activ"),
]
READ = {
    "infl":   ("inflation plus forte que prévu", "Fed plus dure → dollar ↑ taux ↑", -1),
    "activ":  ("économie plus forte que prévu", "moins de raisons de baisser les taux → dollar ↑", -1),
    "claims": ("plus d'inscriptions au chômage", "économie qui ralentit → dollar ↓ taux ↓", 1),
    "unemp":  ("chômage plus haut que prévu", "économie qui ralentit → dollar ↓ taux ↓", 1),
}


def kind_of(title):
    t = title.lower()
    for pat, k in PLAYBOOK:
        if re.search(pat, t):
            return k
    return None


def scenarios(e):
    """Lignes 'si chiffre au-dessus / en dessous' pour un événement."""
    k = kind_of(e["title"])
    f = e.get("forecast") or "la prévision"
    if e["country"] == "EUR":
        return ["🇪🇺 Chiffre fort → euro ↑ → DXY ↓ → <b>or ↑</b>",
                "🇪🇺 Chiffre faible → euro ↓ → DXY ↑ → <b>or ↓</b>"]
    if k == "fed":
        return ["🦅 Ton dur (hausses à venir, inflation trop haute) → dollar ↑ taux ↑ → <b>or ↓</b>",
                "🕊 Ton doux (pause, baisse possible, inquiétude emploi) → dollar ↓ → <b>or ↑</b>"]
    if k in READ:
        what, mech, sign = READ[k]
        above = "or ↑" if sign > 0 else "or ↓"
        below = "or ↓" if sign > 0 else "or ↑"
        return [f"🔺 Au-dessus de {esc(f)} ({what}) → {mech} → <b>{above}</b>",
                f"🔻 En dessous de {esc(f)} → effet inverse → <b>{below}</b>"]
    return ["Impact surtout via le dollar : surprise forte pour l'économie US → dollar ↑ → or ↓"]


def _tag(title):
    t = title.lower()
    for pat, label, w in GOLD_MOVERS:
        if re.search(pat, t):
            return label, w
    return "", 0


def fetch_calendar(state, demo=False):
    cached = cache_get(state, "calendar", 3600)
    if cached is not None and not demo:
        return cached
    try:
        raw = _demo_events() if demo else http_get(
            "https://nfs.faireconomy.media/ff_calendar_thisweek.json", timeout=20).json()
        events = []
        for e in raw:
            impact = e.get("impact", "")
            cur = e.get("country", "")
            label, w = _tag(e.get("title", ""))
            keep = (cur == "USD" and impact in ("High", "Medium")) or (impact == "High" and cur in ("CNY", "EUR")) or w >= 8
            if not keep:
                continue
            try:
                dt = datetime.fromisoformat(e["date"])
            except Exception:
                continue
            events.append({
                "title": e.get("title", ""), "country": cur, "impact": impact,
                "date": dt.isoformat(), "forecast": e.get("forecast", ""),
                "previous": e.get("previous", ""), "actual": e.get("actual", ""),
                "gold_label": label, "gold_weight": w if w else (7 if impact == "High" else 4),
            })
        events.sort(key=lambda x: x["date"])
        cache_set(state, "calendar", events)
        return events
    except Exception as ex:
        log("Calendrier:", ex)
        return cached or []


def is_major(e):
    return (e["country"] == "USD" and (e["impact"] == "High" or e["gold_weight"] >= 8)) or \
           (e["country"] == "EUR" and e["impact"] == "High")


def _groups(events):
    """Regroupe les annonces qui tombent à la même heure (ex : CPI + CPI core)."""
    g = {}
    for e in events:
        if is_major(e):
            g.setdefault(e["date"], []).append(e)
    return g


def pre_event_alerts(state, events, ctx, quiet=False):
    """ctx : {'dxy_day': %, 'y_day': pb, 'bias': (score,label), 'atr': $, 'dp': statut pression dollar}"""
    now = now_utc()
    for date, evs in _groups(events).items():
        dt = datetime.fromisoformat(date)
        mins = (dt - now).total_seconds() / 60
        stage = None
        if config.PRE_EVENT_1H and 40 < mins <= 80:
            stage = "1h"
        elif config.PRE_EVENT_15M and 0 < mins <= 25:
            stage = "15m"
        if not stage:
            continue
        key = f"pre{stage}|{date}"
        if already_fired(state, key):
            continue
        mark_fired(state, key)
        if quiet:
            continue
        main = max(evs, key=lambda e: e["gold_weight"])
        flag = "🇺🇸" if main["country"] == "USD" else "🇪🇺"
        names = "\n".join(f"{flag} <b>{esc(e['title'])}</b>  prév. {esc(e['forecast'] or '—')} | préc. {esc(e['previous'] or '—')}"
                          for e in evs)
        if stage == "1h":
            lines = [f"⏳ <b>DANS {int(round(mins))} MIN — {fmt_paris(dt, '%H:%M')}</b>", "", names,
                     f"🥇 {esc(main['gold_label'] or 'Annonce à fort impact')}", "",
                     "<b>Scénarios pour l'or :</b>"] + scenarios(main)
            c = []
            if ctx.get("dxy_day") is not None:
                c.append(f"DXY {ctx['dxy_day']:+.2f}% aujourd'hui")
            if ctx.get("y_day") is not None:
                c.append(f"taux 10 ans {ctx['y_day']:+.0f} pb")
            if ctx.get("bias"):
                c.append(f"biais or {ctx['bias'][0]:+d} ({ctx['bias'][1]})")
            if c:
                lines += ["", "📌 Contexte : " + " · ".join(c)]
            if ctx.get("dp_text"):
                lines.append("💵 " + ctx["dp_text"])
            if ctx.get("atr"):
                lines.append(f"📏 ATR jour de l'or : {ctx['atr']:.0f}$ → attends-toi à des mèches rapides.")
        else:
            lines = [f"⏰ <b>{int(round(mins))} MIN — ZONE DANGEREUSE</b>", "", names, "",
                     "⚠️ Spread qui s'écarte + mèches dans les 2 sens.",
                     "👉 Pas d'entrée 5 min avant / après. Remonte ou sécurise tes stops si tu es en position."]
        telegram("\n".join(lines), state, kind="pre_event")


def week_events_text(events, only_high=True):
    lines = []
    for e in events:
        if only_high and e["impact"] != "High" and e["gold_weight"] < 8:
            continue
        dt = datetime.fromisoformat(e["date"])
        star = "🔥" if e["gold_weight"] >= 8 else "•"
        lines.append(f"{star} {fmt_paris(dt)} — {e['country']} {e['title']}"
                     + (f" (prév. {e['forecast']})" if e["forecast"] else ""))
    return lines


def _demo_events():
    now = now_utc().replace(second=0, microsecond=0)
    base = now.replace(hour=12, minute=30)
    mon = base - timedelta(days=base.weekday())
    ev = [(1, "ISM Manufacturing PMI", "High"), (2, "JOLTS Job Openings", "High"),
          (2, "CPI m/m", "High"), (3, "FOMC Statement", "High"), (3, "Unemployment Claims", "High"),
          (4, "Non-Farm Employment Change", "High"), (4, "Average Hourly Earnings m/m", "High")]
    out = [{"title": t, "country": "USD", "impact": i,
            "date": (mon + timedelta(days=d - 1, hours=(6 if "FOMC" in t else 0))).isoformat(),
            "forecast": "0.3%", "previous": "0.2%"} for d, t, i in ev]
    # événements relatifs à "maintenant" pour tester les alertes
    out += [
        {"title": "Prelim UoM Inflation Expectations", "country": "USD", "impact": "High",
         "date": (now + timedelta(minutes=60)).isoformat(), "forecast": "4.6%", "previous": "4.6%"},
        {"title": "Fed Governor Waller Speaks", "country": "USD", "impact": "High",
         "date": (now + timedelta(minutes=12)).isoformat(), "forecast": "", "previous": ""},
        {"title": "Core PCE Price Index m/m", "country": "USD", "impact": "High",
         "date": (now - timedelta(minutes=35)).isoformat(), "forecast": "0.2%", "previous": "0.3%", "actual": "0.1%"},
        {"title": "Retail Sales m/m", "country": "USD", "impact": "High",
         "date": (now + timedelta(hours=5)).isoformat(), "forecast": "0.4%", "previous": "0.6%"},
    ]
    return out
