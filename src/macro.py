"""Macro gratuite : taux réels / inflation anticipée / Fed (FRED) + positionnement COT (CFTC)."""
import io

import pandas as pd

from . import config
from .common import http_get, log, cache_get, cache_set


def _fred(series_id):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    df = pd.read_csv(io.StringIO(http_get(url, timeout=30).text))
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")
    s.index = pd.to_datetime(df.iloc[:, 0])
    return s.dropna().tail(400)


def fetch_fred(state, demo=False):
    """Résumé des séries macro (cache 6h)."""
    cached = cache_get(state, "fred", 6 * 3600)
    if cached and not demo:
        return cached
    out = {}
    for key, meta in config.FRED_SERIES.items():
        try:
            if demo:
                import numpy as np
                base = {"REAL10Y": 1.9, "BREAKEVEN": 2.3, "US2Y": 3.6, "FEDFUNDS": 3.88}[key]
                s = pd.Series(base + np.cumsum(np.random.default_rng(len(key)).normal(0, 0.02, 300)))
                dates = pd.bdate_range(end=pd.Timestamp.today(), periods=300)
                s.index = dates
            else:
                s = _fred(meta["id"])
            last = float(s.iloc[-1])
            out[key] = {
                "name": meta["name"], "last": round(last, 3),
                "date": str(s.index[-1].date()),
                "chg5": round(last - float(s.iloc[-6]), 3) if len(s) > 6 else 0,
                "chg20": round(last - float(s.iloc[-21]), 3) if len(s) > 21 else 0,
                "hist": [round(float(v), 3) for v in s.tail(120).values],
                "gold_rel": meta["gold_rel"],
            }
        except Exception as e:
            log(f"FRED {key}: {e}")
    if out:
        cache_set(state, "fred", out)
    return out or (cached or {})


def fetch_cot(state, demo=False):
    """Positionnement des spéculateurs (non-commercials) sur l'or COMEX (cache 12h)."""
    cached = cache_get(state, "cot", 12 * 3600)
    if cached and not demo:
        return cached
    try:
        if demo:
            import numpy as np
            nets = list(150000 + np.cumsum(np.random.default_rng(3).normal(0, 8000, 156)))
            dates = [str(d.date()) for d in pd.date_range(end=pd.Timestamp.today(), periods=156, freq="W-TUE")]
        else:
            url = ("https://publicreporting.cftc.gov/resource/6dca-aqww.json"
                   f"?$where=cftc_contract_market_code='{config.COT_GOLD_CODE}'"
                   "&$order=report_date_as_yyyy_mm_dd DESC&$limit=156")
            rows = http_get(url, timeout=30).json()
            rows = list(reversed(rows))
            nets = [float(r["noncomm_positions_long_all"]) - float(r["noncomm_positions_short_all"]) for r in rows]
            dates = [r["report_date_as_yyyy_mm_dd"][:10] for r in rows]
        if len(nets) < 10:
            return cached or {}
        last = nets[-1]
        pct = sum(1 for n in nets if n <= last) / len(nets)
        out = {
            "date": dates[-1], "net": int(last), "chg_week": int(last - nets[-2]),
            "percentile_3y": round(pct * 100), "hist": [int(n) for n in nets[-52:]],
            "lecture": ("Spéculateurs très chargés à l'achat → risque de purge" if pct > 0.85 else
                        "Spéculateurs peu positionnés → carburant haussier dispo" if pct < 0.2 else
                        "Positionnement neutre"),
        }
        cache_set(state, "cot", out)
        return out
    except Exception as e:
        log("COT:", e)
        return cached or {}
