# 🥇 RADAR OR — XAUUSD

Ton radar macro 100 % gratuit pour l'or. Il tourne tout seul 24h/24 sur GitHub et fait tout ça :

- **Il fouille les news en continu** : Trump, Iran/Israël, Fed, inflation, emploi, dollar, tarifs, Russie, Chine, banques centrales. Les sources sont Google News (14 flux) et GDELT (base mondiale d'événements).
- **Il note chaque news** de -10 à +10 selon son impact sur l'or. Avec l'IA Gemini (gratuite) si elle est configurée, sinon avec un moteur de mots-clés.
- **Il suit 12 actifs corrélés** : DXY, taux US 10 ans et 5 ans, argent, pétrole, VIX, S&P 500, USD/JPY, EUR/USD, Bitcoin, cuivre. Pour chacun, il calcule la corrélation avec l'or sur 20 jours, 60 jours et 1 an.
- **Il détecte les cassures importantes** : plus haut ou plus bas de la veille, de la semaine passée, sur 20 jours, sur 1 an, plus les mouvements anormaux (supérieurs à 1,5× l'ATR). À chaque fois tu reçois une alerte Telegram avec la lecture pour l'or.
- **Il repère les cassures de corrélation** (le lien habituel avec l'or se casse = changement de régime) et t'envoie une alerte.
- **Cycle hebdo lun→mer / jeu→ven** : les stats réelles sur ~6 ans de XAUUSD, le suivi en live de la semaine, une alerte le mercredi soir avec les zones de retour (38,2 / 50 / 61,8 %), puis une alerte quand l'inversion se confirme… ou quand elle échoue.
- **Score de biais macro de -100 à +100.** Il combine :
  - le dollar
  - les taux 10 ans
  - les taux réels
  - les anticipations sur la Fed
  - le momentum de l'or
  - le sentiment des news
  - le VIX
  - le COT

  Tu reçois une alerte quand le biais change de camp.
- **Calendrier éco** filtré sur ce qui fait bouger l'or.
- **Dashboard web** (PC et mobile) qui se met à jour tout seul.

### 📲 Ta journée sur Telegram (heure de Paris, lundi → vendredi)

| Heure | Message |
|---|---|
| **7h00** | ☀️ **Prévision du jour** : biais et ses 3 raisons, session Asie, range attendu, niveaux du jour (pivots, plus haut et plus bas de la veille), annonces du jour avec scénarios « au-dessus / en dessous de la prévision », stats réelles du jour, scénario principal et alternatif |
| **Lundi 7h00** | 🗓 **Prévision de la semaine**, en plus de celle du jour |
| **1h avant** une grosse annonce | ⏳ **Pré-alerte** avec les scénarios pour l'or et le contexte (DXY, taux, biais, pression dollar) |
| **15 min avant** | ⏰ **Zone dangereuse** : pas d'entrée, sécurise tes stops |
| **30 min après** | 📊 **Récap** : réaction du DXY, des taux et de l'or, lecture dure ou douce, mouvement qui tient ou qui s'essouffle |
| **14h00** | 🗽 **Update avant New York** : le scénario du matin tient-il, range déjà fait, annonces de l'après-midi |
| **22h00** | 🌙 **Bilan** : prévision vs réalité, avec le **taux de réussite** sur la durée |
| **En continu** | ⚠️ **Dollar sous pression / en force**<br>🔥 **News en rafale**<br>🚀 **Cassures**<br>⚡ **News chaudes**<br>🔄 **Cycle hebdo**<br>🧭 **Changement de biais** |

**⚠️ « Dollar sous pression ».** Sur la dernière heure, l'app regarde 4 signaux :
- le DXY
- le taux 10 ans
- le pétrole
- l'EUR/USD

Elle regarde aussi les news Fed et dollar. Quand au moins 3 signaux sur 4 vont dans le même sens, tu reçois une alerte avec la **vraie probabilité historique**, calculée sur environ 2 ans de données horaires : *« dans cette config, le dollar a continué dans X % des cas et l'or a monté dans Y % des cas sur 2h »*.

**📊 Probabilités réelles, jamais inventées.** Tous les pourcentages viennent de l'historique :
- les stats du jour de la semaine
- ce qui se passe après une veille forte
- l'heure habituelle du plus haut et du plus bas du jour
- le taux de réussite des cassures
- la pression dollar

Si un avantage est faible (autour de 50 %), l'app te le dit.

---

## ⚙️ INSTALLATION (environ 20 min, une seule fois)

### Étape 1 — Créer le bot Telegram (3 min)
1. Sur Telegram, ouvre **@BotFather** et envoie `/newbot`.
2. Choisis un nom (ex : `Radar Or Timote`) puis un identifiant qui finit par `bot` (ex : `radar_or_timote_bot`).
3. BotFather te donne un **token** du genre `7412345678:AAH...`. **Garde-le.**
4. Ouvre ton nouveau bot et clique **Démarrer** (sinon il ne pourra pas t'écrire).
5. Ouvre **@userinfobot** et envoie-lui un message. Il te répond avec ton **Id** (un nombre). C'est ton **CHAT_ID**.

### Étape 2 — Clé IA gratuite Gemini (2 min, optionnel mais conseillé)
1. Va sur **https://aistudio.google.com/apikey**.
2. Connecte-toi avec ton compte Google et clique **Create API key**.
3. Copie la clé (`AIza...`).

> Sans cette clé, tout marche quand même : les news sont notées par mots-clés et les prévisions utilisent des scénarios automatiques. Avec la clé, l'IA note chaque news et rédige la prévision du lundi comme un vrai stratège.

### Étape 3 — Mettre le projet sur GitHub (8 min)
1. Crée un compte sur **https://github.com** si tu n'en as pas.
2. Clique **+** (en haut à droite), puis **New repository**.
   - Nom : `radar-or`
   - ⚠️ Coche **Public**. C'est obligatoire pour que GitHub Actions et le site soient gratuits et illimités. Tes clés restent secrètes, elles ne sont jamais visibles.
   - Clique **Create repository**.
3. Clique **uploading an existing file** et glisse **tout le contenu** du dossier `radar-or` dézippé : `main.py`, `requirements.txt`, `README.md`, les dossiers `src`, `docs`, `data`. Puis **Commit changes**.
4. ⚠️ Le dossier `.github` est caché (il commence par un point). Sur Mac ou Windows, il ne part pas toujours avec le glisser-déposer. Pour être sûr :
   - clique **Add file → Create new file**
   - dans le nom, tape exactement `.github/workflows/radar.yml`
   - colle dedans le contenu du fichier `.github/workflows/radar.yml` du zip
   - clique **Commit changes**

### Étape 4 — Mettre tes clés secrètes (3 min)
Dans ton repo, va dans **Settings → Secrets and variables → Actions → New repository secret** et crée :

| Nom du secret | Valeur |
|---|---|
| `TELEGRAM_TOKEN` | le token donné par BotFather |
| `TELEGRAM_CHAT_ID` | ton Id donné par @userinfobot |
| `GEMINI_API_KEY` | ta clé Gemini (optionnel) |

### Étape 5 — Activer le site (2 min)
1. **Settings → Pages**.
2. Source : **Deploy from a branch**. Branch : **main**, dossier **/docs**. Clique **Save**.
3. Une minute après, ton app est en ligne sur : `https://TON-PSEUDO.github.io/radar-or/`

👉 Sur ton téléphone, ouvre ce lien puis **Partager → Sur l'écran d'accueil**. Tu as ton app comme une vraie application.

### Étape 6 — Lancer et tester (2 min)
1. Onglet **Actions**. Si GitHub demande d'activer les workflows, clique **I understand… enable**.
2. Clique **Radar Or** (à gauche), puis **Run workflow** et tape `test` → tu dois recevoir *« Radar Or connecté ! »* sur Telegram ✅
3. Relance **Run workflow** avec `daily` → tu reçois ta première prévision du jour (`weekly` pour celle de la semaine, `update` et `recap` pour tester les autres).
4. Ensuite tout tourne seul. Le scan passe toutes les 15 min et les rapports arrivent à l'heure (7h, 14h, 22h, heure de Paris).

> Le tout premier scan est silencieux. Il mémorise les cassures déjà en place pour ne pas t'envoyer 20 alertes d'un coup.

---

## 🔧 Personnaliser

Tout se règle dans **`src/config.py`**. Tu peux le modifier directement sur GitHub avec le crayon ✏️.

- **`ALERTS`** : un interrupteur par type de message. Mets `False` pour couper ce que tu ne veux plus recevoir, par exemple `"news_burst": False`.
- **`DAILY_HOUR = 7`, `NY_UPDATE_HOUR = 14`, `RECAP_HOUR = 22`** : les heures d'envoi, en heure de Paris.
- **`DP_TH`** : les seuils de la pression dollar.
  - Par défaut : DXY ±0,10 %, taux ±2 pb, pétrole ±0,6 %, EUR/USD ±0,10 % sur 1h.
  - Monte-les pour recevoir moins d'alertes.
- **`DP_MIN_SIGNALS = 3`** : passe à `4` pour n'avoir que les configurations les plus nettes.
- **`BURST_TOPICS`** et **`BURST_MIN_COUNT`** : les sujets surveillés pour les news en rafale, et le nombre d'articles qui déclenche l'alerte.
- **`ASSETS`**, **`NEWS_FEEDS`**, **`KEYWORDS`** : les actifs, les sources de news et les mots-clés.
- **`ALERT_NEWS_MIN_IMPACT = 7`** : le seuil des news chaudes.
- **`BIG_MOVE_ATR = 1.5`** : le seuil des mouvements anormaux.

## ❓ Bon à savoir (honnêtement)

- **Délai** : c'est du *quasi* temps réel. Les rapports de 7h, 14h et 22h peuvent arriver avec quelques minutes de retard. Le scan tourne toutes les 15 min, et GitHub peut avoir 2 à 10 min de retard aux heures chargées. Les prix Yahoo ont quelques minutes de délai. Pour de la macro et des cassures H1/H4/D1, c'est parfait. Pour scalper la news à la seconde, non.
- **Prix de l'or** : il vient du future **GC=F**, qui a quelques dollars d'écart avec le spot XAUUSD de ton broker. Les niveaux et les cassures restent valables, mais compare avec ton graphique MT5 / TradingView. Si Yahoo bloque, l'app bascule sur le **spot XAUUSD de Stooq**.
- **Cycle hebdo** : l'app te donne les vraies stats (le pourcentage de semaines où l'inversion a eu lieu). Si le chiffre tourne autour de 50 %, ça veut dire que le pattern n'est **pas** fiable seul. Utilise-le avec le biais macro et le calendrier (une semaine avec le NFP le vendredi casse souvent le schéma).
- **Gemini gratuit** : il a un quota journalier. Si le quota est dépassé, le système bascule automatiquement sur les mots-clés et rien ne plante.
- **Si le workflow s'arrête** : GitHub désactive les tâches planifiées d'un repo public sans activité pendant 60 jours. Ici le bot commit toutes les 15 min, donc ça ne devrait pas arriver. Si jamais c'est le cas : onglet Actions → **Enable workflow**.

## 🧪 Tester sur ton PC (optionnel)
```bash
pip install -r requirements.txt
python main.py scan --demo     # données simulées, sans internet
python main.py daily --demo --loud   # affiche la prévision du jour + toutes les alertes de démo
python main.py daily           # vraies données (messages affichés dans la console si Telegram n'est pas configuré)
```
Puis ouvre `docs/index.html` via un petit serveur : `cd docs && python -m http.server`, et va sur http://localhost:8000.

*Outil d'aide à la décision, pas un conseil financier.*
