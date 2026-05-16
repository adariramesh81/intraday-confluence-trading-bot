# SPEC.md

# Intraday Trading Bot Specification

## Objective
Develop a modular intraday trading bot focused on:
- High probability setups
- Institutional flow alignment
- Risk-controlled execution
- Paper trading first

---

# Strategy Overview

The bot uses a multi-layer confluence strategy:

1. Supertrend → trend direction
2. VWAP → institutional bias
3. Bollinger Bands → entry timing
4. EMA crossover → confirmation
5. RSI → momentum filter
6. Volume → trade strength

---

# Indicator Configuration

## EMA
- Fast EMA: 9
- Slow EMA: 21

## RSI
- Period: 14

## Bollinger Bands
- Period: 20
- Standard deviation: 2

## Supertrend
- ATR Period: 10
- Multiplier: 3

## VWAP
- Intraday reset daily

---

# Market Bias Rules

## Bullish Bias
Conditions:
- Supertrend bullish
- Price above VWAP

Allowed:
- BUY trades only

---

## Bearish Bias
Conditions:
- Supertrend bearish
- Price below VWAP

Allowed:
- SELL trades only

---

# BUY Trade Rules

Execute BUY only if ALL conditions are true:

1. Supertrend bullish
2. Price above VWAP
3. EMA 9 crosses above EMA 21
4. Price pulls back to:
   - VWAP OR
   - Lower Bollinger Band
5. Price rejection candle forms
6. RSI between 50–70
7. Volume >= 1.5x average

---

# SELL Trade Rules

Execute SELL only if ALL conditions are true:

1. Supertrend bearish
2. Price below VWAP
3. EMA 9 crosses below EMA 21
4. Price pulls back to:
   - VWAP OR
   - Upper Bollinger Band
5. Bearish rejection candle forms
6. RSI between 30–50
7. Volume confirmation present

---

# Breakout Mode

## BUY Breakout
- Price closes above upper Bollinger Band
- Strong volume
- Supertrend bullish

## SELL Breakout
- Price closes below lower Bollinger Band
- Strong volume
- Supertrend bearish

---

# Trade Filters

DO NOT TRADE when:
- RSI between 45–55
- VWAP flat
- Supertrend flips frequently
- Bollinger Bands narrow
- First 5 minutes after market open
- Low liquidity conditions

---

# Risk Management

## Position Risk
- Maximum 1% capital risk per trade

## Stop Loss
Use:
- Supertrend line
OR
- 1x ATR

Choose tighter stop.

## Take Profit
- Minimum 1.5R
- Optional target at opposite Bollinger Band

## Trade Limits
- Max 3 trades per day

## Break-Even Rule
Move SL to entry after +0.8R

## Trailing Stop
Use Supertrend trailing.

---

# Trade Scoring

Each trade receives a score:

- VWAP alignment → 30
- Supertrend alignment → 20
- Bollinger reaction → 20
- Volume strength → 15
- RSI strength → 15

Minimum score required:
- 75

---

# Backtesting Requirements

Backtesting must include:
- Multiple symbols
- Different market conditions
- Historical simulation

Metrics:
- Win rate
- Profit factor
- Drawdown
- Sharpe ratio
- Expectancy

---

# Deployment Requirements

## Initial Deployment
- Paper trading only

## Recommended Hosting
- DigitalOcean
- AWS EC2

## Runtime Requirements
- 24/7 uptime
- Auto restart
- Persistent logging

---

# Future Enhancements
- Machine learning probability model
- Options trading support
- Multi-timeframe analysis
- Portfolio optimization
