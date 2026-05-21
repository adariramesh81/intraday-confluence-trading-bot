#!/bin/sh
set -eu

mkdir -p logs data

PORT="${PORT:-8000}"
RUN_PAPER_WORKER="${RUN_PAPER_WORKER:-true}"
LIVE_TRADING="${LIVE_TRADING:-false}"
ALPACA_PAPER="${ALPACA_PAPER:-true}"
RUN_PAPER_WORKER_NORMALIZED="$(printf '%s' "$RUN_PAPER_WORKER" | tr '[:upper:]' '[:lower:]')"
LIVE_TRADING_NORMALIZED="$(printf '%s' "$LIVE_TRADING" | tr '[:upper:]' '[:lower:]')"
ALPACA_PAPER_NORMALIZED="$(printf '%s' "$ALPACA_PAPER" | tr '[:upper:]' '[:lower:]')"

dashboard_pid=""
worker_pid=""

stop_children() {
  if [ -n "$dashboard_pid" ]; then
    kill "$dashboard_pid" 2>/dev/null || true
  fi
  if [ -n "$worker_pid" ]; then
    kill "$worker_pid" 2>/dev/null || true
  fi
}

trap stop_children INT TERM

python -m uvicorn app.dashboard.server:create_app --factory --host 0.0.0.0 --port "$PORT" &
dashboard_pid="$!"
echo "Dashboard started on port $PORT with pid $dashboard_pid."

if [ "$RUN_PAPER_WORKER_NORMALIZED" = "true" ]; then
  if [ "$LIVE_TRADING_NORMALIZED" = "true" ]; then
    echo "Refusing to start paper worker because LIVE_TRADING=true."
    stop_children
    exit 1
  fi
  if [ "$ALPACA_PAPER_NORMALIZED" != "true" ]; then
    echo "Refusing to start paper worker because ALPACA_PAPER is not true."
    stop_children
    exit 1
  fi
  python -m app.trading.paper_runner &
  worker_pid="$!"
  echo "Bot 2 paper worker started with pid $worker_pid."
else
  echo "Bot 2 paper worker disabled because RUN_PAPER_WORKER is not true."
fi

while true; do
  if ! kill -0 "$dashboard_pid" 2>/dev/null; then
    echo "Dashboard process exited."
    stop_children
    exit 1
  fi
  if [ -n "$worker_pid" ] && ! kill -0 "$worker_pid" 2>/dev/null; then
    echo "Bot 2 paper worker process exited."
    stop_children
    exit 1
  fi
  sleep 5
done
