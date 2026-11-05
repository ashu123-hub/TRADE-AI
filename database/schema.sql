-- ============================================================
-- TradeMind AI — Supabase PostgreSQL Schema
-- Run this in the Supabase SQL Editor (https://app.supabase.com)
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─────────────────────────────────────────────
-- 1. users
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username    TEXT NOT NULL UNIQUE,
    email       TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can read own row"
    ON public.users FOR SELECT
    USING (auth.uid() = id);

-- ─────────────────────────────────────────────
-- 2. stocks
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.stocks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol       TEXT NOT NULL UNIQUE,
    company_name TEXT,
    exchange     TEXT NOT NULL DEFAULT 'NSE',
    sector       TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stocks_symbol ON public.stocks (symbol);

ALTER TABLE public.stocks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read stocks" ON public.stocks FOR SELECT USING (true);

-- ─────────────────────────────────────────────
-- 3. historical_prices
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.historical_prices (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stock_symbol TEXT NOT NULL,
    timestamp    TIMESTAMPTZ NOT NULL,
    open         NUMERIC(14,4),
    high         NUMERIC(14,4),
    low          NUMERIC(14,4),
    close        NUMERIC(14,4),
    volume       BIGINT,
    timeframe    TEXT NOT NULL DEFAULT '1d',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (stock_symbol, timestamp, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_hp_symbol     ON public.historical_prices (stock_symbol);
CREATE INDEX IF NOT EXISTS idx_hp_timestamp  ON public.historical_prices (timestamp);
CREATE INDEX IF NOT EXISTS idx_hp_sym_ts     ON public.historical_prices (stock_symbol, timestamp DESC);

ALTER TABLE public.historical_prices ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read prices" ON public.historical_prices FOR SELECT USING (true);

-- ─────────────────────────────────────────────
-- 4. technical_indicators
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.technical_indicators (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stock_symbol TEXT NOT NULL,
    timestamp    TIMESTAMPTZ NOT NULL,
    timeframe    TEXT NOT NULL DEFAULT '1d',
    rsi          NUMERIC(10,4),
    macd         NUMERIC(14,6),
    macd_signal  NUMERIC(14,6),
    macd_hist    NUMERIC(14,6),
    ema_9        NUMERIC(14,4),
    ema_21       NUMERIC(14,4),
    sma_50       NUMERIC(14,4),
    sma_200      NUMERIC(14,4),
    vwap         NUMERIC(14,4),
    bb_upper     NUMERIC(14,4),
    bb_middle    NUMERIC(14,4),
    bb_lower     NUMERIC(14,4),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (stock_symbol, timestamp, timeframe)
);

CREATE INDEX IF NOT EXISTS idx_ti_symbol    ON public.technical_indicators (stock_symbol);
CREATE INDEX IF NOT EXISTS idx_ti_timestamp ON public.technical_indicators (timestamp);

ALTER TABLE public.technical_indicators ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read indicators" ON public.technical_indicators FOR SELECT USING (true);

-- ─────────────────────────────────────────────
-- 5. predictions
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.predictions (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stock_symbol       TEXT NOT NULL,
    prediction_type    TEXT NOT NULL,  -- 'intraday' | 'next_day'
    predicted_price    NUMERIC(14,4),
    predicted_direction TEXT,          -- 'UP' | 'DOWN' | 'NEUTRAL'
    confidence         NUMERIC(5,4),   -- 0.0 – 1.0
    model_used         TEXT,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pred_symbol ON public.predictions (stock_symbol);
CREATE INDEX IF NOT EXISTS idx_pred_created ON public.predictions (created_at DESC);

ALTER TABLE public.predictions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read predictions" ON public.predictions FOR SELECT USING (true);

-- ─────────────────────────────────────────────
-- 6. trading_signals
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.trading_signals (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stock_symbol     TEXT NOT NULL,
    signal           TEXT NOT NULL,  -- 'BUY' | 'SELL' | 'HOLD'
    entry_price      NUMERIC(14,4),
    target_price     NUMERIC(14,4),
    stop_loss        NUMERIC(14,4),
    risk_reward_ratio NUMERIC(8,4),
    explanation      TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sig_symbol  ON public.trading_signals (stock_symbol);
CREATE INDEX IF NOT EXISTS idx_sig_created ON public.trading_signals (created_at DESC);

ALTER TABLE public.trading_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read signals" ON public.trading_signals FOR SELECT USING (true);

-- ─────────────────────────────────────────────
-- 7. portfolios
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.portfolios (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    stock_symbol     TEXT NOT NULL,
    quantity         NUMERIC(14,4) NOT NULL DEFAULT 0,
    average_buy_price NUMERIC(14,4) NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, stock_symbol)
);

CREATE INDEX IF NOT EXISTS idx_port_user   ON public.portfolios (user_id);
CREATE INDEX IF NOT EXISTS idx_port_symbol ON public.portfolios (stock_symbol);

ALTER TABLE public.portfolios ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own portfolio"
    ON public.portfolios FOR SELECT
    USING (auth.uid() = user_id);
CREATE POLICY "Users manage own portfolio"
    ON public.portfolios FOR ALL
    USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────
-- 8. transactions
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.transactions (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    stock_symbol     TEXT NOT NULL,
    transaction_type TEXT NOT NULL,  -- 'BUY' | 'SELL'
    quantity         NUMERIC(14,4) NOT NULL,
    price            NUMERIC(14,4) NOT NULL,
    brokerage        NUMERIC(10,4) DEFAULT 0,
    transaction_date TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_txn_user   ON public.transactions (user_id);
CREATE INDEX IF NOT EXISTS idx_txn_symbol ON public.transactions (stock_symbol);
CREATE INDEX IF NOT EXISTS idx_txn_date   ON public.transactions (transaction_date DESC);

ALTER TABLE public.transactions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users read own transactions"
    ON public.transactions FOR SELECT
    USING (auth.uid() = user_id);
CREATE POLICY "Users manage own transactions"
    ON public.transactions FOR ALL
    USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────
-- 9. backtest_results
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.backtest_results (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    stock_symbol     TEXT NOT NULL,
    strategy         TEXT NOT NULL,
    start_date       DATE,
    end_date         DATE,
    total_return     NUMERIC(10,4),
    win_rate         NUMERIC(5,4),
    maximum_drawdown NUMERIC(10,4),
    profit_factor    NUMERIC(10,4),
    sharpe_ratio     NUMERIC(10,4),
    total_trades     INT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bt_symbol  ON public.backtest_results (stock_symbol);
CREATE INDEX IF NOT EXISTS idx_bt_created ON public.backtest_results (created_at DESC);

ALTER TABLE public.backtest_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Public read backtest" ON public.backtest_results FOR SELECT USING (true);

-- ─────────────────────────────────────────────
-- Utility: updated_at auto-update trigger
-- ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_portfolios_updated_at
    BEFORE UPDATE ON public.portfolios
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
