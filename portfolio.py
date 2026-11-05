"""
TradeMind AI - Portfolio & Paper Trading Manager
Manages paper trading positions, P&L, and transaction history.
Uses in-memory storage with optional Supabase persistence.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import pandas as pd

import database as db
from risk_management import calculate_brokerage, check_daily_loss_limit, calculate_portfolio_exposure

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "paper_trader_01"
PAPER_CAPITAL = 1_000_000.0  # ₹10 Lakh default paper capital


class PaperPortfolio:
    """
    In-memory paper trading portfolio.
    All prices are from live market data — no real order execution.
    """

    def __init__(self, user_id: str = DEFAULT_USER_ID, initial_capital: float = PAPER_CAPITAL):
        self.user_id = user_id
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: dict[str, dict] = {}  # symbol → position dict
        self.transactions: list[dict] = []
        self.daily_pnl = 0.0

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        notes: str = "",
    ) -> dict:
        """Execute a paper BUY order."""
        if quantity <= 0 or price <= 0:
            return {"success": False, "error": "Invalid quantity or price"}

        brok = calculate_brokerage(quantity, price, "BUY")
        total_cost = quantity * price + brok["total_charges"]

        if total_cost > self.cash:
            return {"success": False, "error": f"Insufficient funds. Need ₹{total_cost:,.2f}, have ₹{self.cash:,.2f}"}

        self.cash -= total_cost

        if symbol in self.positions:
            pos = self.positions[symbol]
            total_qty = pos["quantity"] + quantity
            avg_price = (pos["quantity"] * pos["avg_price"] + quantity * price) / total_qty
            pos["quantity"] = total_qty
            pos["avg_price"] = round(avg_price, 2)
        else:
            self.positions[symbol] = {
                "symbol": symbol,
                "quantity": quantity,
                "avg_price": round(price, 2),
                "current_price": price,
                "unrealised_pnl": 0.0,
            }

        txn = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "symbol": symbol,
            "type": "BUY",
            "quantity": quantity,
            "price": round(price, 2),
            "brokerage": brok["total_charges"],
            "total_cost": round(total_cost, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
        self.transactions.append(txn)

        # Persist
        db.add_transaction(self.user_id, symbol, "BUY", quantity, price, brok["total_charges"])

        return {"success": True, "transaction": txn, "cash_remaining": round(self.cash, 2)}

    def sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        notes: str = "",
    ) -> dict:
        """Execute a paper SELL order."""
        if symbol not in self.positions:
            return {"success": False, "error": f"No position in {symbol}"}
        pos = self.positions[symbol]
        if quantity > pos["quantity"]:
            return {"success": False, "error": f"Insufficient shares. Have {pos['quantity']}, selling {quantity}"}

        brok = calculate_brokerage(quantity, price, "SELL")
        proceeds = quantity * price - brok["total_charges"]
        pnl = (price - pos["avg_price"]) * quantity - brok["total_charges"]

        self.cash += proceeds
        self.daily_pnl += pnl

        pos["quantity"] -= quantity
        if pos["quantity"] == 0:
            del self.positions[symbol]

        txn = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "symbol": symbol,
            "type": "SELL",
            "quantity": quantity,
            "price": round(price, 2),
            "brokerage": brok["total_charges"],
            "proceeds": round(proceeds, 2),
            "realised_pnl": round(pnl, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
        self.transactions.append(txn)

        db.add_transaction(self.user_id, symbol, "SELL", quantity, price, brok["total_charges"])

        return {"success": True, "transaction": txn, "realised_pnl": round(pnl, 2), "cash_remaining": round(self.cash, 2)}

    def update_market_prices(self, price_map: dict[str, float]):
        """Update unrealised P&L with current market prices."""
        for symbol, pos in self.positions.items():
            current = price_map.get(symbol, pos["avg_price"])
            pos["current_price"] = current
            pos["unrealised_pnl"] = round((current - pos["avg_price"]) * pos["quantity"], 2)
            pos["unrealised_pnl_pct"] = round((current - pos["avg_price"]) / (pos["avg_price"] + 1e-9) * 100, 2)

    def get_summary(self) -> dict:
        """Return portfolio summary."""
        total_invested = sum(p["quantity"] * p["avg_price"] for p in self.positions.values())
        total_current = sum(p["quantity"] * p.get("current_price", p["avg_price"]) for p in self.positions.values())
        unrealised_pnl = total_current - total_invested
        portfolio_value = self.cash + total_current
        total_return = portfolio_value - self.initial_capital
        total_return_pct = total_return / self.initial_capital * 100

        return {
            "portfolio_value": round(portfolio_value, 2),
            "cash": round(self.cash, 2),
            "invested": round(total_invested, 2),
            "unrealised_pnl": round(unrealised_pnl, 2),
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "num_positions": len(self.positions),
            "initial_capital": self.initial_capital,
            "daily_pnl": round(self.daily_pnl, 2),
        }

    def get_positions_df(self) -> pd.DataFrame:
        if not self.positions:
            return pd.DataFrame()
        rows = list(self.positions.values())
        return pd.DataFrame(rows)

    def get_transactions_df(self) -> pd.DataFrame:
        if not self.transactions:
            return pd.DataFrame()
        return pd.DataFrame(self.transactions)

    def reset(self, capital: float = None):
        """Reset paper portfolio."""
        self.cash = capital or self.initial_capital
        self.initial_capital = self.cash
        self.positions = {}
        self.transactions = []
        self.daily_pnl = 0.0
        logger.info("Paper portfolio reset. Capital: ₹%s", f"{self.cash:,.0f}")


# ─── Global Paper Portfolio ───────────────────────────────────────────────────
_paper_portfolio: PaperPortfolio | None = None


def get_portfolio() -> PaperPortfolio:
    global _paper_portfolio
    if _paper_portfolio is None:
        _paper_portfolio = PaperPortfolio()
    return _paper_portfolio
