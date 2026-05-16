"""Daily trade limit and drawdown protection."""

from __future__ import annotations

from app.risk.types import DailyTradeCounter, DrawdownState, RiskSettings


class DrawdownGuardError(ValueError):
    """Raised when drawdown guard inputs are invalid."""


class DrawdownGuard:
    """Evaluate account drawdown and daily trade-limit protections."""

    def __init__(self, settings: RiskSettings | None = None) -> None:
        self.settings = settings or RiskSettings()

    def can_take_trade(
        self,
        drawdown_state: DrawdownState,
        daily_counter: DailyTradeCounter,
    ) -> tuple[bool, list[str]]:
        """Return whether a new trade is allowed under risk guardrails."""

        self._validate_state(drawdown_state)
        reasons: list[str] = []

        if daily_counter.trades_taken >= self.settings.max_trades_per_day:
            reasons.append("Maximum daily trade limit reached.")
        if self.daily_drawdown_pct(drawdown_state) >= self.settings.max_daily_drawdown_pct:
            reasons.append("Maximum daily drawdown limit reached.")
        if self.total_drawdown_pct(drawdown_state) >= self.settings.max_total_drawdown_pct:
            reasons.append("Maximum total drawdown limit reached.")

        return not reasons, reasons

    def daily_drawdown_pct(self, state: DrawdownState) -> float:
        """Calculate current daily drawdown percentage."""

        self._validate_state(state)
        daily_equity = state.daily_starting_equity + state.daily_realized_pnl
        daily_loss = max(0.0, state.daily_starting_equity - min(state.current_equity, daily_equity))
        return daily_loss / state.daily_starting_equity

    def total_drawdown_pct(self, state: DrawdownState) -> float:
        """Calculate current drawdown from peak equity."""

        self._validate_state(state)
        return max(0.0, state.peak_equity - state.current_equity) / state.peak_equity

    def _validate_state(self, state: DrawdownState) -> None:
        if state.starting_equity <= 0:
            raise DrawdownGuardError("starting_equity must be greater than zero.")
        if state.current_equity <= 0:
            raise DrawdownGuardError("current_equity must be greater than zero.")
        if state.peak_equity <= 0:
            raise DrawdownGuardError("peak_equity must be greater than zero.")
        if state.daily_starting_equity <= 0:
            raise DrawdownGuardError("daily_starting_equity must be greater than zero.")
        if self.settings.max_trades_per_day <= 0:
            raise DrawdownGuardError("max_trades_per_day must be greater than zero.")
        if not 0 < self.settings.max_daily_drawdown_pct <= 1:
            raise DrawdownGuardError("max_daily_drawdown_pct must be between 0 and 1.")
        if not 0 < self.settings.max_total_drawdown_pct <= 1:
            raise DrawdownGuardError("max_total_drawdown_pct must be between 0 and 1.")
