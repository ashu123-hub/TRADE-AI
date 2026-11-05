"""
TradeMind AI - LSTM Model
Long Short-Term Memory neural network for next-day price prediction.
Uses TensorFlow/Keras. Gracefully degrades if TF is not available.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings

logger = logging.getLogger(__name__)
MODEL_DIR = settings.MODELS_DIR


class LSTMModel:
    """
    LSTM for next-day stock price regression.
    Predicts the scaled close price, then inverse-transforms to actual price.
    """

    def __init__(
        self,
        sequence_length: int = 60,
        lstm_units: int = 128,
        dropout_rate: float = 0.2,
        epochs: int = 50,
        batch_size: int = 32,
        patience: int = 10,
    ):
        self.sequence_length = sequence_length
        self.lstm_units = lstm_units
        self.dropout_rate = dropout_rate
        self.epochs = epochs
        self.batch_size = batch_size
        self.patience = patience
        self.model = None
        self.scaler = None
        self.feature_cols: list[str] = []
        self.is_trained = False
        self.training_metrics: dict = {}

    def _build_model(self, n_features: int):
        """Build the LSTM architecture."""
        try:
            import tensorflow as tf
            from tensorflow.keras.models import Sequential
            from tensorflow.keras.layers import LSTM, Dense, Dropout, BatchNormalization
            from tensorflow.keras.optimizers import Adam
            from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau

            tf.random.set_seed(42)
            model = Sequential([
                LSTM(self.lstm_units, return_sequences=True,
                     input_shape=(self.sequence_length, n_features)),
                Dropout(self.dropout_rate),
                BatchNormalization(),
                LSTM(self.lstm_units // 2, return_sequences=False),
                Dropout(self.dropout_rate),
                BatchNormalization(),
                Dense(64, activation="relu"),
                Dropout(self.dropout_rate / 2),
                Dense(1),
            ])
            model.compile(
                optimizer=Adam(learning_rate=0.001),
                loss="huber",
                metrics=["mae"],
            )
            return model
        except ImportError:
            logger.error("TensorFlow not installed. LSTM unavailable.")
            return None

    def train(
        self,
        X_train: np.ndarray,
        X_test: np.ndarray,
        y_train: np.ndarray,
        y_test: np.ndarray,
        scaler,
        feature_cols: list[str],
    ) -> dict:
        """
        Train the LSTM model.
        X arrays must be 3D: (samples, timesteps, features).
        """
        try:
            from tensorflow.keras.callbacks import EarlyStopping, ReduceLROnPlateau
        except ImportError:
            logger.error("TensorFlow not available. Cannot train LSTM.")
            return {"error": "TensorFlow not installed"}

        self.scaler = scaler
        self.feature_cols = feature_cols
        n_features = X_train.shape[2]
        self.model = self._build_model(n_features)
        if self.model is None:
            return {"error": "Could not build model"}

        callbacks = [
            EarlyStopping(monitor="val_loss", patience=self.patience, restore_best_weights=True),
            ReduceLROnPlateau(monitor="val_loss", factor=0.5, patience=5, min_lr=1e-6),
        ]

        logger.info("Training LSTM: %d train, %d test, seq_len=%d, features=%d",
                    len(X_train), len(X_test), self.sequence_length, n_features)

        history = self.model.fit(
            X_train, y_train,
            validation_data=(X_test, y_test),
            epochs=self.epochs,
            batch_size=self.batch_size,
            callbacks=callbacks,
            verbose=0,
        )

        self.is_trained = True

        # Evaluate
        train_pred_sc = self.model.predict(X_train, verbose=0).flatten()
        test_pred_sc = self.model.predict(X_test, verbose=0).flatten()

        # Inverse transform (only the close price column)
        def inv_transform(scaled_vals: np.ndarray) -> np.ndarray:
            dummy = np.zeros((len(scaled_vals), len(self.feature_cols)))
            close_idx = self.feature_cols.index("Close") if "Close" in self.feature_cols else 0
            dummy[:, close_idx] = scaled_vals
            return self.scaler.inverse_transform(dummy)[:, close_idx]

        train_pred = inv_transform(train_pred_sc)
        test_pred = inv_transform(test_pred_sc)
        y_train_actual = inv_transform(y_train)
        y_test_actual = inv_transform(y_test)

        train_rmse = float(np.sqrt(np.mean((train_pred - y_train_actual) ** 2)))
        test_rmse = float(np.sqrt(np.mean((test_pred - y_test_actual) ** 2)))
        test_mae = float(np.mean(np.abs(test_pred - y_test_actual)))

        # Directional accuracy
        y_dir = np.diff(y_test_actual) > 0
        p_dir = np.diff(test_pred) > 0
        dir_acc = float(np.mean(y_dir == p_dir)) if len(y_dir) > 0 else 0.0

        self.training_metrics = {
            "train_rmse": train_rmse,
            "test_rmse": test_rmse,
            "test_mae": test_mae,
            "directional_accuracy": dir_acc,
            "epochs_trained": len(history.history["loss"]),
        }
        logger.info("LSTM trained | Test RMSE: %.4f | Dir Acc: %.3f", test_rmse, dir_acc)
        return self.training_metrics

    def predict_next(self, recent_data: np.ndarray) -> dict:
        """
        Predict next timestep price.
        recent_data: 2D array (timesteps, features) with the last `sequence_length` rows.
        """
        if not self.is_trained or self.model is None:
            return {"predicted_price": None, "direction": "NEUTRAL", "confidence": 0.0}

        try:
            seq = recent_data[-self.sequence_length:]
            if len(seq) < self.sequence_length:
                return {"predicted_price": None, "direction": "NEUTRAL", "confidence": 0.0}

            X = np.expand_dims(seq, axis=0)
            pred_scaled = self.model.predict(X, verbose=0)[0, 0]

            # Inverse transform
            dummy = np.zeros((1, len(self.feature_cols)))
            close_idx = self.feature_cols.index("Close") if "Close" in self.feature_cols else 0
            dummy[0, close_idx] = pred_scaled
            pred_price = float(self.scaler.inverse_transform(dummy)[0, close_idx])

            # Current close (last row, close column)
            current_scaled = seq[-1, close_idx]
            dummy2 = np.zeros((1, len(self.feature_cols)))
            dummy2[0, close_idx] = current_scaled
            current_price = float(self.scaler.inverse_transform(dummy2)[0, close_idx])

            change_pct = (pred_price - current_price) / (current_price + 1e-9) * 100
            direction = "UP" if pred_price > current_price else "DOWN"

            return {
                "predicted_price": round(pred_price, 2),
                "current_price": round(current_price, 2),
                "change_pct": round(change_pct, 2),
                "direction": direction,
                "signal": "BUY" if direction == "UP" else "SELL",
                "confidence": round(min(abs(change_pct) / 5, 1.0), 4),  # heuristic
                "model": "LSTM",
            }
        except Exception as exc:
            logger.error("LSTM prediction error: %s", exc)
            return {"predicted_price": None, "direction": "NEUTRAL", "confidence": 0.0}

    def save(self, symbol: str) -> Path:
        """Save model weights and scaler."""
        model_path = MODEL_DIR / f"lstm_{symbol}.keras"
        scaler_path = MODEL_DIR / f"lstm_{symbol}_scaler.pkl"
        meta_path = MODEL_DIR / f"lstm_{symbol}_meta.pkl"

        if self.model:
            self.model.save(model_path)
        with open(scaler_path, "wb") as f:
            pickle.dump(self.scaler, f)
        with open(meta_path, "wb") as f:
            pickle.dump({
                "feature_cols": self.feature_cols,
                "sequence_length": self.sequence_length,
                "lstm_units": self.lstm_units,
                "metrics": self.training_metrics,
            }, f)
        logger.info("LSTM model saved for %s", symbol)
        return model_path

    @classmethod
    def load(cls, symbol: str) -> "LSTMModel":
        model_path = MODEL_DIR / f"lstm_{symbol}.keras"
        scaler_path = MODEL_DIR / f"lstm_{symbol}_scaler.pkl"
        meta_path = MODEL_DIR / f"lstm_{symbol}_meta.pkl"

        for p in [model_path, scaler_path, meta_path]:
            if not p.exists():
                raise FileNotFoundError(f"LSTM file not found: {p}")

        try:
            from tensorflow.keras.models import load_model
        except ImportError:
            raise RuntimeError("TensorFlow not installed.")

        with open(scaler_path, "rb") as f:
            scaler = pickle.load(f)
        with open(meta_path, "rb") as f:
            meta = pickle.load(f)

        instance = cls(
            sequence_length=meta["sequence_length"],
            lstm_units=meta["lstm_units"],
        )
        instance.model = load_model(model_path)
        instance.scaler = scaler
        instance.feature_cols = meta["feature_cols"]
        instance.training_metrics = meta.get("metrics", {})
        instance.is_trained = True
        return instance

    def model_exists(self, symbol: str) -> bool:
        return (MODEL_DIR / f"lstm_{symbol}.keras").exists()
