# 📈 TradeMind AI: Premium Indian Stock Market Assistant

TradeMind AI is a quantitative stock market research, prediction, and paper-trading platform built specifically for the **National Stock Exchange of India (NSE)**.

It features a fintech user experience inspired by **Groww's** clean, modern interface, powered by an asynchronous **FastAPI** backend and browser client.

---

## 🎨 Official Groww-Inspired Design System

### 1. Color Palette
- **Primary Brand:** Royal Purple (`#6C3CE9`), Deep Purple (`#5125B8`), Light Purple (`#F0EBFF`)
- **Backgrounds:** Pure White (`#FFFFFF`), Secondary Slate (`#F8F8FC`), Card White (`#FFFFFF`), Soft Lavender (`#F5F4FA`)
- **Typography:** Dark Primary (`#171923`), Secondary (`#747887`), Muted (`#A0A3AE`)
- **Trading Indicators:**
  - **BUY / Profit:** Emerald Green (`#16A36A`), Background (`#E8F7EF`)
  - **SELL / Loss:** Coral Red (`#E5484D`), Background (`#FDEBEC`)
  - **HOLD / Caution:** Amber Orange (`#E9A23B`), Background (`#FFF5E5`)

### 2. Dark Mode
- Includes a 1-click **Light/Dark Mode toggle**:
  - Dark Background: `#10121A`, Dark Cards: `#191D29`, Borders: `#303648`, Text: `#F5F5FA`

---

## 🌟 Key Application Modules

1. **🏛️ Market Dashboard**
   - Live NSE/BSE operational status badge (09:15 to 15:30 IST).
   - Real-time indices bar: **NIFTY 50**, **SENSEX**, **BANK NIFTY**, and **NIFTY IT**.
   - Portfolio summary, top gainers, top losers, and **Gemini 1.5 Flash AI** market commentary.

2. **🔍 Stock Explorer & Scanner**
   - Real-time equity scanner across NIFTY 50 and NIFTY Next 50 tickers.
   - Interactive tabs: *All Stocks*, *Top Gainers*, *Top Losers*, *High Volume*, *Momentum Leaders*, and *Breakout Alerts*.

3. **📊 Interactive Stock Details**
   - Click any stock to view company details, live quote, and responsive Plotly candlestick chart.
   - Timeframe switcher: **1D (5m)**, **5D (15m)**, **1M**, **6M**, **1Y**, and **5Y**.
   - Volume sub-panel, EMA 9/21 overlays, and computed Support/Resistance levels.

4. **⭐ Watchlist System**
   - Personal watchlist saved locally in browser storage (`localStorage`).
   - 1-click add/remove and direct trade placement.

5. **⚡ Intraday Prediction Engine**
   - 5-minute and 15-minute directional forecasting.
   - Dual-algorithm ensemble combining **Random Forest** and **XGBoost** with chronological out-of-sample data partitioning.
   - Gemini AI reasoning explaining technical factor alignment.

6. **📅 Next-Day Price & Direction Forecasts**
   - Daily candle forecasting using **Random Forest**, **XGBoost**, and **LSTM Recurrent Neural Networks**.
   - Regression projections for next-session closing prices and confidence levels.

7. **🎯 AI Trading Signal Engine**
   - Automated BUY / SELL / HOLD synthesis combining ML and technical factors (RSI, MACD, Volume Ratios, Bollinger Bands).
   - Dynamic **Entry Price**, **Target Price**, and **Stop-Loss** via Average True Range (ATR).
   - Computes Risk-to-Reward (R:R) ratio.

8. **📐 Technical Analysis Suite**
   - Full-screen technical inspection page with overlay indicators and dual oscillators (RSI 14 with 70/30 thresholds, MACD 12/26/9 histogram).

9. **💼 Portfolio & Paper Trading Simulator**
   - Practice trading on live NSE prices with zero financial risk.
   - Realistic Indian cost model: simulated brokerage (capped at ₹20), STT on delivery sell side, and 18% GST.
   - Live mark-to-market valuations and complete transaction history.

10. **📊 Quantitative Backtesting Engine**
    - Event-driven walk-forward backtest simulation on historical equity data.
    - Strategies: *EMA Crossover (9/21)*, *RSI + Bollinger Bands Mean Reversion*, *MACD Momentum*.
    - Visual equity curves, win rate, maximum drawdown, and Sharpe ratio reports.

11. **⚙️ Settings & System Health**
    - Live connection checks for **Supabase Cloud Database**, **Google Gemini API**, **Finnhub**, and **Yahoo Finance**.

---

## 🚀 How to Run TradeMind AI

### 1. Start the FastAPI Server:
```powershell
cd "c:\Users\ashut\OneDrive\Desktop\TRADE MIND AI\TradeMind_AI"
& "C:\Users\ashut\AppData\Local\Python\bin\python.exe" -m uvicorn server:app --host 127.0.0.1 --port 8000 --reload
```

### 2. Open in Browser:
Visit **`http://127.0.0.1:8000`** in your browser.
