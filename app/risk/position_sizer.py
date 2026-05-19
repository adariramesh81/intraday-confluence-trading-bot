"""Position sizing calculations."""

from __future__ import annotations

import math

from app.risk.types import PositionSize, RiskSettings


class PositionSizingError(ValueError):
    """Raised when position sizing inputs are invalid."""


def calculate_position_size(
    account_equity: float,
    entry_price: float,
    stop_loss: float,
    settings: RiskSettings | None = None,
) -> PositionSize:
    """Calculate position size from account equity and stop distance."""

    config = settings or RiskSettings()
    _validate_inputs(account_equity=account_equity, entry_price=entry_price, stop_loss=stop_loss, settings=config)

    risk_per_share = abs(entry_price - stop_loss)
    capital_at_risk = account_equity * config.risk_per_trade
    raw_quantity = capital_at_risk / risk_per_share
    max_notional = account_equity * config.max_position_notional_pct
    raw_quantity = min(raw_quantity, max_notional / entry_price)
    quantity = _round_quantity(raw_quantity, config)

    return PositionSize(
        quantity=quantity,
        capital_at_risk=quantity * risk_per_share,
        risk_per_share=risk_per_share,
        notional_value=quantity * entry_price,
    )


def _round_quantity(quantity: float, settings: RiskSettings) -> float:
    if settings.allow_fractional_shares:
        return round(quantity, settings.quantity_precision)
    return float(math.floor(quantity))


def _validate_inputs(
    account_equity: float,
    entry_price: float,
    stop_loss: float,
    settings: RiskSettings,
) -> None:
    if account_equity <= 0:
        raise PositionSizingError("account_equity must be greater than zero.")
    if entry_price <= 0:
        raise PositionSizingError("entry_price must be greater than zero.")
    if stop_loss <= 0:
        raise PositionSizingError("stop_loss must be greater than zero.")
    if entry_price == stop_loss:
        raise PositionSizingError("entry_price and stop_loss cannot be equal.")
    if not 0 < settings.risk_per_trade <= 0.01:
        raise PositionSizingError("risk_per_trade must be greater than 0 and no more than 0.01.")
    if not 0 < settings.max_position_notional_pct <= 1:
        raise PositionSizingError("max_position_notional_pct must be between 0 and 1.")
    if settings.quantity_precision < 0:
        raise PositionSizingError("quantity_precision cannot be negative.")
