"""
Agent IA décisionnel — Analyse le marché et les news pour prendre des décisions.
Utilise l'API OpenAI (GPT-4o) pour générer des recommandations structurées.
"""

import json
from openai import OpenAI
from config import OPENAI_API_KEY, AI_MODEL, MAX_POSITION_PERCENT, MAX_POSITIONS, MIN_CASH_PERCENT


client = OpenAI(api_key=OPENAI_API_KEY, base_url="https://api.groq.com/openai/v1")

SYSTEM_PROMPT = """Tu es un gestionnaire de portefeuille professionnel. Ton objectif est de maximiser les rendements à long terme tout en gérant le risque.

## Règles strictes :
- Maximum {max_pos_pct}% du portefeuille par position
- Maximum {max_positions} positions simultanées
- Garder minimum {min_cash_pct}% du portefeuille en cash (réserve de sécurité)
- Frais de transaction : 0.25% par opération (les prendre en compte)
- Tu peux investir, vendre ou ne rien faire (HOLD)

## Ton approche :
1. Analyser les conditions macro (indices, VIX, tendance générale)
2. Analyser les news (impact sur les actifs)
3. Regarder les indicateurs techniques (RSI, tendances, MACD)
4. Prendre une décision argumentée

## Format de réponse OBLIGATOIRE (JSON strict) :
{{
  "market_analysis": "Résumé de ton analyse macro en 2-3 phrases",
  "decisions": [
    {{
      "action": "BUY" | "SELL" | "HOLD",
      "ticker": "SYMBOLE",
      "amount_eur": 500,
      "reasoning": "Explication détaillée de la décision",
      "confidence": 0.8
    }}
  ],
  "overall_sentiment": "BULLISH" | "BEARISH" | "NEUTRAL",
  "risk_level": "LOW" | "MEDIUM" | "HIGH"
}}

Si tu ne veux rien faire aujourd'hui, retourne decisions: [] avec une explication dans market_analysis.
N'invente JAMAIS de données. Base-toi uniquement sur les informations fournies.
""".format(
    max_pos_pct=MAX_POSITION_PERCENT,
    max_positions=MAX_POSITIONS,
    min_cash_pct=MIN_CASH_PERCENT,
)


def get_trading_decisions(
    market_context: str,
    news_summary: str,
    portfolio_state: str,
) -> dict:
    """
    Appelle l'agent IA avec le contexte complet et retourne les décisions.
    """
    user_message = f"""# Contexte du jour — {_today()}

## État de mon portefeuille
{portfolio_state}

## Données de marché
{market_context}

## Actualités
{news_summary}

---

Analyse la situation et donne-moi tes décisions d'investissement pour aujourd'hui.
Rappel : tu peux aussi décider de ne rien faire (HOLD) si le moment n'est pas propice.
"""

    try:
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.3,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        decisions = json.loads(content)

        # Validation basique
        if "decisions" not in decisions:
            decisions["decisions"] = []
        if "market_analysis" not in decisions:
            decisions["market_analysis"] = "Analyse non disponible"

        return decisions

    except json.JSONDecodeError as e:
        return {
            "market_analysis": f"Erreur de parsing de la réponse IA: {e}",
            "decisions": [],
            "overall_sentiment": "NEUTRAL",
            "risk_level": "HIGH",
        }
    except Exception as e:
        return {
            "market_analysis": f"Erreur API: {e}",
            "decisions": [],
            "overall_sentiment": "NEUTRAL",
            "risk_level": "HIGH",
        }


def _today() -> str:
    from datetime import date
    return date.today().strftime("%Y-%m-%d")
