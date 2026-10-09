"""Probabilités RÉELLES calculées sur l'historique (pas de pourcentages inventés).

- daily_stats      : comportement de l'or par jour de la semaine et après une veille forte (≈6 ans)
- breakout_stats   : ce qui se passe quand l'or casse le plus haut / bas de la veille ou des 20 jours
- hourly_stats     : heure habituelle du plus haut / plus bas du jour + stats « pression dollar » (≈2 ans en H1)
"""
import numpy as np
import pandas as pd

from . import config, market
from .common import log, cache_get, cache_set, PARIS

JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]


def _r(x, n=1):
    try:
        if x is None or (isinstance(x, float) and np.isnan(x)):
            return None
        return round(float(x), n)
    except Exception:
        return None


# ===================================================================== journalier
def daily_stats(gold_daily):
    d = gold_daily[gold_daily.index.weekday < 5].iloc[:-1]      # on exclut la bougie en cours
    ret = d.Close.pct_change() * 100
    df = pd.DataFrame({"ret": ret, "rng": d.High - d.Low, "prev": ret.shift(1),
                       "wd": d.index.weekday}).dropna()
    if len(df) < 100:
        return {}
    ly = df.tail(260)
    med_all = float(ly.rng.median())
    by_wd = {}
    for wd in range(5):
        x, xy = df[df.wd == wd], ly[ly.wd == wd]
        by_wd[str(wd)] = {
            "n": int(len(x)), "pct_up": _r((x.ret > 0).mean() * 100),
            "avg_ret": _r(x.ret.mean(), 3),
            "med_range": _r(xy.rng.median()),
            "range_factor": _r(xy.rng.median() / med_all, 2) if len(xy) > 10 else 1.0,
        }
    after = {}
    for name, cond in (("forte_hausse", df.prev > 1.0), ("forte_baisse", df.prev < -1.0),
                       ("normale", df.prev.abs() <= 1.0)):
        x = df[cond]
        after[name] = {"n": int(len(x)), "pct_up": _r((x.ret > 0).mean() * 100), "avg_ret": _r(x.ret.mean(), 3)}
    return {"by_weekday": by_wd, "after": after, "years": _r(len(df) / 252, 1),
            "pct_up_all": _r((df.ret > 0).mean() * 100)}


def prev_day_class(gold_daily):
    """Classe de la dernière journée COMPLÈTE : forte_hausse / forte_baisse / normale."""
    d = gold_daily
    r = (d.Close.iloc[-2] / d.Close.iloc[-3] - 1) * 100
    return ("forte_hausse" if r > 1 else "forte_baisse" if r < -1 else "normale"), round(float(r), 2)


# ===================================================================== cassures
def breakout_stats(gold_daily):
    d = gold_daily.iloc[:-1]
    out = {}
    tests = {
        "pdh": (d.High.shift(1), True), "pdl": (d.Low.shift(1), False),
        "h20": (d.High.shift(1).rolling(20).max(), True), "l20": (d.Low.shift(1).rolling(20).min(), False),
    }
    for key, (lvl, up) in tests.items():
        m = (d.High > lvl) if up else (d.Low < lvl)
        m = m & lvl.notna()
        x, L = d[m], lvl[m]
        if len(x) < 30:
            continue
        hold = (x.Close > L) if up else (x.Close < L)
        ext = (x.High - L) if up else (L - x.Low)
        out[key] = {"n": int(len(x)), "hold_pct": _r(hold.mean() * 100), "ext_med": _r(ext.median())}
    return out


# ===================================================================== horaire (cache 20h)
def hourly_stats(state, demo=False):
    cached = cache_get(state, "hourly_stats", 20 * 3600)
    if cached and not demo and ((cached.get("dollar") or {}).get("n_hours") or 0) > 200:
        return cached
    data = market.fetch_hourly(demo)
    out = {}
    try:
        if "GOLD" in data:
            out["gold_hours"] = _gold_hours(data["GOLD"])
    except Exception as e:
        log("Stats heures or:", e)
    try:
        out["dollar"] = _dollar_hist(data)
    except Exception as e:
        log("Stats pression dollar:", e)
    if out:
        cache_set(state, "hourly_stats", out)
        return out
    return cached or {}


def _gold_hours(g):
    g = g.copy()
    g.index = g.index.tz_convert(PARIS)
    g["date"] = g.index.date
    res = {}
    rows = []
    for dt, x in g.groupby("date"):
        if len(x) < 16:
            continue
        rows.append((x.index[0].weekday(), x.High.idxmax().hour, x.Low.idxmin().hour))
    df = pd.DataFrame(rows, columns=["wd", "hi", "lo"])
    for wd in range(5):
        x = df[df.wd == wd]
        if len(x) < 20:
            continue

        def top(col):
            vc = x[col].value_counts(normalize=True).head(3)
            return [[int(h), _r(p * 100)] for h, p in vc.items()]
        res[str(wd)] = {"n": int(len(x)), "high": top("hi"), "low": top("lo")}
    return res


def _dollar_hist(data):
    need = ("DXY", "US10Y", "OIL", "EURUSD", "GOLD")
    if not all(k in data for k in need):
        return {}
    ser = {}
    for k in need:
        x = data[k]["Close"].copy()
        x.index = x.index.floor("h")
        ser[k] = x[~x.index.duplicated(keep="last")]
    c = pd.concat(ser, axis=1).sort_index()
    # les taux (^TNX) ne cotent qu'aux heures de bourse US : on garde la dernière valeur connue (max 3h)
    c = c.ffill(limit=3).dropna()
    diag = {k: [int(len(v)), str(v.index[0]) if len(v) else None, str(v.index[-1]) if len(v) else None] for k, v in ser.items()}
    if len(c) < 200:
        log("Stats pression dollar : pas assez d'heures communes", diag)
        return {"n_hours": int(len(c)), "diag": diag, "down": {}, "up": {}}
    th = config.DP_TH
    dxy = c.DXY.pct_change() * 100
    y = c.US10Y.diff()
    oil = c.OIL.pct_change() * 100
    eur = c.EURUSD.pct_change() * 100
    down = (dxy < -th["DXY"]).astype(int) + (y < -th["US10Y"]).astype(int) + (oil < -th["OIL"]).astype(int) + (eur > th["EURUSD"]).astype(int)
    up = (dxy > th["DXY"]).astype(int) + (y > th["US10Y"]).astype(int) + (oil > th["OIL"]).astype(int) + (eur < -th["EURUSD"]).astype(int)
    h = config.DP_HORIZON_H
    dxy_f = (c.DXY.shift(-h) / c.DXY - 1) * 100
    gold_f = c.GOLD.shift(-h) - c.GOLD
    valid = dxy_f.notna() & gold_f.notna() & dxy.notna()
    out = {"n_hours": int(valid.sum()), "horizon_h": h,
           "base_gold_up": _r((gold_f[valid] > 0).mean() * 100),
           "base_dxy_down": _r((dxy_f[valid] < 0).mean() * 100), "down": {}, "up": {}}
    for k in (3, 4):
        m = valid & (down >= k)
        if m.sum() >= 25:
            out["down"][str(k)] = {"n": int(m.sum()), "p_dxy": _r((dxy_f[m] < 0).mean() * 100),
                                   "p_gold": _r((gold_f[m] > 0).mean() * 100), "gold_avg": _r(gold_f[m].mean(), 1)}
        m = valid & (up >= k)
        if m.sum() >= 25:
            out["up"][str(k)] = {"n": int(m.sum()), "p_dxy": _r((dxy_f[m] > 0).mean() * 100),
                                 "p_gold": _r((gold_f[m] < 0).mean() * 100), "gold_avg": _r(gold_f[m].mean(), 1)}
    return out
