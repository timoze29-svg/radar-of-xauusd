"""Rapports Telegram : prévision de la semaine (lundi), du jour (7h), update 14h, bilan 22h."""
import json
from datetime import datetime, timedelta

from .common import ask_ai, ai_available, esc, now_utc, fmt_paris, telegram, to_paris
from .calendar_eco import week_events_text


def _top_news(news, hours, n=6):
    lim = now_utc() - timedelta(hours=hours)
    rec = [x for x in news if datetime.fromisoformat(x["published"]) >= lim and x.get("impact")]
    rec.sort(key=lambda x: -abs(x["impact"]))
    return rec[:n]


def _context(snapshot, news_hours):
    """Contexte compact envoyé à l'IA."""
    g = next((a for a in snapshot["assets"] if a["key"] == "GOLD"), {})
    return {
        "date": fmt_paris(now_utc(), "%A %d/%m/%Y %H:%M"),
        "or": {"prix": g.get("price"), "var_jour_%": g.get("chg1"), "var_5j_%": g.get("chg5"),
               "niveaux": g.get("levels")},
        "biais": {"score": snapshot["bias"]["score"], "label": snapshot["bias"]["label"],
                  "moteurs": [(c["name"], c["detail"], c["contrib"]) for c in snapshot["bias"]["components"]]},
        "actifs": [(a["name"], a["price"], a["chg1"], a["chg5"], a["corr"].get("c20"), a["flags"])
                   for a in snapshot["assets"] if a["key"] != "GOLD"],
        "macro": {k: (v["name"], v["last"], v["chg20"]) for k, v in snapshot["macro"].items()},
        "cot": snapshot.get("cot", {}).get("lecture"),
        "cycle_hebdo": {"stats": {k: v for k, v in snapshot["cycle"]["stats"].items() if k != "last_weeks"},
                        "semaine": snapshot["cycle"]["current"]},
        "calendrier": week_events_text(snapshot["calendar"]),
        "news": [(n["title"], n["impact"], n.get("raison")) for n in _top_news(snapshot["news"], news_hours, 12)],
    }


def _levels_block(lv):
    if not lv:
        return ""
    return (f"📐 <b>Niveaux clés or</b>\n"
            f"R2 {lv['r2']:.1f} | R1 {lv['r1']:.1f} | <b>Pivot {lv['pivot']:.1f}</b> | S1 {lv['s1']:.1f} | S2 {lv['s2']:.1f}\n"
            f"Sem. passée : PH {lv['pwh']:.1f} / PB {lv['pwl']:.1f} / clôt. {lv['pwc']:.1f}\n"
            f"Range hebdo moyen (10 sem.) : <b>{lv['avg_week_range']:.0f}$</b> | ATR jour : {lv['atr']:.1f}$")


def _bias_block(b):
    lines = [f"🧭 <b>Biais macro or : {esc(b['label'])} ({b['score']:+d}/100)</b>"]
    for c in b["components"][:6]:
        ic = "🟢" if c["contrib"] > 1 else "🔴" if c["contrib"] < -1 else "⚪"
        lines.append(f"{ic} {esc(c['name'])} : {esc(c['detail'])}")
    return "\n".join(lines)


def _cycle_block(cyc, weekly=True):
    st, cur = cyc.get("stats", {}), cyc.get("current", {})
    if not st:
        return ""
    jours = ["Lun", "Mar", "Mer", "Jeu", "Ven"]
    hi = max(range(5), key=lambda i: st["hi_day_pct"][i])
    lo = max(range(5), key=lambda i: st["lo_day_pct"][i])
    txt = (f"🔄 <b>Cycle hebdo (sur {st['weeks']} semaines)</b>\n"
           f"Inversion jeu→ven vs lun→mer : <b>{st['pct_rev']}%</b> des semaines "
           f"(<b>{st['pct_rev_strong']}%</b> si lun→mer est fort, > {st['median_A']:.0f}$)\n"
           f"Retracement médian quand ça inverse : {st['avg_retrace_pct']}%\n"
           f"Plus haut de la semaine le plus souvent : {jours[hi]} ({st['hi_day_pct'][hi]}%) | "
           f"plus bas : {jours[lo]} ({st['lo_day_pct'][lo]}%)")
    if not weekly and cur.get("texte"):
        txt += f"\n➡️ {esc(cur['texte'])}"
    return txt


def _template_scenarios(snapshot, lv):
    b = snapshot["bias"]["score"]
    if not lv:
        return ""
    if b >= 15:
        return (f"📈 <b>Scénario principal : HAUSSIER</b>\n"
                f"Lun→mer : chercher des achats sur repli vers {lv['pivot']:.0f} / {lv['s1']:.0f}, "
                f"objectifs {lv['r1']:.0f} puis {lv['r2']:.0f}.\n"
                f"Jeu→ven : si la hausse lun→mer est forte, prudence → retour possible vers le pivot.\n"
                f"❌ Invalidation : clôture journalière sous {lv['s1']:.0f}.")
    if b <= -15:
        return (f"📉 <b>Scénario principal : BAISSIER</b>\n"
                f"Lun→mer : chercher des ventes sur rebond vers {lv['pivot']:.0f} / {lv['r1']:.0f}, "
                f"objectifs {lv['s1']:.0f} puis {lv['s2']:.0f}.\n"
                f"Jeu→ven : si la baisse lun→mer est forte, retour possible vers le pivot.\n"
                f"❌ Invalidation : clôture journalière au-dessus de {lv['r1']:.0f}.")
    return (f"↔️ <b>Scénario principal : RANGE</b> entre {lv['s1']:.0f} et {lv['r1']:.0f}.\n"
            f"Attendre la cassure de la semaine passée ({lv['pwl']:.0f} / {lv['pwh']:.0f}) ou les grosses news "
            f"pour prendre une direction. Jouer les extrêmes du range, pas le milieu.")


def weekly_forecast(snapshot, state):
    gold = next((a for a in snapshot["assets"] if a["key"] == "GOLD"), None)
    lv = snapshot.get("gold_levels", {})
    head = (f"🗓 <b>PRÉVISION OR — SEMAINE DU {fmt_paris(now_utc(), '%d/%m/%Y')}</b>\n"
            f"Prix : <b>{gold['price']:.2f}</b>  ({gold['chg5']:+.2f}% sur 5j)" if gold else "")
    ev = week_events_text(snapshot["calendar"])
    ev_block = "📅 <b>News éco de la semaine</b>\n" + ("\n".join(esc(x) for x in ev) if ev else "Aucune news majeure détectée")
    wk_news = _top_news(snapshot["news"], 72, 6)
    news_block = "📰 <b>Ce qui a bougé ce week-end / fin de semaine</b>\n" + (
        "\n".join(f"{'🟢' if n['impact'] > 0 else '🔴'} ({n['impact']:+d}) {esc(n['title'])}" for n in wk_news)
        or "Rien de majeur")

    ai_txt = None
    if ai_available():
        prompt = f"""Tu es le stratège or (XAUUSD) d'un hedge fund. Rédige la PRÉVISION DE LA SEMAINE
en français, style direct de trader, pour un trader particulier qui trade XAUUSD.
Le trader a remarqué que l'or fait souvent un mouvement du lundi au mercredi puis l'inverse jeudi-vendredi :
les stats réelles de ce cycle sont dans les données, utilise-les honnêtement (dis si c'est fiable ou pas).

Structure obligatoire (texte brut, pas de markdown, pas de #, emojis ok) :
1. Le contexte en 3 phrases (ce qui domine l'or cette semaine : Fed, dollar, géopolitique Trump/Iran, etc.)
2. Scénario principal (probabilité estimée en %) : direction lun→mer puis jeu→ven, niveaux d'entrée/objectifs/invalidation
3. Scénario alternatif (probabilité %) et ce qui le déclencherait
4. Les jours / heures dangereux de la semaine (news) et comment les gérer
5. Les 3 choses à surveiller en priorité

Reste factuel, utilise les chiffres fournis, max 1800 caractères.

DONNÉES :
{json.dumps(_context(snapshot, 72), ensure_ascii=False, default=str)}"""
        ai_txt = ask_ai(prompt, temperature=0.5)

    parts = [head, _bias_block(snapshot["bias"]), _levels_block(lv), ev_block,
             _cycle_block(snapshot["cycle"]), news_block,
             ("🧠 <b>Analyse IA</b>\n" + esc(ai_txt)) if ai_txt else _template_scenarios(snapshot, lv),
             "<i>Outil d'aide à la décision, pas un conseil financier.</i>"]
    msg = "\n\n".join(p for p in parts if p)
    telegram(msg, state, kind="weekly")
    return {"date": now_utc().isoformat(), "text": msg, "ai": bool(ai_txt)}


# =====================================================================================
#                         PRÉVISIONS JOURNALIÈRES (7h / 14h / 22h)
# =====================================================================================
from . import intraday as ix                                   # noqa: E402
from .calendar_eco import is_major, scenarios                  # noqa: E402
from .stats import JOURS                                       # noqa: E402


def _today_paris():
    return to_paris(now_utc()).date()


def _gold(snapshot):
    return next((a for a in snapshot["assets"] if a["key"] == "GOLD"), None)


def _daily_pivots(lv):
    H, L, C = lv["pdh"], lv["pdl"], lv["pdc"]
    P = (H + L + C) / 3
    return {"P": P, "R1": 2 * P - L, "S1": 2 * P - H, "R2": P + (H - L), "S2": P - (H - L), "PDH": H, "PDL": L}


def _events_on(events, day, after=None):
    out = []
    for e in events:
        dt = datetime.fromisoformat(e["date"])
        if to_paris(dt).date() != day or not is_major(e):
            continue
        if after is not None and dt <= after:
            continue
        out.append(e)
    return out


def _events_block(evs, title, with_scen=True):
    if not evs:
        return f"{title}\nPas d'annonce majeure → journée plus technique, respecte tes niveaux."
    lines = [title]
    done = set()
    for e in evs:
        dt = datetime.fromisoformat(e["date"])
        flag = "🇺🇸" if e["country"] == "USD" else "🇪🇺"
        lines.append(f"🔥 <b>{fmt_paris(dt, '%H:%M')}</b> {flag} {esc(e['title'])}"
                     + (f" (prév. {esc(e['forecast'])})" if e.get("forecast") else ""))
        if with_scen and e["date"] not in done:
            done.add(e["date"])
            for sc in scenarios(e):
                lines.append("    " + sc)
    return "\n".join(lines)


def _dir(score):
    return "up" if score >= 15 else "down" if score <= -15 else "range"


DIR_TXT = {"up": "📈 HAUSSIER", "down": "📉 BAISSIER", "range": "↔️ RANGE / NEUTRE"}


def _hours_txt(hstats, wd):
    gh = ((hstats or {}).get("gold_hours") or {}).get(str(wd))
    if not gh:
        return ""
    hi = ", ".join(f"{h}h ({p:.0f}%)" for h, p in gh["high"][:2])
    lo = ", ".join(f"{h}h ({p:.0f}%)" for h, p in gh["low"][:2])
    return f"🕐 Le {JOURS[wd].lower()}, plus HAUT du jour souvent vers {hi} · plus BAS vers {lo} (heure de Paris)"


def _scen_template(d, pv, exp):
    def tg(keys, up):
        return " → ".join(f"{k} {v:.0f}" for k, v in sorted(((k, pv[k]) for k in keys), key=lambda x: x[1] if up else -x[1]))
    ups, dns = tg(("R1", "PDH", "R2"), True), tg(("S1", "PDL", "S2"), False)
    ups_alt, dns_alt = tg(("PDH", "R2"), True), tg(("PDL", "S2"), False)
    if d == "up":
        return (f"🎯 <b>Scénario principal — achats sur repli</b>\n"
                f"Zone d'achat : Pivot {pv['P']:.0f} → S1 {pv['S1']:.0f}\n"
                f"Objectifs : {ups}\n"
                f"❌ Invalidation : clôture H1 sous S1 {pv['S1']:.0f}\n\n"
                f"🔁 <b>Alternatif</b> : cassure de S1 → vente vers {dns_alt}")
    if d == "down":
        return (f"🎯 <b>Scénario principal — ventes sur rebond</b>\n"
                f"Zone de vente : Pivot {pv['P']:.0f} → R1 {pv['R1']:.0f}\n"
                f"Objectifs : {dns}\n"
                f"❌ Invalidation : clôture H1 au-dessus de R1 {pv['R1']:.0f}\n\n"
                f"🔁 <b>Alternatif</b> : cassure de R1 → achat vers {ups_alt}")
    return (f"🎯 <b>Scénario principal — range</b> entre S1 {pv['S1']:.0f} et R1 {pv['R1']:.0f}\n"
            f"Jouer les extrêmes, pas le milieu (pivot {pv['P']:.0f}). Range attendu ~{exp:.0f}$.\n\n"
            f"🔁 <b>Alternatif</b> : cassure franche de PDH {pv['PDH']:.0f} ou PDL {pv['PDL']:.0f} "
            f"(souvent sur une annonce) → suivre la cassure")


def _conflict(d, dp):
    if not dp or dp["status"] == "neutre" or d == "range":
        return ""
    if (d == "up" and dp["status"] == "up") or (d == "down" and dp["status"] == "down"):
        return ("⚠️ <b>Attention</b> : le dollar va CONTRE le biais du jour en ce moment "
                "→ attendre que ça se calme ou réduire la taille.")
    return "✅ Le mouvement du dollar CONFIRME le biais du jour."


def daily_forecast(snapshot, state, mkt, ex):
    g, lv = _gold(snapshot), snapshot.get("gold_levels") or {}
    if not g or not lv:
        return None
    now_p = to_paris(now_utc())
    wd, today = now_p.weekday(), now_p.date()
    pv = _daily_pivots(lv)
    b = snapshot["bias"]
    d = _dir(b["score"])
    ds = ex.get("dstats") or {}
    wds = (ds.get("by_weekday") or {}).get(str(min(wd, 4)), {})
    atr = lv.get("atr", 0)
    exp = atr * (wds.get("range_factor") or 1.0)
    asia = ix.session(ix.intra(mkt, "GOLD"), ix.paris_midnight())
    dxy_n = ix.change_since(ix.intra(mkt, "DXY"), ix.paris_midnight())

    head = (f"☀️ <b>PRÉVISION OR — {fmt_paris(now_utc(), '%A %d/%m').upper()}</b>\n"
            f"Prix : <b>{g['price']:.2f}</b>  ·  Biais du jour : <b>{DIR_TXT[d]}</b> ({b['score']:+d}/100)")
    why = "\n".join(f"{'🟢' if c['contrib'] > 1 else '🔴' if c['contrib'] < -1 else '⚪'} {esc(c['name'])} : {esc(c['detail'])}"
                    for c in b["components"][:3])
    blocks = [head, "<b>Pourquoi :</b>\n" + why]

    if asia:
        blocks.append(f"🌏 <b>Session Asie</b> (depuis minuit) : {asia['chg']:+.1f}$ · "
                      f"plus haut {asia['high']:.1f} / plus bas {asia['low']:.1f} (range {asia['range']:.0f}$)"
                      + (f"\nDXY {dxy_n:+.2f}% sur la nuit" if dxy_n is not None else "")
                      + (f"\n⚠️ Plus haut de la veille ({pv['PDH']:.0f}) déjà cassé" if asia["high"] > pv["PDH"] else "")
                      + (f"\n⚠️ Plus bas de la veille ({pv['PDL']:.0f}) déjà cassé" if asia["low"] < pv["PDL"] else ""))

    done = asia["range"] if asia else 0
    blocks.append(f"📏 <b>Range attendu aujourd'hui : ~{exp:.0f}$</b> (ATR {atr:.0f}$ × profil du {JOURS[min(wd, 4)].lower()})"
                  + (f"\nDéjà fait en Asie : {done:.0f}$ ({done / exp * 100:.0f}% du range attendu)" if exp and asia else ""))

    blocks.append(f"📐 <b>Niveaux du jour</b>\n"
                  f"R2 {pv['R2']:.1f} | R1 {pv['R1']:.1f} | <b>Pivot {pv['P']:.1f}</b> | S1 {pv['S1']:.1f} | S2 {pv['S2']:.1f}\n"
                  f"Veille : PDH {pv['PDH']:.1f} / PDL {pv['PDL']:.1f}  ·  Semaine passée : {lv['pwh']:.0f} / {lv['pwl']:.0f}")

    blocks.append(_events_block(_events_on(snapshot["calendar"], today), "📅 <b>Annonces du jour</b>"))

    st = []
    if wds:
        st.append(f"• Le {JOURS[min(wd, 4)].lower()}, l'or a fini en hausse <b>{wds['pct_up']:.0f}%</b> du temps "
                  f"({wds['n']} jours, ~{ds.get('years', '?')} ans)")
    pc = ex.get("prev_class")
    if pc and ds.get("after"):
        a = ds["after"].get(pc[0], {})
        lbl = {"forte_hausse": "après une veille en FORTE HAUSSE", "forte_baisse": "après une veille en FORTE BAISSE",
               "normale": "après une veille normale"}[pc[0]]
        if a:
            st.append(f"• Hier : {pc[1]:+.2f}% → {lbl}, l'or a monté le lendemain <b>{a['pct_up']:.0f}%</b> du temps ({a['n']} cas)")
    ht = _hours_txt(ex.get("hstats"), min(wd, 4))
    if ht:
        st.append(ht)
    cur = (snapshot.get("cycle") or {}).get("current", {})
    if cur.get("texte"):
        st.append(f"🔄 {esc(cur['texte'])}")
    if st:
        blocks.append("📊 <b>Stats réelles</b>\n" + "\n".join(st))

    if ex.get("dp"):
        blocks.append("💵 " + ix.dp_short_text(ex["dp"]) + ("\n" + _conflict(d, ex["dp"]) if _conflict(d, ex["dp"]) else ""))

    ai_txt = None
    if ai_available():
        ai_txt = ask_ai(f"""Tu es stratège or (XAUUSD) pour un trader intraday. En français, style trader direct,
texte brut sans markdown (emojis ok), max 900 caractères :
1) scénario principal du jour avec entrée / objectifs / invalidation en utilisant les niveaux fournis,
2) scénario alternatif et son déclencheur, 3) l'annonce ou l'heure la plus dangereuse et comment la gérer.
Appuie-toi sur les chiffres fournis, n'invente pas de pourcentage.
DONNÉES : {json.dumps({**_context(snapshot, 14), 'pivots_jour': {k: round(v, 1) for k, v in pv.items()},
                      'range_attendu': round(exp), 'asie': asia and {k: v for k, v in asia.items() if not k.startswith('t_')},
                      'stats': st}, ensure_ascii=False, default=str)}""", temperature=0.4)
    blocks.append(("🧠 <b>Analyse IA</b>\n" + esc(ai_txt)) if ai_txt else _scen_template(d, pv, exp))
    blocks.append("<i>Bilan prévision vs réalité ce soir à 22h. Pas un conseil financier.</i>")
    msg = "\n\n".join(blocks)

    state.setdefault("forecasts", {})[str(today)] = {
        "dir": d, "score": b["score"], "p0": g["price"], "exp_range": round(exp, 1),
        "levels": {k: round(v, 2) for k, v in pv.items()}, "ts": now_utc().isoformat()}
    for k in sorted(state["forecasts"])[:-30]:
        del state["forecasts"][k]
    telegram(msg, state, kind="daily")
    return {"date": now_utc().isoformat(), "text": msg, "ai": bool(ai_txt)}


def ny_update(snapshot, state, mkt, ex):
    g, lv = _gold(snapshot), snapshot.get("gold_levels") or {}
    if not g or not lv:
        return None
    today = _today_paris()
    fc = (state.get("forecasts") or {}).get(str(today))
    b = snapshot["bias"]
    price = g["price"]
    day = ix.session(ix.intra(mkt, "GOLD"), ix.paris_midnight())
    lines = [f"🗽 <b>UPDATE AVANT NEW YORK — {fmt_paris(now_utc(), '%H:%M')}</b>",
             f"Prix : <b>{price:.2f}</b>"]
    if fc:
        mv = price - fc["p0"]
        lines[-1] += f"  ({mv:+.1f}$ depuis la prévision de ce matin)"
        pv = fc["levels"]
        d = fc["dir"]
        if d == "up":
            status = ("✅ Le scénario haussier TIENT" if price > pv["P"] else
                      "❌ Scénario haussier INVALIDÉ (sous S1)" if price < pv["S1"] else
                      "⏳ En zone d'achat (entre S1 et pivot) : attendre une confirmation")
        elif d == "down":
            status = ("✅ Le scénario baissier TIENT" if price < pv["P"] else
                      "❌ Scénario baissier INVALIDÉ (au-dessus de R1)" if price > pv["R1"] else
                      "⏳ En zone de vente (entre pivot et R1) : attendre une confirmation")
        else:
            status = ("✅ Le range TIENT" if pv["S1"] <= price <= pv["R1"] else
                      "⚠️ Range CASSÉ → suivre la cassure")
        lines.append(f"Prévision du matin : {DIR_TXT[d]} ({fc['score']:+d}) → maintenant {b['score']:+d} ({esc(b['label'])})")
        lines.append(status)
        if day and fc.get("exp_range"):
            lines.append(f"📏 Range fait : {day['range']:.0f}$ sur ~{fc['exp_range']:.0f}$ attendus "
                         f"({day['range'] / fc['exp_range'] * 100:.0f}%)"
                         + (" → il reste de la place" if day["range"] < 0.7 * fc["exp_range"] else " → journée déjà bien remplie"))
    else:
        lines.append(f"Biais : {esc(b['label'])} ({b['score']:+d})")
        if day:
            lines.append(f"Depuis minuit : {day['chg']:+.1f}$ · range {day['range']:.0f}$")
    blocks = ["\n".join(lines)]
    if ex.get("dp"):
        cf = _conflict(fc["dir"], ex["dp"]) if fc else ""
        blocks.append("💵 " + ix.dp_short_text(ex["dp"]) + ("\n" + cf if cf else ""))
    blocks.append(_events_block(_events_on(snapshot["calendar"], today, after=now_utc()),
                                "📅 <b>Cet après-midi / ce soir</b>"))
    nb = _top_news(snapshot["news"], 6, 4)
    if nb:
        blocks.append("📰 <b>News depuis ce matin</b>\n" + "\n".join(
            f"{'🟢' if n['impact'] > 0 else '🔴'} ({n['impact']:+d}) {esc(n['title'])}" for n in nb))
    ai_txt = None
    if ai_available():
        ai_txt = ask_ai(f"""Stratège or (XAUUSD). En français, 3 lignes max, texte brut : le scénario du matin tient-il,
quoi faire pour la séance US, le piège à éviter. DONNÉES : {json.dumps({'update': lines, 'contexte': _context(snapshot, 6)}, ensure_ascii=False, default=str)}""")
        if ai_txt:
            blocks.append("🧠 " + esc(ai_txt))
    msg = "\n\n".join(blocks)
    telegram(msg, state, kind="ny_update")
    return {"date": now_utc().isoformat(), "text": msg, "ai": bool(ai_txt)}


def _evaluate(fc, last, rng):
    mv = last - fc["p0"]
    exp = fc.get("exp_range") or 1
    d = fc["dir"]
    if d == "up":
        res = "hit" if mv >= 0.15 * exp else "miss" if mv <= -0.15 * exp else "flat"
    elif d == "down":
        res = "hit" if mv <= -0.15 * exp else "miss" if mv >= 0.15 * exp else "flat"
    else:
        res = "hit" if abs(mv) <= 0.3 * exp else "miss"
    return res, mv


def track_summary(state):
    tr = state.get("track") or []
    hits = sum(1 for t in tr if t["res"] == "hit")
    miss = sum(1 for t in tr if t["res"] == "miss")
    flat = sum(1 for t in tr if t["res"] == "flat")
    last20 = tr[-20:]
    h20 = sum(1 for t in last20 if t["res"] == "hit")
    m20 = sum(1 for t in last20 if t["res"] == "miss")
    by = {}
    for d in ("up", "down", "range"):
        x = [t for t in tr if t["dir"] == d]
        hh, mm = sum(1 for t in x if t["res"] == "hit"), sum(1 for t in x if t["res"] == "miss")
        by[d] = {"n": len(x), "rate": round(hh / (hh + mm) * 100) if hh + mm else None}
    return {"n": len(tr), "hits": hits, "miss": miss, "flat": flat,
            "rate": round(hits / (hits + miss) * 100) if hits + miss else None,
            "rate20": round(h20 / (h20 + m20) * 100) if h20 + m20 else None,
            "by_dir": by, "last": tr[-15:]}


def evening_recap(snapshot, state, mkt, ex):
    g = _gold(snapshot)
    if not g:
        return None
    today = _today_paris()
    day = ix.session(ix.intra(mkt, "GOLD"), ix.paris_midnight())
    last = g["price"]
    fc = (state.get("forecasts") or {}).get(str(today))
    lines = [f"🌙 <b>BILAN DU JOUR — {fmt_paris(now_utc(), '%A %d/%m').upper()}</b>"]
    if day:
        lines.append(f"Or : <b>{day['chg']:+.1f}$</b> depuis minuit · plus haut {day['high']:.1f} "
                     f"({fmt_paris(day['t_high'].to_pydatetime(), '%Hh%M')}) / plus bas {day['low']:.1f} "
                     f"({fmt_paris(day['t_low'].to_pydatetime(), '%Hh%M')}) · range {day['range']:.0f}$")
    blocks = ["\n".join(lines)]
    if fc:
        res, mv = _evaluate(fc, last, day["range"] if day else 0)
        icon = {"hit": "✅ PRÉVISION JUSTE", "miss": "❌ PRÉVISION FAUSSE", "flat": "➖ JOURNÉE SANS DIRECTION"}[res]
        ev = [f"<b>{icon}</b>",
              f"Prévu ce matin : {DIR_TXT[fc['dir']]} ({fc['score']:+d}) à {fc['p0']:.1f} → maintenant {last:.1f} ({mv:+.1f}$)"]
        if day and fc.get("exp_range"):
            ev.append(f"Range : {day['range']:.0f}$ réalisé vs ~{fc['exp_range']:.0f}$ attendu "
                      f"({day['range'] / fc['exp_range'] * 100:.0f}%)")
        if day:
            touched = [k for k, v in fc["levels"].items() if day["low"] <= v <= day["high"]]
            if touched:
                ev.append("Niveaux touchés : " + ", ".join(touched))
        blocks.append("\n".join(ev))
        tr = state.setdefault("track", [])
        tr[:] = [t for t in tr if t["date"] != str(today)]
        tr.append({"date": str(today), "dir": fc["dir"], "res": res, "mv": round(mv, 1),
                   "range": round(day["range"], 1) if day else None, "exp": fc.get("exp_range")})
        del tr[:-250]
    else:
        blocks.append("<i>Pas de prévision ce matin (app lancée en cours de journée) : bilan sans note.</i>")
    s = track_summary(state)
    if s["n"]:
        lst = "".join({"hit": "✅", "miss": "❌", "flat": "➖"}[t["res"]] for t in s["last"][-10:])
        blocks.append(f"📈 <b>Fiabilité des prévisions</b> : {s['rate'] if s['rate'] is not None else '—'}% "
                      f"de bonnes directions ({s['hits']} ✅ / {s['miss']} ❌ / {s['flat']} ➖ sur {s['n']} jours)\n"
                      f"20 derniers jours : {s['rate20'] if s['rate20'] is not None else '—'}%  ·  {lst}"
                      + ("\n<i>Encore peu de jours : attends ~20 jours avant de juger.</i>" if s["n"] < 20 else ""))
    dc = ix.day_changes(mkt)
    mv_lines = []
    for k, nm in (("DXY", "DXY"), ("US10Y", "Taux 10 ans"), ("OIL", "Pétrole"), ("EURUSD", "EUR/USD"), ("SPX", "S&P 500"), ("SILVER", "Argent")):
        v = dc.get(k)
        if v is not None:
            mv_lines.append(f"{nm} {v * 100:+.1f} pb" if k == "US10Y" else f"{nm} {v:+.2f}%")
    if mv_lines:
        blocks.append("🌍 <b>Actifs corrélés aujourd'hui</b> : " + " · ".join(mv_lines))
    nb = _top_news(snapshot["news"], 16, 4)
    if nb:
        blocks.append("📰 <b>Ce qui a fait bouger</b>\n" + "\n".join(
            f"{'🟢' if n['impact'] > 0 else '🔴'} ({n['impact']:+d}) {esc(n['title'])}" for n in nb))
    tmr = today + timedelta(days=1)
    if tmr.weekday() >= 5:
        tmr = today + timedelta(days=7 - today.weekday())
    if tmr.weekday() == 0 and today.weekday() >= 4:
        blocks.append("📅 <b>Semaine prochaine</b> : calendrier complet dans la prévision de lundi 7h. Bon week-end 🍻")
    else:
        blocks.append(_events_block(_events_on(snapshot["calendar"], tmr), f"📅 <b>Demain ({JOURS[tmr.weekday()].lower()})</b>",
                                    with_scen=False))
    msg = "\n\n".join(blocks)
    telegram(msg, state, kind="recap")
    return {"date": now_utc().isoformat(), "text": msg, "ai": False}
