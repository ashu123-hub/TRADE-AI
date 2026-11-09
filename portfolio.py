"""
TradeMind AI - Portfolio & Paper Trading Manager (Groww-Style)
Manages paper trading positions, CNC Delivery & MIS Intraday with 5x leverage,
P&L calculations, and transaction history.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

import database as db
from risk_management import calculate_brokerage

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "paper_trader_01"
PAPER_CAPITAL = 1_000_000.0  # ₹10 Lakh default paper capital
MIS_LEVERAGE = 5.0          # 5x Intraday leverage (Groww / Zerodha standard)


class PaperPortfolio:
    """
    Groww-style Paper Trading Portfolio Engine.
    Supports:
    - Delivery (CNC): 100% margin required
    - Intraday (MIS): 5x leverage (20% margin required)
    - Market and Limit orders
    - Real-time P&L mark-to-market
    - 1-Click Square Off for active positions
    - Virtual Funds deposit
    """

    def __init__(self, user_id: str = DEFAULT_USER_ID, initial_capital: float = PAPER_CAPITAL):
        self.user_id = user_id
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.positions: Dict[str, Dict[str, Any]] = {}  # key -> position dict
        self.transactions: List[Dict[str, Any]] = []
        self.daily_pnl = 0.0

    def buy(
        self,
        symbol: str,
        quantity: int,
        price: float,
        product_type: str = "CNC",
        order_type: str = "MARKET",
        notes: str = "",
    ) -> dict:
        """Execute a paper BUY order."""
        if quantity <= 0 or price <= 0:
            return {"success": False, "error": "Invalid quantity or price"}

        sym = symbol.upper().strip()
        prod = product_type.upper().strip()
        if prod not in ["CNC", "MIS"]:
            prod = "CNC"

        brok = calculate_brokerage(quantity, price, "BUY", product_type=prod)
        turnover = quantity * price

        # Margin required: 100% for CNC, 20% (1/5) for MIS
        margin_required = (turnover / MIS_LEVERAGE) if prod == "MIS" else turnover
        total_cash_needed = margin_required + brok["total_charges"]

        if total_cash_needed > self.cash:
            return {
                "success": False,
                "error": f"Insufficient funds. Need ₹{total_cash_needed:,.2f} (Margin: ₹{margin_required:,.2f} + Charges: ₹{brok['total_charges']:.2f}), available ₹{self.cash:,.2f}",
            }

        self.cash -= total_cash_needed
        pos_key = f"{sym}_{prod}"

        if pos_key in self.positions:
            pos = self.positions[pos_key]
            total_qty = pos["quantity"] + quantity
            avg_price = (pos["quantity"] * pos["avg_price"] + quantity * price) / total_qty
            pos["quantity"] = total_qty
            pos["avg_price"] = round(avg_price, 2)
            pos["margin_blocked"] = round(pos.get("margin_blocked", 0.0) + margin_required, 2)
        else:
            self.positions[pos_key] = {
                "id": pos_key,
                "symbol": sym,
                "product_type": prod,
                "order_type": order_type.upper(),
                "quantity": quantity,
                "avg_price": round(price, 2),
                "current_price": round(price, 2),
                "margin_blocked": round(margin_required, 2),
                "unrealised_pnl": 0.0,
                "unrealised_pnl_pct": 0.0,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }

        txn = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "symbol": sym,
            "product_type": prod,
            "order_type": order_type.upper(),
            "type": "BUY",
            "quantity": quantity,
            "price": round(price, 2),
            "margin_blocked": round(margin_required, 2),
            "brokerage": brok["total_charges"],
            "total_cost": round(total_cash_needed, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
        self.transactions.append(txn)

        # Persist transaction
        try:
            db.add_transaction(self.user_id, sym, f"BUY_{prod}", quantity, price, brok["total_charges"])
        except Exception as exc:
            logger.warning("Could not persist transaction: %s", exc)

        return {"success": True, "transaction": txn, "cash_remaining": round(self.cash, 2)}

    def sell(
        self,
        symbol: str,
        quantity: int,
        price: float,
        product_type: str = "CNC",
        order_type: str = "MARKET",
        notes: str = "",
    ) -> dict:
        """Execute a paper SELL order against existing position."""
        sym = symbol.upper().strip()
        prod = product_type.upper().strip()
        if prod not in ["CNC", "MIS"]:
            prod = "CNC"

        pos_key = f"{sym}_{prod}"
        if pos_key not in self.positions:
            # Fallback check without suffix
            if sym in self.positions:
                pos_key = sym
            else:
                return {"success": False, "error": f"No open {prod} position found for {sym}"}

        pos = self.positions[pos_key]
        if quantity > pos["quantity"]:
            return {"success": False, "error": f"Insufficient quantity. Have {pos['quantity']}, trying to sell {quantity}"}

        brok = calculate_brokerage(quantity, price, "SELL", product_type=prod)
        turnover = quantity * price
        pnl = (price - pos["avg_price"]) * quantity - brok["total_charges"]

        # Calculate released cash:
        if prod == "MIS":
            # For MIS, release blocked margin + realized P&L
            margin_per_unit = pos.get("margin_blocked", 0.0) / max(pos["quantity"], 1)
            released_margin = margin_per_unit * quantity
            cash_returned = released_margin + pnl
            pos["margin_blocked"] = round(max(pos.get("margin_blocked", 0.0) - released_margin, 0.0), 2)
        else:
            # For CNC, full sell turnover minus charges is returned to cash
            cash_returned = turnover - brok["total_charges"]

        self.cash += cash_returned
        self.daily_pnl += pnl

        pos["quantity"] -= quantity
        if pos["quantity"] <= 0:
            del self.positions[pos_key]

        txn = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "symbol": sym,
            "product_type": prod,
            "order_type": order_type.upper(),
            "type": "SELL",
            "quantity": quantity,
            "price": round(price, 2),
            "brokerage": brok["total_charges"],
            "proceeds": round(cash_returned, 2),
            "realised_pnl": round(pnl, 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": notes,
        }
        self.transactions.append(txn)

        try:
            db.add_transaction(self.user_id, sym, f"SELL_{prod}", quantity, price, brok["total_charges"])
        except Exception as exc:
            logger.warning("Could not persist transaction: %s", exc)

        return {
            "success": True,
            "transaction": txn,
            "realised_pnl": round(pnl, 2),
            "cash_remaining": round(self.cash, 2),
        }

    def square_off(self, position_id: str, market_price: Optional[float] = None) -> dict:
        """1-Click Square Off for any position (CNC or MIS)."""
        pos = self.positions.get(position_id)
        if not pos:
            # Try searching by symbol
            for k, p in self.positions.items():
                if p.get("symbol") == position_id.upper():
                    pos = p
                    position_id = k
                    break

        if not pos:
            return {"success": False, "error": f"Position {position_id} not found."}

        exec_price = market_price if (market_price and market_price > 0) else pos.get("current_price", pos["avg_price"])
        return self.sell(
            symbol=pos["symbol"],
            quantity=pos["quantity"],
            price=exec_price,
            product_type=pos.get("product_type", "CNC"),
            order_type="MARKET",
            notes="1-Click Square Off",
        )

    def add_funds(self, amount: float) -> dict:
        """Inject virtual capital into paper trading balance."""
        if amount <= 0:
            return {"success": False, "error": "Deposit amount must be positive."}

        self.cash += amount
        self.initial_capital += amount
        txn = {
            "id": str(uuid.uuid4()),
            "user_id": self.user_id,
            "symbol": "CASH_DEPOSIT",
            "product_type": "FUNDS",
            "order_type": "DEPOSIT",
            "type": "DEPOSIT",
            "quantity": 1,
            "price": round(amount, 2),
            "brokerage": 0.0,
            "proceeds": round(amount, 2),
            "realised_pnl": 0.0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "notes": f"Virtual funds added: ₹{amount:,.2f}",
        }
        self.transactions.append(txn)
        return {"success": True, "added_amount": amount, "new_cash": round(self.cash, 2)}

    def update_market_prices(self, price_map: dict[str, float]):
        """Update unrealised P&L with latest market quotes."""
        for pos_key, pos in self.positions.items():
            sym = pos["symbol"]
            current = price_map.get(sym, pos.get("current_price", pos["avg_price"]))
            pos["current_price"] = round(current, 2)
            qty = pos["quantity"]
            avg = pos["avg_price"]
            unrealised = (current - avg) * qty
            pos["unrealised_pnl"] = round(unrealised, 2)
            pos["unrealised_pnl_pct"] = round((current - avg) / (avg + 1e-9) * 100, 2)

    def get_summary(self) -> dict:
        """Return Groww-style portfolio summary separating CNC Holdings and MIS Positions."""
        holdings = [p for p in self.positions.values() if p.get("product_type") == "CNC"]
        positions = [p for p in self.positions.values() if p.get("product_type") == "MIS"]

        # CNC values
        invested_cnc = sum(p["quantity"] * p["avg_price"] for p in holdings)
        current_cnc = sum(p["quantity"] * p.get("current_price", p["avg_price"]) for p in holdings)
        holdings_pnl = current_cnc - invested_cnc

        # MIS values
        margin_mis = sum(p.get("margin_blocked", 0.0) for p in positions)
        positions_pnl = sum(p.get("unrealised_pnl", 0.0) for p in positions)

        total_unrealised_pnl = holdings_pnl + positions_pnl
        # Portfolio value = Free Cash + CNC Current Value + MIS Margin Blocked + MIS Floating P&L
        portfolio_value = self.cash + current_cnc + margin_mis + positions_pnl
        total_return = portfolio_value - self.initial_capital
        total_return_pct = (total_return / self.initial_capital * 100) if self.initial_capital > 0 else 0.0

        return {
            "portfolio_value": round(portfolio_value, 2),
            "cash": round(self.cash, 2),
            "margin_available": round(self.cash, 2),
            "margin_used": round(margin_mis, 2),
            "invested_cnc": round(invested_cnc, 2),
            "current_cnc": round(current_cnc, 2),
            "holdings_pnl": round(holdings_pnl, 2),
            "positions_pnl": round(positions_pnl, 2),
            "unrealised_pnl": round(total_unrealised_pnl, 2),
            "total_return": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "num_holdings": len(holdings),
            "num_positions": len(positions),
            "initial_capital": round(self.initial_capital, 2),
            "daily_pnl": round(self.daily_pnl, 2),
            "holdings": holdings,
            "positions": positions,
        }

    def get_positions_df(self) -> pd.DataFrame:
        if not self.positions:
            return pd.DataFrame()
        return pd.DataFrame(list(self.positions.values()))

    def get_transactions_df(self) -> pd.DataFrame:
        if not self.transactions:
            return pd.DataFrame()
        return pd.DataFrame(self.transactions)

    def reset(self, capital: float = None):
        """Reset paper portfolio to initial state."""
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
