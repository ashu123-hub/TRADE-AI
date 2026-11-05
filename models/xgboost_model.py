"""
TradeMind AI - XGBoost Model
Gradient boosted trees for stock direction and magnitude prediction.
"""

from __future__ import annotations

import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import LabelEncoder

from config import settings

logger = logging.getLogger(__name__)
MODEL_DIR = settings.MODELS_DIR


class XGBoostModel:
    """
    XGBoost classifier for stock direction prediction.
    Outputs: 1 (UP), -1 (DOWN), 0 (NEUTRAL).
    """

    def __init__(
        self,
        n_estimators: int = 300,
        max_depth: int = 6,
        learning_rate: float = 0.05,
        subsample: float = 0.8,
        colsample_bytree: float = 0.8,
        min_child_weight: int = 5,
        gamma: float = 0.1,
        random_state: int = 42,
        n_jobs: int = -1,
    ):
        self.params = dict(
            n_estimators=n_estimators,
            max_depth=max_depth,
            learning_rate=learning_rate,
            subsample=subsample,
            colsample_bytree=colsample_bytree,
            min_child_weight=min_child_weight,
            gamma=gamma,
            random_state=random_state,
            n_jobs=n_jobs,
            use_label_encoder=False,
            eval_metric="mlogloss",
        )
        self.model = None
        self.le = LabelEncoder()
        self.feature_names: list[str] = []
        self.is_trained = False
        self.training_metrics: dict = {}
        self._classes = [-1, 0, 1]

    def _init_model(self):
        try:
            from xgboost import XGBClassifier
            self.model = XGBClassifier(**{k: v for k, v in self.params.items() if k != "use_label_encoder"})
        except ImportError:
            logger.error("xgboost not installed. Run: pip install xgboost")
            raise

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame | None = None,
        y_val: pd.Series | None = None,
        early_stopping_rounds: int = 20,
    ) -> dict:
        self._init_model()
        self.feature_names = list(X_train.columns)

        # Encode labels (XGBoost needs 0-indexed classes)
        y_enc = self.le.fit_transform(y_train)
        logger.info("Training XGBoost on %d samples, %d features", len(X_train), len(self.feature_names))

        fit_kwargs: dict = {}
        if X_val is not None and y_val is not None and len(X_val) > 0:
            y_val_enc = self.le.transform(y_val)
            fit_kwargs["eval_set"] = [(X_val, y_val_enc)]
            try:
                fit_kwargs["verbose"] = False
            except Exception:
                pass

        self.model.fit(X_train, y_enc, **fit_kwargs)
        self.is_trained = True

        train_pred = self.le.inverse_transform(self.model.predict(X_train))
        train_acc = accuracy_score(y_train, train_pred)
        metrics = {"train_accuracy": float(train_acc)}

        if X_val is not None and y_val is not None and len(X_val) > 0:
            val_pred = self.le.inverse_transform(self.model.predict(X_val))
            val_acc = accuracy_score(y_val, val_pred)
            metrics["val_accuracy"] = float(val_acc)
            metrics["classification_report"] = classification_report(
                y_val, val_pred, output_dict=True
            )
            logger.info("XGB Train acc: %.3f | Val acc: %.3f", train_acc, val_acc)

        self.training_metrics = metrics
        return metrics

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained.")
        X_aligned = self._align_features(X)
        raw = self.model.predict(X_aligned)
        return self.le.inverse_transform(raw)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        if not self.is_trained:
            raise RuntimeError("Model not trained.")
        return self.model.predict_proba(self._align_features(X))

    def predict_single(self, X: pd.DataFrame) -> dict:
        if not self.is_trained:
            return {"direction": "NEUTRAL", "confidence": 0.0, "signal": "HOLD"}

        X_last = X.iloc[[-1]]
        pred = self.predict(X_last)[0]
        proba = self.predict_proba(X_last)[0]
        confidence = float(np.max(proba))

        direction = {1: "UP", -1: "DOWN", 0: "NEUTRAL"}.get(int(pred), "NEUTRAL")
        signal = {"UP": "BUY", "DOWN": "SELL", "NEUTRAL": "HOLD"}[direction]

        classes = self.le.classes_
        prob_dict = {str(c): round(float(p), 4) for c, p in zip(classes, proba)}

        return {
            "direction": direction,
            "signal": signal,
            "confidence": round(confidence, 4),
            "probabilities": prob_dict,
            "model": "XGBoost",
        }

    def get_feature_importance(self, top_n: int = 20) -> pd.DataFrame:
        if not self.is_trained:
            return pd.DataFrame()
        importance = self.model.feature_importances_
        return pd.DataFrame({
            "feature": self.feature_names,
            "importance": importance,
        }).sort_values("importance", ascending=False).head(top_n).reset_index(drop=True)

    def save(self, symbol: str, model_type: str = "daily") -> Path:
        path = MODEL_DIR / f"xgb_{symbol}_{model_type}.pkl"
        with open(path, "wb") as f:
            pickle.dump({
                "model": self.model,
                "le": self.le,
                "features": self.feature_names,
                "metrics": self.training_metrics,
            }, f)
        logger.info("XGBoost model saved: %s", path)
        return path

    @classmethod
    def load(cls, symbol: str, model_type: str = "daily") -> "XGBoostModel":
        path = MODEL_DIR / f"xgb_{symbol}_{model_type}.pkl"
        if not path.exists():
            raise FileNotFoundError(f"No saved XGB model for {symbol} ({model_type})")
        with open(path, "rb") as f:
            data = pickle.load(f)
        instance = cls()
        instance.model = data["model"]
        instance.le = data["le"]
        instance.feature_names = data["features"]
        instance.training_metrics = data.get("metrics", {})
        instance.is_trained = True
        return instance

    def model_exists(self, symbol: str, model_type: str = "daily") -> bool:
        return (MODEL_DIR / f"xgb_{symbol}_{model_type}.pkl").exists()

    def _align_features(self, X: pd.DataFrame) -> pd.DataFrame:
        for col in set(self.feature_names) - set(X.columns):
            X = X.copy()
            X[col] = 0.0
        return X[self.feature_names]
