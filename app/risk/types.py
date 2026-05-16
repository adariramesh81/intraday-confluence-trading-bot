"""Risk management data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class TradeSide(str, Enum):
    """Supported trade directions for risk calculations."""

    BUY = "BUY"
    SELL = "SELL"


class RiskDecisionStatus(str, Enum):
    """Risk approval result states."""

    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class RiskSettings:
    """Configurable risk limits from the project specification."""

    risk_per_trade: float = 0.01
    max_trades_per_day: int = 3
    atr_stop_multiplier: float = 1.0
    minimum_reward_r: float = 1.5
    break_even_trigger_r: float = 0.8
    trailing_stop_trigger_r: float = 1.0
    max_daily_drawdown_pct: float = 0.03
    max_total_drawdown_pct: float = 0.10
    allow_fractional_shares: bool = True
    quantity_precision: int = 6


@dataclass(frozen=True)
class PositionSize:
    """Calculated position size and risk details."""

    quantity: float
    capital_at_risk: float
    risk_per_share: float
    notional_value: float


@dataclass(frozen=True)
class TradeLevels:
    """Calculated entry, stop, target, and R-multiple levels."""

    side: TradeSide
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_per_share: float
    reward_per_share: float
    reward_r: float
    atr_stop: float
    supertrend_stop: float | None = None


@dataclass(frozen=True)
class StopUpdate:
    """Updated stop-loss state for an open trade."""

    stop_loss: float
    moved_to_break_even: bool
    trailing_stop_active: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DrawdownState:
    """Account equity drawdown state."""

    starting_equity: float
    current_equity: float
    peak_equity: float
    daily_starting_equity: float
    daily_realized_pnl: float = 0.0


@dataclass(frozen=True)
class RiskDecision:
    """Complete risk decision for a signal without execution side effects."""

    status: RiskDecisionStatus
    levels: TradeLevels | None = None
    position_size: PositionSize | None = None
    reasons: list[str] = field(default_factory=list)
    timestamp: datetime | None = None

    @property
    def approved(self) -> bool:
        """Return whether the risk decision is approved."""

        return self.status == RiskDecisionStatus.APPROVED


@dataclass(frozen=True)
class DailyTradeCounter:
    """Daily trade count snapshot."""

    trading_day: date
    trades_taken: int = 0
