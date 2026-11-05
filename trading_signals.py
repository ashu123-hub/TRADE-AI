"""
TradeMind AI - Trading Signal Engine
Combines ML predictions + technical indicators → BUY/SELL/HOLD signals
with entry, target, stop-loss, and risk/reward.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from config import settings
from indicators import get_latest_indicators, identify_support_resistance
from risk_management import calculate_stop_loss, calculate_target_price, calculate_risk_reward

logger = logging.getLogger(__name__)


SIGNAL_WEIGHTS = {
    "ml_prediction": 0.45,
    "rsi": 0.15,
    "macd": 0.15,
    "ema_cross": 0.10,
    "volume": 0.10,
    "bollinger": 0.05,
}


def compute_signal_score(ml_prediction: dict, indicators: dict, df: pd.DataFrame) -> tuple[float, dict]:
    """
    Compute a composite signal score in [-1, 1].
    Positive = bullish, Negative = bearish, ~0 = neutral.
    Returns (score, component_scores).
    """
    components: dict[str, float] = {}

    # 1. ML Prediction
    ml_dir = ml_prediction.get("direction", "NEUTRAL")
    ml_conf = ml_prediction.get("confidence", 0.5)
    ml_score = {"UP": ml_conf, "DOWN": -ml_conf, "NEUTRAL": 0.0}.get(ml_dir, 0.0)
    components["ml_prediction"] = ml_score

    # 2. RSI
    rsi = indicators.get("RSI")
    if rsi is not None:
        if rsi < 30:
            components["rsi"] = 0.8   # Oversold → bullish
        elif rsi > 70:
            components["rsi"] = -0.8  # Overbought → bearish
        elif rsi < 40:
            components["rsi"] = 0.3
        elif rsi > 60:
            components["rsi"] = -0.3
        else:
            components["rsi"] = 0.0
    else:
        components["rsi"] = 0.0

    # 3. MACD
    macd = indicators.get("MACD")
    macd_sig = indicators.get("MACD_Signal")
    macd_hist = indicators.get("MACD_Hist")
    if macd is not None and macd_sig is not None:
        if macd > macd_sig and macd_hist and macd_hist > 0:
            components["macd"] = 0.7
        elif macd < macd_sig and macd_hist and macd_hist < 0:
            components["macd"] = -0.7
        else:
            components["macd"] = 0.0
    else:
        components["macd"] = 0.0

    # 4. EMA Cross
    ema_bull = indicators.get("ema_cross_bull")
    if ema_bull == 1:
        components["ema_cross"] = 0.6
    elif ema_bull == 0:
        components["ema_cross"] = -0.6
    else:
        components["ema_cross"] = 0.0

    # 5. Volume
    if "volume_ratio" in df.columns:
        vol_ratio = float(df["volume_ratio"].iloc[-1]) if not df.empty else 1.0
        if vol_ratio > 1.5:
            components["volume"] = abs(ml_score) * 0.5  # amplify signal
        else:
            components["volume"] = 0.0
    else:
        components["volume"] = 0.0

    # 6. Bollinger Bands
    bb_pctb = indicators.get("BB_PctB") or (
        (df["Close"].iloc[-1] - indicators.get("BB_Lower", 0)) /
        ((indicators.get("BB_Upper", 1) - indicators.get("BB_Lower", 0)) + 1e-9)
        if not df.empty else None
    )
    if bb_pctb is not None:
        if bb_pctb < 0.05:
            components["bollinger"] = 0.7   # near lower band → oversold
        elif bb_pctb > 0.95:
            components["bollinger"] = -0.7  # near upper band → overbought
        else:
            components["bollinger"] = 0.0
    else:
        components["bollinger"] = 0.0

    # Weighted composite
    score = sum(SIGNAL_WEIGHTS[k] * components.get(k, 0.0) for k in SIGNAL_WEIGHTS)
    return float(score), components


def score_to_signal(score: float, threshold: float = 0.25) -> str:
    """Convert composite score to BUY/SELL/HOLD."""
    if score > threshold:
        return "BUY"
    elif score < -threshold:
        return "SELL"
    return "HOLD"


def generate_trading_signal(
    symbol: str,
    df: pd.DataFrame,
    ml_prediction: dict,
    risk_pct: float = 2.0,
) -> dict:
    """
    Full trading signal generation pipeline.
    Returns a complete signal dict with entry/target/stop-loss/R:R.
    """
    if df.empty:
        return _empty_signal(symbol)

    indicators = get_latest_indicators(df)
    current_price = float(df["Close"].iloc[-1])
    sr = identify_support_resistance(df)

    score, components = compute_signal_score(ml_prediction, indicators, df)
    signal = score_to_signal(score)

    # Risk management
    atr = indicators.get("ATR") or (current_price * 0.015)
    stop_loss = calculate_stop_loss(current_price, signal, atr)
    target_price = calculate_target_price(current_price, signal, atr)
    rr = calculate_risk_reward(current_price, target_price, stop_loss)

    # Expected move
    pred_change_pct = ml_prediction.get("predicted_change_pct") or (
        (target_price - current_price) / current_price * 100 if signal == "BUY"
        else (current_price - target_price) / current_price * 100
    )

    return {
        "symbol": symbol,
        "signal": signal,
        "score": round(score, 4),
        "current_price": round(current_price, 2),
        "entry_price": round(current_price, 2),
        "target_price": round(target_price, 2),
        "stop_loss": round(stop_loss, 2),
        "risk_reward_ratio": round(rr, 2),
        "expected_change_pct": round(pred_change_pct, 2) if pred_change_pct else None,
        "confidence": ml_prediction.get("confidence", 0.0),
        "ml_prediction": ml_prediction,
        "indicators": indicators,
        "support": sr.get("support"),
        "resistance": sr.get("resistance"),
        "signal_components": components,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "TradeMind AI",
        "disclaimer": "Educational purposes only. Not financial advice.",
    }


def _empty_signal(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "signal": "HOLD",
        "score": 0.0,
        "current_price": None,
        "error": "Insufficient data",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def batch_scan_signals(
    symbols: list[str],
    df_map: dict[str, pd.DataFrame],
    predictions: dict[str, dict],
) -> list[dict]:
    """Generate signals for multiple stocks. Returns list sorted by |score|."""
    results = []
    for symbol in symbols:
        df = df_map.get(symbol, pd.DataFrame())
        pred = predictions.get(symbol, {"direction": "NEUTRAL", "confidence": 0.0})
        try:
            sig = generate_trading_signal(symbol, df, pred)
            results.append(sig)
        except Exception as exc:
            logger.error("Signal generation failed for %s: %s", symbol, exc)
    results.sort(key=lambda x: abs(x.get("score", 0.0)), reverse=True)
    return results
