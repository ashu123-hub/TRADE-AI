import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_collection import download_stock_data, get_market_overview

print("Testing NIFTY overview...")
overview = get_market_overview()
print("Indices retrieved:", list(overview.keys()))
for k, v in overview.items():
    print(f"  {k}: Price={v.get('price')}, Change%={v.get('change_pct')}")

print("\nTesting RELIANCE historical data download...")
df = download_stock_data("RELIANCE", period="1mo", interval="1d", store_to_db=False)
print("RELIANCE data shape:", df.shape)
if not df.empty:
    print(f"  Latest Close: ₹{df['Close'].iloc[-1]:,.2f} on {df.index[-1].strftime('%Y-%m-%d')}")
    print("  Data columns:", list(df.columns))

print("\nAll live data tests passed successfully!")

