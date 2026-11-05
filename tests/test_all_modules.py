"""
TradeMind AI - Full System Integration Test Suite
Tests all modules end-to-end:
1. Config & API Keys
2. Indicators & Formula Math
3. Data Preprocessing & Target Creation
4. Risk Management (Brokerage, Stop Loss, Target, R:R)
5. Machine Learning Models (Random Forest, XGBoost fallback, LSTM fallback)
6. Trading Signal Synthesis
7. Portfolio & Paper Trading
8. Backtesting Simulation Engine
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta

def generate_mock_ohlcv(n_bars: int = 150) -> pd.DataFrame:
    """Generate realistic synthetic OHLCV time series for testing."""
    np.random.seed(42)
    start_date = datetime.now(timezone.utc) - timedelta(days=n_bars)
    dates = [start_date + timedelta(days=i) for i in range(n_bars)]
    
    # Generate random walk price
    base_price = 2500.0
    returns = np.random.normal(0.0005, 0.015, n_bars)
    prices = base_price * np.exp(np.cumsum(returns))
    
    highs = prices * (1 + np.abs(np.random.normal(0, 0.008, n_bars)))
    lows = prices * (1 - np.abs(np.random.normal(0, 0.008, n_bars)))
    opens = lows + np.random.uniform(0.2, 0.8, n_bars) * (highs - lows)
    closes = lows + np.random.uniform(0.2, 0.8, n_bars) * (highs - lows)
    volumes = np.random.randint(100_000, 2_000_000, n_bars)
    
    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": volumes,
    }, index=pd.to_datetime(dates))
    return df

def test_config():
    print("Test 1: Config & Environment Loader...", end=" ")
    from config import settings, api_keys
    assert settings.APP_NAME == "TradeMind AI"
    assert settings.DEFAULT_EXCHANGE == "NSE"
    assert settings.NSE_EXCHANGE_SUFFIX == ".NS"
    print("PASSED")

def test_indicators():
    print("Test 2: Technical Indicators Calculation...", end=" ")
    from indicators import add_all_indicators, get_latest_indicators, identify_support_resistance
    df = generate_mock_ohlcv(120)
    df_ind = add_all_indicators(df)
    
    # Check essential columns exist
    for col in ["RSI", "MACD", "MACD_Signal", "EMA_9", "EMA_21", "SMA_50", "VWAP", "BB_Upper", "BB_Lower", "ATR"]:
        assert col in df_ind.columns, f"Missing indicator column: {col}"
    
    latest = get_latest_indicators(df_ind)
    assert latest.get("RSI") is not None
    assert 0 <= latest["RSI"] <= 100
    
    sr = identify_support_resistance(df_ind)
    assert "support" in sr and "resistance" in sr
    print("PASSED")

def test_preprocessing():
    print("Test 3: Feature Engineering & Preprocessing...", end=" ")
    from indicators import add_all_indicators
    from preprocessing import (
        add_time_features,
        add_price_features,
        add_lag_features,
        create_target,
        prepare_features,
        train_test_split_time,
    )
    df = generate_mock_ohlcv(120)
    df = add_all_indicators(df)
    df = add_time_features(df)
    df = add_price_features(df)
    df = add_lag_features(df, lags=[1, 2, 3])
    df = create_target(df, forward_periods=1, threshold=0.005)
    
    assert "target" in df.columns
    assert "day_of_week" in df.columns
    assert "returns" in df.columns
    assert "close_lag_1" in df.columns
    
    X, y = prepare_features(df)
    assert not X.empty
    assert y is not None
    
    X_train, X_test, y_train, y_test = train_test_split_time(X, y, test_size=0.2)
    assert len(X_train) + len(X_test) == len(X)
    # Verify strict chronological ordering (no overlap)
    assert X_train.index[-1] < X_test.index[0]
    print("PASSED")

def test_risk_management():
    print("Test 4: Risk Management & Indian Brokerage...", end=" ")
    from risk_management import (
        calculate_stop_loss,
        calculate_target_price,
        calculate_risk_reward,
        calculate_position_size,
        calculate_brokerage,
    )
    
    entry = 2500.0
    atr = 35.0
    sl = calculate_stop_loss(entry, "BUY", atr)
    assert sl < entry, "BUY Stop Loss must be below entry"
    
    tp = calculate_target_price(entry, "BUY", atr, rr_ratio=2.0)
    assert tp > entry, "BUY Target Price must be above entry"
    
    rr = calculate_risk_reward(entry, tp, sl)
    assert rr > 0, "Risk reward must be positive"
    
    pos = calculate_position_size(100_000, entry, sl, risk_pct=2.0)
    assert pos["quantity"] >= 0
    assert pos["position_value"] <= 100_000 * 0.20 + 1.0  # Respect 20% cap
    
    brok = calculate_brokerage(10, 2500.0, "BUY")
    assert brok["brokerage"] <= 20.0  # Capped at ₹20
    assert brok["total_charges"] > 0
    print("PASSED")

def test_random_forest_model():
    print("Test 5: Random Forest Model...", end=" ")
    from models.random_forest import RandomForestModel
    from indicators import add_all_indicators
    from preprocessing import add_time_features, add_price_features, add_lag_features, create_target, prepare_features, train_test_split_time
    
    df = generate_mock_ohlcv(100)
    df = add_all_indicators(df)
    df = add_time_features(df)
    df = add_price_features(df)
    df = add_lag_features(df)
    df = create_target(df)
    X, y = prepare_features(df)
    X_train, X_test, y_train, y_test = train_test_split_time(X, y)
    
    rf = RandomForestModel(n_estimators=50, max_depth=5)
    metrics = rf.train(X_train, y_train, X_test, y_test)
    assert "train_accuracy" in metrics
    
    pred = rf.predict_single(X_test)
    assert pred["direction"] in ["UP", "DOWN", "NEUTRAL"]
    assert pred["signal"] in ["BUY", "SELL", "HOLD"]
    assert 0.0 <= pred["confidence"] <= 1.0
    print("PASSED")

def test_trading_signal_engine():
    print("Test 6: Trading Signal Synthesis Engine...", end=" ")
    from indicators import add_all_indicators
    from trading_signals import generate_trading_signal
    
    df = generate_mock_ohlcv(100)
    df = add_all_indicators(df)
    mock_ml = {"direction": "UP", "confidence": 0.75, "predicted_change_pct": 2.5}
    sig = generate_trading_signal("RELIANCE", df, mock_ml, risk_pct=2.0)
    
    assert sig["symbol"] == "RELIANCE"
    assert sig["signal"] in ["BUY", "SELL", "HOLD"]
    assert sig["entry_price"] > 0
    assert sig["target_price"] > 0
    assert sig["stop_loss"] > 0
    assert sig["risk_reward_ratio"] > 0
    print("PASSED")

def test_paper_portfolio():
    print("Test 7: Paper Portfolio & Simulated Order Execution...", end=" ")
    from portfolio import PaperPortfolio
    
    port = PaperPortfolio(user_id="test_user", initial_capital=500_000.0)
    
    # Test Buy
    res_buy = port.buy("TCS", quantity=10, price=3500.0, notes="Test purchase")
    assert res_buy["success"] is True
    assert "TCS" in port.positions
    assert port.positions["TCS"]["quantity"] == 10
    assert port.cash < 500_000.0
    
    # Test Mark-to-market
    port.update_market_prices({"TCS": 3600.0})
    assert port.positions["TCS"]["unrealised_pnl"] > 0
    
    # Test Sell
    res_sell = port.sell("TCS", quantity=5, price=3600.0, notes="Partial profit")
    assert res_sell["success"] is True
    assert port.positions["TCS"]["quantity"] == 5
    assert res_sell["realised_pnl"] > 0
    
    # Summary
    summary = port.get_summary()
    assert summary["portfolio_value"] > 0
    assert summary["num_positions"] == 1
    
    # Reset
    port.reset(1_000_000.0)
    assert port.cash == 1_000_000.0
    assert len(port.positions) == 0
    print("PASSED")

def test_backtesting_engine():
    print("Test 8: Backtesting Engine Simulation...", end=" ")
    from backtesting import BacktestEngine, BacktestConfig, strategy_ema_crossover
    
    df = generate_mock_ohlcv(120)
    config = BacktestConfig(initial_capital=100_000.0, commission_pct=0.03, slippage_pct=0.05)
    engine = BacktestEngine(config)
    
    results = engine.run(df, "INFY", strategy_ema_crossover, stop_loss_pct=2.0, take_profit_pct=4.0)
    assert "total_trades" in results
    assert "win_rate" in results
    assert "max_drawdown_pct" in results
    assert "sharpe_ratio" in results
    assert "final_equity" in results
    print("PASSED")

if __name__ == "__main__":
    print("=" * 60)
    print("TradeMind AI: Running Comprehensive System Verification")
    print("=" * 60)
    
    test_config()
    test_indicators()
    test_preprocessing()
    test_risk_management()
    test_random_forest_model()
    test_trading_signal_engine()
    test_paper_portfolio()
    test_backtesting_engine()
    
    print("=" * 60)
    print("ALL 8 SYSTEM MODULE TESTS PASSED PERFECTLY!")
    print("=" * 60)

