"""
TradeMind AI - NSE Stock Scanner
Scans available NSE-listed stocks for technical patterns, momentum, breakouts.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from config import settings
from data_collection import NIFTY_50_SYMBOLS, NIFTY_NEXT_50, download_stock_data, get_top_movers
from indicators import (
    add_all_indicators,
    calculate_rsi,
    identify_support_resistance,
    get_latest_indicators,
)

logger = logging.getLogger(__name__)

POPULAR_NSE_STOCKS = list(dict.fromkeys(NIFTY_50_SYMBOLS + NIFTY_NEXT_50))


# ─── Scanner Core ────────────────────────────────────────────────────────────

def scan_stock(symbol: str, df: pd.DataFrame = None) -> dict | None:
    """
    Compute scanner metrics for one stock.
    Returns None if data is insufficient.
    """
    if df is None or df.empty:
        df = download_stock_data(symbol, interval="1d", period="6mo")

    if df is None or df.empty or len(df) < 30:
        return None

    try:
        df_ind = add_all_indicators(df)
        latest = get_latest_indicators(df_ind)
        last_row = df_ind.iloc[-1]
        prev_row = df_ind.iloc[-2] if len(df_ind) > 1 else last_row

        close = float(last_row["Close"])
        prev_close = float(prev_row["Close"])
        volume = float(last_row.get("Volume", 0))
        avg_volume = float(df["Volume"].tail(20).mean()) if "Volume" in df.columns else 1.0

        change_pct = (close - prev_close) / (prev_close + 1e-9) * 100
        volume_ratio = volume / (avg_volume + 1e-9)

        # Momentum score
        momentum_score = _compute_momentum_score(df_ind, latest)

        # Breakout check
        breakout = _check_breakout(df_ind, latest)

        sr = identify_support_resistance(df_ind)

        return {
            "symbol": symbol,
            "close": round(close, 2),
            "change_pct": round(change_pct, 2),
            "volume": int(volume),
            "volume_ratio": round(volume_ratio, 2),
            "rsi": latest.get("RSI"),
            "macd": latest.get("MACD"),
            "macd_signal": latest.get("MACD_Signal"),
            "ema_9": latest.get("EMA_9"),
            "ema_21": latest.get("EMA_21"),
            "sma_50": latest.get("SMA_50"),
            "atr": latest.get("ATR"),
            "adx": latest.get("ADX"),
            "momentum_score": round(momentum_score, 3),
            "breakout": breakout,
            "support": sr.get("support"),
            "resistance": sr.get("resistance"),
            "week_52_high": round(float(df["High"].tail(252).max()), 2),
            "week_52_low": round(float(df["Low"].tail(252).min()), 2),
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as exc:
        logger.error("scan_stock error for %s: %s", symbol, exc)
        return None


def _compute_momentum_score(df: pd.DataFrame, indicators: dict) -> float:
    """Score in [0, 1]: higher = stronger bullish momentum."""
    score = 0.5  # neutral
    rsi = indicators.get("RSI")
    if rsi is not None:
        if 50 < rsi < 70:
            score += 0.15
        elif rsi > 70:
            score += 0.05
        elif rsi < 30:
            score -= 0.20

    if indicators.get("ema_cross_bull") == 1:
        score += 0.15
    elif indicators.get("ema_cross_bull") == 0:
        score -= 0.15

    if indicators.get("price_above_sma50") == 1:
        score += 0.10

    macd = indicators.get("MACD")
    macd_sig = indicators.get("MACD_Signal")
    if macd is not None and macd_sig is not None:
        score += 0.10 if macd > macd_sig else -0.10

    return max(0.0, min(1.0, score))


def _check_breakout(df: pd.DataFrame, indicators: dict) -> dict:
    """Check for breakout patterns."""
    result = {"type": "NONE", "strength": 0.0, "description": ""}
    if len(df) < 20:
        return result

    close = df["Close"].iloc[-1]
    high_20 = df["High"].tail(20).max()
    low_20 = df["Low"].tail(20).min()
    atr = indicators.get("ATR", close * 0.015)

    if close > high_20 - atr * 0.3:
        result = {
            "type": "BULLISH_BREAKOUT",
            "strength": min((close - high_20 + atr * 0.3) / (atr * 0.3 + 1e-9), 1.0),
            "description": "Price near/above 20-day high",
        }
    elif close < low_20 + atr * 0.3:
        result = {
            "type": "BEARISH_BREAKOUT",
            "strength": min((low_20 + atr * 0.3 - close) / (atr * 0.3 + 1e-9), 1.0),
            "description": "Price near/below 20-day low",
        }

    # Volume confirmation
    vol_ratio = df["Volume"].iloc[-1] / (df["Volume"].tail(20).mean() + 1e-9)
    if vol_ratio > 1.5 and result["type"] != "NONE":
        result["strength"] = min(result["strength"] * 1.3, 1.0)
        result["description"] += " with high volume"

    return result


# ─── Batch Scanner ───────────────────────────────────────────────────────────

def run_full_scan(
    symbols: list[str] = None,
    max_symbols: int = 50,
) -> list[dict]:
    """
    Scan multiple NSE stocks. Returns list of scan results.
    """
    if symbols is None:
        symbols = POPULAR_NSE_STOCKS[:max_symbols]
    else:
        symbols = symbols[:max_symbols]

    results = []
    for sym in symbols:
        try:
            result = scan_stock(sym)
            if result is not None:
                results.append(result)
        except Exception as exc:
            logger.error("Scanner failed for %s: %s", sym, exc)

    logger.info("Scanned %d/%d symbols successfully", len(results), len(symbols))
    return results


def get_top_gainers(scan_results: list[dict], n: int = 10) -> list[dict]:
    return sorted(scan_results, key=lambda x: x.get("change_pct", 0), reverse=True)[:n]


def get_top_losers(scan_results: list[dict], n: int = 10) -> list[dict]:
    return sorted(scan_results, key=lambda x: x.get("change_pct", 0))[:n]


def get_high_volume_stocks(scan_results: list[dict], n: int = 10) -> list[dict]:
    return sorted(scan_results, key=lambda x: x.get("volume_ratio", 0), reverse=True)[:n]


def get_momentum_stocks(scan_results: list[dict], n: int = 10) -> list[dict]:
    return sorted(scan_results, key=lambda x: x.get("momentum_score", 0), reverse=True)[:n]


def get_breakout_stocks(scan_results: list[dict]) -> list[dict]:
    return [s for s in scan_results if s.get("breakout", {}).get("type") != "NONE"]


def filter_stocks(
    scan_results: list[dict],
    min_price: float = 0,
    max_price: float = 1e9,
    min_volume: int = 0,
    min_rsi: float = 0,
    max_rsi: float = 100,
    signal_filter: str = "ALL",
) -> list[dict]:
    """Apply user-defined filters to scanner results."""
    filtered = []
    for s in scan_results:
        price = s.get("close", 0) or 0
        vol = s.get("volume", 0) or 0
        rsi = s.get("rsi") or 50

        if not (min_price <= price <= max_price):
            continue
        if vol < min_volume:
            continue
        if not (min_rsi <= rsi <= max_rsi):
            continue
        filtered.append(s)
    return filtered


def search_stocks(
    query: str,
    scan_results: list[dict] = None,
    all_symbols: list[str] = None,
) -> list[str]:
    """Search stocks by symbol substring."""
    q = query.upper().strip()
    if not q:
        return []
    universe = all_symbols or POPULAR_NSE_STOCKS
    return [s for s in universe if q in s.upper()]
