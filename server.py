"""
TradeMind AI - High Performance FastAPI Backend Server
Serves the Groww-inspired Fintech Web Application and provides RESTful APIs
connecting to all quantitative ML, scanning, backtesting, and paper trading engines.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

# Setup path
ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

# Import existing backend modules
from config import settings, api_keys
import database as db
from data_collection import (
    NIFTY_50_SYMBOLS,
    NIFTY_NEXT_50,
    NIFTY_MIDCAP_SYMBOLS,
    POPULAR_NSE_STOCKS,
    INDEX_SYMBOLS,
    get_market_overview,
    get_top_movers,
    download_stock_data,
    download_intraday_data,
    download_index_data,
)
from indicators import add_all_indicators, get_latest_indicators, identify_support_resistance
from nse_scanner import (
    run_full_scan,
    filter_stocks,
    get_top_gainers,
    get_top_losers,
    get_high_volume_stocks,
    get_momentum_stocks,
    get_breakout_stocks,
    search_stocks,
    scan_stock,
)
from prediction import get_intraday_predictor, get_next_day_predictor
from trading_signals import generate_trading_signal, batch_scan_signals
from risk_management import calculate_brokerage, calculate_position_size
from portfolio import get_portfolio
from backtesting import BacktestEngine, BacktestConfig, AVAILABLE_STRATEGIES
from api_manager import market_data, gemini
from services.yahoo_service import yahoo_service

logger = logging.getLogger("trademind.server")

# ─── FastAPI Application Initialization ─────────────────────────────────────────
app = FastAPI(
    title="TradeMind AI",
    description="AI-Powered Indian Stock Market Prediction & Quantitative Paper Trading Assistant",
    version=settings.APP_VERSION,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Request / Response Schemas ───────────────────────────────────────────────
class TradeOrderRequest(BaseModel):
    symbol: str
    quantity: int = Field(gt=0)
    price: float = Field(gt=0)
    side: Optional[str] = "BUY"
    product_type: Optional[str] = "CNC"  # CNC or MIS
    order_type: Optional[str] = "MARKET"  # MARKET or LIMIT
    notes: Optional[str] = ""

class SquareOffRequest(BaseModel):
    position_id: str
    market_price: Optional[float] = None

class AddFundsRequest(BaseModel):
    amount: float = Field(gt=0)

class BacktestRequest(BaseModel):
    symbol: str
    strategy: str
    period: str = "1y"
    initial_capital: float = 100_000.0
    stop_loss_pct: float = 2.0
    take_profit_pct: float = 4.0
    slippage_pct: float = 0.05

class PredictionRequest(BaseModel):
    symbol: str
    interval: Optional[str] = "5m"
    force_retrain: Optional[bool] = False

# ─── Market & Overview Endpoints ──────────────────────────────────────────────
@app.get("/api/market-overview")
def api_market_overview():
    """Returns status of market and quotes for NIFTY 50, SENSEX, BANK NIFTY, NIFTY IT."""
    try:
        overview = get_market_overview()
        
        # Calculate IST market open/closed status
        now_utc = datetime.now(timezone.utc)
        # IST is UTC + 5:30
        now_ist_total_min = now_utc.hour * 60 + now_utc.minute + 330
        ist_day = (now_utc.weekday() + (1 if now_ist_total_min >= 1440 else 0)) % 7
        ist_min_of_day = now_ist_total_min % 1440
        ist_hour = ist_min_of_day // 60
        ist_min = ist_min_of_day % 60

        is_open = (ist_day < 5) and (
            (ist_hour > 9 or (ist_hour == 9 and ist_min >= 15)) and
            (ist_hour < 15 or (ist_hour == 15 and ist_min <= 30))
        )

        return {
            "indices": overview,
            "market_status": {
                "is_open": is_open,
                "current_time_ist": f"{ist_hour:02d}:{ist_min:02d} IST",
                "schedule": "09:15 AM - 03:30 PM IST (Mon-Fri)",
            }
        }
    except Exception as exc:
        logger.error("Error in market overview: %s", exc)
        return {"indices": {}, "market_status": {"is_open": False, "error": str(exc)}}

@app.get("/api/top-movers")
def api_top_movers(limit: int = 5):
    """Returns top gainers and top losers."""
    try:
        movers = get_top_movers(top_n=limit)
        return movers
    except Exception as exc:
        logger.error("Error in top movers: %s", exc)
        return {"gainers": [], "losers": []}

@app.get("/api/yahoo/status")
def api_yahoo_status():
    """Returns Yahoo Finance live feed connection status and benchmark quotes."""
    return market_data.yf.check_health()

DEFAULT_FEED_SYMBOLS = [
    "^NSEI", "^BSESN", "^NSEBANK",
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "BHARTIARTL", "SBIN", "SUZLON", "IRFC", "HAL",
    "BEL", "TATASTEEL", "ITC", "LT"
]

@app.get("/api/live-feed")
def api_live_feed(symbols: Optional[str] = Query(None)):
    """
    Real-time streaming feed for Indian stocks & benchmark indices.
    Returns live prices, day high/low, 52-week high/low, and percentage changes.
    """
    if symbols:
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        sym_list = DEFAULT_FEED_SYMBOLS

    quotes_dict = market_data.get_batch_quotes(sym_list)
    result_list = []
    for s in sym_list:
        clean = s.upper().replace(".NS", "").replace(".BO", "").strip()
        q = quotes_dict.get(clean) or quotes_dict.get(s)
        if q and q.get("price") is not None:
            result_list.append(q)
        else:
            try:
                single_q = market_data.get_quote(s)
                if single_q.get("price") is not None:
                    result_list.append(single_q)
            except Exception:
                pass

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "count": len(result_list),
        "quotes": result_list,
    }

@app.get("/api/search")
def api_search(q: str = Query(..., min_length=1)):
    """Search stocks by symbol or name."""
    matches = search_stocks(q)
    return {"query": q, "results": matches[:20]}

@app.get("/api/universe")
def api_universe():
    """List supported stock universe."""
    return {
        "nifty_50": NIFTY_50_SYMBOLS,
        "nifty_next_50": NIFTY_NEXT_50,
        "nifty_midcap": NIFTY_MIDCAP_SYMBOLS,
        "all_popular": POPULAR_NSE_STOCKS,
    }

# ─── Stock Explorer & Scanner Endpoints ───────────────────────────────────────
@app.get("/api/scanner")
def api_scanner(
    max_symbols: int = 30,
    min_price: float = 0.0,
    max_price: float = 100_000.0,
    min_rsi: float = 0.0,
    max_rsi: float = 100.0,
    min_volume_ratio: float = 0.0,
):
    """Run full scan with indicators, momentum, and breakouts."""
    try:
        results = run_full_scan(max_symbols=max_symbols)
        filtered = filter_stocks(
            results,
            min_price=min_price,
            max_price=max_price,
            min_rsi=min_rsi,
            max_rsi=max_rsi,
        )
        if min_volume_ratio > 0:
            filtered = [s for s in filtered if s.get("volume_ratio", 0) >= min_volume_ratio]

        return {
            "total_scanned": len(results),
            "total_filtered": len(filtered),
            "results": filtered,
            "top_gainers": get_top_gainers(filtered, 8),
            "top_losers": get_top_losers(filtered, 8),
            "high_volume": get_high_volume_stocks(filtered, 8),
            "momentum_leaders": get_momentum_stocks(filtered, 8),
            "breakouts": get_breakout_stocks(filtered)[:10],
        }
    except Exception as exc:
        logger.error("Scanner error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/stock/{symbol}")
def api_stock_details(symbol: str):
    """Get single stock details, quote, and latest indicators."""
    sym = symbol.upper().strip()
    try:
        q = market_data.get_quote(sym)
        company_info = market_data.get_company_info(sym)
        
        df = download_stock_data(sym, interval="1d", period="3mo", store_to_db=False)
        indicators = {}
        sr = {}
        if not df.empty and len(df) >= 20:
            df_ind = add_all_indicators(df)
            indicators = get_latest_indicators(df_ind)
            sr = identify_support_resistance(df_ind)

        return {
            "symbol": sym,
            "quote": q,
            "company_info": company_info,
            "indicators": indicators,
            "support_resistance": sr,
        }
    except Exception as exc:
        logger.error("Error fetching stock %s: %s", sym, exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/stock/{symbol}/history")
def api_stock_history(
    symbol: str,
    period: str = Query("1y", pattern="^(1d|5d|1mo|3mo|6mo|1y|2y|5y)$"),
    interval: str = Query("1d", pattern="^(5m|15m|1h|1d|1wk)$"),
):
    """Retrieve historical OHLCV chart bars and computed overlays."""
    sym = symbol.upper().strip()
    try:
        if interval in ["5m", "15m"]:
            df = download_intraday_data(sym, interval=interval)
        else:
            df = download_stock_data(sym, interval=interval, period=period, store_to_db=False)

        if df.empty:
            return {"symbol": sym, "bars": [], "indicators": {}}

        df_ind = add_all_indicators(df)

        bars = []
        for ts, row in df_ind.iterrows():
            bars.append({
                "time": ts.strftime("%Y-%m-%d %H:%M") if interval in ["5m", "15m", "1h"] else ts.strftime("%Y-%m-%d"),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row.get("Volume", 0)),
                "ema_9": round(float(row["EMA_9"]), 2) if "EMA_9" in row and row["EMA_9"] == row["EMA_9"] else None,
                "ema_21": round(float(row["EMA_21"]), 2) if "EMA_21" in row and row["EMA_21"] == row["EMA_21"] else None,
                "sma_50": round(float(row["SMA_50"]), 2) if "SMA_50" in row and row["SMA_50"] == row["SMA_50"] else None,
                "bb_upper": round(float(row["BB_Upper"]), 2) if "BB_Upper" in row and row["BB_Upper"] == row["BB_Upper"] else None,
                "bb_lower": round(float(row["BB_Lower"]), 2) if "BB_Lower" in row and row["BB_Lower"] == row["BB_Lower"] else None,
                "rsi": round(float(row["RSI"]), 2) if "RSI" in row and row["RSI"] == row["RSI"] else None,
                "macd": round(float(row["MACD"]), 3) if "MACD" in row and row["MACD"] == row["MACD"] else None,
                "macd_signal": round(float(row["MACD_Signal"]), 3) if "MACD_Signal" in row and row["MACD_Signal"] == row["MACD_Signal"] else None,
                "macd_hist": round(float(row["MACD_Hist"]), 3) if "MACD_Hist" in row and row["MACD_Hist"] == row["MACD_Hist"] else None,
            })

        return {
            "symbol": sym,
            "period": period,
            "interval": interval,
            "bars": bars,
            "latest": get_latest_indicators(df_ind),
        }
    except Exception as exc:
        logger.error("History fetch error for %s: %s", sym, exc)
        raise HTTPException(status_code=500, detail=str(exc))

# ─── Prediction Endpoints ─────────────────────────────────────────────────────
@app.post("/api/predict/intraday")
def api_predict_intraday(req: PredictionRequest):
    """Execute intraday 5m or 15m forecast using RF + XGBoost ensemble."""
    sym = req.symbol.upper().strip()
    interval = req.interval if req.interval in ["5m", "15m"] else "5m"
    try:
        predictor = get_intraday_predictor(interval)
        result = predictor.predict(sym, force_retrain=req.force_retrain)
        
        # Add AI commentary
        explanation = ""
        try:
            explanation = gemini.explain_signal(
                sym,
                result.get("signal", "HOLD"),
                result.get("indicators", {}),
                result
            )
        except Exception:
            explanation = f"Technical analysis indicates {result.get('signal')} stance based on combined intraday indicators."

        result["ai_explanation"] = explanation
        return result
    except Exception as exc:
        logger.error("Intraday prediction error for %s: %s", sym, exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.post("/api/predict/next-day")
def api_predict_next_day(req: PredictionRequest):
    """Execute next-day forecast using RF + XGBoost + LSTM ensemble."""
    sym = req.symbol.upper().strip()
    try:
        predictor = get_next_day_predictor()
        result = predictor.predict(sym, force_retrain=req.force_retrain)

        explanation = ""
        try:
            explanation = gemini.explain_signal(
                sym,
                result.get("signal", "HOLD"),
                result.get("indicators", {}),
                result
            )
        except Exception:
            explanation = f"Technical analysis projects next-day direction as {result.get('direction')} with confidence {result.get('confidence', 0):.1%}."

        result["ai_explanation"] = explanation
        return result
    except Exception as exc:
        logger.error("Next-day prediction error for %s: %s", sym, exc)
        raise HTTPException(status_code=500, detail=str(exc))

# ─── AI Trading Signals Endpoints ─────────────────────────────────────────────
@app.get("/api/signals")
def api_signals(symbols: Optional[str] = None, risk_pct: float = 2.0):
    """Generate multi-factor signals (BUY/SELL/HOLD with Entry, Target, Stop-Loss)."""
    if symbols:
        sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    else:
        sym_list = NIFTY_50_SYMBOLS[:8]

    results = []
    for sym in sym_list:
        try:
            df = download_stock_data(sym, interval="1d", period="1y", store_to_db=False)
            if not df.empty and len(df) >= 30:
                df = add_all_indicators(df)
                predictor = get_next_day_predictor()
                pred = predictor.predict(sym)
                sig = generate_trading_signal(sym, df, pred, risk_pct=risk_pct)
                results.append(sig)
        except Exception as exc:
            logger.warning("Signal failed for %s: %s", sym, exc)

    return {"signals": results}

@app.get("/api/signals/explain")
def api_explain_signal(symbol: str, signal: str):
    """Get Gemini AI explanation for a signal."""
    sym = symbol.upper().strip()
    try:
        df = download_stock_data(sym, interval="1d", period="3mo", store_to_db=False)
        indicators = {}
        if not df.empty:
            df_ind = add_all_indicators(df)
            indicators = get_latest_indicators(df_ind)
        explanation = gemini.explain_signal(sym, signal, indicators, {"current_price": indicators.get("Close", "N/A")})
        return {"symbol": sym, "signal": signal, "explanation": explanation}
    except Exception as exc:
        return {"symbol": sym, "signal": signal, "explanation": f"Educational analysis for {sym} ({signal})."}

# ─── Portfolio & Paper Trading Endpoints ──────────────────────────────────────
@app.get("/api/portfolio")
def api_get_portfolio():
    """Get paper portfolio holdings, positions, cash, P&L, and transaction records."""
    port = get_portfolio()
    # Update real-time market prices for active holdings & positions
    if port.positions:
        unique_syms = list({p["symbol"] for p in port.positions.values()})
        try:
            batch_quotes = market_data.get_batch_quotes(unique_syms)
            price_map = {}
            for sym in unique_syms:
                q = batch_quotes.get(sym)
                if not q or not q.get("price"):
                    q = market_data.get_quote(sym)
                if q and q.get("price"):
                    price_map[sym] = float(q["price"])
            if price_map:
                port.update_market_prices(price_map)
        except Exception as exc:
            logger.warning("Error updating portfolio market prices: %s", exc)

    summary = port.get_summary()
    holdings = summary.get("holdings", [])
    positions = summary.get("positions", [])
    txns = port.transactions

    return {
        "summary": summary,
        "holdings": holdings,
        "positions": positions,
        "transactions": list(reversed(txns))[:50],
    }

@app.post("/api/portfolio/order")
def api_portfolio_order(order: TradeOrderRequest):
    """Execute Groww-style simulated paper order (Delivery CNC or Intraday MIS 5x)."""
    port = get_portfolio()
    side = (order.side or "BUY").upper().strip()
    prod = (order.product_type or "CNC").upper().strip()
    order_type = (order.order_type or "MARKET").upper().strip()

    if side == "BUY":
        res = port.buy(
            symbol=order.symbol.upper(),
            quantity=order.quantity,
            price=order.price,
            product_type=prod,
            order_type=order_type,
            notes=order.notes or "",
        )
    else:
        res = port.sell(
            symbol=order.symbol.upper(),
            quantity=order.quantity,
            price=order.price,
            product_type=prod,
            order_type=order_type,
            notes=order.notes or "",
        )

    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res

@app.post("/api/portfolio/buy")
def api_portfolio_buy(order: TradeOrderRequest):
    """Execute simulated paper BUY order (backward compatible)."""
    order.side = "BUY"
    return api_portfolio_order(order)

@app.post("/api/portfolio/sell")
def api_portfolio_sell(order: TradeOrderRequest):
    """Execute simulated paper SELL order (backward compatible)."""
    order.side = "SELL"
    return api_portfolio_order(order)

@app.post("/api/portfolio/square-off")
def api_portfolio_square_off(req: SquareOffRequest):
    """1-Click Square Off for active intraday MIS or delivery CNC position."""
    port = get_portfolio()
    market_price = req.market_price
    if not market_price:
        pos = port.positions.get(req.position_id)
        if pos:
            try:
                q = market_data.get_quote(pos["symbol"])
                if q.get("price"):
                    market_price = float(q["price"])
            except Exception:
                pass
    res = port.square_off(req.position_id, market_price=market_price)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res

@app.post("/api/portfolio/add-funds")
def api_portfolio_add_funds(req: AddFundsRequest):
    """Add virtual funds to paper trading account."""
    port = get_portfolio()
    res = port.add_funds(req.amount)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))
    return res

@app.post("/api/portfolio/reset")
def api_portfolio_reset(capital: float = Body(1_000_000.0, embed=True)):
    """Reset paper trading portfolio capital and positions."""
    port = get_portfolio()
    port.reset(capital=capital)
    return {"message": "Portfolio reset successfully", "new_capital": capital}

@app.get("/api/brokerage-estimate")
def api_brokerage_estimate(
    quantity: int,
    price: float,
    side: str = "BUY",
    product_type: str = "CNC",
):
    """Calculate simulated Indian brokerage and regulatory charges (Groww/Zerodha model)."""
    return calculate_brokerage(quantity, price, side.upper(), product_type=product_type.upper())

# ─── Quantitative Backtesting Endpoints ───────────────────────────────────────
@app.post("/api/backtest")
def api_run_backtest(req: BacktestRequest):
    """Run quantitative backtest on historical data with commission and slippage."""
    sym = req.symbol.upper().strip()
    if req.strategy not in AVAILABLE_STRATEGIES:
        raise HTTPException(status_code=400, detail=f"Invalid strategy. Choose from: {list(AVAILABLE_STRATEGIES.keys())}")

    try:
        df = download_stock_data(sym, interval="1d", period=req.period, store_to_db=False)
        if df.empty or len(df) < 55:
            raise HTTPException(status_code=400, detail="Insufficient historical data for backtesting.")

        config = BacktestConfig(
            initial_capital=req.initial_capital,
            commission_pct=0.03,
            slippage_pct=req.slippage_pct,
        )
        engine = BacktestEngine(config)
        strat_fn = AVAILABLE_STRATEGIES[req.strategy]
        results = engine.run(
            df,
            sym,
            strat_fn,
            stop_loss_pct=req.stop_loss_pct,
            take_profit_pct=req.take_profit_pct,
        )

        eq_curve = engine.equity_curve
        return {
            "metrics": results,
            "equity_curve": eq_curve,
        }
    except Exception as exc:
        logger.error("Backtest error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

@app.get("/api/backtest/strategies")
def api_backtest_strategies():
    return {"strategies": list(AVAILABLE_STRATEGIES.keys())}

class SaveKeysRequest(BaseModel):
    yahoo_finance_api_key: Optional[str] = None
    gemini_api_key: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_anon_key: Optional[str] = None
    finnhub_api_key: Optional[str] = None
    alpha_vantage_api_key: Optional[str] = None

class TestKeyRequest(BaseModel):
    service: str
    key: Optional[str] = None
    url: Optional[str] = None

def _update_env_file(key_values: Dict[str, str]):
    """Safely updates or appends environment variables to .env file."""
    env_path = ROOT_DIR / ".env"
    existing_lines = []
    if env_path.exists():
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    updated_keys = set()
    new_lines = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in key_values:
                new_lines.append(f"{k}={key_values[k]}")
                updated_keys.add(k)
                continue
        new_lines.append(line)

    # Append any keys that weren't already in .env
    for k, v in key_values.items():
        if k not in updated_keys and v:
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

# ─── Settings & Diagnostics Endpoints ─────────────────────────────────────────
@app.get("/api/settings")
def api_settings():
    """Check API configuration and application settings."""
    def mask_key(val: Optional[str]) -> Optional[str]:
        if not val or len(val) < 8:
            return "Set" if val else None
        return f"{val[:4]}...{val[-4:]}"

    return {
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.APP_ENV,
        "cache_ttl": settings.CACHE_TTL,
        "services": market_data.get_services_status(),
        "keys_configured": {
            "yahoo_finance": bool(api_keys.yahoo_finance_api_key),
            "supabase": bool(api_keys.supabase_url and api_keys.supabase_anon_key),
            "gemini": bool(api_keys.gemini),
            "finnhub": bool(api_keys.finnhub),
            "alpha_vantage": bool(api_keys.alpha_vantage),
        },
        "masked_keys": {
            "yahoo_finance": mask_key(api_keys.yahoo_finance_api_key),
            "gemini": mask_key(api_keys.gemini),
            "supabase_url": api_keys.supabase_url,
            "supabase_anon_key": mask_key(api_keys.supabase_anon_key),
            "finnhub": mask_key(api_keys.finnhub),
            "alpha_vantage": mask_key(api_keys.alpha_vantage),
        },
        "supabase_connected": db.is_connected(),
    }

@app.post("/api/settings/keys")
def api_save_keys(req: SaveKeysRequest):
    """Save API keys into runtime environment and persist to .env."""
    key_map = {}
    if req.yahoo_finance_api_key is not None:
        key_map["YAHOO_FINANCE_API_KEY"] = req.yahoo_finance_api_key.strip()
    if req.gemini_api_key is not None:
        key_map["GEMINI_API_KEY"] = req.gemini_api_key.strip()
    if req.supabase_url is not None:
        key_map["SUPABASE_URL"] = req.supabase_url.strip()
    if req.supabase_anon_key is not None:
        key_map["SUPABASE_ANON_KEY"] = req.supabase_anon_key.strip()
    if req.finnhub_api_key is not None:
        key_map["FINNHUB_API_KEY"] = req.finnhub_api_key.strip()
    if req.alpha_vantage_api_key is not None:
        key_map["ALPHA_VANTAGE_API_KEY"] = req.alpha_vantage_api_key.strip()

    # Update runtime environment
    for k, v in key_map.items():
        if v:
            os.environ[k] = v
        elif k in os.environ:
            del os.environ[k]

    # Persist to .env
    _update_env_file(key_map)

    # Re-initialize services
    gemini._initialized = False
    gemini._model = None
    market_data.gemini._initialized = False
    market_data.gemini._model = None

    db._client = None
    db._initialized = False
    market_data.db._client = None
    market_data.db._initialized = False

    return {
        "success": True,
        "message": "API keys saved and applied successfully!",
        "services": market_data.get_services_status(),
    }

@app.post("/api/settings/test-key")
def api_test_key(req: TestKeyRequest):
    """Test validity of a specific API key without saving."""
    srv = req.service.lower()
    key = req.key.strip() if req.key else ""

    if srv == "gemini":
        if not key:
            return {"valid": False, "message": "API key cannot be empty"}
        try:
            import google.generativeai as genai
            genai.configure(api_key=key)
            m = genai.GenerativeModel("gemini-1.5-flash")
            resp = m.generate_content("Ping", generation_config={"max_output_tokens": 5})
            return {"valid": True, "message": "Google Gemini API key authenticated successfully!"}
        except Exception as exc:
            return {"valid": False, "message": f"Gemini error: {str(exc)}"}

    elif srv == "finnhub":
        if not key:
            return {"valid": False, "message": "API key cannot be empty"}
        try:
            import requests
            r = requests.get("https://finnhub.io/api/v1/news?category=general", headers={"X-Finnhub-Token": key}, timeout=8)
            if r.status_code == 200:
                return {"valid": True, "message": "Finnhub API key authenticated successfully!"}
            elif r.status_code == 401:
                return {"valid": False, "message": "Invalid Finnhub API key"}
            elif r.status_code == 429:
                return {"valid": True, "message": "Finnhub key valid (rate limited currently)"}
            return {"valid": False, "message": f"Finnhub HTTP {r.status_code}"}
        except Exception as exc:
            return {"valid": False, "message": f"Connection error: {str(exc)}"}

    elif srv == "alpha_vantage":
        if not key:
            return {"valid": False, "message": "API key cannot be empty"}
        try:
            import requests
            r = requests.get(f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=IBM&apikey={key}", timeout=10)
            data = r.json()
            if "Global Quote" in data or "Note" in data:
                return {"valid": True, "message": "Alpha Vantage API key verified!"}
            elif "Error Message" in data:
                return {"valid": False, "message": "Invalid Alpha Vantage key"}
            return {"valid": True, "message": "Key accepted by Alpha Vantage"}
        except Exception as exc:
            return {"valid": False, "message": f"Connection error: {str(exc)}"}

    elif srv in ("yahoo", "yahoo_finance"):
        return yahoo_service.validate_api_key(key)

    elif srv == "supabase":
        url = req.url.strip() if req.url else ""
        if not url or not key:
            return {"valid": False, "message": "Both Supabase URL and Anon Key are required"}
        try:
            from supabase import create_client
            client = create_client(url, key)
            client.table("stocks").select("id").limit(1).execute()
            return {"valid": True, "message": "Supabase PostgreSQL connected successfully!"}
        except Exception as exc:
            return {"valid": False, "message": f"Supabase error: {str(exc)}"}

    return {"valid": False, "message": "Unknown service"}

# ─── Static Files & SPA Route ─────────────────────────────────────────────────
STATIC_DIR = ROOT_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)
        return JSONResponse(status_code=404, content={"message": "Frontend static file not found"})

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)

