# AGENTS.md

## Project Overview
This repository contains a production-grade intraday trading bot designed for:
- Paper trading first
- Backtesting and analytics
- Future live trading deployment

The bot uses:
- VWAP
- Supertrend
- Bollinger Bands
- EMA crossover
- RSI
- Volume confirmation

---

## Development Principles

### Safety First
- Paper trading must remain the default mode.
- Never execute live trades unless LIVE_TRADING=true.
- All live trading changes must require explicit confirmation.

---

## Code Quality Standards
- Use modular architecture
- Add docstrings for all public functions
- Use type hints where possible
- Add logging and exception handling
- Avoid hardcoded values

---

## Repository Structure

/data
/indicators
/strategy
/execution
/backtesting
/utils
/tests

---

## Indicator Rules

### VWAP
- Reset daily
- Used as institutional bias filter

### Supertrend
- Defines trend direction
- Used for trailing stop

### Bollinger Bands
- Used for pullback/reversal entries
- Detect volatility squeeze

### RSI
- Momentum filter
- Avoid trades in RSI 45–55 zone

---

## Risk Management Rules
- Risk only 1% capital per trade
- Maximum 3 trades per day
- Use ATR-based stop loss
- Move stop to break-even at +0.8R
- Use trailing stop after profit threshold

---

## Trade Entry Philosophy
Focus on:
- High-quality setups
- Institutional alignment
- Trend continuation
- Pullback entries

Avoid:
- Choppy markets
- Flat VWAP
- Low volume
- Overtrading

---

## Logging Requirements
Log:
- Signals
- Orders
- Trade score
- P&L
- Errors
- Indicator states

---

## Testing Requirements
Every strategy update must:
- Run backtests
- Compare metrics
- Validate no severe drawdown increase

---

## Deployment
Recommended:
- Docker
- DigitalOcean
- AWS EC2

---

## Security
- Never commit API keys
- Use environment variables or config.yaml
- Encrypt secrets where possible
