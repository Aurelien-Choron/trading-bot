# 🤖 Trading Bot — an autonomous investment agent

A trading bot that runs daily, reads the market and the news through an AI agent
(served by [Groq](https://groq.com), `openai/gpt-oss-120b` by default), and acts on
its decisions. Ships with a local dashboard to follow performance in real time.

`main.py` is **idempotent and catches up on missed days automatically**: if it has
not run for several days (outage, machine off, missed cron...), it replays a full
decision cycle for every missed market day — using that day's real closing prices —
before handling the current day. Running `python main.py` several times on the same
day never places duplicate orders. See [Catching up on missed days](#catching-up-on-missed-days).

## Architecture

```
trading-bot/
├── main.py              # Entry point (daily run)
├── config.py            # Configuration (capital, API keys, universe)
├── market_data.py       # Real-time market data (yfinance)
├── news_analyzer.py     # Financial news (RSS + Yahoo)
├── ai_agent.py          # Decision-making AI agent (Groq)
├── portfolio.py         # Portfolio management + JSON persistence
├── local_storage.py     # Local CSV + Excel storage
├── google_sheets.py     # Google Sheets interface (optional)
├── requirements.txt     # Python dependencies
├── dashboard/           # Local web dashboard
│   ├── app.py           # Flask server + chart logic
│   └── templates/
│       └── index.html   # Plotly + Tailwind interface (dark mode)
├── data/                # Data (auto-generated)
│   ├── transactions.csv
│   ├── portefeuille.csv
│   └── journal.csv
├── state/               # Portfolio state
│   ├── portfolio_state.json  # Cash, positions, last_run_date (used by the catch-up)
│   └── run.lock          # Concurrency lock (created/removed automatically)
└── credentials/         # Credentials (not version-controlled)
    └── service_account.json
```

## Local dashboard

An interactive web interface on `http://localhost:5000`:

- **KPIs** — total value, PnL, cash, positions, fees, win rate
- **Time series** — asset prices (3 months) with BUY ▲ / SELL ▼ markers and RSI
- **Trading bot vs lump sum** — live comparison of the bot against a passive
  strategy (€10,000 plus €500/month into an MSCI World ETF)
- **Performance vs benchmark** — portfolio curve against a normalised MSCI World
- **Pie chart** — asset allocation including cash
- **DroneShield panel** — a dedicated AI analysis (sentiment, recommendation, size)
- **Positions table** — average cost, current price, PnL per position
- **AI journal** — the bot's daily analyses
- **Metrics** — win rate, max drawdown, total PnL

### Running the dashboard

```bash
python dashboard/app.py
```

Then open **http://localhost:5000**

The dashboard refreshes itself every 5 minutes during market hours (08:00–22:00).

On startup it **runs `main.py` in the background** (catching up on missed days, plus
the current day if needed). The dashboard stays usable immediately while that
happens, with a banner at the top of the page saying an update is in progress —
its status can be polled at `/api/bootstrap-status`. If the bot has already run
today, that automatic run does nothing further (see the next section).

## Setup

### 1. Install the dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure the API keys

Create a `.env` file:
```
OPENAI_API_KEY=gsk_...       # Groq API key
AI_MODEL=openai/gpt-oss-120b
```

The agent talks to Groq through its OpenAI-compatible endpoint, so any model Groq
serves can be swapped in through `AI_MODEL` without touching the code.

### 3. (Optional) Google Sheets

To log to Google Sheets as well:
- Create a Google Cloud service account
- Put the JSON in `credentials/service_account.json`
- Set `GOOGLE_SHEETS_ID` in `.env`

## Daily use

```bash
python main.py
```

The bot will:
1. Load the portfolio state
2. Fetch real-time market prices
3. Fetch financial news
4. Ask the AI for its recommendations
5. Execute the buys and sells
6. Log the results to CSV (and Google Sheets, if configured)

## Catching up on missed days

The portfolio remembers the date of the last successfully executed cycle in
`state/portfolio_state.json` (`last_run_date`), even when that cycle did nothing
(a HOLD). On startup, `main.py`:

1. Works out which weekdays (Mon–Fri) were missed between `last_run_date` and today.
2. Replays a full cycle for each missed day — **that day's real closing prices**
   (fetched from yfinance), the AI agent's decision, the buys and sells if any, and
   a log dated to that specific day (transactions, portfolio, journal).
3. Then handles the current day normally, with live prices — unless it has already
   run today, in which case it stops without redoing anything.

Limits worth knowing:

- **News**: the free APIs used (RSS, Yahoo Finance) only return *current* news, with
  no archive by past date. For caught-up days the bot therefore reuses the news
  available at catch-up time — stated explicitly in the prompt sent to the AI — not
  the news that actually broke on that day.
- **Closed days**: a missed day with no trading session (weekend, public holiday) is
  skipped silently, since there is no price data for it.
- **Number of days**: catch-up is capped at `MAX_CATCHUP_DAYS` (15 by default, in
  `config.py`) per run so as not to saturate the AI API — the rest is caught up on
  the following run(s).
- **Concurrency**: a file lock (`state/run.lock`) stops two `run_daily()` calls from
  running at once (for instance several dashboard processes restarting together) —
  the second one exits without duplicating anything.

The catch-up triggers both through `python main.py` and through the dashboard's
automatic startup run.

## Investment universe

- **World ETFs**: IWDA, VWCE, CSPX, EUNL
- **Sector ETFs**: IT, Healthcare, Energy
- **US equities**: AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA
- **European equities**: LVMH, ASML, SAP, Siemens
- **Defence**: LMT, RTX, NOC, BA, Thales, DroneShield (DRO.AX)
- **Asia**: SoftBank, Samsung
- **Gold**: SGLD

## Automation (cron)

To run automatically every day at 17:00, after the European close:
```bash
crontab -e
# Add:
0 17 * * 1-5 cd /path/to/trading-bot && python main.py >> logs/daily.log 2>&1
```

Since `main.py` now catches up on missed days by itself (see
[Catching up on missed days](#catching-up-on-missed-days)), a one-off failure of the
cron job or of the machine is no longer blocking: the next run — the following cron,
or simply opening the dashboard — replays whatever was missed.

## Parameters

| Parameter | Value |
|-----------|-------|
| Starting capital | €10,000 |
| Monthly contribution | €500 |
| Transaction fee | 0.25% |
| Max positions | 12 |
| Max per position | 15% of the portfolio |
| Minimum cash | 10% |
| Universe | World ETFs + equities (20 assets) |

## Google Sheets — tabs

| Tab | Contents |
|---------|---------|
| **Transactions** | Every buy and sell with date, amount, fee, PnL and reasoning |
| **Portfolio** | Daily snapshot (value, cash, PnL, sentiment) |
| **Journal** | The day's AI analysis, decisions taken, sentiment |

## License

MIT — see [LICENSE](LICENSE).
