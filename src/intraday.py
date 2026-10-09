"""Alertes intraday : pression sur le dollar, news en rafale, récap après annonce, sessions."""
import re
from datetime import datetime, timedelta

import pandas as pd

from . import config
from .calendar_eco import is_major
from .common import (telegram, esc, already_fired, mark_fired, now_utc, PARIS)


# ===================================================================== helpers
def intra(mkt, key):
    v = mkt.get(key) or {}
    df = v.get("intra")
    if df is None or df.empty:
        return None
    return df


def is_fresh(df, max_min=30):
    if df is None or df.empty:
        return False
    return (pd.Timestamp(now_utc()) - df.index[-1]).total_seconds() / 60 <= max_min


def change_since(df, t_ref, pct=True, col="Close"):
    """Variation entre la dernière bougie <= t_ref et la dernière bougie."""
    if df is None or df.empty:
        return None
    past = df[df.index <= pd.Timestamp(t_ref)]
    if past.empty:
        return None
    a, b = float(past[col].iloc[-1]), float(df[col].iloc[-1])
    return (b / a - 1) * 100 if pct else b - a


def change_over(df, minutes, pct=True):
    if df is None or df.empty:
        return None
    return change_since(df, df.index[-1] - pd.Timedelta(minutes=minutes), pct)


def paris_midnight():
    p = now_utc().astimezone(PARIS)
    return p.replace(hour=0, minute=0, second=0, microsecond=0)


def session(df, start, end=None):
    """Open/high/low/last d'une fenêtre (heures Paris tz-aware)."""
    if df is None or df.empty:
        return None
    x = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        x = x[x.index < pd.Timestamp(end)]
    if x.empty:
        return None
    o, h, l, c = float(x.Open.iloc[0]), float(x.High.max()), float(x.Low.min()), float(x.Close.iloc[-1])
    return {"open": o, "high": h, "low": l, "last": c, "chg": c - o, "range": h - l,
            "t_high": x.High.idxmax(), "t_low": x.Low.idxmin()}


def day_changes(mkt):
    """Variation depuis minuit Paris pour les actifs clés (pour contextes)."""
    out = {}
    mid = paris_midnight()
    for k in ("GOLD", "DXY", "US10Y", "OIL", "EURUSD", "SPX", "SILVER"):
        df = intra(mkt, k)
        if df is None:
            continue
        out[k] = change_since(df, mid, pct=(k != "US10Y"))
    return out


# ===================================================================== pression dollar
LABELS = {"DXY": "DXY", "US10Y": "Taux US 10 ans", "OIL": "Pétrole", "EURUSD": "EUR/USD"}


def dollar_pressure(mkt, news, hist):
    th, win = config.DP_TH, config.DP_WINDOW_MIN
    sigs, down, up, fresh = [], 0, 0, True
    for k in ("DXY", "US10Y", "OIL", "EURUSD"):
        df = intra(mkt, k)
        if df is None:
            continue
        fresh = fresh and is_fresh(df, 40)
        ch = change_over(df, win, pct=(k != "US10Y"))
        if ch is None:
            continue
        # direction pour le DOLLAR : -1 = pousse le dollar à la baisse
        if k == "EURUSD":
            d = -1 if ch > th[k] else 1 if ch < -th[k] else 0
        else:
            d = -1 if ch < -th[k] else 1 if ch > th[k] else 0
        down += d == -1
        up += d == 1
        txt = f"{ch * 100:+.1f} pb" if k == "US10Y" else f"{ch:+.2f}%"
        sigs.append({"key": k, "name": LABELS[k], "chg": round(ch, 4), "txt": txt, "dir": d})
    # news de la dernière heure liées au dollar
    lim = now_utc() - timedelta(minutes=win)
    rel = [n for n in news if datetime.fromisoformat(n["published"]) >= lim and n.get("impact")
           and n.get("cat") in ("fed", "dollar", "taux", "inflation", "emploi", "commerce", "politique US")]
    news_dir, news_avg = 0, 0.0
    if rel:
        news_avg = sum(n["impact"] for n in rel) / len(rel)
    if len(rel) >= 2:
        news_dir = -1 if news_avg >= 3 else 1 if news_avg <= -3 else 0   # impact or + ≈ dollar -
    status = "neutre"
    if down >= config.DP_MIN_SIGNALS or (down >= 2 and news_dir == -1):
        status = "down"
    elif up >= config.DP_MIN_SIGNALS or (up >= 2 and news_dir == 1):
        status = "up"
    prob = None
    n_mkt = down if status == "down" else up if status == "up" else 0
    if hist and status in ("down", "up") and n_mkt >= 3:
        h = hist.get(status) or {}
        k = str(min(n_mkt, 4)) if h.get(str(min(n_mkt, 4))) else "3"
        prob = h.get(k)
        if prob:
            prob = {**prob, "cond": "4/4 signaux" if k == "4" else "au moins 3 signaux sur 4"}
    return {"status": status, "down": int(down), "up": int(up), "signals": sigs, "fresh": bool(fresh and sigs),
            "news": {"count": len(rel), "avg": round(news_avg, 1), "dir": news_dir,
                     "top": [n["title"] for n in sorted(rel, key=lambda n: -abs(n["impact"]))[:2]]},
            "prob": prob, "hist_base": (hist or {}).get("base_gold_up"), "horizon_h": (hist or {}).get("horizon_h"),
            "window_min": win}


def dp_short_text(dp):
    if not dp or dp["status"] == "neutre":
        return "Dollar : pas de pression nette sur la dernière heure"
    s = "Dollar SOUS PRESSION ↓ (haussier or)" if dp["status"] == "down" else "Dollar EN FORCE ↑ (baissier or)"
    return f"{s} — {max(dp['down'], dp['up'])}/4 signaux"


def dollar_pressure_alert(state, dp, quiet=False):
    st = dp["status"]
    if st == "neutre" or not dp["fresh"]:
        return
    last = state.get("dp_last") or {}
    if last.get("status") == st:
        age_h = (now_utc() - datetime.fromisoformat(last["ts"])).total_seconds() / 3600
        if age_h < config.DP_COOLDOWN_H:
            return
    state["dp_last"] = {"status": st, "ts": now_utc().isoformat()}
    if quiet:
        return
    down = st == "down"
    head = ("⚠️ <b>DOLLAR SOUS PRESSION — risque de baisse</b>\n🥇 Lecture : <b>HAUSSIER pour l'or</b>" if down else
            "⚠️ <b>DOLLAR EN FORCE — risque de hausse</b>\n🥇 Lecture : <b>BAISSIER pour l'or</b>")
    lines = [head, "", f"<b>Sur les {dp['window_min']} dernières minutes :</b>"]
    for s in dp["signals"]:
        ok = (s["dir"] == -1) if down else (s["dir"] == 1)
        lines.append(f"{'✅' if ok else '▫️'} {esc(s['name'])} {s['txt']}")
    if dp["news"]["count"]:
        lines.append(f"{'✅' if dp['news']['dir'] == (-1 if down else 1) else '▫️'} "
                     f"News dollar/Fed : {dp['news']['count']} (impact moyen or {dp['news']['avg']:+.1f})")
        for t in dp["news"]["top"]:
            lines.append(f"   • {esc(t)}")
    p = dp.get("prob")
    if p:
        lines += ["", f"📊 <b>Historique (≈2 ans en H1)</b> : quand on a eu {p['cond']} dans ce sens,",
                  f"le dollar a continué {'à baisser' if down else 'à monter'} dans <b>{p['p_dxy']:.0f}%</b> des cas sur {dp['horizon_h']}h,",
                  f"et l'or a {'monté' if down else 'baissé'} dans <b>{p['p_gold']:.0f}%</b> des cas "
                  f"(moyenne {p['gold_avg']:+.1f}$, sur {p['n']} cas)."]
        if dp.get("hist_base") is not None:
            lines.append(f"<i>Pour comparer : l'or monte {dp['hist_base']:.0f}% du temps sur {dp['horizon_h']}h en général.</i>")
        if max(p["p_dxy"], p["p_gold"]) < 55:
            lines.append("⚠️ Avantage statistique faible : à confirmer avec ta technique.")
    else:
        lines += ["", "<i>Pas assez d'historique pour chiffrer cette configuration : à confirmer avec ta technique.</i>"]
    telegram("\n".join(lines), state, kind="dollar_pressure")


# ===================================================================== news en rafale
def news_burst(state, news, quiet=False):
    now = now_utc()
    win = config.BURST_WINDOW_MIN
    lim_recent = now - timedelta(minutes=win)
    lim_base = now - timedelta(hours=24)
    found = []
    for topic, pat in config.BURST_TOPICS.items():
        rx = re.compile(pat, re.I)
        recent, base = [], 0
        for n in news:
            t = datetime.fromisoformat(n["published"])
            if t < lim_base or not rx.search(n["title"]):
                continue
            if t >= lim_recent:
                recent.append(n)
            else:
                base += 1
        base_rate = base / max(1, (24 * 60 - win) / win)
        if len(recent) >= config.BURST_MIN_COUNT and len(recent) >= config.BURST_FACTOR * max(base_rate, 1):
            found.append((topic, recent, base_rate))
    for topic, recent, base_rate in found:
        bucket = int(now.timestamp() // (3 * 3600))
        key = f"burst|{topic}|{bucket}"
        if already_fired(state, key):
            continue
        mark_fired(state, key)
        if quiet:
            continue
        imp = [n["impact"] for n in recent if n.get("impact")]
        avg = sum(imp) / len(imp) if imp else 0
        lect = ("🟢 plutôt HAUSSIER pour l'or" if avg >= 2 else "🔴 plutôt BAISSIER pour l'or" if avg <= -2
                else "⚪ direction pas encore claire")
        top = sorted(recent, key=lambda n: (-abs(n.get("impact", 0)), n["published"]))[:4]
        lines = [f"🔥 <b>NEWS EN RAFALE : {esc(topic).upper()}</b>",
                 f"{len(recent)} articles en {win} min (normale ≈ {base_rate:.1f}) → un sujet s'emballe", "",
                 f"🥇 Impact moyen : {avg:+.1f}/10 → {lect}", ""]
        for n in top:
            lines.append(f"• ({n.get('impact', 0):+d}) {esc(n['title'])} — <i>{esc(n['source'])}</i>")
        lines += ["", "👀 Surveille le DXY et l'or : les gros mouvements suivent souvent ce genre de rafale."]
        telegram("\n".join(lines), state, kind="news_burst")


# ===================================================================== récap après annonce
def post_event_recaps(state, events, mkt, gold_atr, quiet=False):
    now = now_utc()
    g, dxy, y = intra(mkt, "GOLD"), intra(mkt, "DXY"), intra(mkt, "US10Y")
    if g is None:
        return
    groups = {}
    for e in events:
        if is_major(e):
            groups.setdefault(e["date"], []).append(e)
    for date, evs in groups.items():
        dt = datetime.fromisoformat(date)
        mins = (now - dt).total_seconds() / 60
        if not (config.POST_EVENT_DELAY_MIN - 8 <= mins <= config.POST_EVENT_DELAY_MIN + 45):
            continue
        key = f"post|{date}"
        if already_fired(state, key):
            continue
        mark_fired(state, key)
        if quiet:
            continue
        t0 = pd.Timestamp(dt) - pd.Timedelta(minutes=1)
        after = g[g.index >= t0]
        before = g[g.index <= t0]
        if after.empty or before.empty:
            continue
        p0, last = float(before.Close.iloc[-1]), float(g.Close.iloc[-1])
        hi, lo = float(after.High.max()), float(after.Low.min())
        mv = last - p0
        ext = (hi - p0) if mv >= 0 else (p0 - lo)
        d_dxy = change_since(dxy, t0) if dxy is not None else None
        d_y = change_since(y, t0, pct=False) if y is not None else None
        lines = [f"📊 <b>RÉCAP {int(mins)} MIN APRÈS L'ANNONCE</b>", ""]
        for e in evs:
            act = e.get("actual")
            lines.append(f"🇺🇸 <b>{esc(e['title'])}</b> : " +
                         (f"<b>{esc(act)}</b> vs prév. {esc(e['forecast'] or '—')}" if act else
                          f"prév. {esc(e['forecast'] or '—')} (chiffre réel : voir ton calendrier)"))
        lines += ["", "<b>Réaction :</b>"]
        if d_dxy is not None:
            lines.append(f"DXY {d_dxy:+.2f}%")
        if d_y is not None:
            lines.append(f"Taux 10 ans {d_y * 100:+.1f} pb")
        lines.append(f"Or {mv:+.1f}$ (extrême {'+' if mv >= 0 else '-'}{ext:.1f}$, range {hi - lo:.1f}$)")
        # lecture
        read = None
        if d_dxy is not None and d_y is not None:
            if d_dxy > 0.08 and d_y > 0.015:
                read = "🦅 Marché qui lit l'annonce comme DURE (dollar + taux ↑) → pression baissière sur l'or"
            elif d_dxy < -0.08 and d_y < -0.015:
                read = "🕊 Marché qui lit l'annonce comme DOUCE (dollar + taux ↓) → soutien pour l'or"
            else:
                read = "⚪ Réaction mitigée : pas de lecture claire du marché"
        if read:
            lines += ["", read]
        if ext > 0:
            kept = abs(mv) / ext if ext else 0
            if ext >= 0.25 * (gold_atr or 1):
                lines.append("✅ Le mouvement TIENT (garde l'essentiel de son extension)" if kept >= 0.6 else
                             "↩️ Le mouvement S'ESSOUFFLE (plus de la moitié reprise)" if kept < 0.5 else
                             "➖ Mouvement en partie repris")
            else:
                lines.append("😴 Petite réaction (moins de 25% de l'ATR) : l'annonce n'a pas changé la donne")
        telegram("\n".join(lines), state, kind="post_event")
