"""
TradeMind AI - Database Access Layer
Exposes database functions delegating to the modular SupabaseService
while maintaining backward-compatible function signatures.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import pandas as pd

from services.supabase_service import supabase_service

logger = logging.getLogger("trademind.database")


def get_client():
    return supabase_service.get_client()


def is_connected() -> bool:
    return supabase_service.check_health().get("status") == "connected"


def upsert_stock(symbol: str, company_name: str = "", exchange: str = "NSE", sector: str = "") -> bool:
    return supabase_service.upsert_stock(symbol, company_name, exchange, sector)


def get_stocks(exchange: str = "NSE") -> List[Dict[str, Any]]:
    return supabase_service.get_stocks(exchange)


def insert_historical_prices(df: pd.DataFrame, symbol: str, timeframe: str = "1d") -> int:
    return supabase_service.insert_historical_prices(df, symbol, timeframe)


def get_historical_prices(symbol: str, timeframe: str = "1d", limit: int = 500) -> pd.DataFrame:
    return supabase_service.get_historical_prices(symbol, timeframe, limit)


def save_prediction(
    symbol: str,
    prediction_type: str,
    predicted_price: Optional[float],
    predicted_direction: str,
    confidence: float,
    model_used: str = "",
    ai_explanation: str = "",
) -> bool:
    return supabase_service.save_prediction(
        symbol, prediction_type, predicted_price, predicted_direction, confidence, model_used, ai_explanation
    )


def get_recent_predictions(symbol: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    return supabase_service.get_recent_predictions(symbol, limit)


def save_trading_signal(
    symbol: str,
    signal: str,
    entry_price: float,
    target_price: float,
    stop_loss: float,
    risk_reward_ratio: float,
    explanation: str = "",
) -> bool:
    return supabase_service.save_trading_signal(
        symbol, signal, entry_price, target_price, stop_loss, risk_reward_ratio, explanation
    )


def get_recent_signals(limit: int = 20) -> List[Dict[str, Any]]:
    return supabase_service.get_recent_signals(limit)


def add_transaction(
    user_id: str,
    symbol: str,
    txn_type: str,
    quantity: float,
    price: float,
    brokerage: float = 0.0,
) -> bool:
    return supabase_service.save_transaction(user_id, symbol, txn_type, quantity, price, brokerage)


def get_transactions(user_id: str = "paper_trader_01") -> List[Dict[str, Any]]:
    return supabase_service.get_transactions(user_id)


def save_backtest_result(result: Dict[str, Any]) -> bool:
    return supabase_service.save_backtest_result(result)


def get_backtest_results(symbol: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
    return supabase_service.get_backtest_results(symbol, limit)
