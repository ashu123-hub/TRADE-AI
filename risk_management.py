"""
TradeMind AI - Risk Management Module
Stop-loss, target price, position sizing, R:R calculation.
Paper trading only — never executes real orders.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ─── Stop-Loss ───────────────────────────────────────────────────────────────

def calculate_stop_loss(
    entry_price: float,
    signal: str,
    atr: float,
    atr_multiplier: float = 1.5,
    min_pct: float = 0.5,
    max_pct: float = 5.0,
) -> float:
    """
    ATR-based stop-loss.
    BUY: stop below entry. SELL: stop above entry.
    """
    if entry_price <= 0:
        return 0.0
    atr_stop = atr * atr_multiplier
    pct_stop = max(min_pct, min(max_pct, atr_stop / entry_price * 100))
    factor = pct_stop / 100

    if signal == "BUY":
        return round(entry_price * (1 - factor), 2)
    elif signal == "SELL":
        return round(entry_price * (1 + factor), 2)
    return round(entry_price * (1 - factor), 2)  # default


def calculate_target_price(
    entry_price: float,
    signal: str,
    atr: float,
    rr_ratio: float = 2.0,
    atr_multiplier: float = 1.5,
) -> float:
    """
    ATR × RR-based target price.
    """
    if entry_price <= 0:
        return 0.0
    target_move = atr * atr_multiplier * rr_ratio
    if signal == "BUY":
        return round(entry_price + target_move, 2)
    elif signal == "SELL":
        return round(entry_price - target_move, 2)
    return round(entry_price + target_move, 2)


def calculate_risk_reward(
    entry_price: float,
    target_price: float,
    stop_loss: float,
) -> float:
    """Return Risk/Reward ratio."""
    risk = abs(entry_price - stop_loss)
    reward = abs(target_price - entry_price)
    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


# ─── Position Sizing ─────────────────────────────────────────────────────────

def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_loss: float,
    risk_pct: float = 2.0,
) -> dict:
    """
    Fixed-fractional position sizing.
    Risks `risk_pct`% of capital per trade.
    """
    if entry_price <= 0 or stop_loss <= 0 or capital <= 0:
        return {"quantity": 0, "risk_amount": 0.0, "position_value": 0.0}

    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share == 0:
        return {"quantity": 0, "risk_amount": 0.0, "position_value": 0.0}

    risk_amount = capital * (risk_pct / 100)
    quantity = int(risk_amount / risk_per_share)
    position_value = quantity * entry_price

    # Cap at 20% of capital
    max_position = capital * 0.20
    if position_value > max_position:
        quantity = int(max_position / entry_price)
        position_value = quantity * entry_price

    return {
        "quantity": max(quantity, 0),
        "risk_amount": round(risk_amount, 2),
        "position_value": round(position_value, 2),
        "risk_per_share": round(risk_per_share, 2),
    }


def calculate_portfolio_exposure(positions: list[dict], capital: float) -> dict:
    """Calculate current portfolio exposure."""
    total_invested = sum(p.get("quantity", 0) * p.get("avg_price", 0) for p in positions)
    exposure_pct = (total_invested / capital * 100) if capital > 0 else 0.0
    return {
        "total_invested": round(total_invested, 2),
        "exposure_pct": round(exposure_pct, 2),
        "free_capital": round(capital - total_invested, 2),
        "num_positions": len(positions),
    }


# ─── Daily Loss Limit ────────────────────────────────────────────────────────

def check_daily_loss_limit(
    daily_pnl: float,
    capital: float,
    limit_pct: float = 5.0,
) -> dict:
    """Check if daily loss limit is breached."""
    limit = capital * (limit_pct / 100)
    breached = daily_pnl < -limit
    return {
        "daily_pnl": round(daily_pnl, 2),
        "limit": round(-limit, 2),
        "breached": breached,
        "message": "⛔ Daily loss limit reached. Stop trading for today." if breached else "✅ Within daily loss limit.",
    }


# ─── Brokerage ───────────────────────────────────────────────────────────────

def calculate_brokerage(
    quantity: int,
    price: float,
    transaction_type: str = "BUY",
    product_type: str = "CNC",
    brokerage_pct: float = 0.03,
    stt_pct: float = 0.1,
    exchange_charges_pct: float = 0.00335,
    gst_pct: float = 18.0,
) -> dict:
    """
    Approximate Indian brokerage + STT + exchange charges + GST.
    Supports CNC (Delivery) and MIS (Intraday with 5x leverage).
    """
    turnover = quantity * price
    prod = product_type.upper().strip()

    # Brokerage: 0.05% or flat ₹20 (Groww / Zerodha style)
    brokerage = min(turnover * 0.0005, 20.0) if prod == "MIS" else min(turnover * (brokerage_pct / 100), 20.0)
    
    # STT: 0.1% for Delivery (sell only or buy+sell), 0.025% for Intraday (sell only)
    if prod == "MIS":
        stt = turnover * 0.00025 if transaction_type.upper() == "SELL" else 0.0
        stamp_duty = turnover * 0.00003 if transaction_type.upper() == "BUY" else 0.0
    else:
        stt = turnover * 0.001 if transaction_type.upper() == "SELL" else 0.0
        stamp_duty = turnover * 0.00015 if transaction_type.upper() == "BUY" else 0.0

    exchange_charges = turnover * (exchange_charges_pct / 100)
    sebi_charges = turnover * 0.000001  # ₹10 per crore
    gst = (brokerage + exchange_charges + sebi_charges) * (gst_pct / 100)
    total_charges = brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst

    return {
        "turnover": round(turnover, 2),
        "brokerage": round(brokerage, 2),
        "stt": round(stt, 2),
        "exchange_charges": round(exchange_charges, 2),
        "sebi_charges": round(sebi_charges, 2),
        "stamp_duty": round(stamp_duty, 2),
        "gst": round(gst, 2),
        "total_charges": round(total_charges, 2),
        "break_even_price": round((turnover + total_charges) / quantity, 2) if quantity > 0 else 0.0,
    }
