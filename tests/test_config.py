from pathlib import Path

import pytest

from app.config import ConfigError, load_config


def test_load_config_defaults_to_paper_trading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIVE_TRADING", raising=False)
    monkeypatch.delenv("ALPACA_PAPER", raising=False)

    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")

    config = load_config(config_path)

    assert config.trading.live_trading is False
    assert config.alpaca.paper is True
    assert config.trading.risk_per_trade == 0.01
    assert config.trading.max_trades_per_day == 3
    assert config.trading.watchlist == ("SPY",)
    assert config.trading.scan_interval_seconds == 60
    assert config.trading.strategy == "bot2"
    assert config.risk.max_position_notional_pct == 0.15
    assert config.risk.max_daily_drawdown == 0.02
    assert config.market_data.source == "alpaca"
    assert config.market_data.default_timeframe == "1Min"


def test_environment_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
trading:
  default_symbol: QQQ
  max_trades_per_day: 2
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEFAULT_SYMBOL", "SPY")
    monkeypatch.setenv("TRADING_WATCHLIST", "SPY,QQQ")
    monkeypatch.setenv("TRADING_SCAN_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("MAX_TRADES_PER_DAY", "3")
    monkeypatch.setenv("RISK_MAX_OPEN_POSITIONS", "25")

    config = load_config(config_path)

    assert config.trading.default_symbol == "SPY"
    assert config.trading.watchlist == ("SPY", "QQQ")
    assert config.trading.scan_interval_seconds == 30
    assert config.trading.max_trades_per_day == 3
    assert config.risk.max_open_positions == 25


def test_dashboard_auth_environment_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "session-secret")
    monkeypatch.setenv("DASHBOARD_ADMIN_EMAIL", "admin@example.com")

    config = load_config(config_path)

    assert config.dashboard.auth_enabled is True
    assert config.dashboard.session_secret == "session-secret"
    assert config.dashboard.admin_email == "admin@example.com"


def test_live_trading_requires_explicit_non_paper_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("LIVE_TRADING", "true")
    monkeypatch.setenv("ALPACA_PAPER", "true")

    with pytest.raises(ConfigError):
        load_config(config_path)


def test_market_data_retry_attempts_must_be_positive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("MARKET_DATA_RETRY_ATTEMPTS", "0")

    with pytest.raises(ConfigError):
        load_config(config_path)
