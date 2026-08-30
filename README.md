# 🤖 Trading Bot — Robot d'investissement automatique

Robot de trading qui tourne quotidiennement, analyse le marché et les news via un agent IA (Llama 3.3 70B via Groq), et exécute des décisions d'investissement. Inclut un dashboard local pour suivre la performance en temps réel.

`main.py` est **idempotent et rattrape automatiquement les jours manqués** : s'il n'a pas tourné depuis plusieurs jours (panne, machine éteinte, cron raté...), il rejoue un cycle de décision complet pour chaque jour de marché manqué (prix de clôture historiques réels) avant de traiter le jour courant. Lancer `python main.py` plusieurs fois le même jour ne repasse jamais d'ordres en double. Voir [Rattrapage des jours manqués](#rattrapage-des-jours-manqués).

## Architecture

```
trading-bot/
├── main.py              # Point d'entrée (run quotidien)
├── config.py            # Configuration (capital, API keys, univers)
├── market_data.py       # Données de marché temps réel (yfinance)
├── news_analyzer.py     # Actualités financières (RSS + Yahoo)
├── ai_agent.py          # Agent IA décisionnel (Groq/Llama)
├── portfolio.py         # Gestion du portefeuille + persistance JSON
├── local_storage.py     # Stockage local CSV + Excel
├── google_sheets.py     # Interface Google Sheets (optionnel)
├── requirements.txt     # Dépendances Python
├── dashboard/           # Dashboard web local
│   ├── app.py           # Serveur Flask + logique graphiques
│   └── templates/
│       └── index.html   # Interface Plotly + Tailwind (dark mode)
├── data/                # Données (auto-générées)
│   ├── transactions.csv
│   ├── portefeuille.csv
│   └── journal.csv
├── state/               # État du portefeuille
│   ├── portfolio_state.json  # Cash, positions, last_run_date (pour le rattrapage)
│   └── run.lock          # Verrou anti-concurrence (créé/supprimé automatiquement)
└── credentials/         # Credentials (non versionné)
    └── service_account.json
```

## Dashboard Local

Interface web interactive sur `http://localhost:5000` :

- **KPIs** — Valeur totale, PnL, cash, positions, frais, win rate
- **Graphique temporel** — Cours des actifs (3 mois) + marqueurs BUY ▲ / SELL ▼ + RSI
- **Trading Bot vs Lump Sum** — Comparaison en temps réel de la performance du bot vs une stratégie passive (10 000 € + 500 €/mois sur ETF MSCI World)
- **Performance vs Benchmark** — Courbe du portefeuille vs MSCI World normalisé
- **Pie chart** — Répartition des actifs + cash
- **Encart DroneShield** — Analyse IA dédiée (sentiment, recommandation, montant)
- **Tableau positions** — PRU, prix actuel, PnL par position
- **Journal IA** — Analyses quotidiennes du bot
- **Métriques** — Win rate, max drawdown, PnL total

### Lancer le dashboard

```bash
python dashboard/app.py
```

Puis ouvrir : **http://localhost:5000**

Le dashboard se rafraîchit automatiquement toutes les 5 minutes pendant les heures de marché (8h-22h).

Au démarrage, le dashboard **exécute automatiquement `main.py` en arrière-plan** (rattrapage des jours manqués + jour courant si besoin) — le dashboard reste utilisable immédiatement pendant ce temps, avec une bannière en haut de page indiquant que la mise à jour est en cours (statut interrogeable via `/api/bootstrap-status`). Si le bot a déjà tourné aujourd'hui, ce run automatique ne fait rien de plus (voir section suivante).

## Setup

### 1. Installer les dépendances
```bash
pip install -r requirements.txt
```

### 2. Configurer les API keys

Créer un fichier `.env` :
```
OPENAI_API_KEY=gsk_...       # Clé API Groq
AI_MODEL=openai/gpt-oss-120b
```

### 3. (Optionnel) Google Sheets

Pour logger aussi dans Google Sheets :
- Créer un compte de service Google Cloud
- Placer le JSON dans `credentials/service_account.json`
- Renseigner `GOOGLE_SHEETS_ID` dans `.env`

## Utilisation quotidienne

```bash
python main.py
```

Le bot va :
1. Charger l'état du portefeuille
2. Récupérer les prix de marché en temps réel
3. Récupérer les actualités financières
4. Demander à l'IA ses recommandations
5. Exécuter les achats/ventes
6. Logger les résultats en CSV (+ Google Sheets si configuré)

## Rattrapage des jours manqués

Le portefeuille garde en mémoire (`state/portfolio_state.json` → `last_run_date`) la date du dernier cycle exécuté avec succès, même si ce cycle n'a rien fait (HOLD). Au lancement, `main.py` :

1. Calcule les jours ouvrés (lun-ven) manqués entre `last_run_date` et aujourd'hui.
2. Pour chaque jour manqué, rejoue un cycle complet — **prix de clôture réels de ce jour-là** (récupérés via yfinance), décision de l'agent IA, exécution des achats/ventes si pertinent, log daté sur ce jour précis (transactions, portefeuille, journal).
3. Exécute ensuite le jour courant normalement (prix en temps réel), sauf s'il a déjà tourné aujourd'hui — dans ce cas il s'arrête sans rien refaire.

Limites à connaître :
- **Actualités** : les APIs gratuites utilisées (RSS, Yahoo Finance) ne donnent que l'actualité *actuelle*, pas d'archive par date passée. Pour les jours rattrapés, le bot réutilise donc les actualités disponibles au moment du rattrapage (clairement indiqué dans le prompt envoyé à l'IA), pas les actualités réelles de ce jour-là.
- **Jours fermés** : si un jour manqué n'a pas de séance (week-end, jour férié), il est ignoré silencieusement (aucune donnée de prix ce jour-là).
- **Nombre de jours** : rattrapage limité à `MAX_CATCHUP_DAYS` (15 par défaut, `config.py`) par run pour ne pas saturer l'API IA — le reste est rattrapé au(x) lancement(s) suivant(s).
- **Concurrence** : un verrou fichier (`state/run.lock`) empêche deux `run_daily()` de tourner en même temps (ex. plusieurs process dashboard qui redémarrent simultanément) — le second se termine sans rien dupliquer.

Le rattrapage se déclenche aussi bien via `python main.py` que via le lancement automatique du dashboard (voir ci-dessous).

## Univers d'investissement

- **ETFs monde** : IWDA, VWCE, CSPX, EUNL
- **ETFs sectoriels** : IT, Healthcare, Energy
- **Actions US** : AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA
- **Actions Europe** : LVMH, ASML, SAP, Siemens
- **Défense** : LMT, RTX, NOC, BA, Thales, DroneShield (DRO.AX)
- **Asie** : SoftBank, Samsung
- **Or** : SGLD

## Automatisation (cron)

Pour exécuter automatiquement chaque jour à 17h (après les marchés EU) :
```bash
crontab -e
# Ajouter :
0 17 * * 1-5 cd /path/to/trading-bot && python main.py >> logs/daily.log 2>&1
```

Comme `main.py` rattrape désormais automatiquement les jours manqués (voir [Rattrapage des jours manqués](#rattrapage-des-jours-manqués)), une panne ponctuelle du cron ou de la machine n'est plus bloquante : le prochain lancement (cron suivant, ou simplement l'ouverture du dashboard) rattrape ce qui a été manqué.

## Paramètres

| Paramètre | Valeur |
|-----------|--------|
| Capital initial | 10 000 € |
| Apport mensuel | 500 € |
| Frais de transaction | 0,25% |
| Positions max | 12 |
| Max par position | 15% du portfolio |
| Cash minimum | 10% |
| Univers | ETFs + Actions mondiales (20 actifs) |

## Google Sheets — Feuilles

| Feuille | Contenu |
|---------|---------|
| **Transactions** | Chaque achat/vente avec date, montant, frais, PnL, raisonnement |
| **Portefeuille** | Snapshot quotidien (valeur, cash, PnL, sentiment) |
| **Journal** | Analyse IA du jour, décisions prises, sentiment |
