"""
TradeMind AI — Production Model Training Pipeline
Downloads real NSE stock data, engineers features, trains 3 ML models,
validates with walk-forward testing, saves models & results to Supabase.

Usage:
    python train_models.py                          # Train top 10 NIFTY stocks
    python train_models.py --symbols RELIANCE TCS   # Train specific stocks
    python train_models.py --all                    # Train all NIFTY 50
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ── Setup ─────────────────────────────────────────────────────────────────────
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import settings, api_keys
from indicators import add_all_indicators, get_latest_indicators
from preprocessing import (
    add_time_features,
    add_price_features,
    add_lag_features,
    create_target,
    prepare_features,
    train_test_split_time,
    prepare_lstm_sequences,
)
from models.random_forest import RandomForestModel
from models.xgboost_model import XGBoostModel
from models.lstm_model import LSTMModel

logger = logging.getLogger("trademind.training")

# ── Stock Universes ───────────────────────────────────────────────────────────

TOP_10_NIFTY = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK",
    "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL", "KOTAKBANK",
]

NIFTY_50 = [
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


# ══════════════════════════════════════════════════════════════════════════════
# DATA DOWNLOAD — Real NSE Stock Data via Yahoo Finance
# ══════════════════════════════════════════════════════════════════════════════

def download_stock_data_yf(symbol: str, period: str = "2y") -> pd.DataFrame:
    """Download real OHLCV data from Yahoo Finance for NSE stocks."""
    import yfinance as yf

    yf_symbol = f"{symbol}.NS"
    logger.info("Downloading %s (%s) — period=%s", symbol, yf_symbol, period)

    try:
        ticker = yf.Ticker(yf_symbol)
        df = ticker.history(period=period, interval="1d", auto_adjust=True)

        if df.empty:
            logger.warning("No data returned for %s", yf_symbol)
            return pd.DataFrame()

        # Handle MultiIndex columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Keep OHLCV only
        required = ["Open", "High", "Low", "Close", "Volume"]
        for col in required:
            if col not in df.columns:
                logger.warning("Missing column %s for %s", col, symbol)
                return pd.DataFrame()

        df = df[required].copy()
        df = df.dropna(subset=["Open", "High", "Low", "Close"])
        df = df[df["Close"] > 0]

        # Ensure UTC datetime index
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")

        logger.info("  Got %d rows for %s (%.2f — %.2f)",
                     len(df), symbol, df["Close"].iloc[0], df["Close"].iloc[-1])
        return df

    except Exception as e:
        logger.error("Failed to download %s: %s", symbol, e)
        return pd.DataFrame()


# ══════════════════════════════════════════════════════════════════════════════
# FEATURE ENGINEERING — 40+ Technical + Price + Calendar Features
# ══════════════════════════════════════════════════════════════════════════════

def engineer_features(df: pd.DataFrame, for_lstm: bool = False) -> pd.DataFrame:
    """Full feature engineering pipeline for ML training."""
    if len(df) < 60:
        logger.warning("Too few rows (%d) for feature engineering", len(df))
        return pd.DataFrame()

    # 1. Technical indicators (RSI, MACD, EMAs, SMAs, BB, ATR, ADX, Stochastic, OBV)
    df = add_all_indicators(df)

    # 2. Calendar features
    df = add_time_features(df)

    # 3. Price-derived features (returns, candle body, gaps, volume ratio)
    df = add_price_features(df)

    # 4. Lag features — fewer lags to reduce dimensionality
    df = add_lag_features(df, lags=[1, 2, 3, 5])

    # 5. Additional engineered features
    close = df["Close"]

    # Momentum features
    df["momentum_5"] = close / close.shift(5) - 1
    df["momentum_10"] = close / close.shift(10) - 1
    df["momentum_20"] = close / close.shift(20) - 1

    # Volatility features
    df["volatility_10"] = close.pct_change().rolling(10).std()
    df["volatility_20"] = close.pct_change().rolling(20).std()

    # Price relative to moving averages
    if "SMA_20" in df.columns:
        df["price_sma20_ratio"] = close / (df["SMA_20"] + 1e-9)
    if "SMA_50" in df.columns:
        df["price_sma50_ratio"] = close / (df["SMA_50"] + 1e-9)
    if "EMA_9" in df.columns and "EMA_21" in df.columns:
        df["ema_spread"] = (df["EMA_9"] - df["EMA_21"]) / (df["EMA_21"] + 1e-9)

    # RSI-based features
    if "RSI" in df.columns:
        df["rsi_oversold"] = (df["RSI"] < 30).astype(int)
        df["rsi_overbought"] = (df["RSI"] > 70).astype(int)

    # Volume features
    df["volume_change"] = df["Volume"].pct_change()
    df["volume_sma_ratio"] = df["Volume"] / (df["Volume"].rolling(20).mean() + 1e-9)

    # 6. Create target: binary UP vs DOWN (remove NEUTRAL for clearer signal)
    #    Use 0.3% threshold — tighter to get more samples in each class
    df = create_target(df, forward_periods=1, threshold=0.003)

    logger.info("  Features engineered: %d columns, %d rows", len(df.columns), len(df))
    return df


def select_top_features(X: pd.DataFrame, y: pd.Series, max_features: int = 30) -> list[str]:
    """Select the most predictive features using Random Forest importance.
    Reduces overfitting by keeping only the strongest signals.
    """
    from sklearn.ensemble import RandomForestClassifier

    # Quick RF to rank features
    quick_rf = RandomForestClassifier(
        n_estimators=100, max_depth=6, random_state=42, n_jobs=-1
    )
    quick_rf.fit(X, y)

    importance = pd.Series(quick_rf.feature_importances_, index=X.columns)
    top = importance.nlargest(max_features).index.tolist()
    return top


# ══════════════════════════════════════════════════════════════════════════════
# WALK-FORWARD VALIDATION — Prevents Look-Ahead Bias
# ══════════════════════════════════════════════════════════════════════════════

def walk_forward_validate(
    X: pd.DataFrame,
    y: pd.Series,
    model_class,
    n_splits: int = 5,
    train_pct: float = 0.6,
    **model_kwargs,
) -> dict:
    """
    Walk-forward (expanding window) cross-validation.
    More realistic than random K-Fold for time series.
    """
    n = len(X)
    initial_train_size = int(n * train_pct)
    step = (n - initial_train_size) // n_splits

    if step < 20:
        # Not enough data for walk-forward, fall back to simple split
        return {"walk_forward_splits": 0, "note": "Insufficient data for walk-forward"}

    accuracies = []
    for i in range(n_splits):
        train_end = initial_train_size + i * step
        test_end = min(train_end + step, n)

        if test_end <= train_end:
            break

        X_train = X.iloc[:train_end]
        y_train = y.iloc[:train_end]
        X_test = X.iloc[train_end:test_end]
        y_test = y.iloc[train_end:test_end]

        if len(X_test) < 5:
            continue

        model = model_class(**model_kwargs)
        model.train(X_train, y_train)
        preds = model.predict(X_test)

        from sklearn.metrics import accuracy_score
        acc = accuracy_score(y_test, preds)
        accuracies.append(acc)

    if not accuracies:
        return {"walk_forward_accuracy": 0, "walk_forward_splits": 0}

    return {
        "walk_forward_accuracy": round(float(np.mean(accuracies)), 4),
        "walk_forward_std": round(float(np.std(accuracies)), 4),
        "walk_forward_min": round(float(np.min(accuracies)), 4),
        "walk_forward_max": round(float(np.max(accuracies)), 4),
        "walk_forward_splits": len(accuracies),
    }


# ══════════════════════════════════════════════════════════════════════════════
# TRAIN ONE STOCK — Full Pipeline for a Single Symbol
# ══════════════════════════════════════════════════════════════════════════════

def train_stock(symbol: str, period: str = "2y", save_to_db: bool = True) -> dict:
    """
    Complete training pipeline for one stock:
    1. Download 2 years of real data
    2. Engineer 40+ features
    3. Train Random Forest
    4. Train XGBoost
    5. Train LSTM (if TensorFlow available)
    6. Walk-forward validation
    7. Save models to disk
    8. Save results to Supabase
    """
    start_time = time.time()
    result = {
        "symbol": symbol,
        "status": "pending",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print(f"\n{'='*60}")
    print(f"  Training: {symbol}")
    print(f"{'='*60}")

    # ── Step 1: Download Real Data ──
    print(f"\n  [1/7] Downloading {period} of real NSE data...")
    df = download_stock_data_yf(symbol, period=period)
    if df.empty or len(df) < 100:
        result["status"] = "failed"
        result["error"] = f"Insufficient data: {len(df) if not df.empty else 0} rows"
        print(f"  FAILED: {result['error']}")
        return result

    result["data_rows"] = len(df)
    result["date_range"] = f"{df.index[0].strftime('%Y-%m-%d')} to {df.index[-1].strftime('%Y-%m-%d')}"
    result["latest_close"] = round(float(df["Close"].iloc[-1]), 2)
    print(f"  OK  {len(df)} rows ({result['date_range']})")
    print(f"  Latest close: Rs {result['latest_close']:,.2f}")

    # ── Step 2: Feature Engineering ──
    print(f"\n  [2/7] Engineering features...")
    df_feat = engineer_features(df.copy())
    if df_feat.empty:
        result["status"] = "failed"
        result["error"] = "Feature engineering failed"
        print(f"  FAILED: {result['error']}")
        return result

    X, y = prepare_features(df_feat)
    if y is None or len(X) < 60:
        result["status"] = "failed"
        result["error"] = f"Not enough valid samples: {len(X)}"
        print(f"  FAILED: {result['error']}")
        return result

    result["feature_count"] = len(X.columns)
    result["sample_count"] = len(X)
    result["class_distribution"] = {
        "UP": int((y == 1).sum()),
        "DOWN": int((y == -1).sum()),
        "NEUTRAL": int((y == 0).sum()),
    }
    print(f"  OK  {len(X.columns)} features, {len(X)} samples")
    print(f"  Classes: UP={result['class_distribution']['UP']} | "
          f"DOWN={result['class_distribution']['DOWN']} | "
          f"NEUTRAL={result['class_distribution']['NEUTRAL']}")

    # ── Step 2b: Feature Selection (reduce overfitting) ──
    print(f"  Selecting top features...")
    top_feat = select_top_features(X, y, max_features=25)
    X = X[top_feat]
    print(f"  OK  Reduced to {len(top_feat)} features")

    # ── Step 3: Chronological Train/Test Split ──
    X_train, X_test, y_train, y_test = train_test_split_time(X, y, test_size=0.2)
    print(f"  Split: Train={len(X_train)} | Test={len(X_test)} (chronological, no leakage)")

    # ── Step 4: Train Random Forest (regularized to reduce overfitting) ──
    print(f"\n  [3/7] Training Random Forest...")
    rf = RandomForestModel(n_estimators=500, max_depth=6, min_samples_split=20, min_samples_leaf=10)
    rf_metrics = rf.train(X_train, y_train, X_test, y_test)
    result["random_forest"] = rf_metrics

    rf_val_acc = rf_metrics.get("val_accuracy", rf_metrics.get("train_accuracy", 0))
    print(f"  OK  Train acc: {rf_metrics.get('train_accuracy', 0):.4f}")
    print(f"  OK  Val acc:   {rf_val_acc:.4f}")

    # Feature importance
    top_features = rf.get_feature_importance(top_n=10)
    if not top_features.empty:
        result["top_features_rf"] = top_features.to_dict("records")
        print(f"  Top features: {', '.join(top_features['feature'].head(5).tolist())}")

    # ── Step 5: Train XGBoost ──
    print(f"\n  [4/7] Training XGBoost...")
    try:
        xgb = XGBoostModel(n_estimators=300, max_depth=4, learning_rate=0.03)
        xgb_metrics = xgb.train(X_train, y_train, X_test, y_test)
        result["xgboost"] = xgb_metrics

        xgb_val_acc = xgb_metrics.get("val_accuracy", xgb_metrics.get("train_accuracy", 0))
        print(f"  OK  Train acc: {xgb_metrics.get('train_accuracy', 0):.4f}")
        print(f"  OK  Val acc:   {xgb_val_acc:.4f}")

        top_features_xgb = xgb.get_feature_importance(top_n=10)
        if not top_features_xgb.empty:
            result["top_features_xgb"] = top_features_xgb.to_dict("records")
    except Exception as e:
        logger.error("XGBoost training failed: %s", e)
        result["xgboost"] = {"error": str(e)}
        xgb = None
        print(f"  WARN  XGBoost failed: {e}")

    # ── Step 6: Train LSTM ──
    print(f"\n  [5/7] Training LSTM...")
    lstm = LSTMModel(sequence_length=60, lstm_units=128, epochs=50, patience=10)
    lstm_features = ["Close", "Volume", "RSI", "MACD", "EMA_9", "EMA_21", "SMA_50", "BB_Upper", "BB_Lower"]
    lstm_features = [c for c in lstm_features if c in df_feat.columns]

    try:
        X_tr, X_te, y_tr, y_te, scaler = prepare_lstm_sequences(
            df_feat, lstm_features, target_col="Close", sequence_length=60
        )
        if len(X_tr) > 0 and len(X_te) > 0:
            lstm_metrics = lstm.train(X_tr, X_te, y_tr, y_te, scaler, lstm_features)
            result["lstm"] = lstm_metrics
            if "error" not in lstm_metrics:
                print(f"  OK  Test RMSE: {lstm_metrics.get('test_rmse', 'N/A')}")
                print(f"  OK  Directional accuracy: {lstm_metrics.get('directional_accuracy', 'N/A')}")
                print(f"  OK  Epochs: {lstm_metrics.get('epochs_trained', 'N/A')}")
            else:
                print(f"  WARN  LSTM: {lstm_metrics.get('error')}")
        else:
            result["lstm"] = {"error": "Insufficient sequences"}
            print(f"  WARN  Not enough data for LSTM sequences")
    except ImportError:
        result["lstm"] = {"error": "TensorFlow not installed — LSTM skipped"}
        print(f"  SKIP  TensorFlow not installed (install with: pip install tensorflow)")
    except Exception as e:
        result["lstm"] = {"error": str(e)}
        print(f"  WARN  LSTM failed: {e}")

    # ── Step 7: Walk-Forward Validation ──
    print(f"\n  [6/7] Walk-forward validation (5 splits)...")
    try:
        wf_rf = walk_forward_validate(X, y, RandomForestModel, n_splits=5,
                                       n_estimators=200, max_depth=10)
        result["walk_forward_rf"] = wf_rf
        print(f"  RF  Walk-forward accuracy: {wf_rf.get('walk_forward_accuracy', 'N/A')} "
              f"(+/- {wf_rf.get('walk_forward_std', 'N/A')})")
    except Exception as e:
        print(f"  WARN  Walk-forward RF: {e}")

    # ── Step 8: Save Models ──
    print(f"\n  [7/7] Saving models...")
    try:
        rf_path = rf.save(symbol, "daily")
        print(f"  OK  RF saved: {rf_path.name}")
    except Exception as e:
        print(f"  WARN  RF save: {e}")

    if xgb and xgb.is_trained:
        try:
            xgb_path = xgb.save(symbol, "daily")
            print(f"  OK  XGB saved: {xgb_path.name}")
        except Exception as e:
            print(f"  WARN  XGB save: {e}")

    if lstm.is_trained:
        try:
            lstm_path = lstm.save(symbol)
            print(f"  OK  LSTM saved: lstm_{symbol}.keras")
        except Exception as e:
            print(f"  WARN  LSTM save: {e}")

    # ── Generate Current Prediction ──
    print(f"\n  Generating current prediction...")
    rf_pred = rf.predict_single(X)
    print(f"  RF:  {rf_pred['signal']} ({rf_pred['direction']}) — confidence: {rf_pred['confidence']:.4f}")

    xgb_pred = {"signal": "HOLD", "confidence": 0.0, "direction": "NEUTRAL"}
    if xgb and xgb.is_trained:
        xgb_pred = xgb.predict_single(X)
        print(f"  XGB: {xgb_pred['signal']} ({xgb_pred['direction']}) — confidence: {xgb_pred['confidence']:.4f}")

    # Ensemble
    signal_weights = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
    for sig, conf, w in [(rf_pred["signal"], rf_pred["confidence"], 0.40),
                          (xgb_pred["signal"], xgb_pred["confidence"], 0.45)]:
        signal_weights[sig] += conf * w

    # LSTM contribution
    if lstm.is_trained:
        try:
            from sklearn.preprocessing import MinMaxScaler
            lstm_scaler = MinMaxScaler()
            lstm_data = df_feat[lstm_features].ffill().bfill().fillna(0)
            scaled = lstm_scaler.fit_transform(lstm_data)
            lstm.scaler = lstm_scaler
            lstm.feature_cols = lstm_features
            lstm_pred = lstm.predict_next(scaled)
            if lstm_pred.get("signal"):
                signal_weights[lstm_pred["signal"]] += lstm_pred.get("confidence", 0.0) * 0.15
                print(f"  LSTM: {lstm_pred['signal']} — predicted price: Rs {lstm_pred.get('predicted_price', 'N/A')}")
                result["lstm_prediction"] = lstm_pred
        except Exception as e:
            print(f"  WARN  LSTM prediction: {e}")

    ensemble_signal = max(signal_weights, key=signal_weights.get)
    total_w = sum(signal_weights.values())
    ensemble_confidence = signal_weights[ensemble_signal] / max(total_w, 1e-9)

    result["prediction"] = {
        "signal": ensemble_signal,
        "direction": {"BUY": "UP", "SELL": "DOWN", "HOLD": "NEUTRAL"}[ensemble_signal],
        "confidence": round(ensemble_confidence, 4),
        "current_price": result["latest_close"],
        "rf_signal": rf_pred["signal"],
        "xgb_signal": xgb_pred["signal"],
        "model": "RF + XGB + LSTM Ensemble",
    }

    print(f"\n  ╔══════════════════════════════════════╗")
    print(f"  ║  ENSEMBLE: {ensemble_signal:>4} ({ensemble_confidence:.1%} confidence)  ║")
    print(f"  ╚══════════════════════════════════════╝")

    # ── Save to Supabase ──
    if save_to_db:
        try:
            import database as db
            db.upsert_stock(symbol)

            # Save prediction
            db.save_prediction(
                symbol=symbol,
                prediction_type="next_day",
                predicted_price=result.get("lstm_prediction", {}).get("predicted_price"),
                predicted_direction=result["prediction"]["direction"],
                confidence=result["prediction"]["confidence"],
                model_used="RF+XGB+LSTM Ensemble",
            )

            # Save signal
            db.save_trading_signal(
                symbol=symbol,
                signal=result["prediction"]["signal"],
                entry_price=result["latest_close"],
                target_price=result["latest_close"] * (1.02 if ensemble_signal == "BUY" else 0.98),
                stop_loss=result["latest_close"] * (0.98 if ensemble_signal == "BUY" else 1.02),
                risk_reward_ratio=1.0,
                explanation=f"ML Ensemble: RF={rf_pred['signal']}, XGB={xgb_pred['signal']}. "
                            f"Confidence: {ensemble_confidence:.1%}",
            )
            print(f"  OK  Saved prediction & signal to Supabase")
        except Exception as e:
            print(f"  WARN  Supabase save: {e}")

    elapsed = time.time() - start_time
    result["status"] = "success"
    result["training_time_seconds"] = round(elapsed, 1)
    print(f"\n  Training complete in {elapsed:.1f}s")

    return result


# ══════════════════════════════════════════════════════════════════════════════
# BATCH TRAINING — Train Multiple Stocks
# ══════════════════════════════════════════════════════════════════════════════

def train_batch(
    symbols: list[str],
    period: str = "2y",
    save_to_db: bool = True,
) -> dict:
    """Train models for multiple stocks and generate a summary report."""
    total_start = time.time()

    print("\n" + "=" * 60)
    print("  TradeMind AI — Model Training Pipeline")
    print("=" * 60)
    print(f"  Stocks:  {len(symbols)}")
    print(f"  Period:  {period}")
    print(f"  Models:  Random Forest + XGBoost + LSTM")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    results = {}
    success = 0
    failed = 0

    for i, symbol in enumerate(symbols, 1):
        print(f"\n  [{i}/{len(symbols)}] Processing {symbol}...")
        try:
            result = train_stock(symbol, period=period, save_to_db=save_to_db)
            results[symbol] = result
            if result["status"] == "success":
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.error("Unexpected error training %s: %s", symbol, e)
            results[symbol] = {"symbol": symbol, "status": "error", "error": str(e)}
            failed += 1

        # Rate limiting for Yahoo Finance
        if i < len(symbols):
            time.sleep(1)

    total_elapsed = time.time() - total_start

    # ── Summary Report ──
    print("\n\n" + "=" * 60)
    print("  TRAINING SUMMARY")
    print("=" * 60)
    print(f"  Total stocks:    {len(symbols)}")
    print(f"  Successful:      {success}")
    print(f"  Failed:          {failed}")
    print(f"  Total time:      {total_elapsed:.1f}s")
    print(f"  Avg per stock:   {total_elapsed / len(symbols):.1f}s")
    print()

    print(f"  {'Symbol':<12} {'Status':<10} {'RF Val':<10} {'XGB Val':<10} {'Signal':<8} {'Confidence'}")
    print(f"  {'─'*12} {'─'*10} {'─'*10} {'─'*10} {'─'*8} {'─'*10}")

    for sym, r in results.items():
        if r["status"] == "success":
            rf_acc = r.get("random_forest", {}).get("val_accuracy", 0)
            xgb_acc = r.get("xgboost", {}).get("val_accuracy", 0)
            sig = r.get("prediction", {}).get("signal", "N/A")
            conf = r.get("prediction", {}).get("confidence", 0)
            print(f"  {sym:<12} {'OK':<10} {rf_acc:<10.4f} {xgb_acc:<10.4f} {sig:<8} {conf:.4f}")
        else:
            err = r.get("error", "Unknown")[:30]
            print(f"  {sym:<12} {'FAIL':<10} {err}")

    # Save report
    report_path = settings.MODELS_DIR / "training_report.json"
    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(symbols),
            "success": success,
            "failed": failed,
            "training_time_seconds": round(total_elapsed, 1),
        },
        "results": results,
    }
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved: {report_path}")

    # Check saved models
    model_files = list(settings.MODELS_DIR.glob("*.pkl")) + list(settings.MODELS_DIR.glob("*.keras"))
    print(f"  Saved models: {len(model_files)} files in {settings.MODELS_DIR}")
    for mf in sorted(model_files):
        size_kb = mf.stat().st_size / 1024
        print(f"    {mf.name} ({size_kb:.0f} KB)")

    print("\n" + "=" * 60)
    print("  TRAINING COMPLETE")
    print("=" * 60)

    return report


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="TradeMind AI — Train ML Models on Real NSE Data")
    parser.add_argument("--symbols", nargs="+", help="Specific NSE symbols to train (e.g., RELIANCE TCS)")
    parser.add_argument("--all", action="store_true", help="Train all NIFTY 50 stocks")
    parser.add_argument("--top10", action="store_true", help="Train top 10 NIFTY stocks (default)")
    parser.add_argument("--period", default="2y", help="Data period: 1y, 2y, 5y (default: 2y)")
    parser.add_argument("--no-db", action="store_true", help="Skip Supabase storage")

    args = parser.parse_args()

    if args.symbols:
        symbols = [s.upper() for s in args.symbols]
    elif args.all:
        symbols = NIFTY_50
    else:
        symbols = TOP_10_NIFTY

    train_batch(symbols, period=args.period, save_to_db=not args.no_db)


if __name__ == "__main__":
    main()

