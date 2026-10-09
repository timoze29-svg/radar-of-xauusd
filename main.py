"""
RADAR OR — point d'entrée.

  python main.py scan     -> scan complet + alertes + rapports programmés (lancé toutes les 15 min)
  python main.py daily    -> force la PRÉVISION DU JOUR
  python main.py update   -> force la mise à jour avant New York
  python main.py recap    -> force le bilan du soir
  python main.py weekly   -> force la PRÉVISION DE LA SEMAINE
  python main.py test     -> message test sur Telegram

  --demo   : données simulées hors-ligne (aucune alerte envoyée)
  --loud   : avec --demo, génère aussi les alertes (affichées dans la console)

Les rapports programmés sont déclenchés en HEURE DE PARIS (été/hiver géré tout seul) :
  7h prévision du jour (+ semaine le lundi) · 14h update New York · 22h bilan
"""
import json
import os
import sys

from src import config
from src.common import (load_state, save_state, log, now_utc, to_paris, DATA_PATH, telegram,
                        already_fired, mark_fired)
from src import market, macro, news as newsmod, calendar_eco, analysis, reports, stats, intraday as ix

MANUAL = {"daily": "daily", "brief": "daily", "update": "update", "recap": "recap", "weekly": "weekly"}


def due_reports(state):
    p = to_paris(now_utc())
    if p.weekday() >= 5:
        return []
    out = []
    if config.DAILY_HOUR <= p.hour < config.DAILY_HOUR + 4:
        if p.weekday() == 0:
            out.append("weekly")
        out.append("daily")
    if config.NY_UPDATE_HOUR <= p.hour < config.NY_UPDATE_HOUR + 2:
        out.append("update")
    if config.RECAP_HOUR <= p.hour < 24:
        out.append("recap")
    d = str(p.date())
    return [m for m in out if not already_fired(state, f"rep|{m}|{d}")]


def run(mode="scan", demo=False, loud=False):
    state = load_state()
    log(f"=== RADAR OR — mode {mode}{' (DÉMO)' if demo else ''} ===")

    if mode == "test":
        ok = telegram("✅ <b>Radar Or connecté !</b>\nTu recevras ici : prévision du jour (7h), update New York (14h), "
                      "bilan (22h), prévision de la semaine (lundi), pré-alertes annonces, dollar sous pression, "
                      "news en rafale, cassures et news chaudes.", kind="test")
        log("Test Telegram :", "OK" if ok else "ÉCHEC (vérifie TELEGRAM_TOKEN / TELEGRAM_CHAT_ID)")
        return

    # ------------------------------------------------------------ 1. données
    mkt = market.fetch_all(demo)
    log(f"Marchés : {len(mkt)}/{len(config.ASSETS)} actifs")
    prev_snap = {}
    try:
        with open(DATA_PATH, encoding="utf-8") as f:
            prev_snap = json.load(f)
    except Exception:
        pass
    fred = macro.fetch_fred(state, demo)
    cot = macro.fetch_cot(state, demo)
    events = calendar_eco.fetch_calendar(state, demo)

    first_run = not state.get("initialized")
    quiet = (not loud) if demo else first_run
    if first_run and not demo:
        log("1er lancement : initialisation silencieuse des alertes (pas de spam)")
    news = newsmod.update_news(state, demo, quiet=quiet)

    # ------------------------------------------------------------ 2. analyse
    has_gold = "GOLD" in mkt
    corr = analysis.correlations(mkt)
    gold_lv = analysis.levels(mkt["GOLD"]["daily"]) if has_gold else {}
    cycle = analysis.weekly_cycle(mkt["GOLD"]["daily"], mkt["GOLD"]["live"]) if has_gold else {"stats": {}, "current": {}}
    sent = newsmod.news_sentiment(news)
    bias = analysis.bias_score(mkt, fred, cot, sent, gold_lv)
    log(f"Biais or : {bias['score']:+d} ({bias['label']})")

    dstats = stats.daily_stats(mkt["GOLD"]["daily"]) if has_gold else {}
    bstats = stats.breakout_stats(mkt["GOLD"]["daily"]) if has_gold else {}
    hstats = stats.hourly_stats(state, demo)
    dp = ix.dollar_pressure(mkt, news, hstats.get("dollar"))
    log(f"Pression dollar : {dp['status']} (baisse {dp['down']}/4, hausse {dp['up']}/4)")
    dc = ix.day_changes(mkt)

    # ------------------------------------------------------------ 3. alertes
    analysis.breakout_alerts(state, mkt, corr, quiet, bstats)
    analysis.correlation_alerts(state, corr, quiet)
    analysis.cycle_alerts(state, cycle, quiet)
    analysis.bias_alert(state, bias, quiet)
    ix.dollar_pressure_alert(state, dp, quiet)
    ix.news_burst(state, news, quiet)
    ix.post_event_recaps(state, events, mkt, gold_lv.get("atr"), quiet)
    calendar_eco.pre_event_alerts(state, events, {
        "dxy_day": dc.get("DXY"), "y_day": (dc["US10Y"] * 100) if dc.get("US10Y") is not None else None,
        "bias": (bias["score"], bias["label"]), "atr": gold_lv.get("atr"), "dp_text": ix.dp_short_text(dp)}, quiet)
    if has_gold and not demo:
        state["initialized"] = True

    snapshot = {
        "updated": now_utc().isoformat(), "demo": demo, "ai": bool(config.GEMINI_API_KEY),
        "bias": bias, "assets": analysis.assets_table(mkt, corr),
        "gold_levels": {k: round(v, 2) for k, v in gold_lv.items() if isinstance(v, (int, float))},
        "cycle": cycle, "macro": fred, "cot": cot, "calendar": events,
        "news": news[:120], "news_sentiment": {"value": sent[0], "count": sent[1]},
        "dollar_pressure": dp,
        "stats": {"weekday": dstats.get("by_weekday"), "after": dstats.get("after"),
                  "hours": hstats.get("gold_hours"), "dp_hist": hstats.get("dollar"), "breakouts": bstats},
    }
    stale = not has_gold
    if stale and prev_snap.get("assets"):
        log("⚠️ Prix indisponibles : on garde le dernier snapshot de marché")
        for k in ("assets", "gold_levels", "cycle", "bias"):
            snapshot[k] = prev_snap.get(k, snapshot[k])
        snapshot["stale"] = True

    # ------------------------------------------------------------ 4. rapports
    todo = [MANUAL[mode]] if mode in MANUAL else ([] if (demo and not loud) else due_reports(state))
    if stale and todo:
        log("Rapports reportés (pas de prix frais) :", todo)
        todo = []
    ex = {"dstats": dstats, "hstats": hstats, "dp": dp,
          "prev_class": stats.prev_day_class(mkt["GOLD"]["daily"]) if has_gold else None}
    today = str(to_paris(now_utc()).date())
    for rep in todo:
        try:
            if rep == "weekly":
                res = reports.weekly_forecast(snapshot, state)
                state["weekly_forecast"] = res
            elif rep == "daily":
                res = reports.daily_forecast(snapshot, state, mkt, ex)
                state["daily_forecast"] = res
            elif rep == "update":
                res = reports.ny_update(snapshot, state, mkt, ex)
                state["ny_update"] = res
            else:
                res = reports.evening_recap(snapshot, state, mkt, ex)
                state["evening_recap"] = res
            if res:
                mark_fired(state, f"rep|{rep}|{today}")
                log(f"Rapport envoyé : {rep}")
        except Exception as e:
            log(f"Rapport {rep} en erreur : {e}")
            import traceback
            traceback.print_exc()

    for k in ("weekly_forecast", "daily_forecast", "ny_update", "evening_recap"):
        snapshot[k] = state.get(k)
    snapshot["track"] = reports.track_summary(state)
    snapshot["alerts"] = state.get("alerts", [])[:40]

    # ------------------------------------------------------------ 5. sauvegarde
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, default=str, separators=(",", ":"))
    save_state(state)
    log("Terminé ✔")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    run(args[0] if args else (os.getenv("MODE") or "scan"), demo="--demo" in sys.argv, loud="--loud" in sys.argv)
