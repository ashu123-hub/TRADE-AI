"""
TradeMind AI - Backtesting Engine
Historical strategy simulation with entry/exit, brokerage, slippage,
and performance metrics. Prevents look-ahead bias.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import numpy as np
import pandas as pd

from config import settings
from indicators import add_all_indicators
from risk_management import calculate_brokerage

logger = logging.getLogger(__name__)


@dataclass
class BacktestConfig:
    initial_capital: float = 100_000.0
    commission_pct: float = 0.03     # 0.03% per side (Zerodha approx.)
    slippage_pct: float = 0.05       # 0.05% slippage
    risk_per_trade_pct: float = 2.0  # % of capital at risk per trade
    max_position_pct: float = 20.0   # max 20% capital per position
    stt_pct: float = 0.1             # STT on sell side


@dataclass
class Trade:
    symbol: str
    entry_date: datetime
    entry_price: float
    quantity: int
    direction: str  # 'LONG' or 'SHORT'
    exit_date: datetime = None
    exit_price: float = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    charges: float = 0.0
    status: str = "OPEN"  # 'OPEN' | 'CLOSED' | 'STOPPED'


class BacktestEngine:
    """
    Event-driven backtester.
    Strategies are callables: strategy(df_to_now) → 'BUY' | 'SELL' | 'HOLD'
    """

    def __init__(self, config: BacktestConfig = None):
        self.config = config or BacktestConfig()
        self.trades: list[Trade] = []
        self.equity_curve: list[dict] = []

    def _apply_slippage(self, price: float, direction: str) -> float:
        slip = price * self.config.slippage_pct / 100
        return price + slip if direction == "BUY" else price - slip

    def _transaction_cost(self, quantity: int, price: float, side: str) -> float:
        brok = calculate_brokerage(quantity, price, side)
        return brok["total_charges"]

    def run(
        self,
        df: pd.DataFrame,
        symbol: str,
        strategy_fn: Callable[[pd.DataFrame], str],
        stop_loss_pct: float = 2.0,
        take_profit_pct: float = 4.0,
    ) -> dict:
        """
        Run backtest on `df` using `strategy_fn`.
        strategy_fn receives data UP TO current bar (no future data).
        """
        if len(df) < 50:
            return {"error": "Not enough data for backtesting"}

        df = df.copy().sort_index()
        df = add_all_indicators(df)
        df = df.dropna(subset=["Close"])

        capital = self.config.initial_capital
        position: Trade | None = None
        equity_history = []
        all_trades: list[Trade] = []

        # Walk forward (no look-ahead: strategy only sees data[:i+1])
        for i in range(50, len(df)):
            bar = df.iloc[i]
            current_price = float(bar["Close"])
            current_date = df.index[i]

            # Check stop-loss / take-profit on open position
            if position is not None:
                sl_price = position.entry_price * (1 - stop_loss_pct / 100)
                tp_price = position.entry_price * (1 + take_profit_pct / 100)
                low_price = float(bar["Low"])
                high_price = float(bar["High"])

                exit_triggered = False
                exit_price = current_price
                status = "CLOSED"

                if position.direction == "LONG":
                    if low_price <= sl_price:
                        exit_price = sl_price
                        status = "STOPPED"
                        exit_triggered = True
                    elif high_price >= tp_price:
                        exit_price = tp_price
                        exit_triggered = True

                if exit_triggered:
                    exit_price = self._apply_slippage(exit_price, "SELL")
                    charges = self._transaction_cost(position.quantity, exit_price, "SELL")
                    pnl = (exit_price - position.entry_price) * position.quantity - charges - position.charges
                    position.exit_date = current_date
                    position.exit_price = exit_price
                    position.pnl = round(pnl, 2)
                    position.pnl_pct = round(pnl / (position.entry_price * position.quantity) * 100, 2)
                    position.charges += charges
                    position.status = status
                    capital += position.entry_price * position.quantity + pnl
                    all_trades.append(position)
                    position = None

            # Get strategy signal (only uses data[:i+1] — no future data)
            historical_slice = df.iloc[:i + 1]
            try:
                signal = strategy_fn(historical_slice)
            except Exception:
                signal = "HOLD"

            # Execute signal
            if signal == "BUY" and position is None and capital > 100:
                entry_price = self._apply_slippage(current_price, "BUY")
                risk_amount = capital * self.config.risk_per_trade_pct / 100
                risk_per_share = entry_price * stop_loss_pct / 100
                quantity = max(1, int(risk_amount / risk_per_share)) if risk_per_share > 0 else 0
                max_qty = int(capital * self.config.max_position_pct / 100 / entry_price)
                quantity = min(quantity, max_qty)

                if quantity > 0 and entry_price * quantity <= capital:
                    charges = self._transaction_cost(quantity, entry_price, "BUY")
                    capital -= entry_price * quantity + charges
                    position = Trade(
                        symbol=symbol,
                        entry_date=current_date,
                        entry_price=entry_price,
                        quantity=quantity,
                        direction="LONG",
                        charges=charges,
                    )

            elif signal == "SELL" and position is not None:
                exit_price = self._apply_slippage(current_price, "SELL")
                charges = self._transaction_cost(position.quantity, exit_price, "SELL")
                pnl = (exit_price - position.entry_price) * position.quantity - charges - position.charges
                position.exit_date = current_date
                position.exit_price = exit_price
                position.pnl = round(pnl, 2)
                position.pnl_pct = round(pnl / (position.entry_price * position.quantity) * 100, 2)
                position.charges += charges
                position.status = "CLOSED"
                capital += position.entry_price * position.quantity + pnl
                all_trades.append(position)
                position = None

            # Track equity
            portfolio_value = capital
            if position is not None:
                portfolio_value += position.quantity * current_price
            equity_history.append({
                "date": current_date,
                "equity": round(portfolio_value, 2),
                "cash": round(capital, 2),
            })

        # Close any open position at last bar
        if position is not None and len(df) > 0:
            last_price = float(df["Close"].iloc[-1])
            exit_price = self._apply_slippage(last_price, "SELL")
            charges = self._transaction_cost(position.quantity, exit_price, "SELL")
            pnl = (exit_price - position.entry_price) * position.quantity - charges - position.charges
            position.exit_date = df.index[-1]
            position.exit_price = exit_price
            position.pnl = round(pnl, 2)
            position.status = "CLOSED"
            capital += position.entry_price * position.quantity + pnl
            all_trades.append(position)

        self.trades = all_trades
        self.equity_curve = equity_history
        return self._compute_metrics(all_trades, equity_history)

    def _compute_metrics(self, trades: list[Trade], equity_history: list[dict]) -> dict:
        """Compute backtest performance metrics."""
        if not trades:
            return {"error": "No trades executed"}

        pnls = [t.pnl for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_return = sum(pnls)
        win_rate = len(wins) / len(pnls) if pnls else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

        # Drawdown
        equities = [e["equity"] for e in equity_history]
        if equities:
            eq_series = pd.Series(equities)
            rolling_max = eq_series.cummax()
            drawdown = (eq_series - rolling_max) / (rolling_max + 1e-9)
            max_drawdown = float(drawdown.min()) * 100
        else:
            max_drawdown = 0.0

        # Sharpe Ratio (daily returns, annualised)
        if len(equities) > 1:
            daily_returns = pd.Series(equities).pct_change().dropna()
            if daily_returns.std() > 0:
                sharpe = float(daily_returns.mean() / daily_returns.std() * np.sqrt(252))
            else:
                sharpe = 0.0
        else:
            sharpe = 0.0

        initial = self.config.initial_capital
        final_equity = equities[-1] if equities else initial
        total_return_pct = (final_equity - initial) / initial * 100

        return {
            "total_trades": len(trades),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "win_rate": round(win_rate, 4),
            "total_pnl": round(total_return, 2),
            "total_return_pct": round(total_return_pct, 2),
            "max_drawdown_pct": round(max_drawdown, 2),
            "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else 999.0,
            "sharpe_ratio": round(sharpe, 4),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "initial_capital": initial,
            "final_equity": round(final_equity, 2),
            "trades": [vars(t) if hasattr(t, '__dict__') else {} for t in trades],
        }

    def get_equity_df(self) -> pd.DataFrame:
        if not self.equity_curve:
            return pd.DataFrame()
        df = pd.DataFrame(self.equity_curve)
        df["date"] = pd.to_datetime(df["date"])
        return df.set_index("date")


# ─── Built-in Strategies ─────────────────────────────────────────────────────

def strategy_ema_crossover(df: pd.DataFrame, fast: int = 9, slow: int = 21) -> str:
    """EMA crossover strategy."""
    if len(df) < slow + 5:
        return "HOLD"
    close = df["Close"]
    ema_fast = close.ewm(span=fast).mean()
    ema_slow = close.ewm(span=slow).mean()
    if ema_fast.iloc[-1] > ema_slow.iloc[-1] and ema_fast.iloc[-2] <= ema_slow.iloc[-2]:
        return "BUY"
    if ema_fast.iloc[-1] < ema_slow.iloc[-1] and ema_fast.iloc[-2] >= ema_slow.iloc[-2]:
        return "SELL"
    return "HOLD"


def strategy_rsi_bb(df: pd.DataFrame) -> str:
    """RSI + Bollinger Band mean-reversion strategy."""
    if len(df) < 25:
        return "HOLD"
    close = df["Close"]
    # RSI
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - (100 / (1 + gain / (loss + 1e-9)))
    rsi_val = rsi.iloc[-1]
    # Bollinger
    sma = close.rolling(20).mean()
    std = close.rolling(20).std()
    lower = sma - 2 * std
    upper = sma + 2 * std
    price = close.iloc[-1]

    if rsi_val < 35 and price < lower.iloc[-1]:
        return "BUY"
    if rsi_val > 65 and price > upper.iloc[-1]:
        return "SELL"
    return "HOLD"


def strategy_macd(df: pd.DataFrame) -> str:
    """MACD crossover strategy."""
    if len(df) < 35:
        return "HOLD"
    close = df["Close"]
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:
        return "BUY"
    if macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-2] >= signal.iloc[-2]:
        return "SELL"
    return "HOLD"


AVAILABLE_STRATEGIES = {
    "EMA Crossover (9/21)": strategy_ema_crossover,
    "RSI + Bollinger Bands": strategy_rsi_bb,
    "MACD Crossover": strategy_macd,
}
