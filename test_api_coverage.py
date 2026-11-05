"""
TradeMind AI - API Coverage & Free-Tier Limit Verification Suite
Tests Finnhub and Alpha Vantage for:
1. NSE / Indian equity symbol resolution.
2. Historical Daily OHLCV candles.
3. Intraday 5-minute and 15-minute candles.
4. Real-time quote snapshots.
5. Rate limits and free-tier constraints.
"""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from config import api_keys, settings

TEST_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "SBIN"]

def test_finnhub_coverage():
    print("\n" + "=" * 65)
    print("1. FINNHUB API - COVERAGE & LIMITS TEST")
    print("=" * 65)

    key = api_keys.finnhub
    if not key:
        print("[Finnhub] No FINNHUB_API_KEY set in environment or .env.")
        print("[Finnhub] Documentation specifications:")
        print("  - Free-tier rate limit: 60 requests/minute.")
        print("  - Endpoint /quote supports select international symbols with 'NSE:' prefix.")
        print("  - Endpoint /stock/candle supports resolutions: 1, 5, 15, 30, 60, D, W, M.")
        print("  - Coverage Note: Free-tier candles on non-US exchanges (NSE) return 'no_data' unless subscription covers global feeds.")
        print("  - Company profile and market news are fully functional on free tier.")
        return

    headers = {"X-Finnhub-Token": key}
    base_url = "https://finnhub.io/api/v1"

    # Test 1: Quotes with different symbol variations
    print("\n--- Testing Quotes (/quote) ---")
    for sym in TEST_SYMBOLS[:2]:
        for candidate in [f"NSE:{sym}", sym, f"{sym}.NS"]:
            url = f"{base_url}/quote?symbol={candidate}"
            try:
                r = requests.get(url, headers=headers, timeout=8)
                data = r.json() if r.status_code == 200 else {}
                c_price = data.get("c") if isinstance(data, dict) else None
                print(f"  Symbol '{candidate}': status={r.status_code}, c={c_price}")
            except Exception as e:
                print(f"  Symbol '{candidate}': error={e}")

    # Test 2: Daily and Intraday Candles (/stock/candle)
    print("\n--- Testing Candles (/stock/candle) ---")
    now_ts = int(time.time())
    from_ts_daily = now_ts - (30 * 86400) # 30 days
    from_ts_intra = now_ts - (2 * 86400)  # 2 days

    resolutions = [
        ("Daily", "D", from_ts_daily),
        ("15-Minute", "15", from_ts_intra),
        ("5-Minute", "5", from_ts_intra),
    ]

    for label, res, f_ts in resolutions:
        candidate = f"NSE:{TEST_SYMBOLS[0]}"
        url = f"{base_url}/stock/candle?symbol={candidate}&resolution={res}&from={f_ts}&to={now_ts}"
        try:
            r = requests.get(url, headers=headers, timeout=8)
            data = r.json() if r.status_code == 200 else {}
            status_str = data.get("s") if isinstance(data, dict) else None
            num_bars = len(data.get("c", [])) if isinstance(data, dict) and "c" in data else 0
            print(f"  {label} ({res}) on '{candidate}': HTTP {r.status_code}, status='{status_str}', bars={num_bars}")
        except Exception as e:
            print(f"  {label} ({res}) on '{candidate}': error={e}")


def test_alpha_vantage_coverage():
    print("\n" + "=" * 65)
    print("2. ALPHA VANTAGE API - COVERAGE & LIMITS TEST")
    print("=" * 65)

    key = api_keys.alpha_vantage
    if not key:
        print("[Alpha Vantage] No ALPHA_VANTAGE_API_KEY set in environment or .env.")
        print("[Alpha Vantage] Documentation specifications:")
        print("  - Free-tier rate limit: 5 requests/minute, 25 requests/day maximum.")
        print("  - Indian equities covered via Bombay Stock Exchange (BSE:SYMBOL or SYMBOL.BSE).")
        print("  - TIME_SERIES_DAILY returns full/compact historical daily OHLCV.")
        print("  - TIME_SERIES_INTRADAY supports interval=5min and interval=15min.")
        print("  - Strict caching and throttle intervals (12s minimum) required to preserve daily budget.")
        return

    base_url = "https://www.alphavantage.co/query"

    # Test 1: Daily Historical Time Series
    print("\n--- Testing Daily Historical (TIME_SERIES_DAILY) ---")
    sym = TEST_SYMBOLS[0]
    for candidate in [f"BSE:{sym}", f"{sym}.BSE", f"NSE:{sym}"]:
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": candidate,
            "outputsize": "compact",
            "apikey": key,
        }
        try:
            r = requests.get(base_url, params=params, timeout=10)
            data = r.json()
            if "Time Series (Daily)" in data:
                bars = len(data["Time Series (Daily)"])
                print(f"  Symbol '{candidate}': SUCCESS ({bars} daily bars returned)")
                break
            elif "Note" in data:
                print(f"  Symbol '{candidate}': RATE LIMITED ({data['Note'][:60]}...)")
            elif "Information" in data:
                print(f"  Symbol '{candidate}': NOTICE ({data['Information'][:60]}...)")
            elif "Error Message" in data:
                print(f"  Symbol '{candidate}': NOT FOUND / ERROR")
            else:
                print(f"  Symbol '{candidate}': Response keys: {list(data.keys())}")
        except Exception as e:
            print(f"  Symbol '{candidate}': error={e}")

    # Wait to respect 5 calls/min limit
    time.sleep(12)

    # Test 2: Intraday 5min and 15min
    print("\n--- Testing Intraday (TIME_SERIES_INTRADAY) ---")
    for interval in ["5min", "15min"]:
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": f"BSE:{sym}",
            "interval": interval,
            "outputsize": "compact",
            "apikey": key,
        }
        try:
            r = requests.get(base_url, params=params, timeout=10)
            data = r.json()
            key_name = f"Time Series ({interval})"
            if key_name in data:
                bars = len(data[key_name])
                print(f"  Interval '{interval}' on 'BSE:{sym}': SUCCESS ({bars} intraday bars returned)")
            elif "Note" in data:
                print(f"  Interval '{interval}': RATE LIMITED")
            elif "Information" in data:
                print(f"  Interval '{interval}': NOTICE ({data['Information'][:60]}...)")
            else:
                print(f"  Interval '{interval}': Response: {list(data.keys())}")
        except Exception as e:
            print(f"  Interval '{interval}': error={e}")
        time.sleep(12)


if __name__ == "__main__":
    print("=================================================================")
    print(" TRADEMIND AI: MARKET DATA PROVIDER CAPABILITY & LIMIT AUDIT ")
    print("=================================================================")
    test_finnhub_coverage()
    test_alpha_vantage_coverage()
    print("\n=================================================================")
    print(" AUDIT COMPLETED ")
    print("=================================================================")

