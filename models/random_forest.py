"""
TradeMind AI - Random Forest Model
Trains and evaluates Random Forest classifiers for stock direction prediction.
Supports intraday and next-day predictions.
"""

from __future__ import annotations

import logging
import os
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import cross_val_score

from config import settings

logger = logging.getLogger(__name__)

MODEL_DIR = settings.MODELS_DIR


class RandomForestModel:
    """
    Random Forest classifier for stock direction prediction.
    Outputs: 1 (UP), -1 (DOWN), 0 (NEUTRAL).
    """

    def __init__(
        self,
        n_estimators: int = 200,
        max_depth: int = 10,
        min_samples_split: int = 10,
        min_samples_leaf: int = 5,
        random_state: int = 42,
        n_jobs: int = -1,
        class_weight: str = "balanced",
    ):
        self.params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_split=min_samples_split,
            min_samples_leaf=min_samples_leaf,
            random_state=random_state,
            n_jobs=n_jobs,
            class_weight=class_weight,
        )
        self.model = RandomForestClassifier(**self.params)
        self.feature_names: list[str] = []
        self.is_trained = False
        self.training_metrics: dict = {}

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
    ) -> dict:
        """
        Train the model. Returns training metrics.
        Uses chronological split — no data leakage.
        """
        self.feature_names = list(X_train.columns)
        logger.info("Training Random Forest on %d samples, %d features", len(X_train), len(self.feature_names))

        self.model.fit(X_train, y_train)
        self.is_trained = True

        train_pred = self.model.predict(X_train)
        train_acc = accuracy_score(y_train, train_pred)
        metrics = {"train_accuracy": train_acc}

        if X_val is not None and y_val is not None and len(X_val) > 0:
            val_pred = self.model.predict(X_val)
            val_acc = accuracy_score(y_val, val_pred)
            metrics["val_accuracy"] = val_acc
            metrics["classification_report"] = classification_report(
                y_val, val_pred, target_names=["DOWN", "NEUTRAL", "UP"], output_dict=True
            )
            logger.info("RF Train acc: %.3f | Val acc: %.3f", train_acc, val_acc)
        else:
            logger.info("RF Train acc: %.3f (no validation set)", train_acc)

        self.training_metrics = metrics
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Return predicted classes."""
        if not self.is_trained:
            raise RuntimeError("Model not trained.")
        X_aligned = self._align_features(X)
        return self.model.predict(X_aligned)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        """Return class probabilities."""
        if not self.is_trained:
            raise RuntimeError("Model not trained.")
        X_aligned = self._align_features(X)
        return self.model.predict_proba(X_aligned)

    def predict_single(self, X: pd.DataFrame) -> dict:
        """
        Predict for a single sample (last row of X).
        Returns direction, confidence and probabilities.
        """
        if not self.is_trained:
            return {"direction": "NEUTRAL", "confidence": 0.0, "signal": "HOLD"}

        X_last = X.iloc[[-1]]
        pred = self.predict(X_last)[0]
        proba = self.predict_proba(X_last)[0]

        classes = self.model.classes_
        prob_dict = {str(c): round(float(p), 4) for c, p in zip(classes, proba)}
        confidence = float(np.max(proba))

        direction = {1: "UP", -1: "DOWN", 0: "NEUTRAL"}.get(int(pred), "NEUTRAL")
        signal = {"UP": "BUY", "DOWN": "SELL", "NEUTRAL": "HOLD"}[direction]

        return {
            "direction": direction,
            "signal": signal,
            "confidence": round(confidence, 4),
            "probabilities": prob_dict,
            "model": "Random Forest",
        }

    def get_feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        """Return top-N feature importances."""
        if not self.is_trained:
            return pd.DataFrame()
        importance = self.model.feature_importances_
        df = pd.DataFrame({
            "feature": self.feature_names,
            "importance": importance,
        }).sort_values("importance", ascending=False)
        return df.head(top_n).reset_index(drop=True)

    def save(self, symbol: str, model_type: str = "daily") -> Path:
        """Persist model to disk."""
        path = MODEL_DIR / f"rf_{symbol}_{model_type}.pkl"
        with open(path, "wb") as f:
            pickle.dump({"model": self.model, "features": self.feature_names, "metrics": self.training_metrics}, f)
        logger.info("Random Forest model saved: %s", path)
        return path

    @classmethod
    def load(cls, symbol: str, model_type: str = "daily") -> "RandomForestModel":
        """Load a saved model from disk."""
        path = MODEL_DIR / f"rf_{symbol}_{model_type}.pkl"
        if not path.exists():
            raise FileNotFoundError(f"No saved RF model for {symbol} ({model_type})")
        with open(path, "rb") as f:
            data = pickle.load(f)
        instance = cls()
        instance.model = data["model"]
        instance.feature_names = data["features"]
        instance.training_metrics = data.get("metrics", {})
        instance.is_trained = True
        return instance

    def model_exists(self, symbol: str, model_type: str = "daily") -> bool:
        path = MODEL_DIR / f"rf_{symbol}_{model_type}.pkl"
        return path.exists()

    def _align_features(self, X: pd.DataFrame) -> pd.DataFrame:
        """Ensure columns match training features."""
        missing = set(self.feature_names) - set(X.columns)
        for col in missing:
            X = X.copy()
            X[col] = 0.0
        return X[self.feature_names]
