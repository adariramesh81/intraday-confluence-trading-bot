# Railway Deployment

This guide deploys the bot as a read-only Railway dashboard with Alpaca paper account sync enabled. Live trading remains disabled.

## 1. Prepare Secrets

Regenerate your Alpaca paper API key before deploying if it was ever shared or shown in a screenshot.

Do not commit `.env`, `config.yaml`, or SQLite database files. Railway should receive secrets through service variables only.

## 2. Create the Railway Service

1. Push this repository to GitHub.
2. In Railway, create a new project from the GitHub repository.
3. Let Railway use the root `Dockerfile`.
4. Confirm Railway detects `railway.toml`.

The container starts the dashboard with:

```bash
uvicorn app.dashboard.server:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}
```

Railway provides `PORT` automatically.

## 3. Add a Persistent Volume

Create a Railway volume and mount it at:

```text
/app/data
```

The application stores synced account data in:

```text
/app/data/trading_bot.sqlite3
```

## 4. Configure Railway Variables

Add these variables to the Railway service:

```env
APP_ENV=production
ALPACA_API_KEY=<new paper key>
ALPACA_SECRET_KEY=<new paper secret>
ALPACA_PAPER=true
LIVE_TRADING=false
SQLITE_PATH=/app/data/trading_bot.sqlite3
ALPACA_SYNC_ENABLED=true
ALPACA_SYNC_REFRESH_SECONDS=30
DASHBOARD_REFRESH_SECONDS=5
LOG_LEVEL=INFO
LOG_FILE_PATH=logs/trading_bot.log
```

Optional defaults can also be set if you want to override the repo config:

```env
DEFAULT_SYMBOL=SPY
MAX_TRADES_PER_DAY=3
RISK_PER_TRADE=0.01
MARKET_DATA_SOURCE=alpaca
MARKET_DATA_TIMEFRAME=1Min
MARKET_DATA_FEED=iex
MARKET_DATA_ADJUSTMENT=raw
MARKET_DATA_TIMEZONE=America/New_York
ALPACA_SYNC_ORDER_LIMIT=500
ALPACA_SYNC_PORTFOLIO_HISTORY_DAYS=30
```

## 5. Verify Deployment

Railway health checks use:

```text
/api/snapshot
```

After deploy:

1. Open the Railway-generated URL.
2. Confirm the dashboard loads.
3. Confirm `/api/snapshot` returns `200`.
4. Confirm the dashboard shows Alpaca paper cash, equity, buying power, positions, and recent orders.
5. Confirm Railway logs show `Alpaca paper account sync completed.`
6. Confirm logs never show live trading enabled.

For local Docker smoke testing:

```bash
docker build -t intraday-confluence-trading-bot .
docker run --rm -p 8000:8000 \
  -e PORT=8000 \
  -e APP_ENV=production \
  -e ALPACA_PAPER=true \
  -e LIVE_TRADING=false \
  -e SQLITE_PATH=/app/data/trading_bot.sqlite3 \
  -e ALPACA_SYNC_ENABLED=false \
  intraday-confluence-trading-bot
```

Then open:

```text
http://127.0.0.1:8000/api/snapshot
```

## 6. Security Notes

This deployment uses Railway's generated URL for development. Anyone with that URL may view dashboard data, including cash, positions, and trade history.

Before sharing the dashboard URL or using this beyond development, add authentication or network-level access control.
