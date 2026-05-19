from datetime import date

import pytest

from app.risk import (
    DailyTradeCounter,
    DrawdownGuard,
    DrawdownState,
    RiskDecisionStatus,
    RiskManager,
    RiskSettings,
    TradeSide,
    calculate_position_size,
    calculate_trade_levels,
    calculate_unrealized_r,
    update_stop_loss,
)


def _healthy_drawdown_state() -> DrawdownState:
    return DrawdownState(
        starting_equity=100_000,
        current_equity=100_000,
        peak_equity=102_000,
        daily_starting_equity=100_000,
    )


def test_position_size_risks_one_percent_of_capital() -> None:
    size = calculate_position_size(account_equity=100_000, entry_price=100, stop_loss=98)

    assert size.quantity == 150
    assert size.capital_at_risk == 300
    assert size.risk_per_share == 2
    assert size.notional_value == 15_000


def test_position_size_can_use_full_one_percent_when_notional_cap_allows() -> None:
    size = calculate_position_size(
        account_equity=100_000,
        entry_price=100,
        stop_loss=98,
        settings=RiskSettings(max_position_notional_pct=1.0),
    )

    assert size.quantity == 500
    assert size.capital_at_risk == 1000


def test_buy_trade_levels_choose_tighter_supertrend_stop_and_minimum_target() -> None:
    levels = calculate_trade_levels(
        side=TradeSide.BUY,
        entry_price=100,
        atr=2,
        supertrend=99,
        opposite_bollinger_band=101,
    )

    assert levels.atr_stop == 98
    assert levels.supertrend_stop == 99
    assert levels.stop_loss == 99
    assert levels.risk_per_share == 1
    assert levels.take_profit == 101.5
    assert levels.reward_r == 1.5


def test_sell_trade_levels_choose_tighter_supertrend_stop_and_opposite_band_target() -> None:
    levels = calculate_trade_levels(
        side=TradeSide.SELL,
        entry_price=100,
        atr=3,
        supertrend=101,
        opposite_bollinger_band=96,
    )

    assert levels.atr_stop == 103
    assert levels.supertrend_stop == 101
    assert levels.stop_loss == 101
    assert levels.take_profit == 96
    assert levels.reward_r == 4


def test_break_even_rule_moves_stop_after_point_eight_r() -> None:
    levels = calculate_trade_levels(side=TradeSide.BUY, entry_price=100, atr=2)

    update = update_stop_loss(levels, current_price=101.6)

    assert update.stop_loss == 100
    assert update.moved_to_break_even is True
    assert update.trailing_stop_active is False


def test_supertrend_trailing_stop_only_improves_protection() -> None:
    levels = calculate_trade_levels(side=TradeSide.BUY, entry_price=100, atr=2)

    update = update_stop_loss(levels, current_price=103, current_supertrend=101)

    assert update.stop_loss == 101
    assert update.trailing_stop_active is True


def test_sell_break_even_and_trailing_stop_move_downward() -> None:
    levels = calculate_trade_levels(side=TradeSide.SELL, entry_price=100, atr=2)

    update = update_stop_loss(levels, current_price=97, current_supertrend=99)

    assert update.stop_loss == 99
    assert update.moved_to_break_even is True
    assert update.trailing_stop_active is True


def test_sell_unrealized_r_calculation() -> None:
    levels = calculate_trade_levels(side=TradeSide.SELL, entry_price=100, atr=2)

    assert calculate_unrealized_r(levels, current_price=97) == 1.5


def test_drawdown_guard_blocks_daily_trade_limit() -> None:
    guard = DrawdownGuard()

    allowed, reasons = guard.can_take_trade(
        _healthy_drawdown_state(),
        DailyTradeCounter(trading_day=date(2026, 5, 15), trades_taken=3),
    )

    assert allowed is False
    assert "Maximum daily trade limit reached." in reasons


def test_drawdown_guard_blocks_daily_drawdown_limit() -> None:
    guard = DrawdownGuard(RiskSettings(max_daily_drawdown_pct=0.03))
    state = DrawdownState(
        starting_equity=100_000,
        current_equity=96_500,
        peak_equity=102_000,
        daily_starting_equity=100_000,
    )

    allowed, reasons = guard.can_take_trade(
        state,
        DailyTradeCounter(trading_day=date(2026, 5, 15), trades_taken=1),
    )

    assert allowed is False
    assert "Maximum daily drawdown limit reached." in reasons


def test_risk_manager_approves_valid_trade_without_execution() -> None:
    manager = RiskManager()

    decision = manager.evaluate_trade(
        side=TradeSide.BUY,
        account_equity=100_000,
        entry_price=100,
        atr=2,
        drawdown_state=_healthy_drawdown_state(),
        daily_counter=DailyTradeCounter(trading_day=date(2026, 5, 15), trades_taken=0),
        supertrend=99,
        opposite_bollinger_band=104,
    )

    assert decision.status == RiskDecisionStatus.APPROVED
    assert decision.approved is True
    assert decision.levels is not None
    assert decision.position_size is not None
    assert not hasattr(manager, "submit_order")


def test_risk_manager_blocks_guardrail_failure() -> None:
    manager = RiskManager()

    decision = manager.evaluate_trade(
        side=TradeSide.BUY,
        account_equity=100_000,
        entry_price=100,
        atr=2,
        drawdown_state=_healthy_drawdown_state(),
        daily_counter=DailyTradeCounter(trading_day=date(2026, 5, 15), trades_taken=3),
    )

    assert decision.status == RiskDecisionStatus.BLOCKED
    assert decision.approved is False
    assert "Maximum daily trade limit reached." in decision.reasons


def test_risk_manager_blocks_bot2_portfolio_caps() -> None:
    manager = RiskManager()

    decision = manager.evaluate_trade(
        side=TradeSide.BUY,
        account_equity=100_000,
        entry_price=100,
        atr=3,
        drawdown_state=_healthy_drawdown_state(),
        daily_counter=DailyTradeCounter(trading_day=date(2026, 5, 15), trades_taken=0),
        open_positions_count=25,
        deployed_notional=96_000,
        cash=3_000,
        sector_notional=60_000,
    )

    assert decision.status == RiskDecisionStatus.BLOCKED
    assert "Maximum open position limit reached." in decision.reasons
    assert "Maximum deployed capital limit reached." in decision.reasons
    assert "Cash reserve requirement not met." in decision.reasons
    assert "Maximum sector concentration reached." in decision.reasons


def test_risk_settings_default_daily_loss_limit_is_two_percent() -> None:
    assert RiskSettings().max_daily_drawdown_pct == 0.02
    assert RiskSettings().max_open_positions == 25


def test_position_sizer_rejects_more_than_one_percent_risk() -> None:
    with pytest.raises(ValueError):
        calculate_position_size(
            account_equity=100_000,
            entry_price=100,
            stop_loss=99,
            settings=RiskSettings(risk_per_trade=0.02),
        )
