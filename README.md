# intraday-confluence-trading-bot

Production-oriented intraday confluence trading bot. Phase 1 establishes safe configuration, logging, Alpaca paper trading plumbing, tests, and Docker runtime scaffolding. Phase 2 adds Alpaca and yfinance OHLCV market data adapters with validation, retries, and timezone-safe timestamps.

## Phase 1 Quickstart

1. Create a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and add Alpaca paper credentials.
4. Start locally with `python -m app.main`.

Docker:

```powershell
docker compose up --build
```

Dashboard:

```powershell
python -m app.dashboard.server
```

Bot 2 paper-trading runner:

```powershell
python -m app.trading.paper_runner
```

The dashboard is monitoring-only. Start the paper runner separately when you want automated Bot 2 scanning and paper order submission.

Live trading is disabled by default. The bot only leaves paper mode when both `LIVE_TRADING=true` and `ALPACA_PAPER=false` are explicitly configured.
