"""
Backtest 2 ans — Simulation du Trading Bot (mai 2024 → mai 2026).
Utilise un score composite (RSI + MACD + tendance SMA) sans look-ahead bias.
Sauvegarde les résultats dans data/backtest_results.csv pour le dashboard.
"""

import os
import json
import numpy as np
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta

from config import (
    INITIAL_CAPITAL,
    MONTHLY_CONTRIBUTION,
    TRANSACTION_FEE_PERCENT,
    MAX_POSITION_PERCENT,
    MAX_POSITIONS,
    MIN_CASH_PERCENT,
    UNIVERSE,
)

# --- Configuration backtest ---
BACKTEST_START = "2024-05-01"
BACKTEST_END = "2026-05-22"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
RESULTS_FILE = os.path.join(DATA_DIR, "backtest_results.csv")
TRANSACTIONS_FILE = os.path.join(DATA_DIR, "backtest_transactions.csv")

# Sous-ensemble d'actifs les plus liquides pour le backtest (éviter les tickers illiquides)
BACKTEST_UNIVERSE = [
    "IWDA.AS",   # MSCI World
    "CSPX.L",   # S&P 500
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "MC.PA",     # LVMH
    "ASML.AS",
    "LMT",
    "RTX",
    "SGLD.L",   # Or
    "SAP.DE",
]


def download_historical_data(tickers: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """Télécharge les données historiques pour tous les tickers."""
    print(f"📥 Téléchargement des données historiques ({start} → {end})...")
    data = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, start=start, end=end, progress=False)
            if not df.empty and len(df) > 50:
                # Flatten multi-level columns if present
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                data[ticker] = df
                print(f"  ✓ {ticker}: {len(df)} jours")
            else:
                print(f"  ✗ {ticker}: données insuffisantes ({len(df)} jours)")
        except Exception as e:
            print(f"  ✗ {ticker}: erreur - {e}")
    return data


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Calcule RSI, MACD, SMA20, SMA50 sur un DataFrame de prix."""
    close = df["Close"].copy()

    # RSI 14
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df = df.copy()
    df["RSI"] = 100 - (100 / (1 + rs))

    # Moyennes mobiles
    df["SMA20"] = close.rolling(window=20).mean()
    df["SMA50"] = close.rolling(window=50).mean()

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df["MACD"] = ema12 - ema26
    df["MACD_signal"] = df["MACD"].ewm(span=9, adjust=False).mean()
    df["MACD_hist"] = df["MACD"] - df["MACD_signal"]

    return df


def compute_score(row: pd.Series) -> float:
    """
    Score composite pour décision d'achat (-1 à +1).
    Positif = signal d'achat, négatif = signal de vente.
    """
    score = 0.0

    # RSI: survendu = achat, suracheté = vente
    rsi = row.get("RSI", 50)
    if hasattr(rsi, 'item'):
        rsi = rsi.item()
    if pd.isna(rsi):
        return 0.0
    if rsi < 35:
        score += 0.4  # Forte survente
    elif rsi < 45:
        score += 0.2  # Légère survente
    elif rsi > 75:
        score -= 0.5  # Forte surachat
    elif rsi > 65:
        score -= 0.2  # Légère surachat

    # MACD: croisement haussier/baissier
    macd_hist = row.get("MACD_hist", 0)
    if hasattr(macd_hist, 'item'):
        macd_hist = macd_hist.item()
    if pd.notna(macd_hist):
        if macd_hist > 0:
            score += 0.3
        elif macd_hist < 0:
            score -= 0.2

    # Tendance: SMA20 > SMA50 = haussier
    sma20 = row.get("SMA20", 0)
    sma50 = row.get("SMA50", 0)
    price = row.get("Close", 0)
    if hasattr(sma20, 'item'):
        sma20 = sma20.item()
    if hasattr(sma50, 'item'):
        sma50 = sma50.item()
    if hasattr(price, 'item'):
        price = price.item()
    if pd.notna(sma20) and pd.notna(sma50) and sma50 > 0:
        if sma20 > sma50 and price > sma50:
            score += 0.3  # Tendance haussière confirmée
        elif sma20 < sma50 and price < sma20:
            score -= 0.3  # Tendance baissière confirmée

    return max(-1.0, min(1.0, score))


def run_backtest():
    """Exécute le backtest complet."""
    print("=" * 60)
    print("🔄 BACKTEST — Trading Bot Simulation (2 ans)")
    print(f"   Période: {BACKTEST_START} → {BACKTEST_END}")
    print(f"   Capital initial: {INITIAL_CAPITAL:,.0f} €")
    print(f"   Apport mensuel: {MONTHLY_CONTRIBUTION:,.0f} €")
    print(f"   Univers: {len(BACKTEST_UNIVERSE)} actifs")
    print("=" * 60)

    # 1. Télécharger les données
    historical = download_historical_data(BACKTEST_UNIVERSE, BACKTEST_START, BACKTEST_END)
    if not historical:
        print("❌ Aucune donnée disponible. Abandon.")
        return

    # 2. Calculer les indicateurs pour chaque ticker
    print("\n📊 Calcul des indicateurs techniques...")
    for ticker in list(historical.keys()):
        historical[ticker] = compute_indicators(historical[ticker])

    # 3. Déterminer les dates de trading (jours où au moins 5 tickers ont des données)
    all_dates = set()
    for df in historical.values():
        all_dates.update(df.index.tolist())
    all_dates = sorted(all_dates)

    trading_dates = []
    for d in all_dates:
        available = sum(1 for df in historical.values() if d in df.index)
        if available >= 5:
            trading_dates.append(d)

    print(f"   {len(trading_dates)} jours de trading simulés")

    # 4. Simulation
    print("\n🚀 Simulation en cours...")
    cash = INITIAL_CAPITAL
    positions = {}  # {ticker: {"shares": float, "avg_price": float, "total_invested": float}}
    total_invested = INITIAL_CAPITAL
    total_fees = 0.0
    contributions_done = set()
    last_known_prices = {}  # {ticker: last_price} for days with missing data

    # Historique pour le graphique
    portfolio_history = []  # [{date, total_value, cash, positions_value, total_invested}]
    transactions_log = []   # [{date, action, ticker, amount, price, shares, fee}]

    for i, date in enumerate(trading_dates):
        # --- Apport mensuel (1-3 du mois, sauf le premier mois) ---
        month_key = (date.year, date.month)
        start_ts = pd.Timestamp(BACKTEST_START)
        if date.day <= 3 and month_key not in contributions_done and date > start_ts + pd.Timedelta(days=25):
            cash += MONTHLY_CONTRIBUTION
            total_invested += MONTHLY_CONTRIBUTION
            contributions_done.add(month_key)

        # --- Calculer la valeur du portefeuille ---
        positions_value = 0.0
        for ticker, pos in list(positions.items()):
            if ticker in historical and date in historical[ticker].index:
                price = float(historical[ticker].loc[date, "Close"])
                last_known_prices[ticker] = price
                positions_value += pos["shares"] * price
            elif ticker in last_known_prices:
                positions_value += pos["shares"] * last_known_prices[ticker]

        total_value = cash + positions_value

        # --- Évaluer chaque ticker et décider ---
        # On ne trade que 1x par semaine max par ticker (éviter l'overtrading)
        if i % 5 == 0:  # Vérifier les signaux tous les ~5 jours ouvrés (1x/semaine)
            scores = {}
            for ticker in BACKTEST_UNIVERSE:
                if ticker not in historical:
                    continue
                df = historical[ticker]
                if date not in df.index:
                    continue
                row = df.loc[date]
                # Vérifier qu'on a assez d'historique (50 jours min pour SMA50)
                idx = df.index.get_loc(date)
                if idx < 50:
                    continue
                scores[ticker] = compute_score(row)

            # --- Décisions de VENTE ---
            for ticker in list(positions.keys()):
                if ticker not in scores:
                    continue
                if ticker not in historical or date not in historical[ticker].index:
                    continue

                price = float(historical[ticker].loc[date, "Close"])
                pos = positions[ticker]

                # Stop-loss: -8%
                pnl_pct = (price - pos["avg_price"]) / pos["avg_price"]
                should_sell = False

                if pnl_pct <= -0.08:
                    should_sell = True
                    reason = "stop-loss -8%"
                elif scores[ticker] <= -0.5:
                    should_sell = True
                    reason = f"signal vente (score={scores[ticker]:.2f})"

                if should_sell:
                    sell_value = pos["shares"] * price
                    fee = sell_value * TRANSACTION_FEE_PERCENT / 100
                    cash += sell_value - fee
                    total_fees += fee
                    transactions_log.append({
                        "date": date.strftime("%Y-%m-%d"),
                        "action": "SELL",
                        "ticker": ticker,
                        "shares": round(pos["shares"], 4),
                        "price": round(price, 2),
                        "amount": round(sell_value, 2),
                        "fee": round(fee, 2),
                        "pnl": round(sell_value - pos["total_invested"], 2),
                        "reason": reason,
                    })
                    del positions[ticker]

            # --- Décisions d'ACHAT ---
            # Trier par score décroissant
            buy_candidates = [
                (ticker, score) for ticker, score in scores.items()
                if score >= 0.5 and ticker not in positions
            ]
            buy_candidates.sort(key=lambda x: x[1], reverse=True)

            for ticker, score in buy_candidates:
                # Vérifier les contraintes
                if len(positions) >= MAX_POSITIONS:
                    break

                # Recalculer total_value avec les positions actuelles
                current_positions_value = 0.0
                for t, p in positions.items():
                    if t in historical and date in historical[t].index:
                        current_positions_value += p["shares"] * float(historical[t].loc[date, "Close"])
                    elif t in last_known_prices:
                        current_positions_value += p["shares"] * last_known_prices[t]
                current_total = cash + current_positions_value

                # Vérifier cash minimum
                min_cash = current_total * MIN_CASH_PERCENT / 100
                available_cash = cash - min_cash
                if available_cash <= 0:
                    break

                # Montant à investir (proportionnel au score, max 15% du portfolio)
                max_amount = current_total * MAX_POSITION_PERCENT / 100
                # Score entre 0.5 et 1.0 → investir entre 50% et 100% du max
                invest_ratio = 0.5 + (score - 0.5) * 1.0
                amount = min(max_amount * invest_ratio, available_cash)

                if amount < 100:  # Minimum 100€ par trade
                    continue

                price = float(historical[ticker].loc[date, "Close"])
                fee = amount * TRANSACTION_FEE_PERCENT / 100
                net_amount = amount - fee
                shares = net_amount / price

                positions[ticker] = {
                    "shares": shares,
                    "avg_price": price,
                    "total_invested": amount,
                }
                cash -= amount
                total_fees += fee

                transactions_log.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "action": "BUY",
                    "ticker": ticker,
                    "shares": round(shares, 4),
                    "price": round(price, 2),
                    "amount": round(amount, 2),
                    "fee": round(fee, 2),
                    "pnl": 0,
                    "reason": f"signal achat (score={score:.2f})",
                })

        # --- Snapshot quotidien ---
        positions_value = 0.0
        for ticker, pos in positions.items():
            if ticker in historical and date in historical[ticker].index:
                price = float(historical[ticker].loc[date, "Close"])
                last_known_prices[ticker] = price
                positions_value += pos["shares"] * price
            elif ticker in last_known_prices:
                positions_value += pos["shares"] * last_known_prices[ticker]

        total_value = cash + positions_value

        portfolio_history.append({
            "date": date.strftime("%Y-%m-%d"),
            "total_value": round(total_value, 2),
            "cash": round(cash, 2),
            "positions_value": round(positions_value, 2),
            "total_invested": round(total_invested, 2),
            "nb_positions": len(positions),
            "total_fees": round(total_fees, 2),
        })

    # 5. Sauvegarder les résultats
    print("\n💾 Sauvegarde des résultats...")
    os.makedirs(DATA_DIR, exist_ok=True)

    df_history = pd.DataFrame(portfolio_history)
    df_history.to_csv(RESULTS_FILE, index=False)
    print(f"   ✓ {RESULTS_FILE} ({len(df_history)} jours)")

    df_transactions = pd.DataFrame(transactions_log)
    df_transactions.to_csv(TRANSACTIONS_FILE, index=False)
    print(f"   ✓ {TRANSACTIONS_FILE} ({len(df_transactions)} transactions)")

    # 6. Afficher les résultats
    print("\n" + "=" * 60)
    print("📈 RÉSULTATS DU BACKTEST")
    print("=" * 60)

    final_value = portfolio_history[-1]["total_value"]
    total_pnl = final_value - total_invested
    total_pnl_pct = (total_pnl / total_invested) * 100

    # Rendement annualisé
    days = (trading_dates[-1] - trading_dates[0]).days
    annual_return = ((final_value / total_invested) ** (365 / days) - 1) * 100

    # Max drawdown
    values = [h["total_value"] for h in portfolio_history]
    peak = values[0]
    max_dd = 0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100
        if dd > max_dd:
            max_dd = dd

    # Win rate
    sells = [t for t in transactions_log if t["action"] == "SELL"]
    wins = sum(1 for t in sells if t["pnl"] > 0)
    win_rate = (wins / len(sells) * 100) if sells else 0

    print(f"  Capital investi total: {total_invested:,.2f} €")
    print(f"  Valeur finale:         {final_value:,.2f} €")
    print(f"  PnL total:             {total_pnl:+,.2f} € ({total_pnl_pct:+.2f}%)")
    print(f"  Rendement annualisé:   {annual_return:+.2f}%")
    print(f"  Max drawdown:          -{max_dd:.2f}%")
    print(f"  Frais totaux:          {total_fees:,.2f} €")
    print(f"  Nb transactions:       {len(transactions_log)}")
    print(f"  Win rate (ventes):     {win_rate:.1f}%")
    print(f"  Positions finales:     {len(positions)}")
    print("=" * 60)


def run_lumpsum_simulation():
    """Simule la stratégie Lump Sum + DCA sur ETF MSCI World pour comparaison."""
    print("\n📈 Simulation Lump Sum + DCA (IWDA.AS)...")

    try:
        df = yf.download("IWDA.AS", start=BACKTEST_START, end=BACKTEST_END, progress=False)
        if df.empty:
            print("  ❌ Données IWDA indisponibles")
            return
        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
    except Exception as e:
        print(f"  ❌ Erreur: {e}")
        return

    initial_price = float(df["Close"].iloc[0])
    shares = INITIAL_CAPITAL / initial_price
    total_invested = INITIAL_CAPITAL
    contributions_done = set()

    lumpsum_history = []
    start_ts = pd.Timestamp(BACKTEST_START)

    for i, date in enumerate(df.index):
        price = float(df["Close"].iloc[i])

        # Apport mensuel
        month_key = (date.year, date.month)
        if date.day <= 3 and month_key not in contributions_done and date > start_ts + pd.Timedelta(days=25):
            fee = MONTHLY_CONTRIBUTION * TRANSACTION_FEE_PERCENT / 100
            shares += (MONTHLY_CONTRIBUTION - fee) / price
            total_invested += MONTHLY_CONTRIBUTION
            contributions_done.add(month_key)

        lumpsum_history.append({
            "date": date.strftime("%Y-%m-%d"),
            "total_value": round(shares * price, 2),
            "total_invested": round(total_invested, 2),
        })

    # Sauvegarder
    ls_file = os.path.join(DATA_DIR, "backtest_lumpsum.csv")
    pd.DataFrame(lumpsum_history).to_csv(ls_file, index=False)
    print(f"  ✓ {ls_file} ({len(lumpsum_history)} jours)")

    final_value = lumpsum_history[-1]["total_value"]
    pnl = final_value - total_invested
    pnl_pct = (pnl / total_invested) * 100
    print(f"  Valeur finale ETF World: {final_value:,.2f} € ({pnl_pct:+.2f}%)")


if __name__ == "__main__":
    run_backtest()
    run_lumpsum_simulation()
    print("\n✅ Backtest terminé. Relancez le dashboard pour voir les résultats.")
