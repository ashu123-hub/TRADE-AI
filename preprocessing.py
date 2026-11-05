"""
TradeMind AI - Data Preprocessing Module
Cleans, normalises, and engineers features for ML models.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, StandardScaler

logger = logging.getLogger(__name__)


def add_time_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add calendar-based features."""
    df = df.copy()
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index, utc=True)
        except Exception:
            return df

    df["day_of_week"] = df.index.dayofweek
    df["month"] = df.index.month
    df["quarter"] = df.index.quarter
    df["is_month_end"] = df.index.is_month_end.astype(int)
    return df


def add_price_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add return and candle body features."""
    df = df.copy()
    df["returns"] = df["Close"].pct_change()
    df["log_returns"] = np.log(df["Close"] / df["Close"].shift(1))
    df["hl_range"] = (df["High"] - df["Low"]) / df["Close"]
    df["body_size"] = abs(df["Close"] - df["Open"]) / df["Open"]
    df["upper_shadow"] = (df["High"] - df[["Open", "Close"]].max(axis=1)) / df["Close"]
    df["lower_shadow"] = (df[["Open", "Close"]].min(axis=1) - df["Low"]) / df["Close"]
    df["gap"] = (df["Open"] - df["Close"].shift(1)) / df["Close"].shift(1)
    df["volume_ma10"] = df["Volume"].rolling(10).mean()
    df["volume_ratio"] = df["Volume"] / (df["volume_ma10"] + 1e-9)
    return df


def add_lag_features(df: pd.DataFrame, lags: list[int] = [1, 2, 3, 5, 10]) -> pd.DataFrame:
    """Add lagged close and return features."""
    df = df.copy()
    for lag in lags:
        df[f"close_lag_{lag}"] = df["Close"].shift(lag)
        df[f"return_lag_{lag}"] = df["returns"].shift(lag) if "returns" in df.columns else df["Close"].pct_change().shift(lag)
    return df


def create_target(df: pd.DataFrame, forward_periods: int = 1, threshold: float = 0.005) -> pd.DataFrame:
    """
    Create classification target:
    1 = price rises > threshold after `forward_periods` bars
    -1 = price falls > threshold
    0 = neutral
    """
    df = df.copy()
    df["future_return"] = df["Close"].shift(-forward_periods) / df["Close"] - 1
    df["target"] = 0
    df.loc[df["future_return"] > threshold, "target"] = 1
    df.loc[df["future_return"] < -threshold, "target"] = -1
    return df


def prepare_features(df: pd.DataFrame, target_col: str = "target") -> tuple[pd.DataFrame, pd.Series | None]:
    """
    Drop NaN rows, separate features and target.
    Returns (X, y). If target_col is not in df, y is None.
    """
    df = df.copy()
    df = df.replace([np.inf, -np.inf], np.nan)
    
    # Drop columns that have too many NaNs (e.g., SMA_200 when sample length < 200)
    min_valid_samples = max(int(len(df) * 0.3), 10)
    valid_cols = [c for c in df.columns if df[c].notna().sum() >= min_valid_samples]
    df = df[valid_cols]
    
    df = df.dropna()

    exclude = {target_col, "future_return"}
    # Drop non-numeric columns
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    feature_cols = [c for c in numeric_cols if c not in exclude]

    X = df[feature_cols]
    y = df[target_col] if target_col in df.columns else None
    return X, y


def train_test_split_time(
    X: pd.DataFrame,
    y: pd.Series,
    test_size: float = 0.2,
) -> tuple:
    """
    Chronological train/test split (no random shuffle — prevents look-ahead bias).
    """
    n = len(X)
    split = int(n * (1 - test_size))
    return X.iloc[:split], X.iloc[split:], y.iloc[:split], y.iloc[split:]


def scale_features(
    X_train: pd.DataFrame,
    X_test: pd.DataFrame,
    method: str = "standard",
) -> tuple[pd.DataFrame, pd.DataFrame, object]:
    """Scale features. Returns (X_train_scaled, X_test_scaled, scaler)."""
    if method == "minmax":
        scaler = MinMaxScaler()
    else:
        scaler = StandardScaler()

    X_train_sc = pd.DataFrame(
        scaler.fit_transform(X_train), columns=X_train.columns, index=X_train.index
    )
    X_test_sc = pd.DataFrame(
        scaler.transform(X_test), columns=X_test.columns, index=X_test.index
    )
    return X_train_sc, X_test_sc, scaler


def prepare_lstm_sequences(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str = "Close",
    sequence_length: int = 60,
    test_size: float = 0.2,
) -> tuple:
    """
    Prepare 3D sequences for LSTM: (samples, timesteps, features).
    Returns (X_train, X_test, y_train, y_test, scaler).
    """
    data = df[feature_cols].copy()
    data = data.replace([np.inf, -np.inf], np.nan).ffill().bfill().dropna()

    scaler = MinMaxScaler()
    scaled = scaler.fit_transform(data)

    target_idx = feature_cols.index(target_col) if target_col in feature_cols else 0

    X, y = [], []
    for i in range(sequence_length, len(scaled)):
        X.append(scaled[i - sequence_length:i])
        y.append(scaled[i, target_idx])

    X, y = np.array(X), np.array(y)

    split = int(len(X) * (1 - test_size))
    return X[:split], X[split:], y[:split], y[split:], scaler
