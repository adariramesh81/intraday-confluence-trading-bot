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
DASHBOARD_AUTH_ENABLED=true
DASHBOARD_SESSION_SECRET=<long random value>
DASHBOARD_ADMIN_EMAIL=<your email>
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
/healthz
```

After deploy:

1. Open the Railway-generated URL.
2. Confirm `/` redirects to the app login page.
3. Confirm the dashboard loads after signing in with a dashboard user account.
4. Confirm `/healthz` returns `200` without credentials.
5. Confirm `/api/snapshot` returns `401` before signing in.
6. Confirm `/api/snapshot` returns account data after signing in.
7. Confirm the dashboard shows Alpaca paper cash, equity, buying power, positions, and recent orders.
8. Confirm Railway logs show `Alpaca paper account sync completed.`
9. Confirm logs never show live trading enabled.

Generate a session secret locally with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Create or reset the initial admin account with:

```bash
python -m app.dashboard.user_admin create-admin --email you@example.com
```

The command prints a temporary password once. After signing in, change the password and then use **Admin** -> **Dashboard Users** to create friend accounts. Friend accounts receive generated temporary passwords that you copy and send manually.

The unauthenticated snapshot check should be rejected:

```bash
curl -i https://your-railway-url/api/snapshot
```

It should return `401 Unauthorized`.

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
  -e DASHBOARD_AUTH_ENABLED=true \
  -e DASHBOARD_SESSION_SECRET=local-dev-session-secret \
  -e DASHBOARD_ADMIN_EMAIL=you@example.com \
  intraday-confluence-trading-bot
```

Then open:

```text
http://127.0.0.1:8000/
```

## 6. Security Notes

This deployment uses an app login page with SQLite-backed dashboard user accounts. Use a random `DASHBOARD_SESSION_SECRET` and store it only in Railway variables.

Before sharing the dashboard URL or using this beyond development, consider adding a stronger authentication provider or network-level access control.
