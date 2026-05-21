const state = {
  refreshSeconds: Number(window.DASHBOARD_REFRESH_SECONDS || 5),
  watchlist: [],
  watchlistPrices: {},
  tradeHistory: {
    page: 1,
    pageSize: 25,
    pages: 1,
    total: 0,
  },
};

const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const number = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 4,
});

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = value;
  }
}

function signedMoney(value) {
  const amount = Number(value || 0);
  return `${amount >= 0 ? "" : "-"}${money.format(Math.abs(amount))}`;
}

function pct(value) {
  return `${(Number(value || 0) * 100).toFixed(2)}%`;
}

function plClass(value) {
  return Number(value || 0) >= 0 ? "positive" : "negative";
}

async function fetchSnapshot() {
  const response = await fetch("/api/snapshot", { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Snapshot request failed: ${response.status}`);
  }
  return response.json();
}

async function fetchWatchlist() {
  const response = await fetch("/api/watchlist", { headers: { accept: "application/json" } });
  if (!response.ok) {
    throw new Error(`Watchlist request failed: ${response.status}`);
  }
  return response.json();
}

async function saveWatchlist(symbols) {
  const response = await fetch("/api/watchlist", {
    method: "PUT",
    headers: {
      accept: "application/json",
      "content-type": "application/json",
    },
    body: JSON.stringify({ symbols }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Watchlist save failed: ${response.status}`);
  }
  return payload;
}

async function fetchTradeHistory(page = 1, pageSize = 25) {
  const response = await fetch(`/api/trade-history?page=${page}&page_size=${pageSize}`, {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`Trade history request failed: ${response.status}`);
  }
  return response.json();
}

function renderSnapshot(snapshot) {
  renderPortfolio(snapshot.portfolio || {});
  renderPositions(snapshot.positions || []);
  renderSignals(snapshot.signals || []);
  renderBacktests(snapshot.backtest_metrics || {});
  renderHealth(snapshot.health || {});
}

function renderPortfolio(portfolio) {
  setText("portfolio-equity", money.format(portfolio.equity || 0));
  setText("portfolio-cash", money.format(portfolio.cash || 0));
  setText("portfolio-buying-power", money.format(portfolio.buying_power || 0));
  const daily = document.getElementById("portfolio-daily-pl");
  if (daily) {
    daily.textContent = signedMoney(portfolio.daily_pl || 0);
    daily.className = plClass(portfolio.daily_pl || 0);
  }
}

function renderPositions(positions) {
  setText("positions-count", String(positions.length));
  const body = document.getElementById("positions-body");
  if (!body) return;
  body.innerHTML = positions.map((position) => `
    <tr>
      <td>${position.symbol}</td>
      <td>${number.format(position.quantity || 0)}</td>
      <td>${money.format(position.average_entry_price || 0)}</td>
      <td>${money.format(position.current_price || 0)}</td>
      <td>${money.format(position.market_value || 0)}</td>
      <td class="${plClass(position.unrealized_pl)}">${signedMoney(position.unrealized_pl || 0)} (${pct(position.unrealized_plpc || 0)})</td>
    </tr>
  `).join("");
}

function renderTrades(history) {
  const trades = history.items || [];
  state.tradeHistory.page = Number(history.page || 1);
  state.tradeHistory.pageSize = Number(history.page_size || state.tradeHistory.pageSize);
  state.tradeHistory.pages = Number(history.pages || 1);
  state.tradeHistory.total = Number(history.total || 0);
  setText("trades-count", String(state.tradeHistory.total));
  const body = document.getElementById("trades-body");
  if (!body) return;
  if (!trades.length) {
    body.innerHTML = '<tr><td colspan="7">No completed trades from saved fill history.</td></tr>';
    renderTradePagination();
    return;
  }
  body.innerHTML = trades.map((trade) => `
    <tr>
      <td>${escapeHtml(trade.symbol)}</td>
      <td>${escapeHtml(trade.side)}</td>
      <td>${number.format(trade.quantity || 0)}</td>
      <td>${trade.entry_price === null ? "-" : money.format(trade.entry_price || 0)}</td>
      <td>${trade.exit_price === null ? "-" : money.format(trade.exit_price || 0)}</td>
      <td class="${plClass(trade.realized_pl)}">${signedMoney(trade.realized_pl || 0)}</td>
      <td>${formatDate(trade.closed_at)}</td>
    </tr>
  `).join("");
  renderTradePagination();
}

function renderSignals(signals) {
  setText("signals-count", String(signals.length));
  const list = document.getElementById("signals-list");
  if (!list) return;
  list.innerHTML = signals.slice(0, 8).map((signal) => {
    const sideClass = signal.side === "BUY" ? "side-buy" : signal.side === "SELL" ? "side-sell" : "muted-text";
    return `
      <article class="signal-item">
        <div class="signal-main">
          <strong>${signal.symbol}</strong>
          <strong class="${sideClass}">${signal.side}</strong>
        </div>
        <div class="muted-text">${signal.signal_type} | Score ${signal.score}</div>
        <div class="muted-text">${formatDate(signal.timestamp)}</div>
      </article>
    `;
  }).join("");
}

function renderBacktests(metrics) {
  setText("bt-win-rate", pct(metrics.win_rate || 0));
  setText("bt-profit-factor", Number(metrics.profit_factor || 0).toFixed(2));
  setText("bt-drawdown", pct(metrics.drawdown || 0));
  setText("bt-sharpe", Number(metrics.sharpe_ratio || 0).toFixed(2));
  setText("bt-expectancy", money.format(metrics.expectancy || 0));
  setText("bt-trades", String(metrics.total_trades || 0));
}

function renderHealth(health) {
  setText("health-status", health.status || "unknown");
  setText("health-env", health.environment || "-");
  setText("health-paper", String(Boolean(health.paper_trading)));
  setText("health-live", String(Boolean(health.live_trading_enabled)));
  setText("health-updated", formatDate(health.last_updated));
}

function renderWatchlist() {
  setText("watchlist-count", String(state.watchlist.length));
  const body = document.getElementById("watchlist-body");
  if (!body) return;
  body.innerHTML = state.watchlist.map((symbol) => `
    <tr>
      <td>
        <div class="watchlist-symbol-cell">
          <span>${escapeHtml(symbol)}</span>
          <button type="button" data-symbol="${escapeHtml(symbol)}" aria-label="Remove ${escapeHtml(symbol)}">x</button>
        </div>
      </td>
      <td>${formatWatchlistPrice(state.watchlistPrices[symbol])}</td>
    </tr>
  `).join("");
}

function formatWatchlistPrice(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  return money.format(Number(value));
}

function parseSymbols(value) {
  return String(value || "")
    .split(/[,\s]+/)
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean);
}

function addWatchlistSymbols(symbols) {
  const merged = [...state.watchlist];
  symbols.forEach((symbol) => {
    if (!/^[A-Z][A-Z0-9.-]{0,14}$/.test(symbol)) {
      throw new Error(`Invalid symbol: ${symbol}`);
    }
    if (!merged.includes(symbol)) {
      merged.push(symbol);
    }
  });
  if (!merged.length) {
    throw new Error("Add at least one symbol.");
  }
  state.watchlist = merged;
  renderWatchlist();
}

function removeWatchlistSymbol(symbol) {
  state.watchlist = state.watchlist.filter((item) => item !== symbol);
  delete state.watchlistPrices[symbol];
  renderWatchlist();
}

function setWatchlistMessage(message, kind = "") {
  const element = document.getElementById("watchlist-message");
  if (!element) return;
  element.textContent = message;
  element.className = `watchlist-message ${kind}`.trim();
}

function watchlistPriceMap(items) {
  return (items || []).reduce((prices, item) => {
    if (item && item.symbol) {
      prices[item.symbol] = item.current_price;
    }
    return prices;
  }, {});
}

async function loadWatchlist({ clearMessage = true } = {}) {
  try {
    const payload = await fetchWatchlist();
    state.watchlist = payload.symbols || [];
    state.watchlistPrices = watchlistPriceMap(payload.items);
    renderWatchlist();
    if (clearMessage) {
      setWatchlistMessage("");
    }
  } catch (error) {
    setWatchlistMessage(error.message, "error");
  }
}

async function loadTradeHistory(page = state.tradeHistory.page) {
  try {
    renderTrades(await fetchTradeHistory(page, state.tradeHistory.pageSize));
  } catch (error) {
    const body = document.getElementById("trades-body");
    if (body) {
      body.innerHTML = `<tr><td colspan="7">${escapeHtml(error.message)}</td></tr>`;
    }
  }
}

function renderTradePagination() {
  const pagination = document.getElementById("trade-pagination");
  if (!pagination) return;
  if (state.tradeHistory.pages <= 1) {
    pagination.innerHTML = `<span class="muted-text">Page 1 of 1</span>`;
    return;
  }

  pagination.innerHTML = pageTokens(state.tradeHistory.page, state.tradeHistory.pages).map((token) => {
    if (token === "...") {
      return '<span class="trade-page-gap">...</span>';
    }
    const selected = token === state.tradeHistory.page ? ' aria-current="page" disabled' : "";
    return `<button type="button" data-page="${token}"${selected}>${token}</button>`;
  }).join("");
}

function pageTokens(page, pages) {
  const visible = new Set([1, pages, page - 2, page - 1, page, page + 1, page + 2]);
  const numbers = [...visible].filter((value) => value >= 1 && value <= pages).sort((left, right) => left - right);
  const tokens = [];
  numbers.forEach((value, index) => {
    if (index && value - numbers[index - 1] > 1) {
      tokens.push("...");
    }
    tokens.push(value);
  });
  return tokens;
}

function bindWatchlistControls() {
  const form = document.getElementById("watchlist-form");
  const input = document.getElementById("watchlist-input");
  const save = document.getElementById("watchlist-save");
  const body = document.getElementById("watchlist-body");

  if (form && input) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      try {
        addWatchlistSymbols(parseSymbols(input.value));
        input.value = "";
        setWatchlistMessage("Ready to save.", "");
      } catch (error) {
        setWatchlistMessage(error.message, "error");
      }
    });
  }

  if (save) {
    save.addEventListener("click", async () => {
      try {
        const payload = await saveWatchlist(state.watchlist);
        state.watchlist = payload.symbols || [];
        renderWatchlist();
        await loadWatchlist({ clearMessage: false });
        setWatchlistMessage("Watchlist saved.", "success");
      } catch (error) {
        setWatchlistMessage(error.message, "error");
      }
    });
  }

  if (body) {
    body.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-symbol]");
      if (!button) return;
      removeWatchlistSymbol(button.dataset.symbol);
      setWatchlistMessage("Ready to save.", "");
    });
  }
}

function bindTradePagination() {
  const pagination = document.getElementById("trade-pagination");
  if (!pagination) return;
  pagination.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-page]");
    if (!button) return;
    loadTradeHistory(Number(button.dataset.page));
  });
}

function formatDate(value) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString();
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setConnectionState(label, muted = false) {
  const element = document.getElementById("connection-state");
  if (!element) return;
  element.textContent = label;
  element.className = muted ? "status-pill muted" : "status-pill";
}

async function refresh() {
  try {
    renderSnapshot(await fetchSnapshot());
    setConnectionState("Live");
  } catch (error) {
    setConnectionState("Offline", true);
  }
}

function connectWebSocket() {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  const socket = new WebSocket(`${protocol}://${window.location.host}/ws/dashboard`);
  socket.addEventListener("open", () => setConnectionState("Live"));
  socket.addEventListener("message", (event) => renderSnapshot(JSON.parse(event.data)));
  socket.addEventListener("close", () => {
    setConnectionState("Polling", true);
    window.setTimeout(connectWebSocket, state.refreshSeconds * 1000);
  });
}

refresh();
bindWatchlistControls();
bindTradePagination();
loadWatchlist();
loadTradeHistory();
connectWebSocket();
window.setInterval(() => {
  refresh();
  loadWatchlist({ clearMessage: false });
  loadTradeHistory();
}, state.refreshSeconds * 1000);
