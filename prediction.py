"""
TradeMind AI - Unified Prediction Engine
Orchestrates intraday (RF/XGB) and next-day (RF/XGB/LSTM) predictions.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

from config import settings
from data_collection import download_stock_data, download_intraday_data
from indicators import add_all_indicators, get_latest_indicators
from preprocessing import (
    add_time_features,
    add_price_features,
    add_advanced_features,
    add_lag_features,
    create_target,
    prepare_features,
    train_test_split_time,
    prepare_lstm_sequences,
)
from models.random_forest import RandomForestModel
from models.xgboost_model import XGBoostModel
from models.lstm_model import LSTMModel

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# INTRADAY PREDICTION (5m / 15m intervals)
# ═══════════════════════════════════════════════════════════════════════════════

class IntradayPredictor:
    """
    Trains and runs intraday predictions using Random Forest and XGBoost.
    Uses chronological splits to prevent data leakage.
    """

    def __init__(self, interval: str = "5m"):
        self.interval = interval
        self.rf = RandomForestModel(n_estimators=150, max_depth=8)
        self.xgb = XGBoostModel(n_estimators=200, max_depth=5)
        self.feature_names: list[str] = []
        self._is_trained = False

    def prepare(self, symbol: str) -> pd.DataFrame | None:
        """Download and prepare intraday data."""
        df = download_intraday_data(symbol, interval=self.interval)
        if df.empty or len(df) < settings.MIN_DATA_ROWS // 4:
            logger.warning("Insufficient intraday data for %s (%s)", symbol, self.interval)
            return None

        df = add_all_indicators(df)
        df = add_time_features(df)
        df = add_price_features(df)
        df = add_lag_features(df, lags=[1, 2, 3])
        df = create_target(df, forward_periods=1, threshold=0.001)  # 0.1% move
        return df

    def train(self, symbol: str) -> dict:
        """Train both RF and XGB on intraday data."""
        df = self.prepare(symbol)
        if df is None:
            return {"error": "Could not prepare intraday data"}

        X, y = prepare_features(df)
        if y is None or len(X) < 50:
            return {"error": "Not enough samples"}

        X_train, X_test, y_train, y_test = train_test_split_time(X, y, test_size=0.2)
        self.feature_names = list(X.columns)

        rf_metrics = self.rf.train(X_train, y_train, X_test, y_test)
        xgb_metrics = self.xgb.train(X_train, y_train, X_test, y_test)
        self._is_trained = True

        return {
            "random_forest": rf_metrics,
            "xgboost": xgb_metrics,
            "samples": len(X),
            "interval": self.interval,
        }

    def predict(self, symbol: str, force_retrain: bool = False) -> dict:
        """Get current intraday prediction for a symbol."""
        if force_retrain or not self._is_trained:
            self.train(symbol)

        df = self.prepare(symbol)
        if df is None:
            return self._empty_result(symbol)

        X, _ = prepare_features(df)
        if X.empty:
            return self._empty_result(symbol)

        rf_result = self.rf.predict_single(X)
        xgb_result = self.xgb.predict_single(X)

        # Ensemble: majority vote weighted by confidence
        votes = [rf_result["signal"], xgb_result["signal"]]
        rf_conf = rf_result["confidence"]
        xgb_conf = xgb_result["confidence"]
        total_conf = rf_conf + xgb_conf

        signal_weights: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        for sig, conf in [(rf_result["signal"], rf_conf), (xgb_result["signal"], xgb_conf)]:
            signal_weights[sig] += conf
        ensemble_signal = max(signal_weights, key=signal_weights.get)
        ensemble_confidence = signal_weights[ensemble_signal] / (total_conf + 1e-9)

        current_price = float(df["Close"].iloc[-1])
        indicators = get_latest_indicators(df)

        return {
            "symbol": symbol,
            "interval": self.interval,
            "signal": ensemble_signal,
            "direction": {"BUY": "UP", "SELL": "DOWN", "HOLD": "NEUTRAL"}[ensemble_signal],
            "confidence": round(ensemble_confidence, 4),
            "current_price": current_price,
            "rf_signal": rf_result,
            "xgb_signal": xgb_result,
            "indicators": indicators,
            "model": "RF + XGB Ensemble",
        }

    @staticmethod
    def _empty_result(symbol: str) -> dict:
        return {"symbol": symbol, "signal": "HOLD", "direction": "NEUTRAL", "confidence": 0.0, "error": "Insufficient data"}


# ═══════════════════════════════════════════════════════════════════════════════
# NEXT-DAY PREDICTION (daily intervals)
# ═══════════════════════════════════════════════════════════════════════════════

class NextDayPredictor:
    """
    Trains RF, XGB, and LSTM for next-day predictions on daily data.
    """

    def __init__(self):
        self.rf = RandomForestModel(n_estimators=300, max_depth=12)
        self.xgb = XGBoostModel(n_estimators=400, max_depth=8)
        self.lstm = LSTMModel(sequence_length=60, lstm_units=128, epochs=50)
        self._is_trained = False
        self._last_symbol: str = ""

    def prepare(self, symbol: str, period: str = "2y") -> pd.DataFrame | None:
        """Download and engineer features for next-day prediction."""
        df = download_stock_data(symbol, interval="1d", period=period)
        if df.empty or len(df) < settings.MIN_DATA_ROWS:
            logger.warning("Insufficient daily data for %s", symbol)
            return None

        df = add_all_indicators(df)
        df = add_time_features(df)
        df = add_price_features(df)
        df = add_lag_features(df, lags=[1, 2, 3, 5])
        df = add_advanced_features(df)
        df = create_target(df, forward_periods=1, threshold=0.003)
        return df

    def train(self, symbol: str) -> dict:
        """Train all three models on daily data."""
        df = self.prepare(symbol)
        if df is None:
            return {"error": "Could not prepare daily data"}

        X, y = prepare_features(df)
        if y is None or len(X) < settings.MIN_DATA_ROWS:
            return {"error": "Not enough samples for daily prediction"}

        X_train, X_test, y_train, y_test = train_test_split_time(X, y, test_size=0.2)

        rf_metrics = self.rf.train(X_train, y_train, X_test, y_test)
        xgb_metrics = self.xgb.train(X_train, y_train, X_test, y_test)

        # LSTM — uses only Close + indicator columns
        lstm_features = ["Close", "Volume", "RSI", "MACD", "EMA_9", "EMA_21", "SMA_50", "BB_Upper", "BB_Lower"]
        lstm_features = [c for c in lstm_features if c in df.columns]
        try:
            X_tr, X_te, y_tr, y_te, scaler = prepare_lstm_sequences(
                df, lstm_features, target_col="Close", sequence_length=60
            )
            lstm_metrics = self.lstm.train(X_tr, X_te, y_tr, y_te, scaler, lstm_features)
        except Exception as exc:
            logger.error("LSTM training failed: %s", exc)
            lstm_metrics = {"error": str(exc)}

        # Save models
        try:
            self.rf.save(symbol, "daily")
            self.xgb.save(symbol, "daily")
            if self.lstm.is_trained:
                self.lstm.save(symbol)
        except Exception as exc:
            logger.warning("Model save error: %s", exc)

        self._is_trained = True
        self._last_symbol = symbol

        return {
            "random_forest": rf_metrics,
            "xgboost": xgb_metrics,
            "lstm": lstm_metrics,
            "samples": len(X),
        }

    def predict(self, symbol: str, force_retrain: bool = False) -> dict:
        """Get next-day prediction for a symbol."""
        loaded = False
        if not force_retrain:
            if symbol == self._last_symbol and self._is_trained:
                loaded = True
            else:
                loaded = self._try_load_saved(symbol)

        if force_retrain or not loaded:
            train_res = self.train(symbol)
            if "error" in train_res:
                logger.warning("Training error for %s: %s", symbol, train_res.get("error"))

        df = self.prepare(symbol)
        if df is None:
            return self._empty_result(symbol)

        X, _ = prepare_features(df)
        if X.empty:
            return self._empty_result(symbol)

        rf_result = self.rf.predict_single(X)
        xgb_result = self.xgb.predict_single(X)

        # LSTM prediction
        lstm_features = ["Close", "Volume", "RSI", "MACD", "EMA_9", "EMA_21", "SMA_50", "BB_Upper", "BB_Lower"]
        lstm_features = [c for c in lstm_features if c in df.columns]
        lstm_result = {}
        if self.lstm.is_trained:
            try:
                from sklearn.preprocessing import MinMaxScaler
                scaler = MinMaxScaler()
                scaled = scaler.fit_transform(df[lstm_features].ffill().bfill().fillna(0))
                self.lstm.scaler = scaler
                self.lstm.feature_cols = lstm_features
                lstm_result = self.lstm.predict_next(scaled)
            except Exception as exc:
                logger.warning("LSTM predict error: %s", exc)

        # Weighted ensemble signal
        signal_weights: dict[str, float] = {"BUY": 0.0, "SELL": 0.0, "HOLD": 0.0}
        model_weights = [
            (rf_result.get("signal", "HOLD"), rf_result.get("confidence", 0.0), 0.45),
            (xgb_result.get("signal", "HOLD"), xgb_result.get("confidence", 0.0), 0.45),
        ]
        if lstm_result.get("signal"):
            model_weights.append((lstm_result["signal"], lstm_result.get("confidence", 0.0), 0.10))

        for sig, conf, weight in model_weights:
            signal_weights[sig] = signal_weights.get(sig, 0.0) + conf * weight

        ensemble_signal = max(signal_weights, key=signal_weights.get)
        ensemble_confidence = signal_weights[ensemble_signal] / max(sum(signal_weights.values()), 1e-9)

        current_price = float(df["Close"].iloc[-1])
        indicators = get_latest_indicators(df)

        return {
            "symbol": symbol,
            "signal": ensemble_signal,
            "direction": {"BUY": "UP", "SELL": "DOWN", "HOLD": "NEUTRAL"}[ensemble_signal],
            "confidence": round(ensemble_confidence, 4),
            "current_price": current_price,
            "predicted_price": lstm_result.get("predicted_price"),
            "predicted_change_pct": lstm_result.get("change_pct"),
            "rf_signal": rf_result,
            "xgb_signal": xgb_result,
            "lstm_prediction": lstm_result,
            "indicators": indicators,
            "model": "RF + XGB + LSTM Ensemble",
        }

    def _try_load_saved(self, symbol: str) -> bool:
        """Try loading previously trained models from disk."""
        try:
            self.rf = RandomForestModel.load(symbol, "daily")
            self.xgb = XGBoostModel.load(symbol, "daily")
            if self.lstm.model_exists(symbol):
                try:
                    self.lstm = LSTMModel.load(symbol)
                except Exception:
                    pass
            self._is_trained = True
            self._last_symbol = symbol
            logger.info("Loaded saved models for %s", symbol)
            return True
        except FileNotFoundError:
            return False
        except Exception as exc:
            logger.warning("Could not load saved models for %s: %s", symbol, exc)
            return False

    @staticmethod
    def _empty_result(symbol: str) -> dict:
        return {"symbol": symbol, "signal": "HOLD", "direction": "NEUTRAL", "confidence": 0.0, "error": "Insufficient data"}


# ─── Convenience Singletons ──────────────────────────────────────────────────
_intraday_cache: dict[str, IntradayPredictor] = {}
_next_day_predictor = NextDayPredictor()


def get_intraday_predictor(interval: str = "5m") -> IntradayPredictor:
    if interval not in _intraday_cache:
        _intraday_cache[interval] = IntradayPredictor(interval=interval)
    return _intraday_cache[interval]


def get_next_day_predictor() -> NextDayPredictor:
    return _next_day_predictor
