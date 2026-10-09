"""Outils communs : état persistant, cache, Telegram, IA Gemini, heure."""
import html
import json
import os
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from . import config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(ROOT, "data", "state.json")
DATA_PATH = os.path.join(ROOT, "docs", "data.json")
PARIS = ZoneInfo(config.TZ_DISPLAY)
UA = {"User-Agent": "Mozilla/5.0 (RadarOr; +github actions)"}


def now_utc():
    return datetime.now(timezone.utc)


def to_paris(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PARIS)


def fmt_paris(dt, f="%a %d/%m %H:%M"):
    full = {"Monday": "Lundi", "Tuesday": "Mardi", "Wednesday": "Mercredi", "Thursday": "Jeudi",
            "Friday": "Vendredi", "Saturday": "Samedi", "Sunday": "Dimanche"}
    jours = {"Mon": "Lun", "Tue": "Mar", "Wed": "Mer", "Thu": "Jeu", "Fri": "Ven", "Sat": "Sam", "Sun": "Dim"}
    s = to_paris(dt).strftime(f)
    for en, fr in full.items():
        s = s.replace(en, fr)
    for en, fr in jours.items():
        s = s.replace(en, fr)
    return s


def log(*a):
    print(f"[{now_utc():%H:%M:%S}]", *a, flush=True)


# ---------------------------------------------------------------- état
def load_state():
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)


def cache_get(state, key, max_age_s):
    c = state.get("cache", {}).get(key)
    if c and time.time() - c.get("ts", 0) < max_age_s:
        return c.get("data")
    return None


def cache_set(state, key, data):
    state.setdefault("cache", {})[key] = {"ts": time.time(), "data": data}


def already_fired(state, key):
    return key in state.get("fired", {})


def mark_fired(state, key):
    fired = state.setdefault("fired", {})
    fired[key] = time.time()
    # purge > 21 jours
    lim = time.time() - 21 * 86400
    for k in [k for k, v in fired.items() if v < lim]:
        del fired[k]


def http_get(url, timeout=20, **kw):
    r = requests.get(url, headers=UA, timeout=timeout, **kw)
    r.raise_for_status()
    return r


# ---------------------------------------------------------------- Telegram
def esc(s):
    return html.escape(str(s), quote=False)


def telegram(text, state=None, kind="info"):
    """Envoie un message Telegram (HTML). Garde aussi un historique pour l'app."""
    if not config.ALERTS.get(kind, True):
        log(f"[{kind} désactivé dans config.ALERTS] message non envoyé")
        return False
    if state is not None:
        hist = state.setdefault("alerts", [])
        hist.insert(0, {"ts": now_utc().isoformat(), "kind": kind, "text": text})
        del hist[60:]
    if not (config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT_ID):
        if os.getenv("RADAR_DEBUG"):
            log(f"[TELEGRAM non configuré · {kind}]\n" + text + "\n" + "-" * 60)
        else:
            log(f"[TELEGRAM non configuré · {kind}] ", text[:160].replace("\n", " | "))
        return False
    ok = True
    # découpe sur les lignes (évite de couper une balise HTML)
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800 and cur:
            chunks.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    for ch in chunks:
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": config.TELEGRAM_CHAT_ID, "text": ch,
                      "parse_mode": "HTML", "disable_web_page_preview": True},
                timeout=20)
            if r.status_code != 200:
                log("Telegram erreur", r.status_code, r.text[:200])
                ok = False
        except Exception as e:
            log("Telegram exception", e)
            ok = False
        time.sleep(0.5)
    return ok


# ---------------------------------------------------------------- IA (Gemini gratuit)
def ai_available():
    return bool(config.GEMINI_API_KEY)


def ask_ai(prompt, want_json=False, temperature=0.4):
    """Appelle Gemini (palier gratuit). Renvoie texte / objet JSON, ou None si échec."""
    if not ai_available():
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{config.GEMINI_MODEL}:generateContent?key={config.GEMINI_API_KEY}")
    body = {"contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature}}
    if want_json:
        body["generationConfig"]["responseMimeType"] = "application/json"
    for attempt in range(2):
        try:
            r = requests.post(url, json=body, timeout=60)
            if r.status_code == 429:
                log("IA: quota gratuit atteint, secours mots-clés")
                return None
            r.raise_for_status()
            txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
            if want_json:
                txt = txt.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
                return json.loads(txt)
            return txt.strip()
        except Exception as e:
            log("IA erreur:", e)
            time.sleep(2)
    return None
