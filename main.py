"""
Robot de Trading — Point d'entrée principal.

Exécution quotidienne :
1. Récupère les données de marché en temps réel
2. Récupère les actualités financières
3. L'agent IA analyse et décide
4. Exécute les transactions
5. Log tout dans Google Sheets

Rattrapage : si le bot n'a pas tourné depuis plusieurs jours ouvrés, il rejoue
un cycle de décision complet pour chaque jour manqué (prix de clôture historiques
réels) avant de traiter le jour courant. `run_daily()` est donc idempotent :
la relancer plusieurs fois le même jour ne repasse pas d'ordres en double.
"""

import os
import sys
from datetime import date, datetime, timedelta

import pandas as pd

from config import INITIAL_CAPITAL, MONTHLY_CONTRIBUTION, MAX_CATCHUP_DAYS
from market_data import get_current_prices, get_full_market_context, get_full_market_context_for_date
from news_analyzer import get_news_summary
from ai_agent import get_trading_decisions
from portfolio import Portfolio
from local_storage import (
    log_transaction,
    log_portfolio_summary,
    log_daily_journal,
    setup_local_storage,
)

LOCK_FILE = os.path.join(os.path.dirname(__file__), "state", "run.lock")
LOCK_STALE_AFTER = timedelta(minutes=30)


class _RunLockHeld(Exception):
    """Un autre run_daily() détient déjà le verrou."""


class _RunLock:
    """
    Verrou fichier inter-process : empêche deux run_daily() de s'exécuter en même
    temps (ex : plusieurs process dashboard qui redémarrent simultanément et
    déclenchent chacun le rattrapage). Sans ça, deux runs concurrents peuvent tous
    les deux lire le même `last_run_date` avant que l'un ait sauvegardé son état,
    et donc dupliquer un cycle complet (décision IA + logs).
    """

    def __init__(self, path: str):
        self.path = path
        self._acquired = False

    def acquire(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        if os.path.exists(self.path):
            age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(self.path))
            if age < LOCK_STALE_AFTER:
                raise _RunLockHeld()
            # Verrou périmé (run précédent probablement planté) : on le reprend.
            try:
                os.remove(self.path)
            except OSError:
                pass

        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise _RunLockHeld()

        with os.fdopen(fd, "w") as f:
            f.write(f"{os.getpid()} {datetime.now().isoformat()}")
        self._acquired = True

    def release(self):
        if self._acquired and os.path.exists(self.path):
            try:
                os.remove(self.path)
            except OSError:
                pass
        self._acquired = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def run_daily():
    """
    Point d'entrée quotidien. Rattrape d'abord les jours de marché manqués depuis
    le dernier run réussi, puis exécute le cycle du jour courant (sauf s'il a déjà
    été exécuté aujourd'hui). Protégé par un verrou inter-process : si un autre
    run_daily() est déjà en cours, celui-ci s'arrête proprement sans rien dupliquer.
    """
    try:
        with _RunLock(LOCK_FILE):
            _run_daily_locked()
    except _RunLockHeld:
        print("\n⏸ Un autre run est déjà en cours (verrou actif) — run ignoré pour éviter un doublon.")


def _run_daily_locked():
    today = date.today()

    print("=" * 60)
    print(f"  🤖 ROBOT DE TRADING — {today.strftime('%A %d %B %Y')}")
    print(f"  Heure : {datetime.now().strftime('%H:%M:%S')}")
    print("=" * 60)

    print("\n[Portefeuille] Chargement...")
    portfolio = Portfolio()
    print(f"  Cash : {portfolio.cash:,.2f} €")
    print(f"  Positions : {len(portfolio.positions)}")

    last_run = portfolio.get_last_run_date()
    missed_days = _missed_business_days(last_run, today) if last_run else []

    if len(missed_days) > MAX_CATCHUP_DAYS:
        print(
            f"\n⚠ {len(missed_days)} jours manqués détectés — rattrapage limité à "
            f"{MAX_CATCHUP_DAYS} jour(s) sur ce run pour ne pas saturer l'API IA. "
            f"Le reste sera rattrapé au(x) prochain(s) lancement(s)."
        )
        missed_days = missed_days[:MAX_CATCHUP_DAYS]

    if missed_days:
        print(
            f"\n🔄 RATTRAPAGE — {len(missed_days)} jour(s) de marché manqué(s) "
            f"depuis le {last_run.strftime('%d/%m/%Y')}"
        )
        # Une seule récupération de news (best effort) réutilisée pour tous les jours
        # rattrapés : les APIs gratuites ne donnent que l'actualité actuelle, pas
        # d'archive datée du passé.
        catchup_news = get_news_summary(list(portfolio.positions.keys())[:5])

        for i, missed_date in enumerate(missed_days, 1):
            print(f"\n--- Rattrapage {i}/{len(missed_days)} : {missed_date.strftime('%A %d %B %Y')} ---")
            _run_cycle_for_date(portfolio, missed_date, catchup_news, is_catchup=True)

    if last_run == today:
        print(f"\n✓ Déjà exécuté aujourd'hui ({today.strftime('%d/%m/%Y')}). Rien de plus à faire.")
        return

    print(f"\n--- Exécution du jour : {today.strftime('%A %d %B %Y')} ---")
    _run_cycle_for_date(portfolio, today, None, is_catchup=False)


def _missed_business_days(last_run: date, today: date) -> list[date]:
    """Jours ouvrés (lun-ven) strictement après `last_run` et strictement avant `today`."""
    if last_run >= today:
        return []
    start = last_run + timedelta(days=1)
    end = today - timedelta(days=1)
    if start > end:
        return []
    return [d.date() for d in pd.bdate_range(start=start, end=end)]


def _run_cycle_for_date(portfolio: Portfolio, target_date: date, precomputed_news: str, is_catchup: bool) -> bool:
    """
    Exécute un cycle complet de trading pour `target_date` : apport mensuel, prix,
    news, décision IA, exécution des ordres, logging daté sur `target_date`.

    En mode rattrapage (`is_catchup=True`), les prix sont les cours de clôture réels
    de `target_date` (pas les prix actuels). Si le marché était fermé ce jour-là
    (week-end/férié), le cycle est ignoré silencieusement.
    """
    # Apport mensuel (1er au 3 du mois, une seule fois par mois)
    if target_date.day <= 3 and not _contribution_already_done(portfolio, target_date):
        if portfolio.total_invested > INITIAL_CAPITAL:  # Pas le tout premier jour
            portfolio.add_contribution(MONTHLY_CONTRIBUTION, target_date)
            print(f"  💰 Apport mensuel ajouté : +{MONTHLY_CONTRIBUTION:,.2f} €")

    # Données de marché
    if is_catchup:
        market_context, current_prices = get_full_market_context_for_date(target_date)
    else:
        current_prices = get_current_prices()
        market_context = get_full_market_context() if current_prices else ""

    if not current_prices:
        print("  ⚠ Marché fermé ou données indisponibles pour cette date. Ignoré.")
        return False

    print(f"  {len(current_prices)} actifs récupérés")

    # Actualités
    if precomputed_news is not None:
        news_summary = precomputed_news
        if is_catchup:
            news_summary = (
                f"_(⚠ Rattrapage : ces actualités sont celles disponibles au moment du "
                f"rattrapage — elles ne sont pas nécessairement celles du "
                f"{target_date.isoformat()}, qui n'est plus récupérable a posteriori.)_\n\n"
                + news_summary
            )
    else:
        tickers_of_interest = list(portfolio.positions.keys())[:5]
        news_summary = get_news_summary(tickers_of_interest)

    # Décision de l'agent IA
    prices_dict = {t: d["price"] for t, d in current_prices.items()}
    portfolio_state_text = portfolio.get_state_summary(prices_dict)
    ai_decisions = get_trading_decisions(market_context, news_summary, portfolio_state_text)

    print(f"  Sentiment : {ai_decisions.get('overall_sentiment', 'N/A')}")
    print(f"  Risque    : {ai_decisions.get('risk_level', 'N/A')}")
    print(f"  Décisions : {len(ai_decisions.get('decisions', []))}")

    # Exécution des transactions
    transactions_today = []

    for decision in ai_decisions.get("decisions", []):
        action = decision.get("action", "HOLD")
        ticker = decision.get("ticker", "")
        amount = decision.get("amount_eur", 0)
        reasoning = decision.get("reasoning", "")

        if action == "HOLD" or not ticker:
            continue

        if ticker not in prices_dict:
            print(f"  ⚠ {ticker} — prix indisponible, ignoré")
            continue

        price = prices_dict[ticker]

        if action == "BUY" and amount > 0:
            result = portfolio.buy(ticker, amount, price)
            if result:
                transactions_today.append(result)
                log_transaction(result, reasoning, log_date=target_date)
                print(f"  ✓ ACHAT {ticker} — {result['shares']:.4f} parts à {price:.2f} € "
                      f"(total: {result['amount_eur']:.2f} €)")
            else:
                print(f"  ✗ ACHAT {ticker} — Impossible (fonds insuffisants ou contrainte)")

        elif action == "SELL":
            result = portfolio.sell(ticker, price)
            if result:
                transactions_today.append(result)
                log_transaction(result, reasoning, log_date=target_date)
                print(f"  ✓ VENTE {ticker} — {result['shares']:.4f} parts à {price:.2f} € "
                      f"(PnL: {result['pnl']:+.2f} €)")
            else:
                print(f"  ✗ VENTE {ticker} — Position inexistante")

    if not transactions_today:
        print("  → Aucune transaction (HOLD)")

    # Log
    total_value = portfolio.get_total_value(prices_dict)
    portfolio_summary = {
        "cash": portfolio.cash,
        "total_invested": portfolio.total_invested,
        "total_value": total_value,
        "nb_positions": len(portfolio.positions),
        "total_fees": portfolio.total_fees_paid,
    }
    log_portfolio_summary(portfolio_summary, ai_decisions, log_date=target_date)
    log_daily_journal(ai_decisions, transactions_today, log_date=target_date)

    # Marquer ce jour comme traité (même en cas de HOLD) pour le rattrapage futur
    portfolio.mark_run(target_date)

    pnl = total_value - portfolio.total_invested
    print(f"  Valeur totale : {total_value:,.2f} €  |  Cash : {portfolio.cash:,.2f} €  |  "
          f"PnL : {pnl:+,.2f} € ({pnl/portfolio.total_invested*100:+.2f}%)")

    return True


def _contribution_already_done(portfolio: Portfolio, target_date: date) -> bool:
    """Vérifie si l'apport de ce mois a déjà été fait."""
    for entry in reversed(portfolio.history):
        if entry.get("type") == "contribution":
            entry_date = entry.get("date", "")
            if entry_date.startswith(target_date.strftime("%Y-%m")):
                return True
    return False


def setup():
    """Initialisation du stockage local (CSV + Excel)."""
    print("🔧 Setup du stockage local...")
    success = setup_local_storage()
    if success:
        print("✓ Prêt ! Vous pouvez maintenant lancer 'python main.py' quotidiennement.")
    else:
        print("✗ Échec de l'initialisation.")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup()
    else:
        run_daily()
