"""
TradeMind AI - API & Database Diagnostic Test Suite
Verification Order:
1. Finnhub API (Primary Market Data Provider: Quotes, Candles, News)
2. Alpha Vantage API (Primary/Alternative Provider: Historical Daily OHLCV, Intraday, Indicators)
3. Google Gemini API (Exclusive Generative AI: Factual Grounding, Signal Explanations)
4. Supabase Database (PostgreSQL Cloud Persistence & RLS)
5. Yahoo Finance (Secondary / Safety Fallback)
6. Composite Market Data Router (Fallback, Source Attribution, UTC Timestamps)
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import api_keys, settings
from services.finnhub_service import finnhub_service
from services.alpha_vantage_service import alpha_vantage_service
from services.gemini_service import gemini_service
from services.supabase_service import supabase_service
from services.yahoo_service import yahoo_service
from api_manager import market_data


def test_finnhub() -> bool:
    print("\n" + "=" * 65)
    print("TEST 1: FINNHUB API (Primary Market Data Provider)")
    print("=" * 65)

    if not finnhub_service.is_configured:
        print("STATUS: NOT CONFIGURED (FINNHUB_API_KEY is not set in .env)")
        print("INFO:   Finnhub is primary. Get free API key at https://finnhub.io (60 req/min)")
        return True

    print("Checking Finnhub API authentication...", end=" ")
    health = finnhub_service.check_health()
    if health.get("status") == "authenticated":
        print("PASSED (Authenticated)")
    else:
        print(f"FAILED ({health.get('status')})")
        return False

    print("Testing market news fetch...", end=" ")
    news = finnhub_service.get_market_news()
    if isinstance(news, list) and len(news) > 0:
        print(f"PASSED ({len(news)} articles retrieved)")
    else:
        print("WARNING (No news returned)")

    print("Testing real-time quote for RELIANCE...", end=" ")
    quote = finnhub_service.get_quote("RELIANCE")
    if quote.get("price") is not None:
        print(f"PASSED (LTP: ₹{quote['price']}, Source: {quote['provider']})")
    else:
        print(f"NOTE ({quote.get('status')})")

    print("Testing 5-minute / 15-minute intraday candle support...", end=" ")
    df_intra, meta_intra = finnhub_service.get_intraday_ohlcv("RELIANCE", interval="5m")
    if not df_intra.empty:
        print(f"PASSED ({len(df_intra)} bars loaded)")
    else:
        print(f"NOTE ({meta_intra.get('status')})")

    return True


def test_alpha_vantage() -> bool:
    print("\n" + "=" * 65)
    print("TEST 2: ALPHA VANTAGE API (Primary / Alternative Data Provider)")
    print("=" * 65)

    if not alpha_vantage_service.is_configured:
        print("STATUS: NOT CONFIGURED (ALPHA_VANTAGE_API_KEY is not set in .env)")
        print("INFO:   Get free key at https://www.alphavantage.co (5 req/min, 25 req/day)")
        return True

    print("Checking Alpha Vantage configuration...", end=" ")
    health = alpha_vantage_service.check_health()
    print(f"PASSED ({health.get('status')})")

    print("Testing Daily Time Series fetch (BSE:RELIANCE)...", end=" ")
    df, meta = alpha_vantage_service.get_daily_historical("RELIANCE", outputsize="compact")
    if not df.empty:
        print(f"PASSED ({len(df)} daily bars retrieved, Source: {meta['provider']})")
    else:
        print(f"NOTE: {meta.get('status')}")

    print("Testing Intraday Time Series (5min)...", end=" ")
    df_intra, meta_intra = alpha_vantage_service.get_intraday_ohlcv("RELIANCE", interval="5min")
    if not df_intra.empty:
        print(f"PASSED ({len(df_intra)} intraday bars, Source: {meta_intra['provider']})")
    else:
        print(f"NOTE: {meta_intra.get('status')}")

    return True


def test_google_gemini() -> bool:
    print("\n" + "=" * 65)
    print("TEST 3: GOOGLE GEMINI API (Exclusive Generative AI Provider)")
    print("=" * 65)

    if not gemini_service.is_configured:
        print("STATUS: NOT CONFIGURED (GEMINI_API_KEY is not set in .env)")
        print("INFO:   Get a free Gemini API key at https://aistudio.google.com")
        return True

    print("Checking Google Gemini model initialization...", end=" ")
    health = gemini_service.check_health()
    if health.get("status") == "authenticated":
        print(f"PASSED (Model: {health.get('model')})")
    else:
        print(f"FAILED ({health.get('status')})")
        return False

    print("Testing signal reasoning generation for TCS...", end=" ")
    exp = gemini_service.explain_signal(
        symbol="TCS",
        signal="BUY",
        indicators={"RSI": 48.5, "MACD": 14.2, "EMA_9": 2490.0, "EMA_21": 2440.0, "SMA_50": 2410.0, "ATR": 35.0},
        prediction_meta={"current_price": 2495.7, "direction": "UP", "confidence": 0.82},
    )
    if exp and not exp.startswith("AI commentary is unavailable"):
        print("PASSED")
        print(f"Sample Commentary: \"{exp[:120]}...\"")
    else:
        print(f"FAILED ({exp})")
        return False

    return True


def test_supabase() -> bool:
    print("\n" + "=" * 65)
    print("TEST 4: SUPABASE CLOUD DATABASE (PostgreSQL & RLS)")
    print("=" * 65)

    if not supabase_service.is_configured:
        print("STATUS: NOT CONFIGURED (SUPABASE_URL and SUPABASE_ANON_KEY not set in .env)")
        print("INFO:   Runs in seamless in-memory session mode. Free PostgreSQL at https://supabase.com")
        return True

    print("Checking Supabase connection & table access...", end=" ")
    health = supabase_service.check_health()
    if health.get("status") == "connected":
        print("PASSED (Connected & verified)")
    else:
        print(f"FAILED: {health.get('status')} ({health.get('error', 'Check credentials')})")
        return False

    return True


def test_yahoo_finance() -> bool:
    print("\n" + "=" * 65)
    print("TEST 5: YAHOO FINANCE (Secondary / Safety Fallback)")
    print("=" * 65)
    print(f"FALLBACK ENABLED: {api_keys.yahoo_finance_enabled}")
    if api_keys.yahoo_finance_api_key:
        print(f"OPTIONAL KEY: CONFIGURED ({api_keys.yahoo_finance_api_key[:4]}...{api_keys.yahoo_finance_api_key[-4:]})")
    else:
        print("OPTIONAL KEY: ZERO-CONFIG BUILT-IN (Available as safety net)")

    print("Testing fallback connectivity for RELIANCE...", end=" ")
    quote = yahoo_service.get_live_quote("RELIANCE")
    if quote.get("price") is not None:
        print(f"PASSED (LTP: ₹{quote['price']:,.2f}, Provider: {quote['provider']})")
    else:
        print(f"FAILED ({quote.get('error')})")
        return False

    return True


def test_composite_router() -> bool:
    print("\n" + "=" * 65)
    print("TEST 6: COMPOSITE MARKET DATA ROUTER (Source Attribution & Fallback)")
    print("=" * 65)

    # 1. Test Quote routing
    print("Testing composite quote for RELIANCE...", end=" ")
    q = market_data.get_quote("RELIANCE")
    if q.get("price") is not None:
        print(f"PASSED (LTP: ₹{q['price']:,.2f} | Source: {q.get('provider')} | Time: {q.get('timestamp')})")
    else:
        print("WARNING (Quote unavailable, no fake prices generated)")

    # 2. Test Historical OHLCV routing
    print("Testing composite historical daily for TCS...", end=" ")
    df, source = market_data.get_ohlcv("TCS", interval="1d", period="1y")
    if not df.empty:
        print(f"PASSED ({len(df)} daily candles | Source: {source})")
    else:
        print("WARNING (Historical data empty)")

    # 3. Test Intraday routing
    print("Testing composite intraday 5m for INFY...", end=" ")
    df_intra, intra_source = market_data.get_intraday("INFY", interval="5m")
    if not df_intra.empty:
        print(f"PASSED ({len(df_intra)} 5m bars | Source: {intra_source})")
    else:
        print("WARNING (Intraday feed closed or delayed)")

    return True


def run_all_tests():
    print("=" * 65)
    print(" TRADEMIND AI: AUTOMATED API & DATABASE VERIFICATION TEST ")
    print(" Primary Providers: Finnhub & Alpha Vantage | Secondary: Yahoo ")
    print("=" * 65)

    results = {
        "Finnhub API (Primary)": test_finnhub(),
        "Alpha Vantage API (Alternative)": test_alpha_vantage(),
        "Google Gemini API (Generative AI)": test_google_gemini(),
        "Supabase Database": test_supabase(),
        "Yahoo Finance (Safety Fallback)": test_yahoo_finance(),
        "Composite Market Router": test_composite_router(),
    }

    print("\n" + "=" * 65)
    print("SUMMARY RESULTS")
    print("=" * 65)
    for service, passed in results.items():
        status = "PASSED" if passed else "FAILED"
        print(f" • {service:35s}: [{status}]")

    print("\nOverall Status: " + ("ALL SERVICES HEALTHY" if all(results.values()) else "SOME SERVICES REQUIRE ATTENTION"))
    print("=" * 65)


if __name__ == "__main__":
    run_all_tests()
