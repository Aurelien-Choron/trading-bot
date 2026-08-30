"""
Dashboard local du Trading Bot — Flask + Plotly.
Affiche le portefeuille, graphiques, transactions et analyse DroneShield.
"""

import sys
import os
import csv
import io
import json
import threading
import contextlib
from datetime import datetime, date

import yfinance as yf
import pandas as pd
import plotly
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from flask import Flask, render_template, jsonify

# Ajouter le dossier parent au path pour importer les modules du bot
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import STATE_FILE, UNIVERSE, OPENAI_API_KEY, AI_MODEL
from market_data import get_technical_indicators
import main as trading_main

app = Flask(__name__)

# --- Lancement automatique du bot (rattrapage + jour courant) au démarrage ---
# run_daily() est idempotent (voir main.py) : elle rattrape les jours de marché
# manqués puis exécute le jour courant, sauf s'il a déjà tourné aujourd'hui.
BOOTSTRAP_STATUS = {
    "state": "idle",  # idle | running | done | error
    "started_at": None,
    "finished_at": None,
    "log": "",
    "error": None,
}
_bootstrap_lock = threading.Lock()


def _run_bootstrap():
    """Exécute main.run_daily() en arrière-plan (thread) au démarrage du dashboard."""
    with _bootstrap_lock:
        if BOOTSTRAP_STATUS["state"] == "running":
            return
        BOOTSTRAP_STATUS["state"] = "running"
        BOOTSTRAP_STATUS["started_at"] = datetime.now().isoformat()
        BOOTSTRAP_STATUS["error"] = None

    buffer = io.StringIO()
    try:
        with contextlib.redirect_stdout(buffer):
            trading_main.run_daily()
        BOOTSTRAP_STATUS["state"] = "done"
    except Exception as e:
        BOOTSTRAP_STATUS["state"] = "error"
        BOOTSTRAP_STATUS["error"] = str(e)
    finally:
        BOOTSTRAP_STATUS["log"] = buffer.getvalue()[-8000:]
        BOOTSTRAP_STATUS["finished_at"] = datetime.now().isoformat()

# --- Paths ---
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CSV_TRANSACTIONS = os.path.join(DATA_DIR, "transactions.csv")
CSV_PORTFOLIO = os.path.join(DATA_DIR, "portefeuille.csv")
CSV_JOURNAL = os.path.join(DATA_DIR, "journal.csv")


def load_portfolio_state() -> dict:
    """Charge l'état actuel du portefeuille."""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"cash": 0, "positions": {}, "total_invested": 0, "total_fees_paid": 0}


def load_csv(filepath: str) -> list[dict]:
    """Charge un CSV en liste de dicts."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def get_portfolio_value(state: dict) -> dict:
    """Calcule la valeur totale actuelle du portefeuille."""
    positions_value = 0.0
    position_details = []

    for ticker, pos in state.get("positions", {}).items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="2d").dropna(subset=["Close"])
            if not hist.empty:
                price = hist["Close"].iloc[-1]
                value = pos["shares"] * price
                pnl = value - pos["total_invested"]
                pnl_pct = (pnl / pos["total_invested"]) * 100 if pos["total_invested"] > 0 else 0
                positions_value += value
                position_details.append({
                    "ticker": ticker,
                    "shares": pos["shares"],
                    "avg_price": pos["avg_price"],
                    "current_price": round(price, 2),
                    "value": round(value, 2),
                    "invested": pos["total_invested"],
                    "pnl": round(pnl, 2),
                    "pnl_pct": round(pnl_pct, 2),
                    "buy_date": pos.get("buy_date", ""),
                })
        except Exception:
            value = pos["shares"] * pos["avg_price"]
            positions_value += value
            position_details.append({
                "ticker": ticker,
                "shares": pos["shares"],
                "avg_price": pos["avg_price"],
                "current_price": pos["avg_price"],
                "value": round(value, 2),
                "invested": pos["total_invested"],
                "pnl": 0,
                "pnl_pct": 0,
                "buy_date": pos.get("buy_date", ""),
            })

    total_value = state["cash"] + positions_value
    total_pnl = total_value - state["total_invested"]
    total_pnl_pct = (total_pnl / state["total_invested"]) * 100 if state["total_invested"] > 0 else 0

    return {
        "total_value": round(total_value, 2),
        "cash": round(state["cash"], 2),
        "positions_value": round(positions_value, 2),
        "total_invested": round(state["total_invested"], 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": round(total_pnl_pct, 2),
        "total_fees": round(state.get("total_fees_paid", 0), 2),
        "positions": position_details,
        "nb_positions": len(position_details),
    }


def build_price_chart(state: dict, transactions: list[dict]) -> str:
    """Construit le graphique de cours avec marqueurs BUY/SELL."""
    tickers_in_portfolio = list(state.get("positions", {}).keys())
    if not tickers_in_portfolio:
        return "{}"

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.7, 0.3],
        subplot_titles=("Cours des actifs", "RSI"),
    )

    colors = [
        "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
        "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16",
    ]

    for i, ticker in enumerate(tickers_in_portfolio):
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="3mo").dropna(subset=["Close"])
            if hist.empty:
                continue
            hist.index = hist.index.tz_localize(None)

            color = colors[i % len(colors)]

            # Cours
            fig.add_trace(
                go.Scatter(
                    x=hist.index, y=hist["Close"].tolist(),
                    name=ticker, line=dict(color=color, width=2),
                    hovertemplate=f"{ticker}<br>%{{x}}<br>€%{{y:.2f}}<extra></extra>",
                ),
                row=1, col=1,
            )

            # RSI
            delta = hist["Close"].diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))

            fig.add_trace(
                go.Scatter(
                    x=hist.index, y=rsi.tolist(),
                    name=f"RSI {ticker}", line=dict(color=color, width=1, dash="dot"),
                    showlegend=False,
                ),
                row=2, col=1,
            )
        except Exception:
            continue

    # Marqueurs BUY/SELL
    buy_dates, buy_prices, buy_texts = [], [], []
    sell_dates, sell_prices, sell_texts = [], [], []

    for tx in transactions:
        try:
            tx_date = pd.Timestamp(tx["Date"])
            tx_price = float(tx["Prix"])
            tx_ticker = tx["Ticker"]
            if tx["Action"] == "BUY":
                buy_dates.append(tx_date)
                buy_prices.append(tx_price)
                buy_texts.append(f"BUY {tx_ticker}<br>€{tx_price:.2f}")
            elif tx["Action"] == "SELL":
                sell_dates.append(tx_date)
                sell_prices.append(tx_price)
                sell_texts.append(f"SELL {tx_ticker}<br>€{tx_price:.2f}")
        except (ValueError, KeyError):
            continue

    if buy_dates:
        fig.add_trace(
            go.Scatter(
                x=buy_dates, y=buy_prices, mode="markers",
                name="Achats",
                marker=dict(symbol="triangle-up", size=14, color="#10b981", line=dict(width=2, color="white")),
                text=buy_texts, hovertemplate="%{text}<extra></extra>",
            ),
            row=1, col=1,
        )

    if sell_dates:
        fig.add_trace(
            go.Scatter(
                x=sell_dates, y=sell_prices, mode="markers",
                name="Ventes",
                marker=dict(symbol="triangle-down", size=14, color="#ef4444", line=dict(width=2, color="white")),
                text=sell_texts, hovertemplate="%{text}<extra></extra>",
            ),
            row=1, col=1,
        )

    # RSI zones
    fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
    fig.add_hline(y=30, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1e1e2e",
        plot_bgcolor="#1e1e2e",
        height=550,
        margin=dict(l=50, r=30, t=40, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis_rangeslider_visible=False,
    )
    fig.update_yaxes(title_text="Prix (€)", row=1, col=1)
    fig.update_yaxes(title_text="RSI", range=[0, 100], row=2, col=1)

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_pie_chart(portfolio_data: dict) -> str:
    """Construit le pie chart de répartition des actifs."""
    labels = [p["ticker"] for p in portfolio_data["positions"]]
    values = [p["value"] for p in portfolio_data["positions"]]

    # Ajouter le cash
    labels.append("Cash")
    values.append(portfolio_data["cash"])

    colors = [
        "#3b82f6", "#10b981", "#f59e0b", "#ef4444",
        "#8b5cf6", "#ec4899", "#06b6d4", "#84cc16",
        "#6b7280",  # Cash en gris
    ]

    fig = go.Figure(data=[
        go.Pie(
            labels=labels, values=values,
            hole=0.4,
            marker=dict(colors=colors[:len(labels)]),
            textinfo="label+percent",
            textfont_size=12,
            hovertemplate="%{label}<br>€%{value:.2f}<br>%{percent}<extra></extra>",
        )
    ])

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1e1e2e",
        plot_bgcolor="#1e1e2e",
        height=350,
        margin=dict(l=20, r=20, t=30, b=20),
        showlegend=True,
        legend=dict(font=dict(size=11)),
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_performance_chart() -> str:
    """Courbe de la valeur du portefeuille vs benchmark (MSCI World)."""
    portfolio_history = load_csv(CSV_PORTFOLIO)
    if not portfolio_history:
        return "{}"

    dates = []
    values = []
    for row in portfolio_history:
        try:
            dates.append(pd.Timestamp(row["Date"]))
            values.append(float(row["Valeur totale (€)"]))
        except (ValueError, KeyError):
            continue

    if not dates:
        return "{}"

    fig = go.Figure()

    # Courbe portefeuille
    fig.add_trace(go.Scatter(
        x=dates, y=values,
        name="Portefeuille", line=dict(color="#3b82f6", width=2),
        fill="tozeroy", fillcolor="rgba(59, 130, 246, 0.1)",
    ))

    # Benchmark : normaliser MSCI World à la valeur initiale du portefeuille
    try:
        start_date = dates[0] - pd.Timedelta(days=1)
        benchmark = yf.Ticker("IWDA.AS")
        bench_hist = benchmark.history(start=start_date.strftime("%Y-%m-%d"))
        bench_hist = bench_hist.dropna(subset=["Close"])
        if not bench_hist.empty:
            bench_hist.index = bench_hist.index.tz_localize(None)
        if not bench_hist.empty and values:
            initial_value = values[0]
            bench_normalized = bench_hist["Close"] / bench_hist["Close"].iloc[0] * initial_value
            fig.add_trace(go.Scatter(
                x=bench_hist.index, y=bench_normalized.tolist(),
                name="MSCI World (IWDA)", line=dict(color="#6b7280", width=1.5, dash="dash"),
            ))
    except Exception:
        pass

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1e1e2e",
        plot_bgcolor="#1e1e2e",
        height=300,
        margin=dict(l=50, r=30, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title="Valeur (€)",
    )

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


def build_lumpsum_comparison(state: dict) -> tuple[str, dict]:
    """
    Compare la performance du bot vs une stratégie Lump Sum + DCA sur ETF World.
    Simule: 10000€ investis au jour 1 + 500€ le 1er de chaque mois suivant, tout en IWDA.AS.
    """
    from config import INITIAL_CAPITAL, MONTHLY_CONTRIBUTION

    portfolio_history = load_csv(CSV_PORTFOLIO)
    if not portfolio_history:
        return "{}", {}

    # Dates du portefeuille
    dates = []
    bot_values = []
    for row in portfolio_history:
        try:
            dates.append(pd.Timestamp(row["Date"]))
            bot_values.append(float(row["Valeur totale (€)"]))
        except (ValueError, KeyError):
            continue

    if not dates:
        return "{}", {}

    start_date = dates[0]

    # Récupérer l'historique ETF World
    try:
        etf = yf.Ticker("IWDA.AS")
        etf_hist = etf.history(start=(start_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d"))
        etf_hist = etf_hist.dropna(subset=["Close"])
        if not etf_hist.empty:
            etf_hist.index = etf_hist.index.tz_localize(None)
        if etf_hist.empty:
            return "{}", {}
    except Exception:
        return "{}", {}

    # Simuler la stratégie Lump Sum + DCA
    # Investissement initial au premier jour disponible
    etf_dates = etf_hist.index
    initial_price = etf_hist["Close"].iloc[0]
    shares_held = INITIAL_CAPITAL / initial_price
    total_invested_ls = INITIAL_CAPITAL
    contributions_done = set()

    lumpsum_dates = []
    lumpsum_values = []

    for i, d in enumerate(etf_dates):
        price = etf_hist["Close"].iloc[i]

        # Apport mensuel le 1er de chaque mois (sauf le mois de départ)
        month_key = (d.year, d.month)
        if d.day <= 3 and month_key not in contributions_done and d > start_date + pd.Timedelta(days=25):
            shares_held += MONTHLY_CONTRIBUTION / price
            total_invested_ls += MONTHLY_CONTRIBUTION
            contributions_done.add(month_key)

        lumpsum_dates.append(d)
        lumpsum_values.append(float(shares_held * price))

    # Construire le graphique comparatif
    fig = go.Figure()

    # Courbe Bot
    fig.add_trace(go.Scatter(
        x=dates, y=bot_values,
        name="🤖 Trading Bot", line=dict(color="#3b82f6", width=2.5),
        hovertemplate="Bot: €%{y:.2f}<extra></extra>",
    ))

    # Courbe Lump Sum + DCA
    fig.add_trace(go.Scatter(
        x=lumpsum_dates, y=lumpsum_values,
        name="📈 Lump Sum + DCA (ETF World)", line=dict(color="#10b981", width=2.5),
        hovertemplate="ETF World: €%{y:.2f}<extra></extra>",
    ))

    # Ligne du capital investi
    invested_dates = [dates[0], dates[-1]]
    invested_values = [INITIAL_CAPITAL, total_invested_ls]
    fig.add_trace(go.Scatter(
        x=invested_dates, y=invested_values,
        name="💶 Capital investi", line=dict(color="#6b7280", width=1, dash="dot"),
        hovertemplate="Investi: €%{y:.2f}<extra></extra>",
    ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1e1e2e",
        plot_bgcolor="#1e1e2e",
        height=380,
        margin=dict(l=50, r=30, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title="Valeur (€)",
        hovermode="x unified",
    )

    # Statistiques comparatives
    bot_final = bot_values[-1] if bot_values else INITIAL_CAPITAL
    ls_final = lumpsum_values[-1] if lumpsum_values else INITIAL_CAPITAL
    bot_pnl = bot_final - state.get("total_invested", INITIAL_CAPITAL)
    ls_pnl = ls_final - total_invested_ls
    bot_pnl_pct = (bot_pnl / state.get("total_invested", INITIAL_CAPITAL)) * 100
    ls_pnl_pct = (ls_pnl / total_invested_ls) * 100

    stats = {
        "bot_value": round(bot_final, 2),
        "ls_value": round(ls_final, 2),
        "bot_pnl": round(bot_pnl, 2),
        "ls_pnl": round(ls_pnl, 2),
        "bot_pnl_pct": round(bot_pnl_pct, 2),
        "ls_pnl_pct": round(ls_pnl_pct, 2),
        "difference": round(bot_final - ls_final, 2),
        "bot_wins": bot_final > ls_final,
        "total_invested_ls": round(total_invested_ls, 2),
    }

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder), stats


def build_backtest_chart() -> tuple[str, dict]:
    """
    Charge les résultats du backtest 2 ans et construit le graphique
    Trading Bot (simulé) vs Lump Sum + DCA.
    """
    from config import INITIAL_CAPITAL, MONTHLY_CONTRIBUTION

    backtest_file = os.path.join(DATA_DIR, "backtest_results.csv")
    lumpsum_file = os.path.join(DATA_DIR, "backtest_lumpsum.csv")

    if not os.path.exists(backtest_file) or not os.path.exists(lumpsum_file):
        return "{}", {}

    df_bot = pd.read_csv(backtest_file)
    df_ls = pd.read_csv(lumpsum_file)

    if df_bot.empty or df_ls.empty:
        return "{}", {}

    bot_dates = pd.to_datetime(df_bot["date"])
    bot_values = df_bot["total_value"].tolist()
    bot_invested = df_bot["total_invested"].tolist()

    ls_dates = pd.to_datetime(df_ls["date"])
    ls_values = df_ls["total_value"].tolist()
    ls_invested = df_ls["total_invested"].tolist()

    fig = go.Figure()

    # Courbe Bot simulé
    fig.add_trace(go.Scatter(
        x=bot_dates, y=bot_values,
        name="🤖 Trading Bot (backtest)", line=dict(color="#3b82f6", width=2.5),
        hovertemplate="Bot: €%{y:,.2f}<extra></extra>",
    ))

    # Courbe Lump Sum + DCA
    fig.add_trace(go.Scatter(
        x=ls_dates, y=ls_values,
        name="📈 Lump Sum + DCA (ETF World)", line=dict(color="#10b981", width=2.5),
        hovertemplate="ETF World: €%{y:,.2f}<extra></extra>",
    ))

    # Capital investi
    fig.add_trace(go.Scatter(
        x=bot_dates, y=bot_invested,
        name="💶 Capital investi", line=dict(color="#6b7280", width=1, dash="dot"),
        hovertemplate="Investi: €%{y:,.2f}<extra></extra>",
    ))

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#1e1e2e",
        plot_bgcolor="#1e1e2e",
        height=420,
        margin=dict(l=50, r=30, t=30, b=30),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title="Valeur (€)",
        hovermode="x unified",
    )

    # Statistiques
    bot_final = float(bot_values[-1])
    ls_final = float(ls_values[-1])
    total_invested_bot = float(bot_invested[-1])
    total_invested_ls = float(ls_invested[-1])
    bot_pnl = bot_final - total_invested_bot
    ls_pnl = ls_final - total_invested_ls
    bot_pnl_pct = (bot_pnl / total_invested_bot) * 100
    ls_pnl_pct = (ls_pnl / total_invested_ls) * 100

    # Rendement annualisé
    days = (bot_dates.iloc[-1] - bot_dates.iloc[0]).days
    bot_annual = ((bot_final / total_invested_bot) ** (365 / days) - 1) * 100 if days > 0 else 0
    ls_annual = ((ls_final / total_invested_ls) ** (365 / days) - 1) * 100 if days > 0 else 0

    # Max drawdown bot
    peak = bot_values[0]
    max_dd = 0
    for v in bot_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd

    stats = {
        "bot_value": round(bot_final, 2),
        "ls_value": round(ls_final, 2),
        "bot_pnl": round(bot_pnl, 2),
        "ls_pnl": round(ls_pnl, 2),
        "bot_pnl_pct": round(bot_pnl_pct, 2),
        "ls_pnl_pct": round(ls_pnl_pct, 2),
        "bot_annual": round(bot_annual, 2),
        "ls_annual": round(ls_annual, 2),
        "max_drawdown": round(max_dd, 2),
        "difference": round(bot_final - ls_final, 2),
        "bot_wins": bot_final > ls_final,
        "total_invested": round(total_invested_bot, 2),
        "nb_transactions": int(df_bot["nb_positions"].iloc[-1]) if "nb_positions" in df_bot.columns else 0,
        "total_fees": float(df_bot["total_fees"].iloc[-1]) if "total_fees" in df_bot.columns else 0,
    }

    return json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder), stats


def get_droneshield_analysis() -> dict:
    """Analyse dédiée DroneShield via l'agent IA."""
    ticker = "DRO.AX"
    result = {
        "ticker": ticker,
        "name": "DroneShield Ltd",
        "price": None,
        "change_1d": None,
        "change_5d": None,
        "sentiment": "N/A",
        "recommendation": "N/A",
        "amount_suggested": 0,
        "analysis": "Données indisponibles",
        "technicals": {},
    }

    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="5d").dropna(subset=["Close"])
        if hist.empty:
            return result

        price = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2] if len(hist) >= 2 else price
        price_5d = hist["Close"].iloc[0]

        result["price"] = round(float(price), 4)
        result["change_1d"] = round(float((price / prev - 1) * 100), 2)
        result["change_5d"] = round(float((price / price_5d - 1) * 100), 2)

        # Indicateurs techniques
        technicals = get_technical_indicators(ticker, "3mo")
        result["technicals"] = technicals

        # Appel IA pour recommandation
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url="https://api.groq.com/openai/v1")

        prompt = f"""Analyse l'action DroneShield (DRO.AX) et donne ton avis.

Prix actuel: {price:.4f} AUD
Variation 1j: {result['change_1d']:+.2f}%
Variation 5j: {result['change_5d']:+.2f}%
Indicateurs techniques: {json.dumps(technicals)}

Réponds en JSON strict:
{{
  "sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "action": "BUY" | "SELL" | "HOLD",
  "amount_eur": 0-1000,
  "confidence": 0.0-1.0,
  "analysis": "2-3 phrases d'analyse"
}}"""

        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": "Tu es un analyste spécialisé dans les actions de défense/drones. Réponds uniquement en JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        ai_result = json.loads(response.choices[0].message.content)
        result["sentiment"] = ai_result.get("sentiment", "NEUTRAL")
        result["recommendation"] = ai_result.get("action", "HOLD")
        result["amount_suggested"] = ai_result.get("amount_eur", 0)
        result["analysis"] = ai_result.get("analysis", "Analyse non disponible")
        result["confidence"] = ai_result.get("confidence", 0)

    except Exception as e:
        result["analysis"] = f"Erreur: {str(e)[:100]}"

    return result


def compute_metrics(transactions: list[dict], portfolio_data: dict) -> dict:
    """Calcule les métriques de performance."""
    total_trades = len(transactions)
    wins = 0
    for tx in transactions:
        try:
            pnl = float(tx.get("PnL (€)", 0) or 0)
            if pnl > 0:
                wins += 1
        except (ValueError, TypeError):
            pass

    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0

    # Max drawdown depuis l'historique portefeuille
    portfolio_history = load_csv(CSV_PORTFOLIO)
    max_drawdown = 0
    peak = 0
    for row in portfolio_history:
        try:
            val = float(row["Valeur totale (€)"])
            if val > peak:
                peak = val
            dd = (peak - val) / peak * 100 if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd
        except (ValueError, KeyError):
            pass

    return {
        "total_trades": total_trades,
        "win_rate": round(win_rate, 1),
        "max_drawdown": round(max_drawdown, 2),
        "total_fees": portfolio_data["total_fees"],
        "total_pnl": portfolio_data["total_pnl"],
        "total_pnl_pct": portfolio_data["total_pnl_pct"],
    }


@app.route("/")
def index():
    """Page principale du dashboard."""
    state = load_portfolio_state()
    portfolio_data = get_portfolio_value(state)
    transactions = load_csv(CSV_TRANSACTIONS)
    journal = load_csv(CSV_JOURNAL)

    # Graphiques
    price_chart = build_price_chart(state, transactions)
    pie_chart = build_pie_chart(portfolio_data)
    perf_chart = build_performance_chart()
    lumpsum_chart, lumpsum_stats = build_lumpsum_comparison(state)
    backtest_chart, backtest_stats = build_backtest_chart()

    # Métriques
    metrics = compute_metrics(transactions, portfolio_data)

    # DroneShield
    droneshield = get_droneshield_analysis()

    # Dernier journal
    last_journal = journal[-1] if journal else {}

    return render_template(
        "index.html",
        portfolio=portfolio_data,
        transactions=transactions[-20:],  # 20 dernières
        journal=journal[-5:],  # 5 derniers
        last_journal=last_journal,
        price_chart=price_chart,
        pie_chart=pie_chart,
        perf_chart=perf_chart,
        lumpsum_chart=lumpsum_chart,
        lumpsum_stats=lumpsum_stats,
        backtest_chart=backtest_chart,
        backtest_stats=backtest_stats,
        metrics=metrics,
        droneshield=droneshield,
        now=datetime.now().strftime("%d/%m/%Y %H:%M"),
    )


@app.route("/api/refresh")
def api_refresh():
    """Endpoint pour rafraîchir les données sans recharger la page."""
    state = load_portfolio_state()
    portfolio_data = get_portfolio_value(state)
    transactions = load_csv(CSV_TRANSACTIONS)
    metrics = compute_metrics(transactions, portfolio_data)

    return jsonify({
        "portfolio": portfolio_data,
        "metrics": metrics,
        "updated_at": datetime.now().strftime("%d/%m/%Y %H:%M:%S"),
    })


@app.route("/api/droneshield")
def api_droneshield():
    """Endpoint dédié pour actualiser l'analyse DroneShield."""
    return jsonify(get_droneshield_analysis())


@app.route("/api/bootstrap-status")
def api_bootstrap_status():
    """Statut du rattrapage/run automatique lancé au démarrage du dashboard."""
    return jsonify(BOOTSTRAP_STATUS)


if __name__ == "__main__":
    DEBUG_MODE = True

    # En mode debug, Werkzeug relance ce script dans un sous-processus (reloader) qui
    # porte WERKZEUG_RUN_MAIN=true — on ne démarre le rattrapage que dans le process
    # qui sert réellement les requêtes, pour éviter de lancer main.py deux fois.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true" or not DEBUG_MODE:
        threading.Thread(target=_run_bootstrap, daemon=True).start()

    print("🚀 Dashboard Trading Bot — http://localhost:5000")
    app.run(debug=DEBUG_MODE, host="0.0.0.0", port=5000)
