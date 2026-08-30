"""
Récupération des données de marché en temps réel via yfinance.
Fournit prix actuels, historiques récents et indicateurs techniques.
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import date, datetime, timedelta
from config import UNIVERSE


def get_current_prices(tickers: list[str] = None) -> dict[str, dict]:
    """
    Récupère les prix actuels et les variations pour chaque ticker.
    Retourne un dict {ticker: {price, change_1d, change_5d, volume, ...}}
    """
    tickers = tickers or UNIVERSE
    result = {}

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d").dropna(subset=["Close"])
            if hist.empty:
                continue

            current_price = hist["Close"].iloc[-1]
            prev_price = hist["Close"].iloc[-2] if len(hist) >= 2 else current_price
            price_5d_ago = hist["Close"].iloc[0] if len(hist) >= 5 else prev_price

            result[ticker] = {
                "price": round(current_price, 2),
                "change_1d_pct": round((current_price / prev_price - 1) * 100, 2),
                "change_5d_pct": round((current_price / price_5d_ago - 1) * 100, 2),
                "volume": int(hist["Volume"].iloc[-1]),
                "high": round(hist["High"].iloc[-1], 2),
                "low": round(hist["Low"].iloc[-1], 2),
            }
        except Exception as e:
            print(f"  ⚠ Erreur {ticker}: {e}")

    return result


def get_technical_indicators(ticker: str, period: str = "3mo") -> dict:
    """
    Calcule les indicateurs techniques pour un ticker donné.
    RSI, SMA20, SMA50, MACD, Bollinger Bands.
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period=period).dropna(subset=["Close"])
        if len(hist) < 50:
            return {}

        close = hist["Close"]

        # RSI (14 jours)
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(window=14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # Moyennes mobiles
        sma20 = close.rolling(window=20).mean()
        sma50 = close.rolling(window=50).mean()

        # MACD
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd = ema12 - ema26
        macd_signal = macd.ewm(span=9, adjust=False).mean()

        # Bollinger Bands
        bb_mid = sma20
        bb_std = close.rolling(window=20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std

        current_price = close.iloc[-1]

        return {
            "rsi": round(rsi.iloc[-1], 1),
            "sma20": round(sma20.iloc[-1], 2),
            "sma50": round(sma50.iloc[-1], 2),
            "macd": round(macd.iloc[-1], 3),
            "macd_signal": round(macd_signal.iloc[-1], 3),
            "macd_histogram": round((macd.iloc[-1] - macd_signal.iloc[-1]), 3),
            "bb_upper": round(bb_upper.iloc[-1], 2),
            "bb_lower": round(bb_lower.iloc[-1], 2),
            "price_vs_sma20": round((current_price / sma20.iloc[-1] - 1) * 100, 2),
            "price_vs_sma50": round((current_price / sma50.iloc[-1] - 1) * 100, 2),
            "trend": "BULLISH" if sma20.iloc[-1] > sma50.iloc[-1] else "BEARISH",
        }
    except Exception as e:
        print(f"  ⚠ Indicateurs {ticker}: {e}")
        return {}


def get_market_summary() -> str:
    """
    Fournit un résumé textuel de l'état du marché pour l'agent IA.
    Inclut les indices majeurs et les variations.
    """
    indices = {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^STOXX50E": "Euro Stoxx 50",
        "^N225": "Nikkei 225",
        "^VIX": "VIX (Volatilité)",
    }

    summary_parts = ["## État du marché aujourd'hui\n"]

    for ticker, name in indices.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="5d").dropna(subset=["Close"])
            if hist.empty:
                continue
            price = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) >= 2 else price
            change = (price / prev - 1) * 100
            summary_parts.append(f"- **{name}**: {price:,.2f} ({change:+.2f}%)")
        except Exception:
            pass

    return "\n".join(summary_parts)


def get_full_market_context(tickers: list[str] = None) -> str:
    """
    Génère un contexte marché complet pour l'agent IA décisionnel.
    """
    tickers = tickers or UNIVERSE
    prices = get_current_prices(tickers)
    market = get_market_summary()

    context = market + "\n\n## Prix et variations de l'univers d'investissement\n\n"
    context += "| Ticker | Prix | Var 1j | Var 5j | Volume |\n"
    context += "|--------|------|--------|--------|--------|\n"

    for ticker, data in prices.items():
        context += (
            f"| {ticker} | {data['price']:.2f} | {data['change_1d_pct']:+.2f}% "
            f"| {data['change_5d_pct']:+.2f}% | {data['volume']:,} |\n"
        )

    # Indicateurs techniques pour les tickers avec du mouvement
    context += "\n## Indicateurs techniques (actifs significatifs)\n\n"
    for ticker, data in prices.items():
        if abs(data["change_5d_pct"]) > 2 or abs(data["change_1d_pct"]) > 1.5:
            indicators = get_technical_indicators(ticker)
            if indicators:
                context += f"\n### {ticker}\n"
                context += f"- RSI: {indicators.get('rsi', 'N/A')}\n"
                context += f"- Tendance: {indicators.get('trend', 'N/A')}\n"
                context += f"- MACD Histogram: {indicators.get('macd_histogram', 'N/A')}\n"
                context += f"- Prix vs SMA20: {indicators.get('price_vs_sma20', 'N/A')}%\n"
                context += f"- Prix vs SMA50: {indicators.get('price_vs_sma50', 'N/A')}%\n"

    return context


# --- Rattrapage des jours manqués : prix historiques ancrés sur une date passée ---

def get_prices_on_date(target_date: date, tickers: list[str] = None) -> dict[str, dict]:
    """
    Récupère les prix de clôture (et variations) tels qu'ils étaient réellement à une
    date passée. Retourne un dict vide pour les tickers sans séance ce jour-là
    (marché fermé : week-end, jour férié) — l'appelant doit gérer ce cas comme un
    jour non ouvré plutôt que comme une erreur.
    """
    tickers = tickers or UNIVERSE
    result = {}
    start = target_date - timedelta(days=10)
    end = target_date + timedelta(days=1)

    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(start=start, end=end).dropna(subset=["Close"])
            if hist.empty:
                continue
            hist.index = hist.index.tz_localize(None)
            hist = hist[hist.index.date <= target_date]
            if hist.empty or hist.index[-1].date() != target_date:
                continue  # Pas de séance ce jour-là

            current_price = hist["Close"].iloc[-1]
            prev_price = hist["Close"].iloc[-2] if len(hist) >= 2 else current_price
            price_5d_ago = hist["Close"].iloc[-5] if len(hist) >= 5 else prev_price

            result[ticker] = {
                "price": round(current_price, 2),
                "change_1d_pct": round((current_price / prev_price - 1) * 100, 2),
                "change_5d_pct": round((current_price / price_5d_ago - 1) * 100, 2),
                "volume": int(hist["Volume"].iloc[-1]),
                "high": round(hist["High"].iloc[-1], 2),
                "low": round(hist["Low"].iloc[-1], 2),
            }
        except Exception as e:
            print(f"  ⚠ Erreur historique {ticker} ({target_date}): {e}")

    return result


def get_market_summary_for_date(target_date: date) -> str:
    """Résumé textuel des indices majeurs tels qu'ils étaient à une date passée."""
    indices = {
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "^STOXX50E": "Euro Stoxx 50",
        "^N225": "Nikkei 225",
        "^VIX": "VIX (Volatilité)",
    }

    summary_parts = [f"## État du marché au {target_date.isoformat()} (rattrapage)\n"]
    start = target_date - timedelta(days=10)
    end = target_date + timedelta(days=1)

    for ticker, name in indices.items():
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(start=start, end=end).dropna(subset=["Close"])
            if hist.empty:
                continue
            hist.index = hist.index.tz_localize(None)
            hist = hist[hist.index.date <= target_date]
            if hist.empty:
                continue
            price = hist["Close"].iloc[-1]
            prev = hist["Close"].iloc[-2] if len(hist) >= 2 else price
            change = (price / prev - 1) * 100
            summary_parts.append(f"- **{name}**: {price:,.2f} ({change:+.2f}%)")
        except Exception:
            pass

    return "\n".join(summary_parts)


def get_full_market_context_for_date(target_date: date, tickers: list[str] = None) -> tuple[str, dict]:
    """
    Génère un contexte marché "tel qu'il était" à une date passée, pour le rattrapage.
    Contrairement à get_full_market_context(), n'inclut pas d'indicateurs techniques
    (ceux-ci ne peuvent pas être ancrés fiablement sur une date passée avec les
    fonctions existantes) — reste un contexte "best effort" pour l'IA.
    Retourne (contexte_texte, prix_du_jour).
    """
    tickers = tickers or UNIVERSE
    prices = get_prices_on_date(target_date, tickers)
    market = get_market_summary_for_date(target_date)

    context = market + f"\n\n## Prix et variations de l'univers d'investissement au {target_date.isoformat()}\n\n"
    context += "| Ticker | Prix | Var 1j | Var 5j | Volume |\n"
    context += "|--------|------|--------|--------|--------|\n"

    for ticker, data in prices.items():
        context += (
            f"| {ticker} | {data['price']:.2f} | {data['change_1d_pct']:+.2f}% "
            f"| {data['change_5d_pct']:+.2f}% | {data['volume']:,} |\n"
        )

    return context, prices
