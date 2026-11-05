"""
TradeMind AI - Finnhub API Service
Provides company profiles, market news, sentiment, and quotes (where NSE symbols are covered)
with strict rate-limit protection and graceful fallbacks for unsupported tickers.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests
from cachetools import TTLCache

from config import api_keys, settings

logger = logging.getLogger("trademind.services.finnhub")

# Cache TTLs
_fh_news_cache: TTLCache = TTLCache(maxsize=128, ttl=600)   # 10 min
_fh_quote_cache: TTLCache = TTLCache(maxsize=256, ttl=60)   # 1 min
_fh_candle_cache: TTLCache = TTLCache(maxsize=128, ttl=300) # 5 min


class FinnhubService:
    """Production-grade Finnhub REST client with rate-limiting and fallback."""

    BASE_URL = "https://finnhub.io/api/v1"
    PROVIDER_NAME = "Finnhub"

    def __init__(self):
        self._last_call = 0.0
        self._min_interval = 0.5  # 2 req/sec free-tier budget limit

    @property
    def api_key(self) -> Optional[str]:
        return api_keys.finnhub

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 5)

    def _headers(self) -> Dict[str, str]:
        return {"X-Finnhub-Token": self.api_key} if self.api_key else {}

    def _request(self, endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: int = 10) -> Any:
        """Rate-limited HTTP GET with error checking."""
        if not self.is_configured:
            return None

        # Enforce rate-limit interval
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        url = f"{self.BASE_URL}/{endpoint}"
        try:
            resp = requests.get(url, params=params, headers=self._headers(), timeout=timeout)
            self._last_call = time.monotonic()

            if resp.status_code == 429:
                logger.warning("Finnhub rate limit encountered. Backing off.")
                return None
            if resp.status_code == 401:
                logger.warning("Finnhub API key invalid or unauthorized.")
                return None

            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("Finnhub request error [%s]: %s", endpoint, exc)
            return None

    def get_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch quote from Finnhub.
        NOTE: Finnhub supports select Indian symbols with NSE: prefix.
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"fh_quote_{clean_sym}"
        if cache_key in _fh_quote_cache:
            return _fh_quote_cache[cache_key]

        if not self.is_configured:
            return {
                "symbol": clean_sym,
                "price": None,
                "status": "unconfigured",
                "provider": self.PROVIDER_NAME,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        data = self._request("quote", {"symbol": f"NSE:{clean_sym}"})
        if isinstance(data, dict) and data.get("c"):
            quote = {
                "symbol": clean_sym,
                "price": float(data.get("c")),
                "open": float(data.get("o", 0)),
                "high": float(data.get("h", 0)),
                "low": float(data.get("l", 0)),
                "previous_close": float(data.get("pc", 0)),
                "status": "success",
                "provider": self.PROVIDER_NAME,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _fh_quote_cache[cache_key] = quote
            return quote

        # Fallback without exchange prefix
        data_plain = self._request("quote", {"symbol": clean_sym})
        if isinstance(data_plain, dict) and data_plain.get("c"):
            quote = {
                "symbol": clean_sym,
                "price": float(data_plain.get("c")),
                "open": float(data_plain.get("o", 0)),
                "high": float(data_plain.get("h", 0)),
                "low": float(data_plain.get("l", 0)),
                "previous_close": float(data_plain.get("pc", 0)),
                "status": "success",
                "provider": self.PROVIDER_NAME,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            _fh_quote_cache[cache_key] = quote
            return quote

        return {
            "symbol": clean_sym,
            "price": None,
            "status": "unsupported_or_empty",
            "provider": self.PROVIDER_NAME,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_historical_ohlcv(
        self,
        symbol: str,
        resolution: str = "D",
        days: int = 365,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Fetch historical daily/weekly OHLCV candles from Finnhub (/stock/candle).
        Supports resolutions: 'D' (day), 'W' (week), 'M' (month).
        Returns: (df, metadata)
        """
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"fh_hist_{clean_sym}_{resolution}_{days}"
        if cache_key in _fh_candle_cache:
            df, meta = _fh_candle_cache[cache_key]
            meta["cached"] = True
            return df.copy(), meta

        if not self.is_configured:
            return pd.DataFrame(), {
                "provider": self.PROVIDER_NAME,
                "status": "unconfigured",
                "symbol": clean_sym,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        now_ts = int(time.time())
        from_ts = now_ts - (days * 86400)

        # Try with NSE: prefix first, then raw symbol
        data = self._request("stock/candle", {
            "symbol": f"NSE:{clean_sym}",
            "resolution": resolution,
            "from": from_ts,
            "to": now_ts,
        })

        if not isinstance(data, dict) or data.get("s") != "ok":
            data = self._request("stock/candle", {
                "symbol": clean_sym,
                "resolution": resolution,
                "from": from_ts,
                "to": now_ts,
            })

        if isinstance(data, dict) and data.get("s") == "ok" and "t" in data and len(data["t"]) > 0:
            df = pd.DataFrame({
                "Date": pd.to_datetime(data["t"], unit="s", utc=True),
                "Open": [float(x) for x in data.get("o", [])],
                "High": [float(x) for x in data.get("h", [])],
                "Low": [float(x) for x in data.get("l", [])],
                "Close": [float(x) for x in data.get("c", [])],
                "Volume": [float(x) for x in data.get("v", [])],
            }).set_index("Date").sort_index()

            meta = {
                "provider": self.PROVIDER_NAME,
                "status": "success",
                "symbol": clean_sym,
                "rows": len(df),
                "resolution": resolution,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cached": False,
            }
            _fh_candle_cache[cache_key] = (df, meta)
            return df, meta

        return pd.DataFrame(), {
            "provider": self.PROVIDER_NAME,
            "status": "no_data_or_unsupported",
            "symbol": clean_sym,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_intraday_ohlcv(
        self,
        symbol: str,
        interval: str = "5m",
        days: int = 3,
    ) -> Tuple[pd.DataFrame, Dict[str, Any]]:
        """
        Fetch intraday candles (5-minute or 15-minute) from Finnhub (/stock/candle).
        Returns: (df, metadata)
        """
        resolution_map = {
            "1m": "1",
            "5m": "5",
            "15m": "15",
            "30m": "30",
            "60m": "60",
        }
        res = resolution_map.get(interval.lower(), "5")
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"fh_intra_{clean_sym}_{interval}_{days}"
        if cache_key in _fh_candle_cache:
            df, meta = _fh_candle_cache[cache_key]
            meta["cached"] = True
            return df.copy(), meta

        if not self.is_configured:
            return pd.DataFrame(), {
                "provider": self.PROVIDER_NAME,
                "status": "unconfigured",
                "symbol": clean_sym,
                "interval": interval,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        now_ts = int(time.time())
        from_ts = now_ts - (days * 86400)

        data = self._request("stock/candle", {
            "symbol": f"NSE:{clean_sym}",
            "resolution": res,
            "from": from_ts,
            "to": now_ts,
        })

        if not isinstance(data, dict) or data.get("s") != "ok":
            data = self._request("stock/candle", {
                "symbol": clean_sym,
                "resolution": res,
                "from": from_ts,
                "to": now_ts,
            })

        if isinstance(data, dict) and data.get("s") == "ok" and "t" in data and len(data["t"]) > 0:
            df = pd.DataFrame({
                "Date": pd.to_datetime(data["t"], unit="s", utc=True),
                "Open": [float(x) for x in data.get("o", [])],
                "High": [float(x) for x in data.get("h", [])],
                "Low": [float(x) for x in data.get("l", [])],
                "Close": [float(x) for x in data.get("c", [])],
                "Volume": [float(x) for x in data.get("v", [])],
            }).set_index("Date").sort_index()

            meta = {
                "provider": self.PROVIDER_NAME,
                "status": "success",
                "symbol": clean_sym,
                "interval": interval,
                "rows": len(df),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "cached": False,
            }
            _fh_candle_cache[cache_key] = (df, meta)
            return df, meta

        return pd.DataFrame(), {
            "provider": self.PROVIDER_NAME,
            "status": "no_data_or_unsupported",
            "symbol": clean_sym,
            "interval": interval,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_company_news(self, symbol: str, days_back: int = 7) -> List[Dict[str, Any]]:
        """Fetch verified company news articles."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        cache_key = f"fh_news_{clean_sym}"
        if cache_key in _fh_news_cache:
            return _fh_news_cache[cache_key]

        if not self.is_configured:
            return []

        today = datetime.now(timezone.utc)
        from_date = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
        to_date = today.strftime("%Y-%m-%d")

        data = self._request("company-news", {
            "symbol": clean_sym,
            "from": from_date,
            "to": to_date,
        })

        if isinstance(data, list) and len(data) > 0:
            formatted = []
            for item in data[:8]:
                formatted.append({
                    "headline": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "source": item.get("source", "Finnhub"),
                    "url": item.get("url", ""),
                    "datetime": datetime.fromtimestamp(item.get("datetime", 0), timezone.utc).isoformat() if item.get("datetime") else None,
                    "provider": self.PROVIDER_NAME,
                })
            _fh_news_cache[cache_key] = formatted
            return formatted

        return []

    def get_market_news(self, category: str = "general") -> List[Dict[str, Any]]:
        """Fetch general market news."""
        cache_key = f"fh_market_news_{category}"
        if cache_key in _fh_news_cache:
            return _fh_news_cache[cache_key]

        if not self.is_configured:
            return []

        data = self._request("news", {"category": category})
        if isinstance(data, list) and len(data) > 0:
            formatted = []
            for item in data[:8]:
                formatted.append({
                    "headline": item.get("headline", ""),
                    "summary": item.get("summary", ""),
                    "source": item.get("source", "Finnhub"),
                    "url": item.get("url", ""),
                    "datetime": datetime.fromtimestamp(item.get("datetime", 0), timezone.utc).isoformat() if item.get("datetime") else None,
                    "provider": self.PROVIDER_NAME,
                })
            _fh_news_cache[cache_key] = formatted
            return formatted

        return []

    def get_company_profile(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Fetch company profile from Finnhub (/stock/profile2)."""
        clean_sym = symbol.upper().replace(".NS", "").replace(".BO", "").strip()
        if not self.is_configured:
            return None
        data = self._request("stock/profile2", {"symbol": f"NSE:{clean_sym}"})
        if not isinstance(data, dict) or not data.get("name"):
            data = self._request("stock/profile2", {"symbol": clean_sym})
        if isinstance(data, dict) and data.get("name"):
            return {
                "symbol": clean_sym,
                "ticker": clean_sym,
                "company_name": data.get("name"),
                "sector": data.get("finnhubIndustry", "Indian Equities"),
                "industry": data.get("finnhubIndustry", "N/A"),
                "website": data.get("weburl", ""),
                "market_cap": data.get("marketCapitalization"),
                "description": "",
                "provider": self.PROVIDER_NAME,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        return None

    def check_health(self) -> Dict[str, Any]:
        """Verify API authentication and status."""
        if not self.is_configured:
            return {"configured": False, "status": "missing_api_key"}
        # Ping with lightweight call
        res = self._request("news", {"category": "general"})
        if res is not None:
            return {"configured": True, "status": "authenticated", "provider": self.PROVIDER_NAME}
        return {"configured": True, "status": "authentication_or_rate_limit_error"}


# Singleton export
finnhub_service = FinnhubService()

