"""
TradeMind AI - Data Collection Module
Downloads, validates and stores historical stock data.
Prevents duplicate API calls via local cache and Supabase checks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from config import settings
from api_manager import market_data
import database as db

logger = logging.getLogger(__name__)


# ─── NSE Stock Universe ───────────────────────────────────────────────────────

# Curated NIFTY 50 + popular NSE stocks (reliable Yahoo Finance coverage)
NIFTY_50_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
    "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "TITAN",
    "SUNPHARMA", "WIPRO", "BAJFINANCE", "NESTLEIND", "POWERGRID",
    "NTPC", "TECHM", "HCLTECH", "ULTRACEMCO", "ONGC",
    "COALINDIA", "JSWSTEEL", "TATASTEEL", "INDUSINDBK", "M&M",
    "ADANIPORTS", "BAJAJFINSV", "APOLLOHOSP", "DRREDDY", "CIPLA",
    "DIVISLAB", "EICHERMOT", "HEROMOTOCO", "BPCL", "TATACONSUM",
    "BRITANNIA", "GRASIM", "SHRIRAMFIN", "SBILIFE", "HDFCLIFE",
    "BAJAJ-AUTO", "TRENT", "TATAMOTORS", "LTIM", "HINDALCO",
]

NIFTY_NEXT_50 = [
    "ABB", "ACC", "ADANIENT", "AMBUJACEM", "BANKBARODA",
    "BERGEPAINT", "BEL", "CANBK", "CHOLAFIN", "DABUR",
    "DLF", "FEDERALBNK", "GODREJCP", "HAVELLS", "INDHOTEL",
    "IDFCFIRSTB", "INDUSTOWER", "IRCTC", "JUBLFOOD", "LICHSGFIN",
    "LUPIN", "MCDOWELL-N", "MFSL", "MPHASIS", "NAUKRI",
    "OFSS", "PAGEIND", "PIDILITIND", "PNB", "SAIL",
    "SRF", "TORNTPHARM", "TVSMOTOR", "UBL", "VEDL",
    "VOLTAS", "WHIRLPOOL", "ZEEL", "PAYTM",
]

NIFTY_MIDCAP_SYMBOLS = [
    "SUZLON", "IRFC", "IREDA", "HAL", "BHEL", "NHPC", "RVNL",
    "JIOFIN", "BSE", "CDSL", "MAZDOCK", "COCHINSHIP", "RECLTD", "PFC",
    "TATAPOWER", "TATACHEM", "TATAELXSI", "YESBANK", "IDEA", "POLICYBZR",
    "KPITTECH", "PERSISTENT", "COFORGE", "MOTHERSON", "MAXHEALTH", "DIXON",
    "ASTRAL", "POLYCAB", "KALYANKJIL", "PRESTIGE", "OBEROIRLTY", "PHOENIXLTD",
    "ASHOKLEY", "CUMMINSIND", "TIINDIA", "BHARATFORG", "ABCAPITAL", "MUTHOOTFIN",
    "MANAPPURAM", "NMDC", "NATIONALUM", "HINDCOPPER", "EXIDEIND",
    "AUROPHARMA", "ALKEM", "GLENMARK", "BIOCON", "LALPATHLAB", "METROPOLIS",
]

POPULAR_NSE_STOCKS = sorted(list(dict.fromkeys(NIFTY_50_SYMBOLS + NIFTY_NEXT_50 + NIFTY_MIDCAP_SYMBOLS)))

INDEX_SYMBOLS = {
    "NIFTY 50": "^NSEI",
    "SENSEX": "^BSESN",
    "NIFTY BANK": "^NSEBANK",
    "NIFTY IT": "^CNXIT",
}


# ─── Data Validation ─────────────────────────────────────────────────────────

def validate_ohlcv(df: pd.DataFrame, min_rows: int = 20) -> tuple[bool, str]:
    """Check data quality. Returns (is_valid, reason)."""
    if df is None or df.empty:
        return False, "Empty DataFrame"
    if len(df) < min_rows:
        return False, f"Insufficient rows: {len(df)} < {min_rows}"
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(df.columns)
    if missing:
        return False, f"Missing columns: {missing}"
    null_pct = df[["Open", "High", "Low", "Close"]].isnull().mean().mean()
    if null_pct > 0.1:
        return False, f"Too many nulls: {null_pct:.1%}"
    if (df["Close"] <= 0).any():
        return False, "Non-positive close prices"
    return True, "OK"


def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Forward-fill small gaps, drop persistent NaNs."""
    df = df.copy()
    df = df.ffill().bfill()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df = df[df["Close"] > 0]
    return df


# ─── Core Download Function ───────────────────────────────────────────────────

def download_stock_data(
    symbol: str,
    interval: str = "1d",
    period: str = "2y",
    store_to_db: bool = True,
) -> pd.DataFrame:
    """
    Download OHLCV for one symbol.
    1. Try Supabase cache first (daily only).
    2. Fetch from API (Yahoo primary, AV fallback).
    3. Validate and clean.
    4. Store to Supabase.
    """
    # Only use DB cache for daily data
    if interval == "1d" and store_to_db:
        cached = db.get_historical_prices(symbol, timeframe="1d", limit=1000)
        if len(cached) >= settings.MIN_DATA_ROWS:
            logger.info("Using Supabase cache for %s (%d rows)", symbol, len(cached))
            return cached

    df, source = market_data.get_ohlcv(symbol, interval=interval, period=period)
    valid, reason = validate_ohlcv(df, min_rows=10)
    if not valid:
        logger.warning("Data validation failed for %s: %s", symbol, reason)
        return pd.DataFrame()

    df = clean_ohlcv(df)

    if store_to_db and interval == "1d" and not df.empty:
        db.upsert_stock(symbol)
        db.insert_historical_prices(df, symbol, timeframe=interval)

    logger.info("Downloaded %d rows for %s via %s", len(df), symbol, source)
    return df


def download_intraday_data(symbol: str, interval: str = "5m") -> pd.DataFrame:
    """Download intraday data (not stored to DB due to volume)."""
    df, source = market_data.get_intraday(symbol, interval=interval)
    valid, reason = validate_ohlcv(df, min_rows=5)
    if not valid:
        logger.warning("Intraday validation failed for %s: %s", symbol, reason)
        return pd.DataFrame()
    return clean_ohlcv(df)


def download_index_data(index_name: str = "NIFTY 50", period: str = "1y") -> pd.DataFrame:
    """Download index (NIFTY, SENSEX) data."""
    yf_symbol = INDEX_SYMBOLS.get(index_name, "^NSEI")
    try:
        import yfinance as yf
        df = yf.download(yf_symbol, period=period, interval="1d", auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
        df.index = pd.to_datetime(df.index, utc=True)
        return clean_ohlcv(df)
    except Exception as exc:
        logger.error("Index download failed for %s: %s", index_name, exc)
        return pd.DataFrame()


# ─── Bulk Operations ─────────────────────────────────────────────────────────

def download_multiple_stocks(
    symbols: list[str],
    interval: str = "1d",
    period: str = "1y",
    max_symbols: int = 50,
) -> dict[str, pd.DataFrame]:
    """Download data for multiple symbols. Returns symbol -> DataFrame map."""
    results: dict[str, pd.DataFrame] = {}
    symbols = symbols[:max_symbols]
    for sym in symbols:
        try:
            df = download_stock_data(sym, interval=interval, period=period)
            if not df.empty:
                results[sym] = df
        except Exception as exc:
            logger.error("Failed to download %s: %s", sym, exc)
    logger.info("Downloaded %d/%d symbols", len(results), len(symbols))
    return results


def get_market_overview() -> dict:
    """Return current NIFTY 50 and SENSEX data for dashboard with provider attribution."""
    overview = {}
    for name, yf_sym in INDEX_SYMBOLS.items():
        # First attempt primary market data provider
        q = market_data.get_quote(yf_sym)
        if q.get("price") is not None and q.get("status") != "unavailable":
            overview[name] = {
                "symbol": yf_sym,
                "price": q.get("price"),
                "change": q.get("change"),
                "change_pct": q.get("change_pct"),
                "source": q.get("provider", "Primary Provider"),
                "timestamp": q.get("timestamp", datetime.now(timezone.utc).isoformat()),
            }
            continue

        # Secondary fallback if enabled
        try:
            import yfinance as yf
            ticker = yf.Ticker(yf_sym)
            info = ticker.fast_info
            current = getattr(info, "last_price", None)
            prev_close = getattr(info, "previous_close", None)
            if current and prev_close:
                change = current - prev_close
                change_pct = (change / prev_close) * 100
            else:
                change = change_pct = None

            overview[name] = {
                "symbol": yf_sym,
                "price": current,
                "change": change,
                "change_pct": change_pct,
                "source": "Yahoo Finance (Safety Fallback)",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except Exception as exc:
            logger.warning("Could not fetch %s: %s", name, exc)
    return overview


def get_top_movers(symbols: list[str] = None, top_n: int = 5) -> dict:
    """
    Compute today's top gainers and losers from a list of NSE symbols.
    Uses Yahoo Finance batch download for efficiency.
    """
    if symbols is None:
        symbols = NIFTY_50_SYMBOLS[:30]

    try:
        import yfinance as yf
        yf_symbols = [s + ".NS" for s in symbols]
        df = yf.download(
            " ".join(yf_symbols),
            period="2d",
            interval="1d",
            auto_adjust=True,
            progress=False,
        )
        if df.empty:
            return {"gainers": [], "losers": []}

        close = df["Close"] if "Close" in df else df.xs("Close", axis=1, level=0) if isinstance(df.columns, pd.MultiIndex) else pd.DataFrame()
        if close.empty or len(close) < 2:
            return {"gainers": [], "losers": []}

        changes = {}
        for col in close.columns:
            sym = str(col).replace(".NS", "")
            series = close[col].dropna()
            if len(series) >= 2:
                prev = series.iloc[-2]
                curr = series.iloc[-1]
                if prev and prev > 0:
                    changes[sym] = {
                        "symbol": sym,
                        "current_price": round(curr, 2),
                        "change_pct": round((curr - prev) / prev * 100, 2),
                    }

        sorted_changes = sorted(changes.values(), key=lambda x: x["change_pct"], reverse=True)
        return {
            "gainers": sorted_changes[:top_n],
            "losers": sorted_changes[-top_n:][::-1],
        }
    except Exception as exc:
        logger.error("get_top_movers error: %s", exc)
        return {"gainers": [], "losers": []}
