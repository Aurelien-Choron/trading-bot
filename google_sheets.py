"""
Interface Google Sheets — Log les transactions et le récapitulatif du portefeuille.
Utilise un compte de service Google pour l'authentification.
"""

import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
from config import GOOGLE_SHEETS_ID, GOOGLE_CREDENTIALS_FILE


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Noms des feuilles dans le Google Sheet
SHEET_TRANSACTIONS = "Transactions"
SHEET_PORTFOLIO = "Portefeuille"
SHEET_DAILY_LOG = "Journal"


def _get_client() -> gspread.Client:
    """Authentification avec le compte de service."""
    creds = Credentials.from_service_account_file(GOOGLE_CREDENTIALS_FILE, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_or_create_sheet(spreadsheet, title: str, headers: list[str]):
    """Récupère ou crée une feuille avec les en-têtes."""
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=1000, cols=len(headers))
        worksheet.append_row(headers, value_input_option="RAW")
    return worksheet


def log_transaction(transaction: dict, reasoning: str):
    """
    Ajoute une ligne dans la feuille Transactions.
    """
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)

        headers = [
            "Date", "Heure", "Action", "Ticker", "Parts", "Prix",
            "Montant (€)", "Frais (€)", "PnL (€)", "Cash restant (€)", "Raisonnement"
        ]
        ws = _get_or_create_sheet(spreadsheet, SHEET_TRANSACTIONS, headers)

        now = datetime.now()
        row = [
            now.strftime("%Y-%m-%d"),
            now.strftime("%H:%M:%S"),
            transaction.get("action", ""),
            transaction.get("ticker", ""),
            transaction.get("shares", ""),
            transaction.get("price", ""),
            transaction.get("amount_eur", ""),
            transaction.get("fee", ""),
            transaction.get("pnl", ""),
            transaction.get("cash_remaining", ""),
            reasoning,
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"  ✓ Transaction loguée: {transaction['action']} {transaction['ticker']}")

    except Exception as e:
        print(f"  ⚠ Erreur Google Sheets (transaction): {e}")


def log_portfolio_summary(portfolio_state: dict, ai_analysis: dict):
    """
    Met à jour la feuille Portefeuille avec l'état actuel.
    """
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)

        headers = [
            "Date", "Valeur totale (€)", "Cash (€)", "Positions (€)",
            "Total investi (€)", "PnL (€)", "PnL (%)", "Nb positions",
            "Frais cumulés (€)", "Sentiment IA", "Niveau risque"
        ]
        ws = _get_or_create_sheet(spreadsheet, SHEET_PORTFOLIO, headers)

        cash = portfolio_state.get("cash", 0)
        total_invested = portfolio_state.get("total_invested", 0)
        total_value = portfolio_state.get("total_value", 0)
        positions_value = total_value - cash
        pnl = total_value - total_invested
        pnl_pct = (pnl / total_invested * 100) if total_invested > 0 else 0

        row = [
            datetime.now().strftime("%Y-%m-%d"),
            round(total_value, 2),
            round(cash, 2),
            round(positions_value, 2),
            round(total_invested, 2),
            round(pnl, 2),
            round(pnl_pct, 2),
            portfolio_state.get("nb_positions", 0),
            round(portfolio_state.get("total_fees", 0), 2),
            ai_analysis.get("overall_sentiment", "N/A"),
            ai_analysis.get("risk_level", "N/A"),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"  ✓ Récapitulatif portefeuille logué")

    except Exception as e:
        print(f"  ⚠ Erreur Google Sheets (portefeuille): {e}")


def log_daily_journal(ai_analysis: dict, transactions_today: list[dict]):
    """
    Log l'analyse quotidienne dans la feuille Journal.
    """
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)

        headers = [
            "Date", "Analyse marché", "Sentiment", "Risque",
            "Nb transactions", "Détail décisions"
        ]
        ws = _get_or_create_sheet(spreadsheet, SHEET_DAILY_LOG, headers)

        decisions_text = ""
        for t in transactions_today:
            decisions_text += f"{t['action']} {t['ticker']} ({t.get('amount_eur', 0):.0f}€) | "

        if not decisions_text:
            decisions_text = "HOLD — Aucune action"

        row = [
            datetime.now().strftime("%Y-%m-%d"),
            ai_analysis.get("market_analysis", "")[:500],
            ai_analysis.get("overall_sentiment", "N/A"),
            ai_analysis.get("risk_level", "N/A"),
            len(transactions_today),
            decisions_text.rstrip(" | "),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        print(f"  ✓ Journal quotidien logué")

    except Exception as e:
        print(f"  ⚠ Erreur Google Sheets (journal): {e}")


def setup_spreadsheet():
    """
    Initialise le Google Sheet avec les feuilles nécessaires.
    À appeler une seule fois lors du setup.
    """
    try:
        client = _get_client()
        spreadsheet = client.open_by_key(GOOGLE_SHEETS_ID)

        # Créer les feuilles
        _get_or_create_sheet(spreadsheet, SHEET_TRANSACTIONS, [
            "Date", "Heure", "Action", "Ticker", "Parts", "Prix",
            "Montant (€)", "Frais (€)", "PnL (€)", "Cash restant (€)", "Raisonnement"
        ])
        _get_or_create_sheet(spreadsheet, SHEET_PORTFOLIO, [
            "Date", "Valeur totale (€)", "Cash (€)", "Positions (€)",
            "Total investi (€)", "PnL (€)", "PnL (%)", "Nb positions",
            "Frais cumulés (€)", "Sentiment IA", "Niveau risque"
        ])
        _get_or_create_sheet(spreadsheet, SHEET_DAILY_LOG, [
            "Date", "Analyse marché", "Sentiment", "Risque",
            "Nb transactions", "Détail décisions"
        ])

        print("✓ Google Sheet initialisé avec les feuilles :")
        print(f"  - {SHEET_TRANSACTIONS}")
        print(f"  - {SHEET_PORTFOLIO}")
        print(f"  - {SHEET_DAILY_LOG}")
        return True

    except Exception as e:
        print(f"✗ Erreur setup Google Sheets: {e}")
        return False
