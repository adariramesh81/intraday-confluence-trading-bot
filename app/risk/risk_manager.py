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
        open_positions_count: int = 0,
        deployed_notional: float = 0.0,
        cash: float | None = None,
        sector_notional: float = 0.0,
    ) -> RiskDecision:
        """Return a complete risk decision for a proposed trade signal."""

        allowed, guard_reasons = self.drawdown_guard.can_take_trade(drawdown_state, daily_counter)
        guard_reasons.extend(
            self._portfolio_guard_reasons(
                account_equity=account_equity,
                open_positions_count=open_positions_count,
                deployed_notional=deployed_notional,
                cash=cash,
                sector_notional=sector_notional,
            )
        )
        allowed = not guard_reasons
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

    def _portfolio_guard_reasons(
        self,
        account_equity: float,
        open_positions_count: int,
        deployed_notional: float,
        cash: float | None,
        sector_notional: float,
    ) -> list[str]:
        reasons: list[str] = []
        if open_positions_count >= self.settings.max_open_positions:
            reasons.append("Maximum open position limit reached.")
        if account_equity > 0 and deployed_notional / account_equity >= self.settings.max_deployed_pct:
            reasons.append("Maximum deployed capital limit reached.")
        if cash is not None and account_equity > 0 and cash / account_equity < self.settings.cash_reserve_pct:
            reasons.append("Cash reserve requirement not met.")
        if account_equity > 0 and sector_notional / account_equity >= self.settings.max_sector_pct:
            reasons.append("Maximum sector concentration reached.")
        return reasons

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
