"""
Gestion du portefeuille — État, achats, ventes, valorisation.
Persistance de l'état dans un fichier JSON local.
"""

import json
import os
from datetime import date, datetime
from typing import Optional
from config import (
    INITIAL_CAPITAL, TRANSACTION_FEE_PERCENT,
    MAX_POSITION_PERCENT, MIN_CASH_PERCENT, STATE_FILE,
)


class Portfolio:
    def __init__(self):
        self.cash = INITIAL_CAPITAL
        self.positions: dict[str, dict] = {}  # {ticker: {shares, avg_price, total_invested}}
        self.total_invested = INITIAL_CAPITAL
        self.total_fees_paid = 0.0
        self.history: list[dict] = []  # Historique des actions
        self.start_date = date.today().isoformat()
        self.last_run_date: Optional[str] = None  # Date ISO du dernier cycle exécuté (même HOLD)

        # Charger l'état existant s'il existe
        self._load_state()

    def _load_state(self):
        """Charge l'état du portefeuille depuis le fichier JSON."""
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            self.cash = state.get("cash", self.cash)
            self.positions = state.get("positions", {})
            self.total_invested = state.get("total_invested", self.total_invested)
            self.total_fees_paid = state.get("total_fees_paid", 0.0)
            self.history = state.get("history", [])
            self.start_date = state.get("start_date", self.start_date)
            self.last_run_date = state.get("last_run_date")

    def _save_state(self):
        """Sauvegarde l'état du portefeuille."""
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        state = {
            "cash": round(self.cash, 2),
            "positions": self.positions,
            "total_invested": round(self.total_invested, 2),
            "total_fees_paid": round(self.total_fees_paid, 4),
            "history": self.history,
            "start_date": self.start_date,
            "last_run_date": self.last_run_date,
            "last_updated": datetime.now().isoformat(),
        }
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    def get_last_run_date(self) -> Optional[date]:
        """Retourne la date du dernier cycle exécuté avec succès, ou None si jamais exécuté."""
        if not self.last_run_date:
            return None
        return date.fromisoformat(self.last_run_date)

    def mark_run(self, run_date: date):
        """Marque qu'un cycle complet (rattrapage ou jour courant) a été exécuté pour cette date."""
        self.last_run_date = run_date.isoformat()
        self._save_state()

    def add_contribution(self, amount: float, contribution_date: date = None):
        """Ajoute un apport au portefeuille et l'enregistre dans l'historique."""
        self.cash += amount
        self.total_invested += amount
        self.history.append({
            "type": "contribution",
            "date": (contribution_date or date.today()).isoformat(),
            "amount": amount,
        })
        self._save_state()

    def buy(self, ticker: str, amount_eur: float, price: float) -> Optional[dict]:
        """
        Achète un actif. Retourne le détail de la transaction ou None si impossible.
        """
        fee = amount_eur * TRANSACTION_FEE_PERCENT / 100
        total_cost = amount_eur + fee

        if total_cost > self.cash:
            return None

        # Vérifier la contrainte de cash minimum
        total_value = self.get_total_value_estimate()
        if (self.cash - total_cost) < total_value * MIN_CASH_PERCENT / 100:
            # On ajuste le montant pour respecter la contrainte
            max_invest = self.cash - (total_value * MIN_CASH_PERCENT / 100)
            if max_invest <= 0:
                return None
            amount_eur = min(amount_eur, max_invest * (1 - TRANSACTION_FEE_PERCENT / 100))
            fee = amount_eur * TRANSACTION_FEE_PERCENT / 100
            total_cost = amount_eur + fee

        shares = amount_eur / price

        # Mettre à jour les positions
        if ticker in self.positions:
            pos = self.positions[ticker]
            total_shares = pos["shares"] + shares
            pos["avg_price"] = (pos["shares"] * pos["avg_price"] + shares * price) / total_shares
            pos["shares"] = round(total_shares, 6)
            pos["total_invested"] += amount_eur
        else:
            self.positions[ticker] = {
                "shares": round(shares, 6),
                "avg_price": round(price, 4),
                "total_invested": round(amount_eur, 2),
                "buy_date": date.today().isoformat(),
            }

        self.cash -= total_cost
        self.total_fees_paid += fee
        self._save_state()

        return {
            "action": "BUY",
            "ticker": ticker,
            "shares": round(shares, 6),
            "price": round(price, 4),
            "amount_eur": round(amount_eur, 2),
            "fee": round(fee, 4),
            "cash_remaining": round(self.cash, 2),
        }

    def sell(self, ticker: str, price: float, shares: float = None) -> Optional[dict]:
        """
        Vend un actif (tout ou une partie). Retourne le détail ou None.
        """
        if ticker not in self.positions:
            return None

        pos = self.positions[ticker]
        shares_to_sell = shares or pos["shares"]
        shares_to_sell = min(shares_to_sell, pos["shares"])

        gross_amount = shares_to_sell * price
        fee = gross_amount * TRANSACTION_FEE_PERCENT / 100
        net_amount = gross_amount - fee

        # PnL
        cost_basis = shares_to_sell * pos["avg_price"]
        pnl = net_amount - cost_basis

        # Mettre à jour
        pos["shares"] = round(pos["shares"] - shares_to_sell, 6)
        if pos["shares"] <= 0.0001:
            del self.positions[ticker]
        else:
            pos["total_invested"] -= cost_basis

        self.cash += net_amount
        self.total_fees_paid += fee
        self._save_state()

        return {
            "action": "SELL",
            "ticker": ticker,
            "shares": round(shares_to_sell, 6),
            "price": round(price, 4),
            "amount_eur": round(net_amount, 2),
            "fee": round(fee, 4),
            "pnl": round(pnl, 2),
            "cash_remaining": round(self.cash, 2),
        }

    def get_total_value_estimate(self) -> float:
        """Estimation rapide de la valeur totale (cash + positions au cost)."""
        positions_value = sum(
            pos["shares"] * pos["avg_price"] for pos in self.positions.values()
        )
        return self.cash + positions_value

    def get_total_value(self, current_prices: dict[str, float]) -> float:
        """Valeur totale précise avec les prix actuels."""
        positions_value = sum(
            pos["shares"] * current_prices.get(ticker, pos["avg_price"])
            for ticker, pos in self.positions.items()
        )
        return self.cash + positions_value

    def get_state_summary(self, current_prices: dict[str, float] = None) -> str:
        """Résumé du portefeuille pour l'agent IA."""
        total = self.get_total_value(current_prices) if current_prices else self.get_total_value_estimate()
        pnl = total - self.total_invested
        pnl_pct = (pnl / self.total_invested * 100) if self.total_invested > 0 else 0

        lines = [
            f"- **Cash disponible** : {self.cash:,.2f} € ({self.cash/total*100:.1f}%)",
            f"- **Valeur totale** : {total:,.2f} €",
            f"- **Total investi** : {self.total_invested:,.2f} €",
            f"- **PnL** : {pnl:+,.2f} € ({pnl_pct:+.2f}%)",
            f"- **Frais totaux** : {self.total_fees_paid:.2f} €",
            f"- **Positions actives** : {len(self.positions)}/{12}",
            f"- **Depuis** : {self.start_date}",
            "",
            "### Positions détaillées :",
        ]

        if self.positions:
            lines.append("| Ticker | Parts | Px Achat | Px Actuel | Valeur | PnL |")
            lines.append("|--------|-------|----------|-----------|--------|-----|")
            for ticker, pos in self.positions.items():
                current = current_prices.get(ticker, pos["avg_price"]) if current_prices else pos["avg_price"]
                value = pos["shares"] * current
                pos_pnl = value - pos["shares"] * pos["avg_price"]
                lines.append(
                    f"| {ticker} | {pos['shares']:.4f} | {pos['avg_price']:.2f} "
                    f"| {current:.2f} | {value:.2f} € | {pos_pnl:+.2f} € |"
                )
        else:
            lines.append("_Aucune position ouverte_")

        return "\n".join(lines)
