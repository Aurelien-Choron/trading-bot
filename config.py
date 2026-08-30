"""
Configuration du robot de trading.
Variables d'environnement et paramètres de simulation.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- Capital ---
INITIAL_CAPITAL = 10_000.0  # € mise de départ
MONTHLY_CONTRIBUTION = 500.0  # € apport mensuel

# --- Frais ---
TRANSACTION_FEE_PERCENT = 0.25  # 0.25% par transaction

# --- Univers d'investissement (ETFs + actions mondiales) ---
UNIVERSE = [
    # ETFs monde
    "IWDA.AS",   # iShares Core MSCI World (Amsterdam)
    "VWCE.DE",   # Vanguard FTSE All-World (Xetra)
    "CSPX.L",    # iShares Core S&P 500 (Londres)
    "EUNL.DE",   # iShares Core MSCI World (Xetra)
    # ETFs sectoriels
    "IUIT.L",    # iShares S&P 500 IT Sector
    "IHCL.L",    # iShares S&P 500 Health Care
    "IUES.L",    # iShares S&P 500 Energy
    # Actions US
    "AAPL",      # Apple
    "MSFT",      # Microsoft
    "GOOGL",     # Alphabet
    "AMZN",      # Amazon
    "NVDA",      # Nvidia
    "META",      # Meta
    "TSLA",      # Tesla
    # Actions Europe
    "MC.PA",     # LVMH
    "ASML.AS",   # ASML
    "SAP.DE",    # SAP
    "SIE.DE",    # Siemens
    # ETF Or
    "SGLD.L",    # Invesco Physical Gold ETC (Londres)
    # Actions Défense/Armement
    "LMT",       # Lockheed Martin
    "RTX",       # RTX (ex-Raytheon)
    "NOC",       # Northrop Grumman
    "BA",        # Boeing
    "HO.PA",     # Thales (Paris)
    # Actions Asie
    "9984.T",    # SoftBank
    "005930.KS", # Samsung
    # Drones / Surveillance
    "DRO.AX",   # DroneShield (ASX)
]

# --- API Keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "")
GOOGLE_CREDENTIALS_FILE = os.getenv(
    "GOOGLE_CREDENTIALS_FILE",
    os.path.join(os.path.dirname(__file__), "credentials", "service_account.json")
)

# --- AI Agent ---
AI_MODEL = os.getenv("AI_MODEL", "openai/gpt-oss-120b")

# --- Gestion du risque ---
MAX_POSITION_PERCENT = 15.0    # Max 15% du portefeuille par position
MAX_POSITIONS = 10             # Max 10 positions simultanées
MIN_CASH_PERCENT = 10.0        # Garder min 10% en cash

# --- Rattrapage des jours manqués ---
# Nombre max de jours de marché rattrapés en un seul run (1 appel IA par jour).
# Si plus de jours sont manqués, le reste est rattrapé au(x) prochain(s) lancement(s).
MAX_CATCHUP_DAYS = 15

# --- Fichier d'état local ---
STATE_FILE = os.path.join(os.path.dirname(__file__), "state", "portfolio_state.json")
