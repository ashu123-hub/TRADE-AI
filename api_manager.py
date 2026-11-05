"""
TradeMind AI - Central API Manager & Orchestrator
Coordinates external market data providers (Yahoo Finance, Finnhub, Alpha Vantage),
AI technical reasoning (Google Gemini), and cloud persistence (Supabase).
Provides automatic fallback, health monitoring, and data provider attribution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import settings, api_keys
from services.yahoo_service import yahoo_service, YahooFinanceService
from services.finnhub_service import finnhub_service, FinnhubService
from services.alpha_vantage_service import alpha_vantage_service, AlphaVantageService
from services.gemini_service import gemini_service, GeminiService
from services.supabase_service import supabase_service, SupabaseService

logger = logging.getLogger("trademind.api_manager")


class MarketDataFetcher:
    """
    Unified composite market data manager with Finnhub and Alpha Vantage
    as primary alternative market data providers:
    1. Historical OHLCV: Alpha Vantage (Primary) -> Finnhub (Alternative) -> Yahoo (Safety Fallback)
    2. Quotes: Finnhub (Primary) -> Alpha Vantage (Alternative) -> Yahoo (Safety Fallback)
    3. Intraday (5m/15m): Finnhub (Primary) -> Alpha Vantage (Alternative) -> Yahoo (Safety Fallback)
    4. News & Sentiment: Finnhub API (Primary)
    5. Explanations: Google Gemini API (Exclusive Generative AI)
    """

    def __init__(self):
        self.fh = finnhub_service
        self.av = alpha_vantage_service
        self.yf = yahoo_service
        self.gemini = gemini_service
        self.db = supabase_service

    def get_ohlcv(
        self,
        symbol: str,
        interval: str = "1d",
        period: str = "1y",
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, str]:
        """
        Fetch historical OHLCV data using Alpha Vantage & Finnhub as primary providers.
        Returns: (DataFrame, provider_name)
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

        # 1. Primary: Alpha Vantage (for daily data)
        if interval == "1d" and self.av.is_configured:
            try:
                df, meta = self.av.get_daily_historical(clean_sym, outputsize="full")
                if not df.empty and len(df) > 0:
                    return df, self.av.PROVIDER_NAME
            except Exception as exc:
                logger.warning("Alpha Vantage daily fetch error for %s: %s", clean_sym, exc)

        # 2. Alternative: Finnhub Candles
        if self.fh.is_configured:
            try:
                res = "D" if interval == "1d" else ("W" if "w" in interval.lower() else "D")
                df, meta = self.fh.get_historical_ohlcv(clean_sym, resolution=res)
                if not df.empty and len(df) > 0:
                    return df, self.fh.PROVIDER_NAME
            except Exception as exc:
                logger.warning("Finnhub candle fetch error for %s: %s", clean_sym, exc)

        # 3. Secondary Safety Fallback (Yahoo Finance if enabled)
        if api_keys.yahoo_finance_enabled:
            try:
                df, meta = self.yf.get_historical_ohlcv(symbol, period=period, interval=interval, start=start, end=end)
                if not df.empty and len(df) > 0:
                    return df, f"{self.yf.PROVIDER_NAME} (Safety Fallback)"
            except Exception as exc:
                logger.warning("Yahoo Finance fallback failed for %s: %s", symbol, exc)

        # Never fake data
        return pd.DataFrame(), "none"

    def get_intraday(self, symbol: str, interval: str = "5m") -> Tuple[pd.DataFrame, str]:
        """
        Fetch intraday 5m or 15m OHLCV bars using Finnhub & Alpha Vantage as primary providers.
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

        # 1. Primary: Finnhub Intraday Candles
        if self.fh.is_configured:
            try:
                df, meta = self.fh.get_intraday_ohlcv(clean_sym, interval=interval)
                if not df.empty and len(df) > 0:
                    return df, self.fh.PROVIDER_NAME
            except Exception as exc:
                logger.warning("Finnhub intraday fetch error for %s: %s", clean_sym, exc)

        # 2. Alternative: Alpha Vantage Intraday
        if self.av.is_configured:
            try:
                av_interval = "15min" if "15" in interval else "5min"
                df, meta = self.av.get_intraday_ohlcv(clean_sym, interval=av_interval)
                if not df.empty and len(df) > 0:
                    return df, self.av.PROVIDER_NAME
            except Exception as exc:
                logger.warning("Alpha Vantage intraday fetch error for %s: %s", clean_sym, exc)

        # 3. Secondary Safety Fallback (Yahoo Finance if enabled)
        if api_keys.yahoo_finance_enabled:
            try:
                df, meta = self.yf.get_intraday_ohlcv(symbol, interval=interval)
                if not df.empty and len(df) > 0:
                    return df, f"{self.yf.PROVIDER_NAME} (Safety Fallback)"
            except Exception as exc:
                logger.error("Yahoo Finance intraday fallback failed for %s: %s", symbol, exc)

        # Never fake data
        return pd.DataFrame(), "none"

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch real-time quote with primary providers:
        1. Finnhub (Primary)
        2. Alpha Vantage (Alternative)
        3. Yahoo Finance (Safety Fallback)
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()

        # 1. Primary: Finnhub
        if self.fh.is_configured:
            try:
                fh_q = self.fh.get_quote(clean_sym)
                if fh_q.get("price") is not None and fh_q.get("price") > 0:
                    return fh_q
            except Exception as exc:
                logger.warning("Finnhub quote error for %s: %s", clean_sym, exc)

        # 2. Alternative: Alpha Vantage Global Quote
        if self.av.is_configured:
            try:
                av_q = self.av.get_quote(clean_sym)
                if av_q.get("price") is not None and av_q.get("price") > 0:
                    return av_q
            except Exception as exc:
                logger.warning("Alpha Vantage quote error for %s: %s", clean_sym, exc)

        # 3. Secondary Safety Fallback (Yahoo Finance if enabled)
        if api_keys.yahoo_finance_enabled:
            try:
                yf_q = self.yf.get_live_quote(symbol)
                if yf_q.get("price") is not None:
                    yf_q["provider"] = f"{self.yf.PROVIDER_NAME} (Safety Fallback)"
                    return yf_q
            except Exception as exc:
                logger.warning("Yahoo Finance quote fallback failed for %s: %s", symbol, exc)

        # Never generate fake stock prices
        return {
            "symbol": clean_sym,
            "price": None,
            "status": "unavailable",
            "provider": "None",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_company_info(self, symbol: str) -> Dict[str, Any]:
        """Fetch company info trying Finnhub first, then secondary fallback."""
        if self.fh.is_configured:
            try:
                prof = self.fh.get_company_profile(symbol)
                if prof:
                    return prof
            except Exception as exc:
                logger.warning("Finnhub company profile error: %s", exc)

        if api_keys.yahoo_finance_enabled:
            return self.yf.get_company_profile(symbol)

        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        return {
            "symbol": clean_sym,
            "ticker": clean_sym,
            "company_name": clean_sym,
            "sector": "Indian Equities",
            "provider": "None",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_news(self, symbol: str, days_back: int = 7) -> List[Dict[str, Any]]:
        """Fetch verified company news from Finnhub."""
        return self.fh.get_company_news(symbol, days_back=days_back)

    def get_market_news(self) -> List[Dict[str, Any]]:
        """Fetch broad market news from Finnhub."""
        return self.fh.get_market_news("general")

    def get_services_status(self) -> Dict[str, Any]:
        """Comprehensive health report of all connected services."""
        return {
            "finnhub": {
                "name": "Finnhub API (Primary Market Data)",
                "status": "connected" if self.fh.is_configured else "unconfigured",
                "coverage": "NSE Real-Time Quotes, Intraday Candles, Company News & Sentiment",
                "role": "Primary Market Data Provider",
                "auth_required": True,
            },
            "alpha_vantage": {
                "name": "Alpha Vantage API (Primary/Alternative)",
                "status": "connected" if self.av.is_configured else "unconfigured",
                "coverage": "Historical Daily OHLCV, Intraday (5m/15m), Technical Indicators",
                "role": "Primary Historical Data Provider",
                "auth_required": True,
            },
            "yahoo_finance": {
                "name": "Yahoo Finance (Secondary / Safety Fallback)",
                "status": "standby" if api_keys.yahoo_finance_enabled else "disabled",
                "coverage": "Secondary Fallback for Historical & Intraday Data",
                "role": "Secondary Safety Net",
                "auth_required": False,
                "api_key_configured": bool(api_keys.yahoo_finance_api_key),
            },
            "google_gemini": {
                "name": "Google Gemini API (1.5 Flash)",
                "status": "connected" if self.gemini.is_configured else "unconfigured",
                "coverage": "Grounded Technical Analysis Reasoning & Signal Explanations",
                "role": "Exclusive Generative AI Provider",
                "auth_required": True,
            },
            "supabase": {
                "name": "Supabase Cloud Database (PostgreSQL)",
                "status": "connected" if self.db.is_configured else "unconfigured",
                "coverage": "Historical Data, Signals, Predictions, Portfolios",
                "role": "Primary Relational Database",
                "auth_required": True,
            },
        }


# Singleton instances for backward compatibility & direct import
market_data = MarketDataFetcher()
gemini = gemini_service
db = supabase_service

# Class re-exports
YahooFinanceAPI = YahooFinanceService
FinnhubAPI = FinnhubService
AlphaVantageAPI = AlphaVantageService
GeminiAPI = GeminiService
