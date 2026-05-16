"""Strategy engine data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SignalSide(str, Enum):
    """Possible signal directions."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class MarketBias(str, Enum):
    """Institutional market bias states."""

    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class SignalType(str, Enum):
    """Signal setup categories."""

    NONE = "NONE"
    PULLBACK = "PULLBACK"
    BREAKOUT = "BREAKOUT"


@dataclass(frozen=True)
class StrategySettings:
    """Configurable strategy defaults from the project specification."""

    fast_ema_period: int = 9
    slow_ema_period: int = 21
    rsi_period: int = 14
    bollinger_period: int = 20
    bollinger_std_dev: float = 2.0
    supertrend_atr_period: int = 10
    supertrend_multiplier: float = 3.0
    volume_average_period: int = 20
    volume_confirmation_multiplier: float = 1.5
    minimum_trade_score: int = 75
    pullback_tolerance_pct: float = 0.003
    rejection_wick_body_ratio: float = 0.5
    rsi_neutral_lower: float = 45.0
    rsi_neutral_upper: float = 55.0
    vwap_flat_lookback: int = 5
    vwap_flat_tolerance_pct: float = 0.0002
    supertrend_flip_lookback: int = 10
    max_supertrend_flips: int = 2
    bollinger_squeeze_threshold: float = 0.01
    low_liquidity_volume_ratio: float = 0.5
    market_timezone: str = "America/New_York"


@dataclass(frozen=True)
class TradeScore:
    """Trade score components and pass/fail state."""

    total: int
    components: dict[str, int]
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class StrategyDecision:
    """Signal-only strategy decision with no execution side effects."""

    side: SignalSide
    signal_type: SignalType
    market_bias: MarketBias
    score: TradeScore
    symbol: str | None = None
    timestamp: datetime | None = None
    reasons: list[str] = field(default_factory=list)
    filtered_reasons: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def should_trade(self) -> bool:
        """Return whether the decision represents a tradable signal."""

        return self.side in {SignalSide.BUY, SignalSide.SELL} and self.score.passed and not self.filtered_reasons
