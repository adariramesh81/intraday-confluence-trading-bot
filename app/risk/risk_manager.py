"""Risk management facade for signal-only trading decisions."""

from __future__ import annotations

import logging
from datetime import datetime

from app.risk.drawdown_guard import DrawdownGuard
from app.risk.position_sizer import calculate_position_size
from app.risk.trade_levels import calculate_trade_levels, update_stop_loss
from app.risk.types import (
    DailyTradeCounter,
    DrawdownState,
    RiskDecision,
    RiskDecisionStatus,
    RiskSettings,
    StopUpdate,
    TradeLevels,
    TradeSide,
)
from app.utils.logger import get_logger


class RiskManager:
    """Coordinate position sizing, levels, and account-level risk guards."""

    def __init__(
        self,
        settings: RiskSettings | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.settings = settings or RiskSettings()
        self.logger = logger or get_logger(__name__)
        self.drawdown_guard = DrawdownGuard(self.settings)

    def evaluate_trade(
        self,
        side: TradeSide | str,
        account_equity: float,
        entry_price: float,
        atr: float,
        drawdown_state: DrawdownState,
        daily_counter: DailyTradeCounter,
        supertrend: float | None = None,
        opposite_bollinger_band: float | None = None,
        timestamp: datetime | None = None,
    ) -> RiskDecision:
        """Return a complete risk decision for a proposed trade signal."""

        allowed, guard_reasons = self.drawdown_guard.can_take_trade(drawdown_state, daily_counter)
        if not allowed:
            self.logger.info("Risk decision blocked by account guardrails.", extra={"reasons": guard_reasons})
            return RiskDecision(
                status=RiskDecisionStatus.BLOCKED,
                reasons=guard_reasons,
                timestamp=timestamp,
            )

        try:
            levels = calculate_trade_levels(
                side=side,
                entry_price=entry_price,
                atr=atr,
                supertrend=supertrend,
                opposite_bollinger_band=opposite_bollinger_band,
                settings=self.settings,
            )
            position_size = calculate_position_size(
                account_equity=account_equity,
                entry_price=entry_price,
                stop_loss=levels.stop_loss,
                settings=self.settings,
            )
        except ValueError as exc:
            reason = str(exc)
            self.logger.exception("Risk decision blocked by invalid risk inputs.")
            return RiskDecision(
                status=RiskDecisionStatus.BLOCKED,
                reasons=[reason],
                timestamp=timestamp,
            )

        if position_size.quantity <= 0:
            return RiskDecision(
                status=RiskDecisionStatus.BLOCKED,
                levels=levels,
                position_size=position_size,
                reasons=["Calculated quantity is zero."],
                timestamp=timestamp,
            )

        self.logger.info(
            "Risk decision approved.",
            extra={
                "side": levels.side.value,
                "entry_price": levels.entry_price,
                "stop_loss": levels.stop_loss,
                "take_profit": levels.take_profit,
                "quantity": position_size.quantity,
                "capital_at_risk": position_size.capital_at_risk,
            },
        )
        return RiskDecision(
            status=RiskDecisionStatus.APPROVED,
            levels=levels,
            position_size=position_size,
            reasons=[],
            timestamp=timestamp,
        )

    def manage_open_trade_stop(
        self,
        levels: TradeLevels,
        current_price: float,
        current_stop_loss: float | None = None,
        current_supertrend: float | None = None,
    ) -> StopUpdate:
        """Return an updated stop-loss using break-even and trailing rules."""

        return update_stop_loss(
            levels=levels,
            current_price=current_price,
            current_stop_loss=current_stop_loss,
            current_supertrend=current_supertrend,
            settings=self.settings,
        )
