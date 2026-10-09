"""Cerveau du radar : niveaux, cassures, corrélations, cycle hebdo, score de biais."""
import math

import numpy as np
import pandas as pd

from . import config
from .common import (telegram, esc, already_fired, mark_fired, now_utc)

JOURS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]


def _f(x, n=2):
    try:
        return round(float(x), n)
    except Exception:
        return None


def _p(key, v):
    n = config.ASSETS.get(key, {}).get("fmt", 2)
    return f"{v:,.{n}f}".replace(",", " ")


# ================================================================== niveaux
def levels(daily):
    hist, cur = daily.iloc[:-1], daily.iloc[-1]
    if len(hist) < 25:
        return {}
    weeks = daily.index.to_period("W")
    cur_w = weeks[-1]
    pw = daily[weeks == cur_w - 1]
    if pw.empty:
        pw = hist.tail(5)
    cw = daily[weeks == cur_w]
    tr = pd.concat([hist.High - hist.Low,
                    (hist.High - hist.Close.shift()).abs(),
                    (hist.Low - hist.Close.shift()).abs()], axis=1).max(axis=1)
    atr = float(tr.tail(14).mean())
    H, L, C = float(pw.High.max()), float(pw.Low.min()), float(pw.Close.iloc[-1])
    P = (H + L + C) / 3
    # range hebdo moyen sur 10 semaines
    wk = hist.groupby(hist.index.to_period("W")).agg({"High": "max", "Low": "min"})
    avg_wr = float((wk.High - wk.Low).tail(10).mean())
    return {
        "date": str(daily.index[-1].date()), "week": str(cur_w),
        "pdh": float(hist.High.iloc[-1]), "pdl": float(hist.Low.iloc[-1]), "pdc": float(hist.Close.iloc[-1]),
        "pwh": H, "pwl": L, "pwc": C,
        "h20": float(hist.High.tail(20).max()), "l20": float(hist.Low.tail(20).min()),
        "h250": float(hist.High.tail(250).max()), "l250": float(hist.Low.tail(250).min()),
        "atr": atr, "week_open": float(cw.Open.iloc[0]),
        "week_high": float(cw.High.max()), "week_low": float(cw.Low.min()),
        "pivot": P, "r1": 2 * P - L, "s1": 2 * P - H, "r2": P + (H - L), "s2": P - (H - L),
        "avg_week_range": avg_wr,
        "sma20": float(daily.Close.tail(20).mean()), "sma50": float(daily.Close.tail(50).mean()),
        "sma200": float(daily.Close.tail(200).mean()) if len(daily) >= 200 else None,
    }


# ================================================================== corrélations
def correlations(mkt):
    if "GOLD" not in mkt:
        return {}
    g = mkt["GOLD"]["daily"].Close.pct_change()
    out = {}
    for k, v in mkt.items():
        if k == "GOLD":
            continue
        s = v["daily"].Close.pct_change() if k not in ("US10Y", "US05Y") else v["daily"].Close.diff()
        df = pd.concat([g, s], axis=1, join="inner").dropna()
        if len(df) < 65:
            continue
        c20 = df.iloc[-20:].corr().iloc[0, 1]
        c60 = df.iloc[-60:].corr().iloc[0, 1]
        c250 = df.iloc[-250:].corr().iloc[0, 1] if len(df) >= 250 else c60
        roll = df.iloc[:, 0].rolling(20).corr(df.iloc[:, 1]).dropna().tail(120)
        out[k] = {"c20": _f(c20), "c60": _f(c60), "c250": _f(c250),
                  "hist": [_f(x) for x in roll.values]}
    return out


def _implication(key, direction_up, corr):
    """Effet probable sur l'or d'un mouvement de l'actif."""
    rel = config.ASSETS[key]["gold_rel"]
    c60 = (corr or {}).get("c60") or 0
    if rel == 0:
        rel = 1 if c60 > 0.3 else -1 if c60 < -0.3 else 0
    if rel == 0:
        return 0, "⚪ neutre pour l'or"
    eff = rel if direction_up else -rel
    return eff, ("🟢 haussier pour l'or" if eff > 0 else "🔴 baissier pour l'or")


# ================================================================== tableau actifs
def assets_table(mkt, corr):
    rows = []
    for k, v in mkt.items():
        d = v["daily"]
        live = v["live"]
        lv = levels(d)
        prev = float(d.Close.iloc[-2])
        p5 = float(d.Close.iloc[-6]) if len(d) > 6 else prev
        is_rate = k in ("US10Y", "US05Y")
        chg1 = (live - prev) if is_rate else (live / prev - 1) * 100
        chg5 = (live - p5) if is_rate else (live / p5 - 1) * 100
        pos = []
        if lv:
            if live > lv["pwh"]: pos.append("au-dessus PH sem. passée")
            if live < lv["pwl"]: pos.append("sous PB sem. passée")
            if live >= lv["h20"]: pos.append("plus haut 20j")
            if live <= lv["l20"]: pos.append("plus bas 20j")
            if live >= lv["h250"]: pos.append("PLUS HAUT 1 AN")
            if live <= lv["l250"]: pos.append("PLUS BAS 1 AN")
        _, impl = _implication(k, chg1 > 0, corr.get(k)) if k != "GOLD" else (0, "")
        rows.append({
            "key": k, "name": config.ASSETS[k]["name"], "price": _f(live, 5),
            "chg1": _f(chg1, 3), "chg5": _f(chg5, 3), "is_rate": is_rate,
            "corr": corr.get(k, {}), "gold_rel": config.ASSETS[k]["gold_rel"],
            "implication": impl, "flags": pos,
            "levels": {kk: _f(vv, 5) for kk, vv in lv.items() if isinstance(vv, (int, float))},
            "spark": [_f(x, 5) for x in d.Close.tail(60).values],
        })
    return rows


# ================================================================== cassures
LEVELS_CHECK = [
    # (nom, clé haut, clé bas, importance, période de dédoublonnage)
    ("de la VEILLE", "pdh", "pdl", "moyenne", "day"),
    ("de la SEMAINE PASSÉE", "pwh", "pwl", "forte", "week"),
    ("sur 20 JOURS", "h20", "l20", "forte", "week"),
    ("sur 1 AN", "h250", "l250", "MAJEURE", "week"),
]


def breakout_alerts(state, mkt, corr, demo=False, bstats=None):
    fired = []
    for k, v in mkt.items():
        d, live = v["daily"], v["live"]
        lv = levels(d)
        if not lv:
            continue
        for name, hk, lk, imp, per in LEVELS_CHECK:
            if hk == "pdh" and k not in config.ALERT_PREV_DAY_ASSETS and k != "GOLD":
                continue
            period_key = lv["date"] if per == "day" else lv["week"]
            for up, lvl in ((True, lv[hk]), (False, lv[lk])):
                broke = live > lvl if up else live < lvl
                if not broke:
                    continue
                key = f"brk|{k}|{hk}|{'up' if up else 'dn'}|{period_key}"
                if already_fired(state, key):
                    continue
                mark_fired(state, key)
                if demo:
                    continue
                eff, impl = _implication(k, up, corr.get(k)) if k != "GOLD" else (0, "")
                c = corr.get(k, {})
                icon = "🚀" if up else "💥"
                txt = (f"{icon} <b>CASSURE {imp.upper()}</b> {'⬆️' if up else '⬇️'}\n\n"
                       f"<b>{esc(config.ASSETS[k]['name'])}</b> casse le {'plus haut' if up else 'plus bas'} {name}"
                       f"\nNiveau : {_p(k, lvl)} → prix : <b>{_p(k, live)}</b>")
                if k == "GOLD":
                    txt += f"\nATR jour : {lv['atr']:.1f}$ | Pivot hebdo : {lv['pivot']:.1f}"
                    bs = (bstats or {}).get(hk if up else lk)
                    if bs:
                        txt += (f"\n\n📊 <b>Historique</b> : quand l'or casse ce niveau, il CLÔTURE "
                                f"{'au-dessus' if up else 'en dessous'} dans <b>{bs['hold_pct']:.0f}%</b> des cas "
                                f"(extension médiane {bs['ext_med']:.0f}$, {bs['n']} cas)."
                                + ("\n⚠️ Moins d'1 chance sur 2 : attention au faux break." if bs['hold_pct'] < 50 else ""))
                else:
                    txt += f"\n\n🥇 Lecture or : <b>{impl}</b>"
                    if c:
                        txt += f"\nCorrélation avec l'or : 20j {c.get('c20')} | 60j {c.get('c60')}"
                telegram(txt, state, kind="breakout")
                fired.append(key)
        # mouvement anormal du jour
        prev = float(d.Close.iloc[-2])
        mv = live - prev
        if lv["atr"] > 0 and abs(mv) > config.BIG_MOVE_ATR * lv["atr"]:
            key = f"big|{k}|{lv['date']}"
            if not already_fired(state, key):
                mark_fired(state, key)
                if not demo:
                    eff, impl = _implication(k, mv > 0, corr.get(k)) if k != "GOLD" else (0, "")
                    telegram(f"🌋 <b>MOUVEMENT ANORMAL</b> — {esc(config.ASSETS[k]['name'])}\n"
                             f"{'+' if mv > 0 else ''}{_p(k, mv)} aujourd'hui = {abs(mv) / lv['atr']:.1f}× l'ATR"
                             + (f"\n🥇 {impl}" if impl else ""), state, kind="big_move")
    return fired


def correlation_alerts(state, corr, demo=False):
    for k, c in corr.items():
        c20, c60 = c.get("c20"), c.get("c60")
        if c20 is None or c60 is None:
            continue
        if abs(c60) >= config.CORR_BREAK_MIN and abs(c20) >= 0.2 and np.sign(c20) != np.sign(c60):
            week = str(pd.Timestamp.utcnow().to_period("W"))
            key = f"corr|{k}|{week}"
            if already_fired(state, key):
                continue
            mark_fired(state, key)
            if not demo:
                telegram(f"🔀 <b>CASSURE DE CORRÉLATION</b> — {esc(config.ASSETS[k]['name'])}\n"
                         f"Corrélation avec l'or : 60j = {c60} → 20j = {c20}\n"
                         f"Le lien habituel est cassé : souvent un changement de régime "
                         f"(un nouveau moteur domine l'or). À surveiller.", state, kind="corr")


# ================================================================== cycle hebdo
def weekly_cycle(gold_daily, live):
    d = gold_daily.copy()
    d["wd"] = d.index.weekday
    d["wk"] = d.index.to_period("W")
    cur_wk = d["wk"].iloc[-1]
    rows = []
    for wk, g in d.groupby("wk"):
        if wk == cur_wk:
            continue
        a, b = g[g.wd <= 2], g[g.wd >= 3]
        if a.empty or b.empty:
            continue
        o, mid, c = a.Open.iloc[0], a.Close.iloc[-1], b.Close.iloc[-1]
        A, B = mid - o, c - mid
        rows.append({"A": A, "B": B, "rev": np.sign(A) != np.sign(B) and B != 0,
                     "hi_day": int(g.High.idxmax().weekday()), "lo_day": int(g.Low.idxmin().weekday()),
                     "ret": (-B / A) if A != 0 else 0, "range": g.High.max() - g.Low.min()})
    df = pd.DataFrame(rows)
    stats = {}
    if len(df) > 20:
        med = df.A.abs().median()
        strong = df[df.A.abs() >= med]
        up, dn = df[df.A > 0], df[df.A < 0]
        revs = df[df.rev]
        stats = {
            "weeks": int(len(df)),
            "pct_rev": round(df.rev.mean() * 100, 1),
            "pct_rev_strong": round(strong.rev.mean() * 100, 1),
            "pct_rev_after_up": round(up.rev.mean() * 100, 1) if len(up) else None,
            "pct_rev_after_down": round(dn.rev.mean() * 100, 1) if len(dn) else None,
            "median_A": round(float(med), 2),
            "avg_retrace_pct": round(float(revs.ret.median() * 100), 1) if len(revs) else None,
            "hi_day_pct": [round((df.hi_day == i).mean() * 100, 1) for i in range(5)],
            "lo_day_pct": [round((df.lo_day == i).mean() * 100, 1) for i in range(5)],
            "last_weeks": [{"A": round(float(r.A), 1), "B": round(float(r.B), 1), "rev": bool(r.rev)}
                           for r in df.tail(12).itertuples()],
        }
    # semaine en cours
    g = d[d.wk == cur_wk]
    a = g[g.wd <= 2]
    today_wd = int(g.wd.iloc[-1])
    cur = {"today": JOURS[today_wd], "week_open": _f(g.Open.iloc[0])}
    if today_wd <= 2:
        cur.update(phase=1, A=_f(live - g.Open.iloc[0]),
                   texte=f"Phase 1 (lun→mer) en cours : {live - g.Open.iloc[0]:+.1f}$ depuis l'ouverture de la semaine")
    elif not a.empty:
        A = float(a.Close.iloc[-1] - a.Open.iloc[0])
        mid = float(a.Close.iloc[-1])
        B = live - mid
        retr = (-B / A * 100) if A else 0
        weak = bool(stats) and abs(A) < 0.4 * stats["median_A"]
        status = ("lun→mer sans vraie direction (pattern non applicable)" if weak else
                  "inversion en cours ✅" if np.sign(B) != np.sign(A) and abs(B) >= 0.382 * abs(A)
                  else "le pattern ÉCHOUE (continuation) ⚠️" if np.sign(B) == np.sign(A) and abs(B) >= 0.5 * abs(A)
                  else "en attente")
        cur.update(phase=2, A=_f(A), B=_f(B), mid=_f(mid), retrace_pct=_f(retr, 1), status=status,
                   targets={"38.2%": _f(mid - 0.382 * A), "50%": _f(mid - 0.5 * A), "61.8%": _f(mid - 0.618 * A)},
                   texte=f"Phase 2 (jeu→ven) : lun→mer = {A:+.1f}$, depuis mercredi {B:+.1f}$ → {status}")
    return {"stats": stats, "current": cur}


def cycle_alerts(state, cycle, demo=False):
    cur, st = cycle.get("current", {}), cycle.get("stats", {})
    if not cur or not st:
        return
    now = now_utc()
    week = str(pd.Timestamp(now).tz_localize(None).to_period("W"))
    # Fin de phase 1 : mercredi soir (après 20h UTC) ou jeudi/vendredi si pas encore envoyé
    if ((now.weekday() == 2 and now.hour >= 20) or now.weekday() in (3, 4)) and cur.get("phase") == 2:
        key = f"cyc_end|{week}"
        if not already_fired(state, key):
            mark_fired(state, key)
            A = cur["A"]
            strong = abs(A) >= st["median_A"]
            p = st["pct_rev_after_up"] if A > 0 else st["pct_rev_after_down"]
            t = cur["targets"]
            if not demo:
                telegram(
                    f"🔄 <b>CYCLE HEBDO — FIN DE PHASE 1</b>\n\n"
                    f"Lun→Mer : <b>{A:+.1f}$</b> ({'mouvement FORT' if strong else 'mouvement faible'})\n"
                    f"Historique : inversion jeu→ven dans <b>{p}%</b> des semaines "
                    f"{'haussières' if A > 0 else 'baissières'} "
                    f"({st['pct_rev_strong']}% quand le mouvement est fort)\n"
                    f"Retracement médian quand ça inverse : {st['avg_retrace_pct']}%\n\n"
                    f"🎯 Zones de retour : 38.2% {t['38.2%']} | 50% {t['50%']} | 61.8% {t['61.8%']}\n"
                    + ("⚪ Lun→mer trop plat : pas de biais d'inversion exploitable cette semaine."
                       if abs(A) < 0.4 * st["median_A"] else
                       f"{'📉 Biais jeu→ven : RETOUR À LA BAISSE' if A > 0 else '📈 Biais jeu→ven : RETOUR À LA HAUSSE'}"
                       f" — à confirmer avec le biais macro."), state, kind="cycle")
    if cur.get("phase") == 2:
        if cur.get("status", "").startswith("inversion"):
            key = f"cyc_rev|{week}"
            if not already_fired(state, key):
                mark_fired(state, key)
                if not demo:
                    telegram(f"✅ <b>INVERSION HEBDO CONFIRMÉE</b>\n{cur['texte']}\n"
                             f"Retracement actuel : {cur['retrace_pct']}% du mouvement lun→mer", state, kind="cycle")
        elif "ÉCHOUE" in cur.get("status", ""):
            key = f"cyc_fail|{week}"
            if not already_fired(state, key):
                mark_fired(state, key)
                if not demo:
                    telegram(f"⚠️ <b>CYCLE HEBDO : PAS D'INVERSION CETTE SEMAINE</b>\n{cur['texte']}\n"
                             f"Le marché continue dans le sens lun→mer — ne pas forcer le contre-trend.",
                             state, kind="cycle")


# ================================================================== score de biais
def _t(x):
    return math.tanh(x)


def bias_score(mkt, fred, cot, news_sent, gold_lv):
    comps = []

    def add(name, val, w, detail):
        if val is None or (isinstance(val, float) and math.isnan(val)):
            return
        comps.append({"name": name, "value": round(max(-1, min(1, val)), 3), "weight": w, "detail": detail})

    def chg5(k, pct=True):
        if k not in mkt:
            return None
        d = mkt[k]["daily"].Close
        live = mkt[k]["live"]
        p = float(d.iloc[-6])
        return (live / p - 1) * 100 if pct else live - p

    c = chg5("DXY")
    if c is not None:
        add("Dollar (DXY 5j)", -_t(c / 1.0), 0.18, f"{c:+.2f}% sur 5 jours")
    c = chg5("US10Y", pct=False)
    if c is not None:
        add("Taux US 10 ans (5j)", -_t(c / 0.15), 0.12, f"{c * 100:+.0f} pb sur 5 jours")
    if "REAL10Y" in fred:
        r = fred["REAL10Y"]
        add("Taux réels 10 ans (20j)", -_t(r["chg20"] / 0.2), 0.15, f"{r['last']:.2f}% ({r['chg20']:+.2f} sur 20j)")
    if "US2Y" in fred and "FEDFUNDS" in fred:
        sp = fred["US2Y"]["last"] - fred["FEDFUNDS"]["last"]
        add("Fed (2 ans vs taux Fed)", _t(-sp / 0.5), 0.10,
            f"2 ans {fred['US2Y']['last']:.2f}% vs Fed {fred['FEDFUNDS']['last']:.2f}% → "
            + ("baisses de taux anticipées" if sp < -0.15 else "hausses anticipées" if sp > 0.15 else "statu quo"))
    if gold_lv:
        p = mkt["GOLD"]["live"]
        add("Momentum or (vs MM50)", _t((p / gold_lv["sma50"] - 1) / 0.03), 0.15,
            f"prix {p:.0f} vs MM20 {gold_lv['sma20']:.0f} / MM50 {gold_lv['sma50']:.0f}")
    s, n = news_sent
    if n:
        add("Sentiment news 24h", s * 1.5, 0.20, f"{n} news notées, moyenne {s:+.2f}")
    if "VIX" in mkt:
        v = mkt["VIX"]["live"]
        add("Peur marchés (VIX)", _t((v - 18) / 8) * 0.7, 0.05, f"VIX {v:.1f}")
    if cot:
        add("Positionnement COT (contrarian)", -(cot["percentile_3y"] - 50) / 50 * 0.8, 0.05,
            f"net spéculateurs {cot['net']:,} — percentile 3 ans {cot['percentile_3y']}%".replace(",", " "))
    if not comps:
        return {"score": 0, "label": "Données insuffisantes", "components": []}
    tw = sum(c["weight"] for c in comps)
    score = round(100 * sum(c["value"] * c["weight"] for c in comps) / tw)
    for c in comps:
        c["contrib"] = round(100 * c["value"] * c["weight"] / tw, 1)
    label = ("FORTEMENT HAUSSIER" if score >= 40 else "Haussier" if score >= 15 else
             "Neutre" if score > -15 else "Baissier" if score > -40 else "FORTEMENT BAISSIER")
    return {"score": score, "label": label, "components": sorted(comps, key=lambda c: -abs(c["contrib"]))}


def bias_alert(state, bias, demo=False):
    """Alerte quand le biais change de camp."""
    prev = state.get("last_bias_label")
    lab = bias["label"]
    state["last_bias_label"] = lab
    if prev and prev != lab and not demo:
        main = ", ".join(f"{c['name']} ({c['contrib']:+.0f})" for c in bias["components"][:3])
        telegram(f"🧭 <b>CHANGEMENT DE BIAIS OR</b> : {esc(prev)} → <b>{esc(lab)}</b> (score {bias['score']:+d})\n"
                 f"Moteurs principaux : {esc(main)}", state, kind="bias")
