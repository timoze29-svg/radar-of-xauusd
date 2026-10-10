"""
RADAR OR (XAUUSD) — configuration centrale.
Tout se règle ici : actifs suivis, sources de news, mots-clés, seuils d'alertes.
"""
import os

# ---------------------------------------------------------------------------
# Secrets (à mettre dans GitHub > Settings > Secrets and variables > Actions)
# ---------------------------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")          # optionnel (gratuit)
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")   # vide = choix auto du modèle Flash le plus récent

TZ_DISPLAY = "Europe/Paris"

# ---------------------------------------------------------------------------
# Actifs suivis (tickers Yahoo Finance, gratuits)
# gold_rel : effet habituel sur l'or quand l'actif MONTE
#   -1 = baissier pour l'or, +1 = haussier pour l'or, 0 = relation variable
# ---------------------------------------------------------------------------
ASSETS = {
    "GOLD":   {"ticker": "GC=F",      "name": "Or (XAUUSD)",       "gold_rel": 1,  "fmt": 2},
    "DXY":    {"ticker": "DX-Y.NYB",  "name": "Dollar Index DXY",  "gold_rel": -1, "fmt": 2},
    "US10Y":  {"ticker": "^TNX",      "name": "Taux US 10 ans",    "gold_rel": -1, "fmt": 3},
    "US05Y":  {"ticker": "^FVX",      "name": "Taux US 5 ans",     "gold_rel": -1, "fmt": 3},
    "SILVER": {"ticker": "SI=F",      "name": "Argent (XAG)",      "gold_rel": 1,  "fmt": 3},
    "OIL":    {"ticker": "CL=F",      "name": "Pétrole WTI",       "gold_rel": 1,  "fmt": 2},
    "VIX":    {"ticker": "^VIX",      "name": "VIX (indice peur)", "gold_rel": 1,  "fmt": 2},
    "SPX":    {"ticker": "^GSPC",     "name": "S&P 500",           "gold_rel": 0,  "fmt": 1},
    "USDJPY": {"ticker": "JPY=X",     "name": "USD/JPY",           "gold_rel": -1, "fmt": 3},
    "EURUSD": {"ticker": "EURUSD=X",  "name": "EUR/USD",           "gold_rel": 1,  "fmt": 5},
    "BTC":    {"ticker": "BTC-USD",   "name": "Bitcoin",           "gold_rel": 0,  "fmt": 0},
    "COPPER": {"ticker": "HG=F",      "name": "Cuivre",            "gold_rel": 0,  "fmt": 4},
}

# ---------------------------------------------------------------------------
# Séries macro FRED (gratuit, sans clé)
# ---------------------------------------------------------------------------
FRED_SERIES = {
    "REAL10Y":   {"id": "DFII10", "name": "Taux réel US 10 ans (TIPS)", "gold_rel": -1},
    "BREAKEVEN": {"id": "T10YIE", "name": "Inflation anticipée 10 ans", "gold_rel": 1},
    "US2Y":      {"id": "DGS2",   "name": "Taux US 2 ans",              "gold_rel": -1},
    "FEDFUNDS":  {"id": "DFF",    "name": "Taux Fed (effectif)",        "gold_rel": -1},
}

COT_GOLD_CODE = "088691"   # COMEX Gold, rapport CFTC

# ---------------------------------------------------------------------------
# Sources de news (RSS gratuits). Ajoute/enlève ce que tu veux.
# ---------------------------------------------------------------------------
def gnews(q):
    from urllib.parse import quote
    return f"https://news.google.com/rss/search?q={quote(q)}+when:1d&hl=en-US&gl=US&ceid=US:en"

NEWS_FEEDS = [
    ("Or",              gnews("gold price")),
    ("Trump",           gnews("Trump Truth Social")),
    ("Trump / Iran",    gnews("Trump Iran")),
    ("Iran / Israël",   gnews("Iran Israel strike")),
    ("Moyen-Orient",    gnews("Middle East escalation")),
    ("Tarifs",          gnews("Trump tariffs")),
    ("Fed",             gnews("Federal Reserve Powell rates")),
    ("Inflation US",    gnews("US inflation CPI")),
    ("Emploi US",       gnews("nonfarm payrolls jobs report")),
    ("Dollar",          gnews("dollar index DXY")),
    ("Banques centr.",  gnews("central bank gold buying")),
    ("Russie/Ukraine",  gnews("Russia Ukraine")),
    ("Chine/Taïwan",    gnews("China Taiwan")),
    ("Dette US",        gnews("US debt Treasury yields")),
]

# GDELT (base mondiale d'événements, gratuite) — requête géopolitique large
GDELT_QUERY = '(gold OR iran OR "federal reserve" OR tariffs OR missile OR sanctions) sourcelang:english'

MAX_NEWS_KEEP = 200          # news gardées dans l'app
NEWS_MAX_AGE_H = 72          # durée de vie d'une news dans l'app
AI_MAX_NEWS_PER_RUN = 30     # limite pour rester dans le gratuit Gemini

# ---------------------------------------------------------------------------
# Scoring des news par mots-clés (utilisé si pas d'IA ou en secours)
# (regex, impact sur l'or de -10 à +10, catégorie)
# ---------------------------------------------------------------------------
KEYWORDS = [
    # Géopolitique -> haussier or
    (r"\b(strike|strikes|airstrike|missile|attack|bomb|invasion|invade|war\b|warfare)", 6, "géopolitique"),
    (r"\b(escalat|retaliat|mobiliz|nuclear)", 6, "géopolitique"),
    (r"\b(sanction)", 4, "géopolitique"),
    (r"\b(hormuz|strait)", 6, "géopolitique"),
    (r"\b(coup|assassinat|terror)", 5, "géopolitique"),
    # Désescalade -> baissier or
    (r"\b(ceasefire|cease-fire|truce|peace (deal|talks|agreement)|de-escalat|deal reached|hostages? released)", -5, "géopolitique"),
    # Fed / taux
    (r"\b(rate cut|cuts? rates|dovish|easing|pivot)", 6, "fed"),
    (r"\b(rate hike|hikes? rates|hawkish|tightening|higher for longer)", -6, "fed"),
    (r"\b(fire powell|powell (fired|out|resign)|fed independence)", 7, "fed"),
    # Inflation / emploi
    (r"\b(inflation (cools|eases|slows|falls)|cpi (cools|eases|lower))", 4, "inflation"),
    (r"\b(inflation (hot|surges|jumps|accelerat|rises)|hotter.than.expected)", -3, "inflation"),
    (r"\b(jobs? (miss|weak|slump)|unemployment (rises|jumps)|layoffs|recession)", 5, "emploi"),
    (r"\b(jobs? (beat|strong|surge)|payrolls (beat|surge))", -4, "emploi"),
    # Dollar / taux
    (r"\b(dollar (falls|slides|weakens|tumbles|drops))", 5, "dollar"),
    (r"\b(dollar (rises|rallies|strengthens|surges|jumps))", -5, "dollar"),
    (r"\b(yields? (fall|drop|slide|tumble))", 4, "taux"),
    (r"\b(yields? (rise|jump|surge|climb|spike))", -4, "taux"),
    # Commerce / Trump
    (r"\b(tariff|trade war|import tax)", 4, "commerce"),
    (r"\b(trade deal|tariff (pause|relief|exemption))", -3, "commerce"),
    (r"\b(shutdown|default|debt ceiling)", 4, "politique US"),
    # Demande d'or
    (r"\b(central banks? (buy|add|purchas)|gold reserves|pboc gold)", 5, "banques centrales"),
    (r"\b(gold (record|all-time high|surges|soars))", 3, "or"),
    (r"\b(gold (slumps|tumbles|plunges|selloff))", -3, "or"),
]

# Mots qui renforcent l'importance d'une news (multiplicateur)
KEY_ACTORS = r"\b(trump|powell|fed|iran|israel|putin|xi jinping|opec|treasury|bessent)\b"

# ---------------------------------------------------------------------------
# Alertes Telegram
# ---------------------------------------------------------------------------
ALERT_NEWS_MIN_IMPACT = 7            # |impact| >= 7 -> alerte
BIG_MOVE_ATR = 1.5                   # mouvement du jour > 1.5 x ATR = alerte
ALERT_PREV_DAY_ASSETS = ["GOLD", "DXY", "US10Y"]   # cassure plus haut/bas de la veille
CORR_BREAK_MIN = 0.4                 # corrélation 60j min pour surveiller une casse

# ---------------------------------------------------------------------------
# INTERRUPTEURS : mets False pour ne plus recevoir un type de message Telegram
# ---------------------------------------------------------------------------
ALERTS = {
    "weekly":          True,   # 🗓 prévision de la semaine (lundi matin)
    "daily":           True,   # ☀️ prévision du jour (7h)
    "ny_update":       True,   # 🗽 mise à jour avant New York (14h)
    "recap":           True,   # 🌙 bilan prévision vs réalité (22h)
    "pre_event":       True,   # ⏳ pré-alertes 1h et 15 min avant les annonces
    "post_event":      True,   # 📊 récap 30 min après les grosses annonces
    "dollar_pressure": True,   # ⚠️ dollar sous pression / dollar en force
    "news_burst":      True,   # 🔥 news en rafale
    "news":            True,   # ⚡ news à fort impact
    "breakout":        True,   # 🚀 cassures de niveaux
    "big_move":        True,   # 🌋 mouvements anormaux
    "corr":            True,   # 🔀 cassures de corrélation
    "cycle":           True,   # 🔄 cycle hebdo
    "bias":            True,   # 🧭 changement de biais
}

# Heures d'envoi (heure de Paris, lundi→vendredi). Le changement d'heure été/hiver est géré tout seul.
DAILY_HOUR = 7          # prévision du jour (+ prévision de la semaine le lundi)
NY_UPDATE_HOUR = 14     # mise à jour avant l'ouverture de New York
RECAP_HOUR = 22         # bilan du soir

# Pré-alertes annonces
PRE_EVENT_1H = True
PRE_EVENT_15M = True
POST_EVENT_DELAY_MIN = 30

# Pression dollar : mouvement sur 1h à partir duquel un signal compte
DP_WINDOW_MIN = 60
DP_TH = {"DXY": 0.10, "US10Y": 0.02, "OIL": 0.6, "EURUSD": 0.10}   # % (taux : en points, 0.02 = 2 pb)
DP_MIN_SIGNALS = 3          # nb de signaux alignés (sur 4) pour déclencher l'alerte
DP_HORIZON_H = 2            # horizon des probabilités historiques (heures)
DP_COOLDOWN_H = 3           # pas de nouvelle alerte dans le même sens avant X heures

# News en rafale
BURST_WINDOW_MIN = 45
BURST_MIN_COUNT = 6
BURST_FACTOR = 3.0          # x fois plus d'articles que la normale
BURST_TOPICS = {
    "Trump":            r"\btrump\b",
    "Iran":             r"\biran",
    "Fed / Powell":     r"\b(fed|powell|fomc|federal reserve)\b",
    "Tarifs douaniers": r"\btariff",
    "Israël":           r"\bisrael",
    "Chine":            r"\b(china|chinese|beijing|xi jinping)\b",
    "Russie / Ukraine": r"\b(russia|putin|ukraine|kremlin)\b",
    "Pétrole / Hormuz": r"\b(oil|opec|hormuz|crude)\b",
    "Or":               r"\bgold\b",
}
