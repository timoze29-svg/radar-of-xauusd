"""Données de marché (Yahoo Finance via yfinance) + secours Stooq + mode démo hors-ligne.

Chaque actif renvoie :
  daily : bougies journalières (index date sans fuseau)
  intra : bougies 5 min des 5 derniers jours (index UTC) -> alertes intraday
  live  : dernier prix
"""
import numpy as np
import pandas as pd

from . import config
from .common import log

RATES = ("US10Y", "US05Y")
HOURLY_KEYS = ("GOLD", "DXY", "US10Y", "OIL", "EURUSD")


def _clean_daily(df):
    if df is None or df.empty:
        return None
    df = df[["Open", "High", "Low", "Close"]].dropna()
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df = df[~df.index.duplicated(keep="last")]
    return df


def _clean_intra(df):
    if df is None or df.empty:
        return None
    df = df[["Open", "High", "Low", "Close"]].dropna()
    idx = pd.to_datetime(df.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    df.index = idx
    return df[~df.index.duplicated(keep="last")].sort_index()


def _fix_rate(key, df):
    """Yahoo donne parfois le taux x10 (42.1 au lieu de 4.21)."""
    if df is not None and key in RATES and float(df["Close"].median()) > 20:
        df = df.copy()
        df[["Open", "High", "Low", "Close"]] = df[["Open", "High", "Low", "Close"]] / 10
    return df


STOOQ = {"GOLD": "xauusd", "SILVER": "xagusd", "USDJPY": "usdjpy", "EURUSD": "eurusd"}


def _stooq(key):
    """Secours gratuit (spot) si Yahoo bloque."""
    import io
    from .common import http_get
    sym = STOOQ.get(key)
    if not sym:
        return None
    txt = http_get(f"https://stooq.com/q/d/l/?s={sym}&i=d", timeout=20).text
    df = pd.read_csv(io.StringIO(txt))
    df = df.rename(columns=str.title).set_index("Date")
    df.index = pd.to_datetime(df.index)
    return _clean_daily(df.tail(1600))


def fetch_all(demo=False):
    if demo:
        return _demo_data()
    import yfinance as yf
    out = {}
    for key, a in config.ASSETS.items():
        try:
            t = yf.Ticker(a["ticker"])
            period = "6y" if key == "GOLD" else "2y"
            daily = _fix_rate(key, _clean_daily(t.history(period=period, interval="1d", auto_adjust=False)))
            if daily is None or len(daily) < 30:
                log(f"{key}: pas assez de données")
                continue
            live, live_t, intra = float(daily["Close"].iloc[-1]), None, None
            try:
                intra = _fix_rate(key, _clean_intra(t.history(period="5d", interval="5m", auto_adjust=False)))
                if intra is not None and not intra.empty:
                    live = float(intra["Close"].iloc[-1])
                    live_t = intra.index[-1].isoformat()
                    daily.iloc[-1, daily.columns.get_loc("Close")] = live
                    daily.iloc[-1, daily.columns.get_loc("High")] = max(daily["High"].iloc[-1], live)
                    daily.iloc[-1, daily.columns.get_loc("Low")] = min(daily["Low"].iloc[-1], live)
            except Exception as e:
                log(f"{key}: intraday indispo ({e})")
            out[key] = {"daily": daily, "intra": intra, "live": live, "live_time": live_t}
        except Exception as e:
            log(f"{key}: erreur {e}")
        if key not in out and key in STOOQ:
            try:
                daily = _stooq(key)
                if daily is not None and len(daily) > 30:
                    out[key] = {"daily": daily, "intra": None, "live": float(daily.Close.iloc[-1]), "live_time": None}
                    log(f"{key}: récupéré via Stooq (secours)")
            except Exception as e:
                log(f"{key}: Stooq indispo ({e})")
    return out


def fetch_hourly(demo=False):
    """Historique horaire ~2 ans (pour les probabilités). Appelé 1 fois / jour (cache)."""
    if demo:
        return _demo_hourly()
    import yfinance as yf
    out = {}
    for key in HOURLY_KEYS:
        try:
            df = _fix_rate(key, _clean_intra(
                yf.Ticker(config.ASSETS[key]["ticker"]).history(period="730d", interval="1h", auto_adjust=False)))
            if df is not None and len(df) > 500:
                out[key] = df
        except Exception as e:
            log(f"Horaire {key}: {e}")
    return out


# ------------------------------------------------------------------ démo
DEMO_BASE = {"GOLD": 4140, "DXY": 102.3, "US10Y": 5.28, "US05Y": 4.9, "SILVER": 49, "OIL": 91,
             "VIX": 16, "SPX": 7750, "USDJPY": 151, "EURUSD": 1.118, "BTC": 80700, "COPPER": 4.9}
DEMO_CORR = {"GOLD": 1, "DXY": -0.5, "US10Y": -0.4, "US05Y": -0.35, "SILVER": 0.8, "OIL": 0.2,
             "VIX": 0.15, "SPX": 0.1, "USDJPY": -0.3, "EURUSD": 0.5, "BTC": 0.2, "COPPER": 0.3}
DEMO_VOL = {"GOLD": 0.011, "DXY": 0.004, "US10Y": 0.02, "US05Y": 0.02, "SILVER": 0.02, "OIL": 0.02,
            "VIX": 0.06, "SPX": 0.01, "USDJPY": 0.005, "EURUSD": 0.004, "BTC": 0.03, "COPPER": 0.015}
# scénario démo de la dernière heure : dollar qui lâche (comme le 08/10 au soir)
DEMO_LAST_HOUR = {"GOLD": 0.45, "DXY": -0.18, "US10Y": -0.04, "OIL": -1.1, "EURUSD": 0.15}


def _ohlc(close, vol, rng):
    op = np.r_[close[0], close[:-1]]
    hi = np.maximum(op, close) * (1 + np.abs(rng.normal(0, vol / 2, len(close))))
    lo = np.minimum(op, close) * (1 - np.abs(rng.normal(0, vol / 2, len(close))))
    return op, hi, lo


def _demo_data():
    rng = np.random.default_rng(7)
    end = pd.Timestamp.utcnow().tz_localize(None).normalize()
    idx = pd.bdate_range(end=end, periods=1500)
    common = rng.normal(0, 1, len(idx))
    now5 = pd.Timestamp.now(tz="UTC").floor("5min")
    iidx = pd.date_range(end=now5, periods=5 * 288, freq="5min")
    icommon = rng.normal(0, 1, len(iidx))
    out = {}
    for k in config.ASSETS:
        c, v = DEMO_CORR[k], DEMO_VOL[k]
        eps = c * common + np.sqrt(1 - c * c) * rng.normal(0, 1, len(idx))
        r = (0.0004 if k == "GOLD" else 0) + v * eps
        close = DEMO_BASE[k] * np.exp(np.cumsum(r - np.mean(r)) * 0.9)
        close = close / close[-1] * DEMO_BASE[k]
        op, hi, lo = _ohlc(close, v, rng)
        daily = pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": close}, index=idx)
        # intraday 5 min
        iv = v / np.sqrt(288)
        ieps = c * icommon + np.sqrt(1 - c * c) * rng.normal(0, 1, len(iidx))
        ic = np.exp(np.cumsum(iv * ieps))
        lh = DEMO_LAST_HOUR.get(k)
        if lh is not None:  # impose le mouvement de la dernière heure
            if k == "US10Y":
                ramp = np.linspace(0, lh / DEMO_BASE[k], 12)
            else:
                ramp = np.linspace(0, lh / 100, 12)
            ic[-12:] = ic[-13] * (1 + ramp)
        ic = ic / ic[-1] * DEMO_BASE[k]
        iop, ihi, ilo = _ohlc(ic, iv, rng)
        intra = pd.DataFrame({"Open": iop, "High": ihi, "Low": ilo, "Close": ic}, index=iidx)
        daily.iloc[-1, daily.columns.get_loc("High")] = max(daily.High.iloc[-1], ic[-288:].max())
        daily.iloc[-1, daily.columns.get_loc("Low")] = min(daily.Low.iloc[-1], ic[-288:].min())
        out[k] = {"daily": daily, "intra": intra, "live": float(ic[-1]), "live_time": iidx[-1].isoformat()}
    return out


def _demo_hourly():
    rng = np.random.default_rng(11)
    n = 12000
    idx = pd.date_range(end=pd.Timestamp.now(tz="UTC").floor("h"), periods=n, freq="h")
    idx = idx[idx.weekday < 5]
    n = len(idx)
    usd = rng.normal(0, 1, n)                       # facteur dollar commun
    usd_s = np.convolve(usd, np.ones(3) / 3, mode="same")  # légère persistance
    out = {}
    spec = {"DXY": (0.0012, 0.8), "US10Y": (0.012, 0.5), "OIL": (0.006, -0.3), "EURUSD": (0.0012, -0.75), "GOLD": (0.003, -0.55)}
    for k, (v, b) in spec.items():
        e = b * usd_s + np.sqrt(max(0, 1 - b * b)) * rng.normal(0, 1, n)
        if k == "US10Y":
            c = DEMO_BASE[k] + np.cumsum(v * e)
        else:
            c = DEMO_BASE[k] * np.exp(np.cumsum(v * e))
        op, hi, lo = _ohlc(c, v, rng)
        out[k] = pd.DataFrame({"Open": op, "High": hi, "Low": lo, "Close": c}, index=idx)
    return out
