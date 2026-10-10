"""Radar news : RSS + GDELT, scoring IA (Gemini gratuit) ou mots-clés, alertes fortes."""
import hashlib
import re
from datetime import datetime, timedelta, timezone

from . import config
from .common import (ask_ai, ai_available, esc, http_get, log, now_utc,
                     telegram, already_fired, mark_fired, fmt_paris)


def _hash(title):
    t = re.sub(r"[^a-z0-9 ]", "", title.lower())
    t = re.sub(r"\s+", " ", t).strip()[:90]
    return hashlib.md5(t.encode()).hexdigest()[:12]


def _parse_date(entry):
    for k in ("published_parsed", "updated_parsed"):
        v = entry.get(k)
        if v:
            return datetime(*v[:6], tzinfo=timezone.utc)
    return now_utc()


def collect_raw(demo=False):
    if demo:
        return _demo_news()
    import feedparser
    items = []
    for label, url in config.NEWS_FEEDS:
        try:
            feed = feedparser.parse(http_get(url, timeout=20).content)
            for e in feed.entries[:15]:
                title = e.get("title", "").strip()
                src = ""
                if " - " in title:          # Google News: "Titre - Source"
                    title, src = title.rsplit(" - ", 1)
                items.append({"title": title, "source": src or label, "theme": label,
                              "link": e.get("link", ""), "published": _parse_date(e).isoformat()})
        except Exception as ex:
            log(f"RSS {label}: {ex}")
    # GDELT
    try:
        from urllib.parse import quote
        url = ("https://api.gdeltproject.org/api/v2/doc/doc?query=" + quote(config.GDELT_QUERY) +
               "&mode=artlist&format=json&maxrecords=40&timespan=3h&sort=datedesc")
        for a in http_get(url, timeout=25).json().get("articles", []):
            d = a.get("seendate", "")
            try:
                pub = datetime.strptime(d, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except Exception:
                pub = now_utc()
            items.append({"title": a.get("title", "").strip(), "source": a.get("domain", "GDELT"),
                          "theme": "Géopolitique", "link": a.get("url", ""), "published": pub.isoformat()})
    except Exception as ex:
        log("GDELT:", ex)
    return items


def keyword_score(title):
    t = title.lower()
    score, cats, why = 0.0, [], []
    for pat, imp, cat in config.KEYWORDS:
        if re.search(pat, t):
            score += imp
            cats.append(cat)
            why.append(cat)
    if score == 0:
        return 0, "autre", "aucun déclencheur"
    # négation / pause : "will not attack", "pauses strike", "rules out strikes"... = désescalade
    if "géopolitique" in cats and re.search(
            r"\b(not|won't|wont|no plans?|never)\b.{0,25}\b(attack|strike|invade|war|bomb)|"
            r"\b(pause[sd]?|delay[sed]*|hold[s]? off|rule[sd]? out|call[sed]* off|back[s]? down|postpone[sd]?)\b", t):
        return -4, "géopolitique", "désescalade (attaque écartée / reportée) → baissier or"
    # article d'analyse / explication : impact réduit
    if re.search(r"^(how|why|what)\b|what happens next|explainer|analysis|opinion|\?$", t):
        score *= 0.4
    if re.search(config.KEY_ACTORS, t):
        score *= 1.3
    score = max(-10, min(10, round(score)))
    cat = max(set(cats), key=cats.count)
    sens = "haussier" if score > 0 else "baissier"
    return score, cat, f"{sens} or ({', '.join(sorted(set(why)))})"


def ai_score(items):
    """Note un lot de titres avec l'IA. Renvoie {idx: (impact, cat, raison)}."""
    if not items or not ai_available():
        return {}
    lines = "\n".join(f"{i}. {it['title']} ({it['source']})" for i, it in enumerate(items))
    prompt = f"""Tu es un analyste macro senior spécialisé sur l'or (XAUUSD).
Pour chaque titre d'actualité ci-dessous, estime l'impact PROBABLE à court terme sur le prix de l'or :
-10 = très baissier, 0 = sans effet / hors sujet, +10 = très haussier.
Raisonne avec les vrais mécanismes : taux réels, dollar, Fed, valeur refuge (géopolitique),
risque Trump (tarifs, pressions sur la Fed, Iran), achats des banques centrales, inflation.
Sois sévère : la plupart des titres valent entre -3 et +3. Garde ±7 à ±10 pour les vrais chocs.

Réponds UNIQUEMENT en JSON : une liste d'objets
{{"id": numéro, "impact": entier, "cat": "géopolitique|fed|inflation|emploi|dollar|taux|commerce|banques centrales|politique US|or|autre", "raison": "max 15 mots en français"}}

Titres :
{lines}"""
    res = ask_ai(prompt, want_json=True, temperature=0.2)
    out = {}
    if isinstance(res, dict):   # certains modèles renvoient {"items": [...]}
        res = next((v for v in res.values() if isinstance(v, list)), None)
    if isinstance(res, list):
        for r in res:
            try:
                out[int(r["id"])] = (max(-10, min(10, int(r["impact"]))), r.get("cat", "autre"), r.get("raison", ""))
            except Exception:
                pass
    return out


def update_news(state, demo=False, quiet=False):
    seen = state.setdefault("seen_news", [])
    seen_set = set(seen)
    stored = state.setdefault("news", [])
    raw = collect_raw(demo)
    cutoff = now_utc() - timedelta(hours=config.NEWS_MAX_AGE_H)
    fresh = []
    for it in raw:
        if not it["title"]:
            continue
        h = _hash(it["title"])
        if h in seen_set:
            continue
        if datetime.fromisoformat(it["published"]) < cutoff:
            continue
        seen_set.add(h)
        seen.append(h)
        it["id"] = h
        fresh.append(it)
    del seen[:-3000]
    log(f"News : {len(raw)} récupérées, {len(fresh)} nouvelles")

    # IA d'abord sur les plus récentes, mots-clés pour le reste / en secours
    fresh.sort(key=lambda x: x["published"], reverse=True)
    batch = fresh[:config.AI_MAX_NEWS_PER_RUN]
    scored_ai = ai_score(batch) if not demo else {}
    for i, it in enumerate(fresh):
        if i in scored_ai and i < len(batch):
            imp, cat, why = scored_ai[i]
            it.update(impact=imp, cat=cat, raison=why, method="IA")
        else:
            imp, cat, why = keyword_score(it["title"])
            it.update(impact=imp, cat=cat, raison=why, method="mots-clés")

    # l'IA re-note aussi les news récentes déjà en stock qui n'ont été notées que par mots-clés
    if not demo and ai_available():
        room = config.AI_MAX_NEWS_PER_RUN - len(batch)
        lim24 = now_utc() - timedelta(hours=24)
        old_kw = [n for n in stored if n.get("method") == "mots-clés"
                  and datetime.fromisoformat(n["published"]) >= lim24][:max(0, room)]
        if old_kw:
            res = ai_score(old_kw)
            for i, n in enumerate(old_kw):
                if i in res:
                    imp, cat, why = res[i]
                    n.update(impact=imp, cat=cat, raison=why, method="IA")

    stored.extend(fresh)
    stored[:] = [n for n in stored if datetime.fromisoformat(n["published"]) >= cutoff]
    stored.sort(key=lambda x: x["published"], reverse=True)
    # on garde en priorité tout ce qui a un impact, puis le reste
    if len(stored) > config.MAX_NEWS_KEEP:
        important = [n for n in stored if n.get("impact", 0) != 0]
        rest = [n for n in stored if n.get("impact", 0) == 0]
        stored[:] = (important + rest)[:config.MAX_NEWS_KEEP]
        stored.sort(key=lambda x: x["published"], reverse=True)

    # alertes fortes
    for it in fresh:
        if abs(it.get("impact", 0)) >= config.ALERT_NEWS_MIN_IMPACT and not already_fired(state, "news|" + it["id"]):
            mark_fired(state, "news|" + it["id"])
            if quiet:
                continue
            arrow = "🟢 HAUSSIER" if it["impact"] > 0 else "🔴 BAISSIER"
            telegram(
                f"⚡ <b>NEWS À FORT IMPACT OR</b> — {arrow} ({it['impact']:+d}/10)\n\n"
                f"<b>{esc(it['title'])}</b>\n"
                f"📰 {esc(it['source'])} · {fmt_paris(datetime.fromisoformat(it['published']))}\n"
                f"🧠 {esc(it['raison'])} [{it['method']}]\n"
                f"🔗 {esc(it['link'])}", state, kind="news")
    return stored


def news_sentiment(news, hours=24):
    """Moyenne pondérée de l'impact des news récentes, entre -1 et +1."""
    lim = now_utc() - timedelta(hours=hours)
    vals = []
    for n in news:
        if datetime.fromisoformat(n["published"]) >= lim and n.get("impact"):
            age_h = (now_utc() - datetime.fromisoformat(n["published"])).total_seconds() / 3600
            w = max(0.2, 1 - age_h / hours) * (abs(n["impact"]) / 10)
            vals.append((n["impact"] / 10, w))
    if not vals:
        return 0.0, 0
    s = sum(v * w for v, w in vals) / sum(w for _, w in vals)
    return round(s, 3), len(vals)


def _demo_news():
    now = now_utc()
    ex = [
        ("Trump threatens new strikes on Iran nuclear sites", "Reuters", "Trump / Iran"),
        ("Fed's Powell signals rate cut possible in December", "Bloomberg", "Fed"),
        ("Dollar rallies after strong retail sales data", "CNBC", "Dollar"),
        ("China central bank adds gold to reserves for 12th month", "Reuters", "Banques centr."),
        ("Israel and Iran agree to ceasefire talks in Oman", "AP", "Iran / Israël"),
        ("Trump announces 25% tariffs on EU imports", "WSJ", "Tarifs"),
        ("Treasury yields jump as inflation hotter than expected", "FT", "Dette US"),
        ("Gold hits record high above key level", "Kitco", "Or"),
        ("US jobless claims rise, layoffs spread to tech", "MarketWatch", "Emploi US"),
        ("Oil prices steady ahead of OPEC meeting", "Reuters", "Moyen-Orient"),
    ]
    return [{"title": t, "source": s, "theme": th, "link": "https://example.com",
             "published": (now - timedelta(minutes=37 * i)).isoformat()} for i, (t, s, th) in enumerate(ex)]
