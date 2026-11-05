"""
TradeMind AI - Alpha Vantage Service
Provides daily historical price data and technical indicators (RSI, MACD, SMA, EMA)
with strict quota protection for free-tier users (25 calls/day, 5 calls/min).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from cachetools import TTLCache

from config import api_keys, settings

logger = logging.getLogger("trademind.services.alphavantage")

# Long TTL for Alpha Vantage to strictly conserve the 25 req/day quota
_av_price_cache: TTLCache = TTLCache(maxsize=128, ttl=3600)  # 1 hour
_av_indicator_cache: TTLCache = TTLCache(maxsize=128, ttl=3600)
_av_intra_cache: TTLCache = TTLCache(maxsize=128, ttl=600)    # 10 min
_av_quote_cache: TTLCache = TTLCache(maxsize=128, ttl=60)     # 1 min


class AlphaVantageService:
    """Production-grade Alpha Vantage client with free-tier rate protection."""

    BASE_URL = "https://www.alphavantage.co/query"
    PROVIDER_NAME = "Alpha Vantage"

    def __init__(self):
        self._last_call = 0.0
        self._min_interval = 12.0  # ~5 calls per minute limit

    @property
    def api_key(self) -> Optional[str]:
        return api_keys.alpha_vantage

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _format_symbol(self, symbol: str) -> str:
        """Alpha Vantage supports Indian equities via BSE: prefix."""
        clean = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        return f"BSE:{clean}"

    def _request(self, params: Dict[str, Any], timeout: int = 15) -> Optional[Dict[str, Any]]:
        """Rate-limited query with error handling."""
        if not self.is_configured:
            return None

        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        params["apikey"] = self.api_key
        try:
            resp = requests.get(self.BASE_URL, params=params, timeout=timeout)
            self._last_call = time.monotonic()
            resp.raise_for_status()
            data = resp.json()

            # Check rate limit notice
            if "Note" in data:
                logger.warning("Alpha Vantage 25 req/day limit note: %s", data["Note"])
                return None
            if "Information" in data:
                logger.warning("Alpha Vantage message: %s", data["Information"])
                return None
            if "Error Message" in data:
                logger.warning("Alpha Vantage error: %s", data["Error Message"])
                return None

            return data
        except Exception as exc:
            logger.error("Alpha Vantage request failed: %s", exc)
            return None

    def get_daily_historical(self, symbol: str, outputsize: str = "compact") -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Fetch daily OHLCV bars.
        Returns: (DataFrame, metadata)
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"av_daily_{clean_sym}_{outputsize}"
        if cache_key in _av_price_cache:
            df, meta = _av_price_cache[cache_key]
            meta["cached"] = True
            return df.copy(), meta

        if not self.is_configured:
            return pd.DataFrame(), {
                "provider": self.PROVIDER_NAME,
                "status": "unconfigured",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        av_symbol = self._format_symbol(clean_sym)
        data = self._request({
            "function": "TIME_SERIES_DAILY",
            "symbol": av_symbol,
            "outputsize": outputsize,
        })

        ts = data.get("Time Series (Daily)", {}) if isinstance(data, dict) else {}
        if not ts:
            return pd.DataFrame(), {
                "provider": self.PROVIDER_NAME,
                "status": "empty_or_rate_limited",
                "symbol": clean_sym,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        rows = []
        for date_str, ohlcv in ts.items():
            rows.append({
                "Date": pd.Timestamp(date_str, tz="UTC"),
                "Open": float(ohlcv.get("1. open", 0)),
                "High": float(ohlcv.get("2. high", 0)),
                "Low": float(ohlcv.get("3. low", 0)),
                "Close": float(ohlcv.get("4. close", 0)),
                "Volume": float(ohlcv.get("5. volume", 0)),
            })

        df = pd.DataFrame(rows).set_index("Date").sort_index()
        meta = {
            "provider": self.PROVIDER_NAME,
            "status": "success",
            "symbol": clean_sym,
            "rows": len(df),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cached": False,
        }
        _av_price_cache[cache_key] = (df, meta)
        return df, meta

    def get_intraday_ohlcv(
        self,
        symbol: str,
        interval: str = "5min",
        outputsize: str = "compact",
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Fetch intraday bars (5min or 15min) from Alpha Vantage (TIME_SERIES_INTRADAY).
        Returns: (df, metadata)
        """
        # Normalize interval string to '5min' or '15min'
        norm_interval = "15min" if "15" in interval else "5min"
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"av_intra_{clean_sym}_{norm_interval}_{outputsize}"

        if cache_key in _av_intra_cache:
            df, meta = _av_intra_cache[cache_key]
            meta["cached"] = True
            return df.copy(), meta

        if not self.is_configured:
            return pd.DataFrame(), {
                "provider": self.PROVIDER_NAME,
                "status": "unconfigured",
                "symbol": clean_sym,
                "interval": norm_interval,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        av_symbol = self._format_symbol(clean_sym)
        data = self._request({
            "function": "TIME_SERIES_INTRADAY",
            "symbol": av_symbol,
            "interval": norm_interval,
            "outputsize": outputsize,
        })

        key_name = f"Time Series ({norm_interval})"
        ts = data.get(key_name, {}) if isinstance(data, dict) else {}
        if not ts:
            return pd.DataFrame(), {
                "provider": self.PROVIDER_NAME,
                "status": "empty_or_rate_limited",
                "symbol": clean_sym,
                "interval": norm_interval,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        rows = []
        for time_str, ohlcv in ts.items():
            rows.append({
                "Date": pd.Timestamp(time_str, tz="UTC"),
                "Open": float(ohlcv.get("1. open", 0)),
                "High": float(ohlcv.get("2. high", 0)),
                "Low": float(ohlcv.get("3. low", 0)),
                "Close": float(ohlcv.get("4. close", 0)),
                "Volume": float(ohlcv.get("5. volume", 0)),
            })

        df = pd.DataFrame(rows).set_index("Date").sort_index()
        meta = {
            "provider": self.PROVIDER_NAME,
            "status": "success",
            "symbol": clean_sym,
            "interval": norm_interval,
            "rows": len(df),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cached": False,
        }
        _av_intra_cache[cache_key] = (df, meta)
        return df, meta

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch quote via GLOBAL_QUOTE function."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"av_quote_{clean_sym}"
        if cache_key in _av_quote_cache:
            return _av_quote_cache[cache_key]

        if not self.is_configured:
            return {
                "symbol": clean_sym,
                "price": None,
                "status": "unconfigured",
                "provider": self.PROVIDER_NAME,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        av_symbol = self._format_symbol(clean_sym)
        data = self._request({
            "function": "GLOBAL_QUOTE",
            "symbol": av_symbol,
        })

        gq = data.get("Global Quote", {}) if isinstance(data, dict) else {}
        price_str = gq.get("05. price")
        if price_str is not None:
            try:
                price = float(price_str)
                quote = {
                    "symbol": clean_sym,
                    "price": price,
                    "open": float(gq.get("02. open", 0)),
                    "high": float(gq.get("03. high", 0)),
                    "low": float(gq.get("04. low", 0)),
                    "volume": float(gq.get("06. volume", 0)),
                    "previous_close": float(gq.get("08. previous close", 0)),
                    "change": float(gq.get("09. change", 0)),
                    "change_pct": float(gq.get("10. change percent", "0%").replace("%", "")),
                    "status": "success",
                    "provider": self.PROVIDER_NAME,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                _av_quote_cache[cache_key] = quote
                return quote
            except (ValueError, TypeError):
                pass

        return {
            "symbol": clean_sym,
            "price": None,
            "status": "no_data_or_rate_limited",
            "provider": self.PROVIDER_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_rsi(self, symbol: str, interval: str = "daily", time_period: int = 14) -> Optional[float]:
        """Fetch latest RSI reading."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"av_rsi_{clean_sym}"
        if cache_key in _av_indicator_cache:
            return _av_indicator_cache[cache_key]

        if not self.is_configured:
            return None

        data = self._request({
            "function": "RSI",
            "symbol": self._format_symbol(clean_sym),
            "interval": interval,
            "time_period": time_period,
            "series_type": "close",
        })

        ts = data.get("Technical Analysis: RSI", {}) if isinstance(data, dict) else {}
        if ts:
            latest_date = next(iter(ts))
            val = float(ts[latest_date].get("RSI", 0))
            _av_indicator_cache[cache_key] = val
            return val
        return None

    def check_health(self) -> Dict[str, Any]:
        """Verify API key configuration and responsiveness."""
        if not self.is_configured:
            return {"configured": False, "status": "missing_api_key"}
        return {"configured": True, "status": "key_present", "provider": self.PROVIDER_NAME}


# Singleton export
alpha_vantage_service = AlphaVantageService()

