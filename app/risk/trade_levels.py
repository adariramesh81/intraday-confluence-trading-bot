"""Stop-loss, take-profit, break-even, and trailing-stop calculations."""

from __future__ import annotations

from app.risk.types import RiskSettings, StopUpdate, TradeLevels, TradeSide

_R_THRESHOLD_EPSILON = 1e-9


class TradeLevelError(ValueError):
    """Raised when trade level inputs are invalid."""


def calculate_trade_levels(
    side: TradeSide | str,
    entry_price: float,
    atr: float,
    supertrend: float | None = None,
    opposite_bollinger_band: float | None = None,
    settings: RiskSettings | None = None,
) -> TradeLevels:
    """Calculate initial stop-loss and take-profit levels for a trade."""

    config = settings or RiskSettings()
    trade_side = TradeSide(side)
    _validate_common_inputs(entry_price=entry_price, atr=atr, settings=config)

    atr_stop = _atr_stop(trade_side, entry_price, atr, config)
    supertrend_stop = _valid_supertrend_stop(trade_side, entry_price, supertrend)
    stop_loss = _choose_tighter_stop(trade_side, atr_stop, supertrend_stop)
    risk_per_share = abs(entry_price - stop_loss)
    if risk_per_share <= 0:
        raise TradeLevelError("risk_per_share must be greater than zero.")

    minimum_target = _minimum_take_profit(trade_side, entry_price, risk_per_share, config)
    take_profit = _choose_take_profit(trade_side, minimum_target, opposite_bollinger_band)
    reward_per_share = abs(take_profit - entry_price)

    return TradeLevels(
        side=trade_side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_per_share=risk_per_share,
        reward_per_share=reward_per_share,
        reward_r=reward_per_share / risk_per_share,
        atr_stop=atr_stop,
        supertrend_stop=supertrend_stop,
    )


def update_stop_loss(
    levels: TradeLevels,
    current_price: float,
    current_stop_loss: float | None = None,
    current_supertrend: float | None = None,
    settings: RiskSettings | None = None,
) -> StopUpdate:
    """Apply break-even and trailing stop rules to an open trade."""

    config = settings or RiskSettings()
    if current_price <= 0:
        raise TradeLevelError("current_price must be greater than zero.")

    active_stop = current_stop_loss if current_stop_loss is not None else levels.stop_loss
    if active_stop <= 0:
        raise TradeLevelError("current_stop_loss must be greater than zero.")

    stop_loss = active_stop
    moved_to_break_even = False
    trailing_stop_active = False
    reasons: list[str] = []
    profit_r = calculate_unrealized_r(levels, current_price)

    if _meets_r_threshold(profit_r, config.break_even_trigger_r):
        break_even_stop = levels.entry_price
        improved_stop = _protective_max(levels.side, stop_loss, break_even_stop)
        if improved_stop != stop_loss:
            stop_loss = improved_stop
            moved_to_break_even = True
            reasons.append("Moved stop to break-even at +0.8R or better.")

    if _meets_r_threshold(profit_r, config.trailing_stop_trigger_r) and current_supertrend is not None:
        trailing_candidate = _valid_supertrend_stop(levels.side, current_price, current_supertrend)
        if trailing_candidate is not None:
            improved_stop = _protective_max(levels.side, stop_loss, trailing_candidate)
            if improved_stop != stop_loss:
                stop_loss = improved_stop
                trailing_stop_active = True
                reasons.append("Applied Supertrend trailing stop.")

    return StopUpdate(
        stop_loss=stop_loss,
        moved_to_break_even=moved_to_break_even,
        trailing_stop_active=trailing_stop_active,
        reasons=reasons,
    )


def calculate_unrealized_r(levels: TradeLevels, current_price: float) -> float:
    """Calculate current unrealized profit as an R multiple."""

    if levels.risk_per_share <= 0:
        raise TradeLevelError("levels.risk_per_share must be greater than zero.")
    if levels.side == TradeSide.BUY:
        return (current_price - levels.entry_price) / levels.risk_per_share
    return (levels.entry_price - current_price) / levels.risk_per_share


def _atr_stop(side: TradeSide, entry_price: float, atr: float, settings: RiskSettings) -> float:
    distance = atr * settings.atr_stop_multiplier
    return entry_price - distance if side == TradeSide.BUY else entry_price + distance


def _valid_supertrend_stop(side: TradeSide, reference_price: float, supertrend: float | None) -> float | None:
    if supertrend is None or supertrend <= 0:
        return None
    if side == TradeSide.BUY and supertrend < reference_price:
        return supertrend
    if side == TradeSide.SELL and supertrend > reference_price:
        return supertrend
    return None


def _choose_tighter_stop(side: TradeSide, atr_stop: float, supertrend_stop: float | None) -> float:
    if supertrend_stop is None:
        return atr_stop
    if side == TradeSide.BUY:
        return max(atr_stop, supertrend_stop)
    return min(atr_stop, supertrend_stop)


def _minimum_take_profit(
    side: TradeSide,
    entry_price: float,
    risk_per_share: float,
    settings: RiskSettings,
) -> float:
    distance = risk_per_share * settings.minimum_reward_r
    return entry_price + distance if side == TradeSide.BUY else entry_price - distance


def _choose_take_profit(
    side: TradeSide,
    minimum_target: float,
    opposite_bollinger_band: float | None,
) -> float:
    if opposite_bollinger_band is None or opposite_bollinger_band <= 0:
        return minimum_target
    if side == TradeSide.BUY and opposite_bollinger_band >= minimum_target:
        return opposite_bollinger_band
    if side == TradeSide.SELL and opposite_bollinger_band <= minimum_target:
        return opposite_bollinger_band
    return minimum_target


def _protective_max(side: TradeSide, current_stop: float, candidate_stop: float) -> float:
    if side == TradeSide.BUY:
        return max(current_stop, candidate_stop)
    return min(current_stop, candidate_stop)


def _meets_r_threshold(profit_r: float, threshold_r: float) -> bool:
    return profit_r + _R_THRESHOLD_EPSILON >= threshold_r


def _validate_common_inputs(entry_price: float, atr: float, settings: RiskSettings) -> None:
    if entry_price <= 0:
        raise TradeLevelError("entry_price must be greater than zero.")
    if atr <= 0:
        raise TradeLevelError("atr must be greater than zero.")
    if settings.atr_stop_multiplier <= 0:
        raise TradeLevelError("atr_stop_multiplier must be greater than zero.")
    if settings.minimum_reward_r < 1.5:
        raise TradeLevelError("minimum_reward_r must be at least 1.5.")
    if settings.break_even_trigger_r <= 0:
        raise TradeLevelError("break_even_trigger_r must be greater than zero.")
    if settings.trailing_stop_trigger_r <= 0:
        raise TradeLevelError("trailing_stop_trigger_r must be greater than zero.")
