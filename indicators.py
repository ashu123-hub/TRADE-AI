"""
TradeMind AI - Technical Indicators Module
Computes RSI, MACD, EMA, SMA, VWAP, Bollinger Bands, and more
using the `ta` library with pandas fallbacks.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ─── Individual Indicators ────────────────────────────────────────────────────

def calculate_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    try:
        import ta
        return ta.momentum.RSIIndicator(close, window=period).rsi()
    except Exception:
        delta = close.diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / (loss + 1e-9)
        return 100 - (100 / (1 + rs))


def calculate_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    try:
        import ta
        macd_ind = ta.trend.MACD(close, window_fast=fast, window_slow=slow, window_sign=signal)
        return pd.DataFrame({
            "MACD": macd_ind.macd(),
            "MACD_Signal": macd_ind.macd_signal(),
            "MACD_Hist": macd_ind.macd_diff(),
        })
    except Exception:
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=signal, adjust=False).mean()
        return pd.DataFrame({
            "MACD": macd_line,
            "MACD_Signal": signal_line,
            "MACD_Hist": macd_line - signal_line,
        })


def calculate_ema(close: pd.Series, period: int) -> pd.Series:
    return close.ewm(span=period, adjust=False).mean()


def calculate_sma(close: pd.Series, period: int) -> pd.Series:
    return close.rolling(window=period).mean()


def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
    """VWAP — resets daily."""
    typical_price = (high + low + close) / 3
    tp_vol = typical_price * volume
    cumulative_tp_vol = tp_vol.cumsum()
    cumulative_vol = volume.cumsum()
    return cumulative_tp_vol / (cumulative_vol + 1e-9)


def calculate_bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    try:
        import ta
        bb = ta.volatility.BollingerBands(close, window=period, window_dev=num_std)
        return pd.DataFrame({
            "BB_Upper": bb.bollinger_hband(),
            "BB_Middle": bb.bollinger_mavg(),
            "BB_Lower": bb.bollinger_lband(),
            "BB_Width": bb.bollinger_wband(),
            "BB_PctB": bb.bollinger_pband(),
        })
    except Exception:
        sma = close.rolling(period).mean()
        std = close.rolling(period).std()
        upper = sma + num_std * std
        lower = sma - num_std * std
        return pd.DataFrame({
            "BB_Upper": upper,
            "BB_Middle": sma,
            "BB_Lower": lower,
            "BB_Width": (upper - lower) / (sma + 1e-9),
            "BB_PctB": (close - lower) / (upper - lower + 1e-9),
        })


def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    try:
        import ta
        return ta.volatility.AverageTrueRange(high, low, close, window=period).average_true_range()
    except Exception:
        hl = high - low
        hc = (high - close.shift(1)).abs()
        lc = (low - close.shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return tr.rolling(period).mean()


def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.DataFrame:
    try:
        import ta
        adx_ind = ta.trend.ADXIndicator(high, low, close, window=period)
        return pd.DataFrame({
            "ADX": adx_ind.adx(),
            "ADX_Pos": adx_ind.adx_pos(),
            "ADX_Neg": adx_ind.adx_neg(),
        })
    except Exception:
        return pd.DataFrame({"ADX": pd.Series(dtype=float), "ADX_Pos": pd.Series(dtype=float), "ADX_Neg": pd.Series(dtype=float)})


def calculate_stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3
) -> pd.DataFrame:
    try:
        import ta
        stoch = ta.momentum.StochasticOscillator(high, low, close, window=k_period, smooth_window=d_period)
        return pd.DataFrame({"Stoch_K": stoch.stoch(), "Stoch_D": stoch.stoch_signal()})
    except Exception:
        lowest_low = low.rolling(k_period).min()
        highest_high = high.rolling(k_period).max()
        k = 100 * (close - lowest_low) / (highest_high - lowest_low + 1e-9)
        d = k.rolling(d_period).mean()
        return pd.DataFrame({"Stoch_K": k, "Stoch_D": d})


def calculate_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """On-Balance Volume."""
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


# ─── Composite: Add all indicators to DataFrame ──────────────────────────────

def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all technical indicators to an OHLCV DataFrame.
    Returns enriched DataFrame.
    """
    df = df.copy()
    if len(df) < 30:
        logger.warning("Not enough data for indicators (%d rows)", len(df))
        return df

    close = df["Close"]
    high = df["High"]
    low = df["Low"]
    volume = df["Volume"]

    # RSI
    df["RSI"] = calculate_rsi(close)
    df["RSI_14"] = df["RSI"]

    # MACD
    macd_df = calculate_macd(close)
    df = pd.concat([df, macd_df], axis=1)

    # EMAs
    for period in [9, 21, 50, 200]:
        df[f"EMA_{period}"] = calculate_ema(close, period)

    # SMAs
    for period in [20, 50, 200]:
        df[f"SMA_{period}"] = calculate_sma(close, period)

    # VWAP
    df["VWAP"] = calculate_vwap(high, low, close, volume)

    # Bollinger Bands
    bb_df = calculate_bollinger_bands(close)
    df = pd.concat([df, bb_df], axis=1)

    # ATR
    df["ATR"] = calculate_atr(high, low, close)

    # ADX
    adx_df = calculate_adx(high, low, close)
    df = pd.concat([df, adx_df], axis=1)

    # Stochastic
    stoch_df = calculate_stochastic(high, low, close)
    df = pd.concat([df, stoch_df], axis=1)

    # OBV
    df["OBV"] = calculate_obv(close, volume)

    # Trend signals
    df["ema_cross_bull"] = (df["EMA_9"] > df["EMA_21"]).astype(int)
    df["price_above_sma50"] = (close > df["SMA_50"]).astype(int)
    df["price_above_sma200"] = (close > df["SMA_200"]).astype(int)
    df["golden_cross"] = ((df["SMA_50"] > df["SMA_200"]) & (df["SMA_50"].shift(1) <= df["SMA_200"].shift(1))).astype(int)
    df["death_cross"] = ((df["SMA_50"] < df["SMA_200"]) & (df["SMA_50"].shift(1) >= df["SMA_200"].shift(1))).astype(int)

    logger.debug("Indicators added. DataFrame shape: %s", df.shape)
    return df


def get_latest_indicators(df: pd.DataFrame) -> dict:
    """Return the most recent row's indicator values as a dict."""
    if df.empty:
        return {}
    row = df.iloc[-1]
    keys = ["RSI", "MACD", "MACD_Signal", "MACD_Hist",
            "EMA_9", "EMA_21", "SMA_50", "SMA_200",
            "VWAP", "BB_Upper", "BB_Middle", "BB_Lower",
            "ATR", "ADX", "Stoch_K", "Stoch_D", "OBV",
            "ema_cross_bull", "price_above_sma50", "price_above_sma200"]
    return {k: round(float(row[k]), 4) if k in row.index and pd.notna(row[k]) else None for k in keys}


def identify_support_resistance(df: pd.DataFrame, window: int = 10) -> dict:
    """Simple pivot-based support and resistance levels."""
    if len(df) < window * 3:
        return {"support": None, "resistance": None}
    close = df["Close"]
    # Local minima and maxima
    highs = df["High"].rolling(window, center=True).max()
    lows = df["Low"].rolling(window, center=True).min()
    resistance_levels = df.loc[df["High"] == highs, "High"].dropna().tail(3).values.tolist()
    support_levels = df.loc[df["Low"] == lows, "Low"].dropna().tail(3).values.tolist()
    return {
        "support": min(support_levels) if support_levels else None,
        "resistance": max(resistance_levels) if resistance_levels else None,
        "support_levels": sorted(support_levels),
        "resistance_levels": sorted(resistance_levels, reverse=True),
    }


def get_signal_summary(indicators: dict) -> str:
    """Return a quick textual summary of indicator readings."""
    parts = []
    rsi = indicators.get("RSI")
    if rsi is not None:
        if rsi > 70:
            parts.append(f"RSI {rsi:.1f} (Overbought)")
        elif rsi < 30:
            parts.append(f"RSI {rsi:.1f} (Oversold)")
        else:
            parts.append(f"RSI {rsi:.1f} (Neutral)")

    macd = indicators.get("MACD")
    macd_sig = indicators.get("MACD_Signal")
    if macd is not None and macd_sig is not None:
        trend = "Bullish" if macd > macd_sig else "Bearish"
        parts.append(f"MACD {trend}")

    if indicators.get("ema_cross_bull") == 1:
        parts.append("EMA Bullish Cross")
    elif indicators.get("ema_cross_bull") == 0:
        parts.append("EMA Bearish Cross")

    return " | ".join(parts) if parts else "Insufficient data"
