"""
Récupération et synthèse des actualités financières.
Utilise les feeds RSS gratuits + Yahoo Finance news.
"""

import yfinance as yf
import xml.etree.ElementTree as ET
from urllib.request import urlopen, Request
from datetime import datetime


# Feeds RSS financiers gratuits
RSS_FEEDS = [
    ("Reuters Business", "https://feeds.reuters.com/reuters/businessNews"),
    ("CNBC Top News", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114"),
    ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
]


def get_rss_news(max_per_feed: int = 5) -> list[dict]:
    """Récupère les dernières news depuis les feeds RSS financiers."""
    news = []

    for feed_name, url in RSS_FEEDS:
        try:
            req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urlopen(req, timeout=10) as response:
                tree = ET.parse(response)
            root = tree.getroot()

            # Gérer les namespaces Atom vs RSS
            items = root.findall(".//item")
            if not items:
                items = root.findall(".//{http://www.w3.org/2005/Atom}entry")

            for item in items[:max_per_feed]:
                title = item.findtext("title") or item.findtext("{http://www.w3.org/2005/Atom}title") or ""
                summary = item.findtext("description") or item.findtext("{http://www.w3.org/2005/Atom}summary") or ""
                published = item.findtext("pubDate") or item.findtext("{http://www.w3.org/2005/Atom}published") or ""
                link = item.findtext("link") or ""
                if not link:
                    link_el = item.find("{http://www.w3.org/2005/Atom}link")
                    if link_el is not None:
                        link = link_el.get("href", "")

                news.append({
                    "source": feed_name,
                    "title": title.strip(),
                    "summary": summary[:200].strip(),
                    "published": published,
                    "link": link.strip(),
                })
        except Exception as e:
            print(f"  ⚠ Feed {feed_name}: {e}")

    return news


def get_ticker_news(ticker: str) -> list[dict]:
    """Récupère les news spécifiques à un ticker via Yahoo Finance."""
    try:
        stock = yf.Ticker(ticker)
        news_items = stock.news or []
        result = []
        for item in news_items[:5]:
            result.append({
                "source": item.get("publisher", "Yahoo Finance"),
                "title": item.get("title", ""),
                "summary": "",
                "published": datetime.fromtimestamp(
                    item.get("providerPublishTime", 0)
                ).strftime("%Y-%m-%d %H:%M") if item.get("providerPublishTime") else "",
                "link": item.get("link", ""),
            })
        return result
    except Exception as e:
        print(f"  ⚠ News {ticker}: {e}")
        return []


def get_news_summary(tickers_of_interest: list[str] = None) -> str:
    """
    Génère un résumé textuel des news pour l'agent IA.
    """
    parts = ["## Actualités financières du jour\n"]

    # News générales
    general_news = get_rss_news(max_per_feed=3)
    if general_news:
        parts.append("### Actualités générales\n")
        for n in general_news[:10]:
            parts.append(f"- [{n['source']}] **{n['title']}**")
            if n["summary"]:
                parts.append(f"  _{n['summary'][:150]}_")

    # News spécifiques aux tickers d'intérêt
    if tickers_of_interest:
        parts.append("\n### Actualités par actif\n")
        for ticker in tickers_of_interest[:5]:
            ticker_news = get_ticker_news(ticker)
            if ticker_news:
                parts.append(f"\n**{ticker}:**")
                for n in ticker_news[:3]:
                    parts.append(f"- {n['title']}")

    return "\n".join(parts)
