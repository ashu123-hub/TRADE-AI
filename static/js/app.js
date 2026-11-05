/**
 * TradeMind AI — Frontend Application Logic
 * Groww-Inspired Fintech Single Page Application
 */

// ─── Global State ─────────────────────────────────────────────────────────────
let currentView = "dashboard";
let currentDetailSymbol = "RELIANCE";
let currentDetailPeriod = "1y";
let currentDetailInterval = "1d";
let scannerData = [];
let supportedUniverse = [];
let watchlist = JSON.parse(localStorage.getItem("trademind_watchlist") || '["RELIANCE", "TCS", "HDFCBANK", "INFY"]');

// ─── Theme Management (Light / Dark) ─────────────────────────────────────────
function initTheme() {
  const savedTheme = localStorage.getItem("trademind_theme") || "light";
  document.documentElement.setAttribute("data-theme", savedTheme);
  updateThemeButtonUI(savedTheme);

  document.getElementById("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "light";
    const next = cur === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    localStorage.setItem("trademind_theme", next);
    updateThemeButtonUI(next);
    // Redraw charts if on chart view
    if (currentView === "explore" || currentView === "technical" || currentView === "dashboard") {
      if (document.getElementById("stock-plotly-chart")) loadStockChart(currentDetailSymbol, currentDetailPeriod, currentDetailInterval);
      if (document.getElementById("ta-plotly-chart")) loadTechnicalChart();
    }
  });
}

function updateThemeButtonUI(theme) {
  const icon = document.getElementById("theme-icon");
  const label = document.getElementById("theme-label");
  if (theme === "dark") {
    icon.textContent = "☀️";
    label.textContent = "Light Mode";
  } else {
    icon.textContent = "🌙";
    label.textContent = "Dark Mode";
  }
}

// ─── Navigation Router ────────────────────────────────────────────────────────
function initNavigation() {
  const navLinks = document.querySelectorAll(".nav-link");
  navLinks.forEach(link => {
    link.addEventListener("click", (e) => {
      e.preventDefault();
      const targetView = link.getAttribute("data-view");
      switchView(targetView);
    });
  });
}

function switchView(viewName) {
  currentView = viewName;

  // Update nav links active class
  document.querySelectorAll(".nav-link").forEach(l => {
    if (l.getAttribute("data-view") === viewName) {
      l.classList.add("active");
    } else {
      l.classList.remove("active");
    }
  });

  // Switch visible section
  document.querySelectorAll(".view-section").forEach(sec => {
    sec.classList.remove("active");
  });

  const activeSec = document.getElementById(`view-${viewName}`);
  if (activeSec) {
    activeSec.classList.add("active");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // Auto-load view data
  if (viewName === "dashboard") loadDashboard();
  else if (viewName === "explore" && scannerData.length === 0) runScanner();
  else if (viewName === "watchlist") renderWatchlist();
  else if (viewName === "portfolio") loadPortfolio();
  else if (viewName === "signals") loadTradingSignals();
  else if (viewName === "settings") loadSettings();
  else if (viewName === "technical") loadTechnicalChart();
}

// ─── Toast Notifications ──────────────────────────────────────────────────────
function showToast(message, type = "info") {
  const toast = document.getElementById("toast-notify");
  const msgEl = document.getElementById("toast-message");
  msgEl.textContent = message;
  toast.className = `toast show ${type}`;
  setTimeout(() => {
    toast.classList.remove("show");
  }, 3500);
}

// ─── Global Search ────────────────────────────────────────────────────────────
function initGlobalSearch() {
  const input = document.getElementById("global-search-input");
  const dropdown = document.getElementById("search-dropdown");

  input.addEventListener("input", async (e) => {
    const q = e.target.value.trim();
    if (q.length < 1) {
      dropdown.style.display = "none";
      return;
    }

    try {
      const res = await fetch(`/api/search?q=${encodeURIComponent(q)}`);
      const data = await res.json();
      const matches = data.results || [];

      if (matches.length === 0) {
        dropdown.innerHTML = `<div style="padding:12px; font-size:0.85rem; color:var(--text-muted); text-align:center;">No matching NSE symbols found</div>`;
        dropdown.style.display = "block";
        return;
      }

      dropdown.innerHTML = matches.map(sym => `
        <div class="search-item" onclick="openStockDetail('${sym}')">
          <span class="sym">${sym}</span>
          <span class="tag">NSE Equity</span>
        </div>
      `).join("");
      dropdown.style.display = "block";
    } catch (err) {
      console.error(err);
    }
  });

  document.addEventListener("click", (e) => {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = "none";
    }
  });
}

// ─── Universe Setup ───────────────────────────────────────────────────────────
async function loadUniverse() {
  try {
    const res = await fetch("/api/universe");
    const data = await res.json();
    supportedUniverse = data.all_popular || [];
    
    // Populate select boxes across pages
    const selectIds = ["intra-stock-select", "next-stock-select", "ta-stock-select", "pt-stock-select", "bt-stock-select"];
    selectIds.forEach(id => {
      const sel = document.getElementById(id);
      if (sel) {
        sel.innerHTML = supportedUniverse.map(s => `<option value="${s}">${s}</option>`).join("");
      }
    });

    if (document.getElementById("pt-stock-select")) fetchPTStockPrice();
  } catch (err) {
    console.error("Failed to load stock universe:", err);
  }
}

// ─── 1. Dashboard View ────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    // 1. Market Overview & Indices
    const res = await fetch("/api/market-overview");
    const data = await res.json();

    const pill = document.getElementById("market-status-pill");
    const pillText = document.getElementById("market-status-text");
    if (data.market_status?.is_open) {
      pill.className = "market-status-pill open";
      pillText.textContent = `NSE Live (${data.market_status.current_time_ist})`;
    } else {
      pill.className = "market-status-pill closed";
      pillText.textContent = `NSE Closed (${data.market_status?.current_time_ist || 'IST'})`;
    }

    const indicesContainer = document.getElementById("indices-container");
    if (data.indices && Object.keys(data.indices).length > 0) {
      indicesContainer.innerHTML = Object.entries(data.indices).map(([name, idx]) => {
        const changePct = idx.change_pct;
        const isPos = changePct >= 0;
        const changeClass = isPos ? "positive" : "negative";
        const sign = isPos ? "+" : "";
        return `
          <div class="index-card">
            <div class="index-name">${name}</div>
            <div class="index-price">₹${(idx.price || 0).toLocaleString("en-IN", {minimumFractionDigits: 2, maximumFractionDigits: 2})}</div>
            <div class="index-change ${changeClass}">${sign}${changePct ? changePct.toFixed(2) : 0.00}%</div>
          </div>
        `;
      }).join("");
    }

    // 2. Top Movers
    const moversRes = await fetch("/api/top-movers?limit=5");
    const movers = await moversRes.json();

    const gainersBody = document.querySelector("#dash-gainers-table tbody");
    if (movers.gainers && movers.gainers.length > 0) {
      gainersBody.innerHTML = movers.gainers.map(g => `
        <tr onclick="openStockDetail('${g.symbol}')" style="cursor:pointer;">
          <td><strong>${g.symbol}</strong></td>
          <td>₹${g.current_price?.toFixed(2)}</td>
          <td class="positive">+${g.change_pct?.toFixed(2)}%</td>
          <td><button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); openOrderModal('${g.symbol}', 'BUY')">Trade</button></td>
        </tr>
      `).join("");
    }

    const losersBody = document.querySelector("#dash-losers-table tbody");
    if (movers.losers && movers.losers.length > 0) {
      losersBody.innerHTML = movers.losers.map(l => `
        <tr onclick="openStockDetail('${l.symbol}')" style="cursor:pointer;">
          <td><strong>${l.symbol}</strong></td>
          <td>₹${l.current_price?.toFixed(2)}</td>
          <td class="negative">${l.change_pct?.toFixed(2)}%</td>
          <td><button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); openOrderModal('${l.symbol}', 'BUY')">Trade</button></td>
        </tr>
      `).join("");
    }

    // 3. Portfolio Card Quick Summary
    const portRes = await fetch("/api/portfolio");
    const port = await portRes.json();
    if (port.summary) {
      document.getElementById("dash-port-val").textContent = `₹${port.summary.portfolio_value.toLocaleString("en-IN", {minimumFractionDigits: 2})}`;
      document.getElementById("dash-port-cash").textContent = `₹${port.summary.cash.toLocaleString("en-IN", {minimumFractionDigits: 2})}`;
      const retEl = document.getElementById("dash-port-ret");
      retEl.textContent = `${port.summary.total_return_pct >= 0 ? '+' : ''}${port.summary.total_return_pct.toFixed(2)}%`;
      retEl.className = port.summary.total_return_pct >= 0 ? "badge badge-buy" : "badge badge-sell";
    }

    // 4. AI Market Commentary
    const aiSummaryEl = document.getElementById("dash-ai-summary");
    aiSummaryEl.textContent = `NIFTY 50 and benchmark indices are trading with active domestic volume. Key support and resistance zones are holding across banking and IT equities. Technical setup reflects institutional consolidation ahead of macro data releases.`;

    // 5. Yahoo Finance Connection Check
    try {
      const yfRes = await fetch("/api/yahoo/status");
      const yfData = await yfRes.json();
      const yfPill = document.getElementById("yahoo-status-pill");
      if (yfPill && yfData.status === "connected") {
        yfPill.innerHTML = `<span style="font-size:0.75rem; font-weight:700;">📡 Yahoo Finance: Live</span>`;
      }
    } catch (e) {
      console.warn(e);
    }

  } catch (err) {
    console.error("Dashboard load error:", err);
  }
}

// ─── 2. Explore Stocks & Scanner ──────────────────────────────────────────────
async function runScanner() {
  const tbody = document.getElementById("scanner-table-body");
  tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:32px;">Scanning NSE universe (computing RSI, MACD, EMAs, Breakouts)...</td></tr>`;

  try {
    const res = await fetch("/api/scanner?max_symbols=35");
    const data = await res.json();
    scannerData = data.results || [];
    renderScanTable(scannerData);
    showToast(`Successfully scanned ${scannerData.length} NSE stocks!`, "success");
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; color:var(--color-sell); padding:24px;">Failed to load scanner data.</td></tr>`;
  }
}

function renderScanTable(stocks) {
  const tbody = document.getElementById("scanner-table-body");
  if (!stocks || stocks.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center; padding:24px;">No stocks match filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = stocks.map(s => {
    const isPos = s.change_pct >= 0;
    const changeClass = isPos ? "positive" : "negative";
    const sign = isPos ? "+" : "";
    const btype = s.breakout?.type || "NONE";
    const bColor = btype.includes("BULLISH") ? "var(--color-buy)" : (btype.includes("BEARISH") ? "var(--color-sell)" : "var(--text-muted)");

    return `
      <tr onclick="openStockDetail('${s.symbol}')" style="cursor:pointer;">
        <td><strong>${s.symbol}</strong></td>
        <td>₹${s.close?.toFixed(2)}</td>
        <td class="${changeClass}">${sign}${s.change_pct?.toFixed(2)}%</td>
        <td>${s.volume_ratio ? s.volume_ratio.toFixed(2) + 'x' : '--'}</td>
        <td>${s.rsi ? s.rsi.toFixed(1) : '--'}</td>
        <td>${s.macd ? s.macd.toFixed(2) : '--'}</td>
        <td><span class="badge ${s.momentum_score > 0.6 ? 'badge-buy' : 'badge-hold'}">${(s.momentum_score * 100).toFixed(0)}%</span></td>
        <td style="color:${bColor}; font-weight:600; font-size:0.8rem;">${btype !== 'NONE' ? btype : '--'}</td>
        <td><button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); openOrderModal('${s.symbol}', 'BUY')">Trade</button></td>
      </tr>
    `;
  }).join("");
}

function filterScanTable(filterType, element) {
  document.querySelectorAll(".filter-bar .pill-tab").forEach(p => p.classList.remove("active"));
  if (element) element.classList.add("active");

  if (!scannerData || scannerData.length === 0) return;

  let filtered = [...scannerData];
  if (filterType === "gainers") {
    filtered = filtered.sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0)).slice(0, 10);
  } else if (filterType === "losers") {
    filtered = filtered.sort((a, b) => (a.change_pct || 0) - (b.change_pct || 0)).slice(0, 10);
  } else if (filterType === "volume") {
    filtered = filtered.sort((a, b) => (b.volume_ratio || 0) - (a.volume_ratio || 0)).slice(0, 10);
  } else if (filterType === "momentum") {
    filtered = filtered.sort((a, b) => (b.momentum_score || 0) - (a.momentum_score || 0)).slice(0, 10);
  } else if (filterType === "breakouts") {
    filtered = filtered.filter(s => s.breakout && s.breakout.type !== "NONE");
  }

  renderScanTable(filtered);
}

// ─── 3. Stock Detail & Interactive Chart ──────────────────────────────────────
async function openStockDetail(symbol) {
  currentDetailSymbol = symbol;
  switchView("stock-detail");

  document.getElementById("detail-symbol").textContent = symbol;
  document.getElementById("detail-company-name").textContent = "Fetching company information...";

  // Check watchlist button
  const isWatch = watchlist.includes(symbol);
  document.getElementById("detail-watchlist-btn").textContent = isWatch ? "★ In Watchlist" : "⭐ Add to Watchlist";

  try {
    const res = await fetch(`/api/stock/${symbol}`);
    const data = await res.json();

    if (data.company_info?.company_name) {
      document.getElementById("detail-company-name").textContent = `${data.company_info.company_name} • ${data.company_info.sector || 'NSE'}`;
    }

    if (data.quote) {
      document.getElementById("detail-price").textContent = `₹${(data.quote.price || 0).toLocaleString("en-IN", {minimumFractionDigits: 2})}`;
      const change = data.quote.price - (data.quote.previous_close || data.quote.price);
      const changePct = (change / (data.quote.previous_close || 1)) * 100;
      const chgEl = document.getElementById("detail-change");
      chgEl.textContent = `${changePct >= 0 ? '+' : ''}${changePct.toFixed(2)}% (₹${change.toFixed(2)})`;
      chgEl.className = changePct >= 0 ? "stock-hero-change positive" : "stock-hero-change negative";
    }

    // Indicators
    const ind = data.indicators || {};
    document.getElementById("ind-rsi").textContent = ind.RSI ? ind.RSI.toFixed(1) : "--";
    document.getElementById("ind-macd").textContent = ind.MACD ? ind.MACD.toFixed(2) : "--";
    document.getElementById("ind-ema").textContent = ind.EMA_9 && ind.EMA_21 ? `₹${ind.EMA_9.toFixed(0)} / ₹${ind.EMA_21.toFixed(0)}` : "--";
    const sr = data.support_resistance || {};
    document.getElementById("ind-sr").textContent = sr.support && sr.resistance ? `S: ₹${sr.support.toFixed(0)} | R: ₹${sr.resistance.toFixed(0)}` : "--";

    // Load Default Chart
    loadStockChart(symbol, currentDetailPeriod, currentDetailInterval);
  } catch (err) {
    console.error("Detail load error:", err);
  }
}

function changeChartTimeframe(period, interval, btn) {
  currentDetailPeriod = period;
  currentDetailInterval = interval;
  document.querySelectorAll(".timeframe-selector .tf-btn").forEach(b => b.classList.remove("active"));
  if (btn) btn.classList.add("active");
  loadStockChart(currentDetailSymbol, period, interval);
}

async function loadStockChart(symbol, period, interval) {
  const chartEl = document.getElementById("stock-plotly-chart");
  chartEl.innerHTML = `<div style="display:flex; justify-content:center; align-items:center; height:100%; color:var(--text-muted);">Loading interactive candlestick chart...</div>`;

  try {
    const res = await fetch(`/api/stock/${symbol}/history?period=${period}&interval=${interval}`);
    const data = await res.json();
    const bars = data.bars || [];

    if (bars.length === 0) {
      chartEl.innerHTML = `<div style="display:flex; justify-content:center; align-items:center; height:100%; color:var(--text-muted);">No chart bars available for this timeframe.</div>`;
      return;
    }

    const times = bars.map(b => b.time);
    const opens = bars.map(b => b.open);
    const highs = bars.map(b => b.high);
    const lows = bars.map(b => b.low);
    const closes = bars.map(b => b.close);
    const vols = bars.map(b => b.volume);
    const volColors = closes.map((c, i) => c >= opens[i] ? "#16A36A" : "#E5484D");

    const traces = [
      {
        type: "candlestick",
        x: times,
        open: opens,
        high: highs,
        low: lows,
        close: closes,
        name: "Candles",
        increasing: { line: { color: "#16A36A" } },
        decreasing: { line: { color: "#E5484D" } },
        yaxis: "y1",
      },
      {
        type: "bar",
        x: times,
        y: vols,
        marker: { color: volColors },
        opacity: 0.3,
        name: "Volume",
        yaxis: "y2",
      }
    ];

    // EMA overlays if present
    if (bars[0].ema_9) {
      traces.push({
        type: "scatter", mode: "lines", x: times, y: bars.map(b => b.ema_9),
        name: "EMA 9", line: { color: "#3985E8", width: 1.5 }, yaxis: "y1"
      });
    }
    if (bars[0].ema_21) {
      traces.push({
        type: "scatter", mode: "lines", x: times, y: bars.map(b => b.ema_21),
        name: "EMA 21", line: { color: "#E9A23B", width: 1.5 }, yaxis: "y1"
      });
    }

    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    const layout = {
      template: isDark ? "plotly_dark" : "plotly_white",
      paper_bgcolor: isDark ? "#191D29" : "#FFFFFF",
      plot_bgcolor: isDark ? "#191D29" : "#FFFFFF",
      margin: { l: 40, r: 40, t: 10, b: 20 },
      showlegend: true,
      legend: { orientation: "h", y: 1.05, x: 0 },
      xaxis: {
        rangeslider: { visible: false },
        gridcolor: isDark ? "#262C3D" : "#F0EFF4",
      },
      yaxis: {
        title: "Price (₹)",
        domain: [0.25, 1],
        gridcolor: isDark ? "#262C3D" : "#F0EFF4",
      },
      yaxis2: {
        title: "Volume",
        domain: [0, 0.20],
        showgrid: false,
      }
    };

    Plotly.newPlot(chartEl, traces, layout, { responsive: true, displayModeBar: false });
  } catch (err) {
    console.error("Chart render error:", err);
  }
}

// ─── 4. Watchlist System ──────────────────────────────────────────────────────
function toggleCurrentWatchlist() {
  const sym = currentDetailSymbol;
  const idx = watchlist.indexOf(sym);
  if (idx > -1) {
    watchlist.splice(idx, 1);
    showToast(`Removed ${sym} from Watchlist`, "info");
    document.getElementById("detail-watchlist-btn").textContent = "⭐ Add to Watchlist";
  } else {
    watchlist.push(sym);
    showToast(`Added ${sym} to Watchlist`, "success");
    document.getElementById("detail-watchlist-btn").textContent = "★ In Watchlist";
  }
  localStorage.setItem("trademind_watchlist", JSON.stringify(watchlist));
  renderWatchlist();
}

async function renderWatchlist() {
  const tbody = document.getElementById("watchlist-table-body");
  if (watchlist.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:32px;">No stocks saved to watchlist. Click ⭐ on any stock to track.</td></tr>`;
    return;
  }

  tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:24px;">Loading watchlist quotes...</td></tr>`;

  const rows = [];
  for (const sym of watchlist) {
    try {
      const res = await fetch(`/api/stock/${sym}`);
      const data = await res.json();
      const q = data.quote || {};
      const change = q.price ? (q.price - (q.previous_close || q.price)) : 0;
      const changePct = q.previous_close ? (change / q.previous_close) * 100 : 0;
      const isPos = changePct >= 0;

      rows.push(`
        <tr onclick="openStockDetail('${sym}')" style="cursor:pointer;">
          <td><strong>${sym}</strong></td>
          <td>₹${(q.price || 0).toFixed(2)}</td>
          <td class="${isPos ? 'positive' : 'negative'}">${isPos ? '+' : ''}${changePct.toFixed(2)}%</td>
          <td>₹${(q.day_high || 0).toFixed(2)}</td>
          <td>₹${(q.day_low || 0).toFixed(2)}</td>
          <td>
            <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); openOrderModal('${sym}', 'BUY')">Trade</button>
            <button class="btn btn-secondary btn-sm" style="color:var(--color-sell);" onclick="event.stopPropagation(); removeWatchlist('${sym}')">Remove</button>
          </td>
        </tr>
      `);
    } catch (e) {
      console.warn(e);
    }
  }

  tbody.innerHTML = rows.join("");
}

function removeWatchlist(sym) {
  watchlist = watchlist.filter(s => s !== sym);
  localStorage.setItem("trademind_watchlist", JSON.stringify(watchlist));
  renderWatchlist();
  showToast(`Removed ${sym} from Watchlist`, "info");
}

// ─── 5. Intraday Prediction ───────────────────────────────────────────────────
async function runIntradayPrediction() {
  const sym = document.getElementById("intra-stock-select").value;
  const interval = document.getElementById("intra-interval-select").value;

  const resCard = document.getElementById("intra-result-card");
  resCard.style.display = "block";
  document.getElementById("intra-direction").textContent = "Calculating...";
  document.getElementById("intra-ai-exp").textContent = "Requesting model inference...";

  try {
    const res = await fetch("/api/predict/intraday", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym, interval: interval })
    });
    const data = await res.json();

    const sig = data.signal || "HOLD";
    const badge = document.getElementById("intra-badge");
    badge.textContent = sig;
    badge.className = `badge badge-${sig.toLowerCase()}`;

    document.getElementById("intra-direction").textContent = `${data.direction || 'NEUTRAL'} (${sig})`;
    document.getElementById("intra-confidence").textContent = `${((data.confidence || 0) * 100).toFixed(1)}%`;
    document.getElementById("intra-rf-sig").textContent = `${data.rf_signal?.signal || '--'} (${((data.rf_signal?.confidence || 0) * 100).toFixed(0)}%)`;
    document.getElementById("intra-xgb-sig").textContent = `${data.xgb_signal?.signal || '--'} (${((data.xgb_signal?.confidence || 0) * 100).toFixed(0)}%)`;
    document.getElementById("intra-ai-exp").textContent = data.ai_explanation || "No commentary available.";
  } catch (err) {
    showToast("Intraday prediction failed.", "error");
  }
}

// ─── 6. Next-Day Prediction ───────────────────────────────────────────────────
async function runNextDayPrediction() {
  const sym = document.getElementById("next-stock-select").value;

  const resCard = document.getElementById("next-result-card");
  resCard.style.display = "block";
  document.getElementById("next-pred-price").textContent = "Computing models...";

  try {
    const res = await fetch("/api/predict/next-day", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym })
    });
    const data = await res.json();

    const sig = data.signal || "HOLD";
    const badge = document.getElementById("next-badge");
    badge.textContent = sig;
    badge.className = `badge badge-${sig.toLowerCase()}`;

    if (data.predicted_price) {
      document.getElementById("next-pred-price").textContent = `₹${data.predicted_price.toFixed(2)}`;
      const chg = data.predicted_change_pct || 0;
      const chgBadge = document.getElementById("next-pred-change");
      chgBadge.textContent = `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}% expected`;
      chgBadge.className = chg >= 0 ? "badge badge-buy" : "badge badge-sell";
    } else {
      document.getElementById("next-pred-price").textContent = `₹${(data.current_price || 0).toFixed(2)}`;
      document.getElementById("next-pred-change").textContent = "Directional only";
    }

    document.getElementById("next-rf-sig").textContent = `${data.rf_signal?.signal || '--'}`;
    document.getElementById("next-xgb-sig").textContent = `${data.xgb_signal?.signal || '--'}`;
    document.getElementById("next-conf").textContent = `${((data.confidence || 0) * 100).toFixed(1)}%`;
    document.getElementById("next-ai-exp").textContent = data.ai_explanation || "No commentary available.";
  } catch (err) {
    showToast("Next-day prediction failed.", "error");
  }
}

// ─── 7. AI Trading Signals ────────────────────────────────────────────────────
async function loadTradingSignals() {
  const container = document.getElementById("signals-container");
  container.innerHTML = `<div class="card"><p>Generating algorithmic signals across top NSE equities...</p></div>`;

  try {
    const res = await fetch("/api/signals");
    const data = await res.json();
    const signals = data.signals || [];

    if (signals.length === 0) {
      container.innerHTML = `<div class="card"><p>No signals available. Check API connectivity.</p></div>`;
      return;
    }

    container.innerHTML = signals.map(s => {
      const sig = s.signal || "HOLD";
      return `
        <div class="card">
          <div class="card-header">
            <div>
              <h3 style="font-size:1.2rem; font-weight:700;">${s.symbol}</h3>
              <p style="font-size:0.8rem; color:var(--text-secondary);">Score: ${s.score?.toFixed(3)}</p>
            </div>
            <span class="badge badge-${sig.toLowerCase()}">${sig}</span>
          </div>
          <div class="grid-2" style="margin-bottom:14px; font-size:0.85rem;">
            <div><span>Entry:</span> <strong>₹${s.entry_price?.toFixed(2)}</strong></div>
            <div><span>Target:</span> <strong style="color:var(--color-buy);">₹${s.target_price?.toFixed(2)}</strong></div>
            <div><span>Stop-Loss:</span> <strong style="color:var(--color-sell);">₹${s.stop_loss?.toFixed(2)}</strong></div>
            <div><span>R:R Ratio:</span> <strong>${s.risk_reward_ratio?.toFixed(2)}:1</strong></div>
          </div>
          <div style="display:flex; gap:8px;">
            <button class="btn btn-secondary btn-sm" style="flex:1;" onclick="openStockDetail('${s.symbol}')">Chart</button>
            <button class="btn btn-primary btn-sm" style="flex:1;" onclick="openOrderModal('${s.symbol}', '${sig === 'SELL' ? 'SELL' : 'BUY'}')">Execute</button>
          </div>
        </div>
      `;
    }).join("");
  } catch (err) {
    container.innerHTML = `<div class="card"><p style="color:var(--color-sell);">Failed to load trading signals.</p></div>`;
  }
}

// ─── 8. Technical Analysis Suite ──────────────────────────────────────────────
async function loadTechnicalChart() {
  const sym = document.getElementById("ta-stock-select")?.value || "RELIANCE";
  const chartEl = document.getElementById("ta-plotly-chart");
  chartEl.innerHTML = `<div style="display:flex; justify-content:center; align-items:center; height:100%; color:var(--text-muted);">Rendering technical indicators...</div>`;

  try {
    const res = await fetch(`/api/stock/${sym}/history?period=1y&interval=1d`);
    const data = await res.json();
    const bars = data.bars || [];

    const times = bars.map(b => b.time);
    const opens = bars.map(b => b.open);
    const highs = bars.map(b => b.high);
    const lows = bars.map(b => b.low);
    const closes = bars.map(b => b.close);

    const traces = [
      {
        type: "candlestick", x: times, open: opens, high: highs, low: lows, close: closes,
        name: "Candles", yaxis: "y1",
        increasing: { line: { color: "#16A36A" } }, decreasing: { line: { color: "#E5484D" } }
      },
      {
        type: "scatter", mode: "lines", x: times, y: bars.map(b => b.ema_9),
        name: "EMA 9", line: { color: "#3985E8", width: 1.2 }, yaxis: "y1"
      },
      {
        type: "scatter", mode: "lines", x: times, y: bars.map(b => b.ema_21),
        name: "EMA 21", line: { color: "#E9A23B", width: 1.2 }, yaxis: "y1"
      },
      {
        type: "scatter", mode: "lines", x: times, y: bars.map(b => b.bb_upper),
        name: "BB Upper", line: { color: "rgba(108,60,233,0.4)", dash: "dot" }, yaxis: "y1"
      },
      {
        type: "scatter", mode: "lines", x: times, y: bars.map(b => b.bb_lower),
        name: "BB Lower", line: { color: "rgba(108,60,233,0.4)", dash: "dot" }, yaxis: "y1"
      },
      {
        type: "scatter", mode: "lines", x: times, y: bars.map(b => b.rsi),
        name: "RSI", line: { color: "#6C3CE9", width: 1.5 }, yaxis: "y2"
      }
    ];

    const isDark = document.documentElement.getAttribute("data-theme") === "dark";
    const layout = {
      template: isDark ? "plotly_dark" : "plotly_white",
      paper_bgcolor: isDark ? "#191D29" : "#FFFFFF",
      plot_bgcolor: isDark ? "#191D29" : "#FFFFFF",
      margin: { l: 40, r: 40, t: 10, b: 20 },
      showlegend: true,
      legend: { orientation: "h", y: 1.05 },
      xaxis: { rangeslider: { visible: false }, gridcolor: isDark ? "#262C3D" : "#F0EFF4" },
      yaxis: { domain: [0.35, 1], title: "Price (₹)", gridcolor: isDark ? "#262C3D" : "#F0EFF4" },
      yaxis2: { domain: [0, 0.28], title: "RSI (14)", range: [0, 100], gridcolor: isDark ? "#262C3D" : "#F0EFF4" }
    };

    Plotly.newPlot(chartEl, traces, layout, { responsive: true, displayModeBar: false });
  } catch (err) {
    console.error("Technical chart error:", err);
  }
}

// ─── 9. Portfolio View ────────────────────────────────────────────────────────
async function loadPortfolio() {
  try {
    const res = await fetch("/api/portfolio");
    const data = await res.json();
    const summary = data.summary || {};

    document.getElementById("port-total-val").textContent = `₹${(summary.portfolio_value || 0).toLocaleString("en-IN", {minimumFractionDigits: 2})}`;
    document.getElementById("port-cash-val").textContent = `₹${(summary.cash || 0).toLocaleString("en-IN", {minimumFractionDigits: 2})}`;
    const pnlEl = document.getElementById("port-pnl-val");
    pnlEl.textContent = `₹${(summary.total_return || 0).toFixed(2)}`;
    pnlEl.className = summary.total_return >= 0 ? "positive" : "negative";
    document.getElementById("port-daily-val").textContent = `₹${(summary.daily_pnl || 0).toFixed(2)}`;

    // Holdings Table
    const hbody = document.getElementById("holdings-table-body");
    const holdings = data.holdings || [];
    if (holdings.length === 0) {
      hbody.innerHTML = `<tr><td colspan="8" style="text-align:center; padding:24px;">No active holdings. Place a simulated trade.</td></tr>`;
    } else {
      hbody.innerHTML = holdings.map(h => {
        const curVal = h.quantity * h.current_price;
        const pnl = h.unrealised_pnl || 0;
        const pnlPct = h.unrealised_pnl_pct || 0;
        const isPos = pnl >= 0;
        return `
          <tr onclick="openStockDetail('${h.symbol}')" style="cursor:pointer;">
            <td><strong>${h.symbol}</strong></td>
            <td>${h.quantity}</td>
            <td>₹${h.avg_price?.toFixed(2)}</td>
            <td>₹${h.current_price?.toFixed(2)}</td>
            <td>₹${curVal.toFixed(2)}</td>
            <td class="${isPos ? 'positive' : 'negative'}">${isPos ? '+' : ''}₹${pnl.toFixed(2)}</td>
            <td class="${isPos ? 'positive' : 'negative'}">${isPos ? '+' : ''}${pnlPct.toFixed(2)}%</td>
            <td>
              <button class="btn btn-sell btn-sm" onclick="event.stopPropagation(); openOrderModal('${h.symbol}', 'SELL')">Exit</button>
            </td>
          </tr>
        `;
      }).join("");
    }

    // Transactions Table
    const tbody = document.getElementById("transactions-table-body");
    const txns = data.transactions || [];
    if (txns.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:24px;">No transactions recorded yet.</td></tr>`;
    } else {
      tbody.innerHTML = txns.map(t => `
        <tr>
          <td>${t.timestamp ? t.timestamp.substring(0, 16).replace('T', ' ') : '--'}</td>
          <td><strong>${t.symbol}</strong></td>
          <td><span class="badge ${t.type === 'BUY' ? 'badge-buy' : 'badge-sell'}">${t.type}</span></td>
          <td>${t.quantity}</td>
          <td>₹${t.price?.toFixed(2)}</td>
          <td>₹${t.brokerage?.toFixed(2)}</td>
          <td>₹${((t.quantity * t.price) + (t.brokerage || 0)).toFixed(2)}</td>
        </tr>
      `).join("");
    }
  } catch (err) {
    console.error("Portfolio load error:", err);
  }
}

// ─── 10. Paper Trading Execution ──────────────────────────────────────────────
async function fetchPTStockPrice() {
  const sym = document.getElementById("pt-stock-select").value;
  try {
    const res = await fetch(`/api/stock/${sym}`);
    const data = await res.json();
    if (data.quote?.price) {
      document.getElementById("pt-price-input").value = data.quote.price.toFixed(2);
      updateBrokerageCalc();
    }
  } catch (e) {
    console.warn(e);
  }
}

async function updateBrokerageCalc() {
  const qty = parseInt(document.getElementById("pt-qty-input").value) || 0;
  const price = parseFloat(document.getElementById("pt-price-input").value) || 0;
  const side = document.getElementById("pt-side-select").value;

  const turnover = qty * price;
  document.getElementById("pt-turnover").textContent = `₹${turnover.toLocaleString("en-IN", {minimumFractionDigits: 2})}`;

  try {
    const res = await fetch(`/api/brokerage-estimate?quantity=${qty}&price=${price}&side=${side}`);
    const brok = await res.json();
    document.getElementById("pt-charges").textContent = `₹${brok.total_charges.toFixed(2)}`;
    const total = side === "BUY" ? (turnover + brok.total_charges) : (turnover - brok.total_charges);
    document.getElementById("pt-total-cost").textContent = `₹${total.toLocaleString("en-IN", {minimumFractionDigits: 2})}`;
  } catch (e) {
    console.warn(e);
  }
}

async function executePaperTrade() {
  const sym = document.getElementById("pt-stock-select").value;
  const side = document.getElementById("pt-side-select").value;
  const qty = parseInt(document.getElementById("pt-qty-input").value) || 0;
  const price = parseFloat(document.getElementById("pt-price-input").value) || 0;

  if (qty <= 0 || price <= 0) {
    showToast("Invalid quantity or price.", "error");
    return;
  }

  const endpoint = side === "BUY" ? "/api/portfolio/buy" : "/api/portfolio/sell";
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym, quantity: qty, price: price })
    });
    const data = await res.json();

    if (!res.ok) {
      showToast(data.detail || "Order failed.", "error");
    } else {
      showToast(`Simulated ${side} order for ${qty} shares of ${sym} executed!`, "success");
      loadPortfolio();
    }
  } catch (err) {
    showToast("Trade execution error.", "error");
  }
}

async function resetPaperPortfolio() {
  if (!confirm("Are you sure you want to reset your paper trading capital to ₹10,00,000?")) return;
  try {
    const res = await fetch("/api/portfolio/reset", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ capital: 1000000.0 })
    });
    if (res.ok) {
      showToast("Paper portfolio reset to ₹10,00,000 capital.", "success");
      loadPortfolio();
    }
  } catch (err) {
    showToast("Reset failed.", "error");
  }
}

// ─── 11. Backtesting Engine ───────────────────────────────────────────────────
async function runBacktest() {
  const sym = document.getElementById("bt-stock-select").value;
  const strat = document.getElementById("bt-strategy-select").value;
  const period = document.getElementById("bt-period-select").value;
  const cap = parseFloat(document.getElementById("bt-capital-input").value) || 100000;
  const sl = parseFloat(document.getElementById("bt-sl-input").value) || 2.0;
  const tp = parseFloat(document.getElementById("bt-tp-input").value) || 4.0;

  const card = document.getElementById("bt-results-card");
  card.style.display = "block";
  document.getElementById("bt-ret").textContent = "Simulating...";

  try {
    const res = await fetch("/api/backtest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        symbol: sym,
        strategy: strat,
        period: period,
        initial_capital: cap,
        stop_loss_pct: sl,
        take_profit_pct: tp
      })
    });
    const data = await res.json();

    if (!res.ok) {
      showToast(data.detail || "Backtest failed.", "error");
      return;
    }

    const m = data.metrics || {};
    const retEl = document.getElementById("bt-ret");
    retEl.textContent = `${m.total_return_pct >= 0 ? '+' : ''}${m.total_return_pct?.toFixed(2)}%`;
    retEl.className = m.total_return_pct >= 0 ? "positive" : "negative";

    document.getElementById("bt-winrate").textContent = `${((m.win_rate || 0) * 100).toFixed(1)}%`;
    document.getElementById("bt-dd").textContent = `${m.max_drawdown_pct?.toFixed(2)}%`;
    document.getElementById("bt-sharpe").textContent = m.sharpe_ratio?.toFixed(2) || "0.00";

    // Equity Curve Chart
    const eqCurve = data.equity_curve || [];
    if (eqCurve.length > 0) {
      const dates = eqCurve.map(e => e.date);
      const equities = eqCurve.map(e => e.equity);
      const isDark = document.documentElement.getAttribute("data-theme") === "dark";

      Plotly.newPlot("bt-equity-chart", [{
        type: "scatter", mode: "lines", x: dates, y: equities,
        fill: "tozeroy", line: { color: "#6C3CE9", width: 2 },
        name: "Equity (₹)"
      }], {
        template: isDark ? "plotly_dark" : "plotly_white",
        paper_bgcolor: isDark ? "#191D29" : "#FFFFFF",
        plot_bgcolor: isDark ? "#191D29" : "#FFFFFF",
        margin: { l: 40, r: 20, t: 10, b: 20 },
        xaxis: { gridcolor: isDark ? "#262C3D" : "#F0EFF4" },
        yaxis: { gridcolor: isDark ? "#262C3D" : "#F0EFF4" }
      }, { responsive: true, displayModeBar: false });
    }
  } catch (err) {
    showToast("Backtest execution error.", "error");
  }
}

// ─── 12. Settings & Diagnostics ───────────────────────────────────────────────
async function loadSettings() {
  const listEl = document.getElementById("settings-keys-list");
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    const services = data.services || {};

    listEl.innerHTML = Object.entries(services).map(([key, s]) => {
      const isConn = s.status === "connected";
      const badgeClass = isConn ? "badge-buy" : "badge-hold";
      const icon = isConn ? "🟢" : "⚪";
      return `
        <div style="padding:12px; margin-bottom:10px; background:var(--bg-lavender); border-radius:var(--radius-md); border:1px solid var(--border);">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <strong>${icon} ${s.name}</strong>
            <span class="badge ${badgeClass}">${s.status.toUpperCase()}</span>
          </div>
          ${s.role ? `<p style="font-size:0.75rem; color:var(--primary-purple); font-weight:600; margin:0 0 2px 0;">Role: ${s.role}</p>` : ""}
          <p style="font-size:0.8rem; color:var(--text-secondary); margin:0;">Coverage: ${s.coverage}</p>
        </div>
      `;
    }).join("");

    // Populate masked key placeholders if configured
    if (data.masked_keys) {
      const mk = data.masked_keys;
      const yKey = document.getElementById("cfg-yahoo-key");
      if (yKey && !yKey.value && mk.yahoo_finance) yKey.placeholder = `Configured (${mk.yahoo_finance})`;

      const gInput = document.getElementById("cfg-gemini-key");
      if (gInput && !gInput.value && mk.gemini) gInput.placeholder = `Configured (${mk.gemini})`;

      const sUrl = document.getElementById("cfg-supabase-url");
      if (sUrl && !sUrl.value && mk.supabase_url) sUrl.value = mk.supabase_url;

      const sKey = document.getElementById("cfg-supabase-key");
      if (sKey && !sKey.value && mk.supabase_anon_key) sKey.placeholder = `Configured (${mk.supabase_anon_key})`;

      const fKey = document.getElementById("cfg-finnhub-key");
      if (fKey && !fKey.value && mk.finnhub) fKey.placeholder = `Configured (${mk.finnhub})`;

      const aKey = document.getElementById("cfg-alphavantage-key");
      if (aKey && !aKey.value && mk.alpha_vantage) aKey.placeholder = `Configured (${mk.alpha_vantage})`;
    }
  } catch (err) {
    listEl.textContent = "Error reading diagnostic info.";
  }
}

function togglePasswordVisibility(inputId) {
  const el = document.getElementById(inputId);
  if (!el) return;
  el.type = el.type === "password" ? "text" : "password";
}

async function testServiceKey(service) {
  const feedbackEl = document.getElementById(`test-feedback-${service}`);
  if (feedbackEl) {
    feedbackEl.style.display = "block";
    feedbackEl.style.color = "var(--text-secondary)";
    feedbackEl.innerHTML = "<em>Testing connection...</em>";
  }

  let key = "";
  let url = "";
  if (service === "yahoo_finance") key = document.getElementById("cfg-yahoo-key").value;
  else if (service === "gemini") key = document.getElementById("cfg-gemini-key").value;
  else if (service === "finnhub") key = document.getElementById("cfg-finnhub-key").value;
  else if (service === "alpha_vantage") key = document.getElementById("cfg-alphavantage-key").value;
  else if (service === "supabase") {
    url = document.getElementById("cfg-supabase-url").value;
    key = document.getElementById("cfg-supabase-key").value;
  }

  try {
    const res = await fetch("/api/settings/test-key", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ service, key, url })
    });
    const result = await res.json();
    if (feedbackEl) {
      if (result.valid) {
        feedbackEl.style.color = "var(--accent-green)";
        feedbackEl.innerHTML = `✅ ${result.message}`;
      } else {
        feedbackEl.style.color = "var(--accent-red)";
        feedbackEl.innerHTML = `❌ ${result.message}`;
      }
    }
  } catch (err) {
    if (feedbackEl) {
      feedbackEl.style.color = "var(--accent-red)";
      feedbackEl.innerHTML = `❌ Request failed: ${err.message}`;
    }
  }
}

async function saveApiKeys() {
  const btn = document.getElementById("btn-save-keys");
  const origText = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = "⏳ Saving...";

  const payload = {};
  const yahoo = document.getElementById("cfg-yahoo-key").value.trim();
  const gemini = document.getElementById("cfg-gemini-key").value.trim();
  const subUrl = document.getElementById("cfg-supabase-url").value.trim();
  const subKey = document.getElementById("cfg-supabase-key").value.trim();
  const finnhub = document.getElementById("cfg-finnhub-key").value.trim();
  const av = document.getElementById("cfg-alphavantage-key").value.trim();

  if (yahoo) payload.yahoo_finance_api_key = yahoo;
  if (gemini) payload.gemini_api_key = gemini;
  if (subUrl) payload.supabase_url = subUrl;
  if (subKey) payload.supabase_anon_key = subKey;
  if (finnhub) payload.finnhub_api_key = finnhub;
  if (av) payload.alpha_vantage_api_key = av;

  try {
    const res = await fetch("/api/settings/keys", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (data.success) {
      showToast("API keys saved and applied successfully!", "success");
      await loadSettings();
    } else {
      showToast(data.message || "Failed to save keys", "error");
    }
  } catch (err) {
    showToast(`Error saving keys: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = origText;
  }
}

// ─── Quick Order Modal ────────────────────────────────────────────────────────
async function openOrderModal(symbol, side = "BUY") {
  document.getElementById("modal-sym").value = symbol;
  document.getElementById("modal-side").value = side;
  document.getElementById("modal-qty").value = 10;
  document.getElementById("modal-order-title").textContent = `Place Simulated ${side} Order`;

  try {
    const res = await fetch(`/api/stock/${symbol}`);
    const data = await res.json();
    if (data.quote?.price) {
      document.getElementById("modal-price").value = data.quote.price.toFixed(2);
      updateModalCalc();
    }
  } catch (e) {
    console.warn(e);
  }

  document.getElementById("order-modal").classList.add("active");
}

function closeOrderModal() {
  document.getElementById("order-modal").classList.remove("active");
}

function updateModalCalc() {
  const qty = parseInt(document.getElementById("modal-qty").value) || 0;
  const price = parseFloat(document.getElementById("modal-price").value) || 0;
  const turnover = qty * price;
  document.getElementById("modal-total-cost").textContent = `₹${turnover.toLocaleString("en-IN", {minimumFractionDigits: 2})}`;
}

async function submitModalOrder() {
  const sym = document.getElementById("modal-sym").value;
  const side = document.getElementById("modal-side").value;
  const qty = parseInt(document.getElementById("modal-qty").value) || 0;
  const price = parseFloat(document.getElementById("modal-price").value) || 0;

  if (qty <= 0 || price <= 0) {
    showToast("Please provide valid quantity and price.", "error");
    return;
  }

  const endpoint = side === "BUY" ? "/api/portfolio/buy" : "/api/portfolio/sell";
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: sym, quantity: qty, price: price })
    });
    const data = await res.json();

    if (!res.ok) {
      showToast(data.detail || "Order rejected.", "error");
    } else {
      closeOrderModal();
      showToast(`Simulated ${side} order for ${qty} shares of ${sym} executed!`, "success");
      loadPortfolio();
    }
  } catch (err) {
    showToast("Order submission error.", "error");
  }
}

// ─── Initialization on DOM Ready ──────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initTheme();
  initNavigation();
  initGlobalSearch();
  loadUniverse();
  loadDashboard();
});

