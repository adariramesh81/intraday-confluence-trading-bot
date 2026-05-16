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
    monkeypatch.setenv("MAX_TRADES_PER_DAY", "3")

    config = load_config(config_path)

    assert config.trading.default_symbol == "SPY"
    assert config.trading.max_trades_per_day == 3


def test_dashboard_auth_environment_overrides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DASHBOARD_AUTH_ENABLED", "true")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "secret")

    config = load_config(config_path)

    assert config.dashboard.auth_enabled is True
    assert config.dashboard.username == "admin"
    assert config.dashboard.password == "secret"


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
