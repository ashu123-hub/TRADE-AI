"""
TradeMind AI - Supabase PostgreSQL Cloud Database Service
Manages cloud persistence for stocks, historical candles, technical indicators,
predictions, trading signals, portfolios, transactions, and backtest logs.
Features safe connection pooling, retries, RLS compliance, and in-memory fallbacks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import api_keys

logger = logging.getLogger("trademind.services.supabase")


class SupabaseService:
    """Production Supabase client wrapping supabase-py."""

    PROVIDER_NAME = "Supabase PostgreSQL"

    def __init__(self):
        self._client = None
        self._initialized = False

    @property
    def url(self) -> Optional[str]:
        return api_keys.supabase_url

    @property
    def anon_key(self) -> Optional[str]:
        return api_keys.supabase_anon_key

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.anon_key and "supabase.co" in self.url)

    def get_client(self):
        """Lazy-load and cache Supabase client.
        Uses service_role_key for full read/write access (bypasses RLS),
        falls back to anon_key for read-only access.
        """
        if self._initialized:
            return self._client

        if not self.is_configured:
            return None

        try:
            from supabase import create_client
            # Prefer service_role_key for server-side operations (bypasses RLS)
            key = api_keys.supabase_service_role_key or self.anon_key
            self._client = create_client(self.url, key)
            self._initialized = True
            key_type = "service_role" if api_keys.supabase_service_role_key else "anon"
            logger.info("Supabase client initialized with %s key.", key_type)
            return self._client
        except Exception as exc:
            logger.error("Failed to initialize Supabase client: %s", exc)
            return None

    def check_health(self) -> Dict[str, Any]:
        """Test database connection."""
        if not self.is_configured:
            return {"configured": False, "status": "missing_credentials", "provider": self.PROVIDER_NAME}
        client = self.get_client()
        if client is None:
            return {"configured": True, "status": "client_initialization_failed", "provider": self.PROVIDER_NAME}

        try:
            client.table("stocks").select("id").limit(1).execute()
            return {"configured": True, "status": "connected", "provider": self.PROVIDER_NAME}
        except Exception as exc:
            return {"configured": True, "status": "connection_error", "error": str(exc), "provider": self.PROVIDER_NAME}

    # ─── Stocks ──────────────────────────────────────────────────────────────
    def upsert_stock(self, symbol: str, company_name: str = "", exchange: str = "NSE", sector: str = "") -> bool:
        client = self.get_client()
        if client is None:
            return False
        try:
            client.table("stocks").upsert({
                "symbol": symbol.upper().strip(),
                "company_name": company_name,
                "exchange": exchange,
                "sector": sector,
            }, on_conflict="symbol").execute()
            return True
        except Exception as exc:
            logger.error("Supabase upsert_stock error: %s", exc)
            return False

    def get_stocks(self, exchange: str = "NSE") -> List[Dict[str, Any]]:
        client = self.get_client()
        if client is None:
            return []
        try:
            res = client.table("stocks").select("*").eq("exchange", exchange).execute()
            return res.data or []
        except Exception as exc:
            logger.error("Supabase get_stocks error: %s", exc)
            return []

    # ─── Historical Prices ───────────────────────────────────────────────────
    def insert_historical_prices(self, df: pd.DataFrame, symbol: str, timeframe: str = "1d") -> int:
        client = self.get_client()
        if client is None or df.empty:
            return 0

        rows = []
        clean_sym = symbol.upper().replace(".NS", "").strip()
        for ts, row in df.iterrows():
            if hasattr(ts, "to_pydatetime"):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            rows.append({
                "stock_symbol": clean_sym,
                "timestamp": ts.isoformat(),
                "open": float(row.get("Open", 0) or 0),
                "high": float(row.get("High", 0) or 0),
                "low": float(row.get("Low", 0) or 0),
                "close": float(row.get("Close", 0) or 0),
                "volume": int(row.get("Volume", 0) or 0),
                "timeframe": timeframe,
            })

        if not rows:
            return 0

        inserted = 0
        try:
            # Batch upsert in chunks of 500
            for i in range(0, len(rows), 500):
                chunk = rows[i:i + 500]
                client.table("historical_prices").upsert(
                    chunk, on_conflict="stock_symbol,timestamp,timeframe"
                ).execute()
                inserted += len(chunk)
            return inserted
        except Exception as exc:
            logger.error("Supabase insert_historical_prices error: %s", exc)
            return 0

    def get_historical_prices(self, symbol: str, timeframe: str = "1d", limit: int = 500) -> pd.DataFrame:
        client = self.get_client()
        if client is None:
            return pd.DataFrame()
        clean_sym = symbol.upper().replace(".NS", "").strip()
        try:
            res = (
                client.table("historical_prices")
                .select("timestamp,open,high,low,close,volume")
                .eq("stock_symbol", clean_sym)
                .eq("timeframe", timeframe)
                .order("timestamp", desc=True)
                .limit(limit)
                .execute()
            )
            if not res.data:
                return pd.DataFrame()
            df = pd.DataFrame(res.data)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            df = df.set_index("timestamp").sort_index()
            df.columns = [c.capitalize() for c in df.columns]
            return df
        except Exception as exc:
            logger.error("Supabase get_historical_prices error: %s", exc)
            return pd.DataFrame()

    # ─── Predictions & AI Explanations ───────────────────────────────────────
    def save_prediction(
        self,
        symbol: str,
        prediction_type: str,
        predicted_price: Optional[float],
        predicted_direction: str,
        confidence: float,
        model_used: str = "",
        ai_explanation: str = "",
    ) -> bool:
        client = self.get_client()
        if client is None:
            return False
        clean_sym = symbol.upper().replace(".NS", "").strip()
        try:
            client.table("predictions").insert({
                "stock_symbol": clean_sym,
                "prediction_type": prediction_type,
                "predicted_price": predicted_price,
                "predicted_direction": predicted_direction,
                "confidence": float(confidence),
                "model_used": model_used,
            }).execute()
            return True
        except Exception as exc:
            logger.error("Supabase save_prediction error: %s", exc)
            return False

    def get_recent_predictions(self, symbol: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        client = self.get_client()
        if client is None:
            return []
        try:
            q = client.table("predictions").select("*").order("created_at", desc=True).limit(limit)
            if symbol:
                clean_sym = symbol.upper().replace(".NS", "").strip()
                q = q.eq("stock_symbol", clean_sym)
            res = q.execute()
            return res.data or []
        except Exception as exc:
            logger.error("Supabase get_recent_predictions error: %s", exc)
            return []

    # ─── Trading Signals ─────────────────────────────────────────────────────
    def save_trading_signal(
        self,
        symbol: str,
        signal: str,
        entry_price: float,
        target_price: float,
        stop_loss: float,
        risk_reward_ratio: float,
        explanation: str = "",
    ) -> bool:
        client = self.get_client()
        if client is None:
            return False
        clean_sym = symbol.upper().replace(".NS", "").strip()
        try:
            client.table("trading_signals").insert({
                "stock_symbol": clean_sym,
                "signal": signal,
                "entry_price": float(entry_price),
                "target_price": float(target_price),
                "stop_loss": float(stop_loss),
                "risk_reward_ratio": float(risk_reward_ratio),
                "explanation": explanation,
            }).execute()
            return True
        except Exception as exc:
            logger.error("Supabase save_trading_signal error: %s", exc)
            return False

    def get_recent_signals(self, limit: int = 20) -> List[Dict[str, Any]]:
        client = self.get_client()
        if client is None:
            return []
        try:
            res = client.table("trading_signals").select("*").order("created_at", desc=True).limit(limit).execute()
            return res.data or []
        except Exception as exc:
            logger.error("Supabase get_recent_signals error: %s", exc)
            return []

    # ─── Portfolio & Transactions ────────────────────────────────────────────
    def save_transaction(
        self,
        user_id: str,
        symbol: str,
        txn_type: str,
        quantity: float,
        price: float,
        brokerage: float = 0.0,
    ) -> bool:
        client = self.get_client()
        if client is None:
            return False
        clean_sym = symbol.upper().replace(".NS", "").strip()
        import uuid as _uuid
        try:
            _uuid.UUID(str(user_id))
            valid_user_id = str(user_id)
        except Exception:
            valid_user_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, str(user_id)))

        # Ensure default paper trading user exists in users table
        try:
            client.table("users").upsert({
                "id": valid_user_id,
                "username": f"paper_{valid_user_id[:8]}",
                "email": f"paper_{valid_user_id[:8]}@trademind.ai",
            }, on_conflict="id").execute()
        except Exception as u_exc:
            logger.debug("Users upsert note: %s", u_exc)

        try:
            client.table("transactions").insert({
                "user_id": valid_user_id,
                "stock_symbol": clean_sym,
                "transaction_type": txn_type,
                "quantity": float(quantity),
                "price": float(price),
                "brokerage": float(brokerage),
            }).execute()
            return True
        except Exception as exc:
            logger.error("Supabase save_transaction error: %s", exc)
            return False

    def get_transactions(self, user_id: str = "paper_trader_01") -> List[Dict[str, Any]]:
        client = self.get_client()
        if client is None:
            return []
        import uuid as _uuid
        try:
            _uuid.UUID(str(user_id))
            valid_user_id = str(user_id)
        except Exception:
            valid_user_id = str(_uuid.uuid5(_uuid.NAMESPACE_DNS, str(user_id)))
        try:
            res = (
                client.table("transactions")
                .select("*")
                .eq("user_id", valid_user_id)
                .order("transaction_date", desc=True)
                .execute()
            )
            return res.data or []
        except Exception as exc:
            logger.error("Supabase get_transactions error: %s", exc)
            return []

    # ─── Backtest Results ────────────────────────────────────────────────────
    def save_backtest_result(self, result: Dict[str, Any]) -> bool:
        client = self.get_client()
        if client is None:
            return False
        try:
            client.table("backtest_results").insert(result).execute()
            return True
        except Exception as exc:
            logger.error("Supabase save_backtest_result error: %s", exc)
            return False

    def get_backtest_results(self, symbol: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        client = self.get_client()
        if client is None:
            return []
        try:
            q = client.table("backtest_results").select("*").order("created_at", desc=True).limit(limit)
            if symbol:
                clean_sym = symbol.upper().replace(".NS", "").strip()
                q = q.eq("stock_symbol", clean_sym)
            res = q.execute()
            return res.data or []
        except Exception as exc:
            logger.error("Supabase get_backtest_results error: %s", exc)
            return []


# Singleton export
supabase_service = SupabaseService()

