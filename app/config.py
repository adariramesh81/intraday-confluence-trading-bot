"""Configuration loading and validation for the trading bot."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class LoggingConfig:
    """Logging settings used by the application."""

    level: str = "INFO"
    file_path: Path = Path("logs/trading_bot.log")
    max_bytes: int = 10_485_760
    backup_count: int = 5


@dataclass(frozen=True)
class AlpacaConfig:
    """Alpaca brokerage credentials and endpoint settings."""

    api_key: str = ""
    secret_key: str = ""
    paper: bool = True
    paper_base_url: str = "https://paper-api.alpaca.markets"
    live_base_url: str = "https://api.alpaca.markets"


@dataclass(frozen=True)
class TradingConfig:
    """Trading risk and mode settings."""

    live_trading: bool = False
    default_symbol: str = "SPY"
    max_trades_per_day: int = 3
    risk_per_trade: float = 0.01


@dataclass(frozen=True)
class MarketDataConfig:
    """Market data provider, retry, and timezone settings."""

    source: str = "alpaca"
    default_timeframe: str = "1Min"
    feed: str = "iex"
    adjustment: str = "raw"
    timezone: str = "America/New_York"
    retry_attempts: int = 3
    retry_backoff_seconds: float = 1.0
    timeout_seconds: int = 30


@dataclass(frozen=True)
class DashboardConfig:
    """Dashboard runtime settings."""

    host: str = "127.0.0.1"
    port: int = 8000
    refresh_seconds: int = 5
    title: str = "Intraday Confluence Bot"
    auth_enabled: bool = False
    session_secret: str = ""
    admin_email: str = ""


@dataclass(frozen=True)
class AlertConfig:
    """Telegram and email alert settings."""

    enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    email_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    email_to: str = ""


@dataclass(frozen=True)
class StorageConfig:
    """Local persistent storage settings."""

    sqlite_path: Path = Path("data/trading_bot.sqlite3")


@dataclass(frozen=True)
class AlpacaSyncConfig:
    """Alpaca paper account sync settings."""

    enabled: bool = True
    refresh_seconds: int = 30
    order_limit: int = 500
    portfolio_history_days: int = 30


@dataclass(frozen=True)
class AppConfig:
    """Root application configuration."""

    env: str = "development"
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    alpaca: AlpacaConfig = field(default_factory=AlpacaConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    alerts: AlertConfig = field(default_factory=AlertConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    alpaca_sync: AlpacaSyncConfig = field(default_factory=AlpacaSyncConfig)


class ConfigError(ValueError):
    """Raised when configuration values are missing or invalid."""


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    """Load configuration from YAML and environment variable overrides."""

    _load_dotenv_if_available()
    config_path = Path(path)
    raw_config: dict[str, Any] = {}

    if config_path.exists():
        try:
            import yaml
        except ImportError as exc:
            raise ConfigError("PyYAML is required to load config.yaml.") from exc

        with config_path.open("r", encoding="utf-8") as config_file:
            loaded = yaml.safe_load(config_file) or {}
            if not isinstance(loaded, dict):
                raise ConfigError("config.yaml must contain a mapping at the top level.")
            raw_config = loaded

    config = _build_config(raw_config)
    return _apply_environment_overrides(config)


def _build_config(raw_config: Mapping[str, Any]) -> AppConfig:
    app_config = _mapping(raw_config.get("app"))
    logging_config = _mapping(raw_config.get("logging"))
    alpaca_config = _mapping(raw_config.get("alpaca"))
    trading_config = _mapping(raw_config.get("trading"))
    market_data_config = _mapping(raw_config.get("market_data"))
    dashboard_config = _mapping(raw_config.get("dashboard"))
    alert_config = _mapping(raw_config.get("alerts"))
    storage_config = _mapping(raw_config.get("storage"))
    alpaca_sync_config = _mapping(raw_config.get("alpaca_sync"))

    return _validate_config(
        AppConfig(
            env=str(app_config.get("env", "development")),
            logging=LoggingConfig(
                level=str(logging_config.get("level", "INFO")),
                file_path=Path(str(logging_config.get("file_path", "logs/trading_bot.log"))),
                max_bytes=_as_int(logging_config.get("max_bytes", 10_485_760), "logging.max_bytes"),
                backup_count=_as_int(logging_config.get("backup_count", 5), "logging.backup_count"),
            ),
            alpaca=AlpacaConfig(
                api_key=str(alpaca_config.get("api_key", "")),
                secret_key=str(alpaca_config.get("secret_key", "")),
                paper=_as_bool(alpaca_config.get("paper", True), "alpaca.paper"),
                paper_base_url=str(
                    alpaca_config.get("paper_base_url", "https://paper-api.alpaca.markets")
                ),
                live_base_url=str(alpaca_config.get("live_base_url", "https://api.alpaca.markets")),
            ),
            trading=TradingConfig(
                live_trading=_as_bool(trading_config.get("live_trading", False), "trading.live_trading"),
                default_symbol=str(trading_config.get("default_symbol", "SPY")),
                max_trades_per_day=_as_int(
                    trading_config.get("max_trades_per_day", 3), "trading.max_trades_per_day"
                ),
                risk_per_trade=_as_float(trading_config.get("risk_per_trade", 0.01), "trading.risk_per_trade"),
            ),
            market_data=MarketDataConfig(
                source=str(market_data_config.get("source", "alpaca")),
                default_timeframe=str(market_data_config.get("default_timeframe", "1Min")),
                feed=str(market_data_config.get("feed", "iex")),
                adjustment=str(market_data_config.get("adjustment", "raw")),
                timezone=str(market_data_config.get("timezone", "America/New_York")),
                retry_attempts=_as_int(
                    market_data_config.get("retry_attempts", 3), "market_data.retry_attempts"
                ),
                retry_backoff_seconds=_as_float(
                    market_data_config.get("retry_backoff_seconds", 1.0),
                    "market_data.retry_backoff_seconds",
                ),
                timeout_seconds=_as_int(
                    market_data_config.get("timeout_seconds", 30), "market_data.timeout_seconds"
                ),
            ),
            dashboard=DashboardConfig(
                host=str(dashboard_config.get("host", "127.0.0.1")),
                port=_as_int(dashboard_config.get("port", 8000), "dashboard.port"),
                refresh_seconds=_as_int(
                    dashboard_config.get("refresh_seconds", 5),
                    "dashboard.refresh_seconds",
                ),
                title=str(dashboard_config.get("title", "Intraday Confluence Bot")),
                auth_enabled=_as_bool(
                    dashboard_config.get("auth_enabled", False),
                    "dashboard.auth_enabled",
                ),
                session_secret=str(dashboard_config.get("session_secret", "")),
                admin_email=str(dashboard_config.get("admin_email", "")),
            ),
            alerts=AlertConfig(
                enabled=_as_bool(alert_config.get("enabled", False), "alerts.enabled"),
                telegram_bot_token=str(alert_config.get("telegram_bot_token", "")),
                telegram_chat_id=str(alert_config.get("telegram_chat_id", "")),
                email_enabled=_as_bool(alert_config.get("email_enabled", False), "alerts.email_enabled"),
                smtp_host=str(alert_config.get("smtp_host", "")),
                smtp_port=_as_int(alert_config.get("smtp_port", 587), "alerts.smtp_port"),
                smtp_username=str(alert_config.get("smtp_username", "")),
                smtp_password=str(alert_config.get("smtp_password", "")),
                email_from=str(alert_config.get("email_from", "")),
                email_to=str(alert_config.get("email_to", "")),
            ),
            storage=StorageConfig(
                sqlite_path=Path(str(storage_config.get("sqlite_path", "data/trading_bot.sqlite3"))),
            ),
            alpaca_sync=AlpacaSyncConfig(
                enabled=_as_bool(alpaca_sync_config.get("enabled", True), "alpaca_sync.enabled"),
                refresh_seconds=_as_int(
                    alpaca_sync_config.get("refresh_seconds", 30),
                    "alpaca_sync.refresh_seconds",
                ),
                order_limit=_as_int(alpaca_sync_config.get("order_limit", 500), "alpaca_sync.order_limit"),
                portfolio_history_days=_as_int(
                    alpaca_sync_config.get("portfolio_history_days", 30),
                    "alpaca_sync.portfolio_history_days",
                ),
            ),
        )
    )


def _apply_environment_overrides(config: AppConfig) -> AppConfig:
    logging_config = LoggingConfig(
        level=os.getenv("LOG_LEVEL", config.logging.level),
        file_path=Path(os.getenv("LOG_FILE_PATH", str(config.logging.file_path))),
        max_bytes=_env_int("LOG_MAX_BYTES", config.logging.max_bytes),
        backup_count=_env_int("LOG_BACKUP_COUNT", config.logging.backup_count),
    )
    alpaca_config = AlpacaConfig(
        api_key=os.getenv("ALPACA_API_KEY", config.alpaca.api_key),
        secret_key=os.getenv("ALPACA_SECRET_KEY", config.alpaca.secret_key),
        paper=_env_bool("ALPACA_PAPER", config.alpaca.paper),
        paper_base_url=os.getenv("ALPACA_PAPER_BASE_URL", config.alpaca.paper_base_url),
        live_base_url=os.getenv("ALPACA_LIVE_BASE_URL", config.alpaca.live_base_url),
    )
    trading_config = TradingConfig(
        live_trading=_env_bool("LIVE_TRADING", config.trading.live_trading),
        default_symbol=os.getenv("DEFAULT_SYMBOL", config.trading.default_symbol),
        max_trades_per_day=_env_int("MAX_TRADES_PER_DAY", config.trading.max_trades_per_day),
        risk_per_trade=_env_float("RISK_PER_TRADE", config.trading.risk_per_trade),
    )
    market_data_config = MarketDataConfig(
        source=os.getenv("MARKET_DATA_SOURCE", config.market_data.source),
        default_timeframe=os.getenv("MARKET_DATA_TIMEFRAME", config.market_data.default_timeframe),
        feed=os.getenv("MARKET_DATA_FEED", config.market_data.feed),
        adjustment=os.getenv("MARKET_DATA_ADJUSTMENT", config.market_data.adjustment),
        timezone=os.getenv("MARKET_DATA_TIMEZONE", config.market_data.timezone),
        retry_attempts=_env_int("MARKET_DATA_RETRY_ATTEMPTS", config.market_data.retry_attempts),
        retry_backoff_seconds=_env_float(
            "MARKET_DATA_RETRY_BACKOFF_SECONDS",
            config.market_data.retry_backoff_seconds,
        ),
        timeout_seconds=_env_int("MARKET_DATA_TIMEOUT_SECONDS", config.market_data.timeout_seconds),
    )
    dashboard_config = DashboardConfig(
        host=os.getenv("DASHBOARD_HOST", config.dashboard.host),
        port=_env_int("DASHBOARD_PORT", config.dashboard.port),
        refresh_seconds=_env_int("DASHBOARD_REFRESH_SECONDS", config.dashboard.refresh_seconds),
        title=os.getenv("DASHBOARD_TITLE", config.dashboard.title),
        auth_enabled=_env_bool("DASHBOARD_AUTH_ENABLED", config.dashboard.auth_enabled),
        session_secret=os.getenv("DASHBOARD_SESSION_SECRET", config.dashboard.session_secret),
        admin_email=os.getenv("DASHBOARD_ADMIN_EMAIL", config.dashboard.admin_email),
    )
    alert_config = AlertConfig(
        enabled=_env_bool("ALERTS_ENABLED", config.alerts.enabled),
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", config.alerts.telegram_bot_token),
        telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", config.alerts.telegram_chat_id),
        email_enabled=_env_bool("EMAIL_ALERTS_ENABLED", config.alerts.email_enabled),
        smtp_host=os.getenv("SMTP_HOST", config.alerts.smtp_host),
        smtp_port=_env_int("SMTP_PORT", config.alerts.smtp_port),
        smtp_username=os.getenv("SMTP_USERNAME", config.alerts.smtp_username),
        smtp_password=os.getenv("SMTP_PASSWORD", config.alerts.smtp_password),
        email_from=os.getenv("ALERT_EMAIL_FROM", config.alerts.email_from),
        email_to=os.getenv("ALERT_EMAIL_TO", config.alerts.email_to),
    )
    storage_config = StorageConfig(
        sqlite_path=Path(os.getenv("SQLITE_PATH", str(config.storage.sqlite_path))),
    )
    alpaca_sync_config = AlpacaSyncConfig(
        enabled=_env_bool("ALPACA_SYNC_ENABLED", config.alpaca_sync.enabled),
        refresh_seconds=_env_int("ALPACA_SYNC_REFRESH_SECONDS", config.alpaca_sync.refresh_seconds),
        order_limit=_env_int("ALPACA_SYNC_ORDER_LIMIT", config.alpaca_sync.order_limit),
        portfolio_history_days=_env_int(
            "ALPACA_SYNC_PORTFOLIO_HISTORY_DAYS",
            config.alpaca_sync.portfolio_history_days,
        ),
    )
    return _validate_config(
        AppConfig(
            env=os.getenv("APP_ENV", config.env),
            logging=logging_config,
            alpaca=alpaca_config,
            trading=trading_config,
            market_data=market_data_config,
            dashboard=dashboard_config,
            alerts=alert_config,
            storage=storage_config,
            alpaca_sync=alpaca_sync_config,
        )
    )


def _validate_config(config: AppConfig) -> AppConfig:
    if config.logging.max_bytes <= 0:
        raise ConfigError("logging.max_bytes must be greater than zero.")
    if config.logging.backup_count < 0:
        raise ConfigError("logging.backup_count cannot be negative.")
    if config.trading.max_trades_per_day <= 0:
        raise ConfigError("trading.max_trades_per_day must be greater than zero.")
    if not 0 < config.trading.risk_per_trade <= 0.01:
        raise ConfigError("trading.risk_per_trade must be greater than 0 and no more than 0.01.")
    if config.trading.live_trading and config.alpaca.paper:
        raise ConfigError("LIVE_TRADING=true requires ALPACA_PAPER=false for explicit live mode selection.")
    if config.market_data.source not in {"alpaca", "yfinance"}:
        raise ConfigError("market_data.source must be either 'alpaca' or 'yfinance'.")
    if config.market_data.retry_attempts <= 0:
        raise ConfigError("market_data.retry_attempts must be greater than zero.")
    if config.market_data.retry_backoff_seconds < 0:
        raise ConfigError("market_data.retry_backoff_seconds cannot be negative.")
    if config.market_data.timeout_seconds <= 0:
        raise ConfigError("market_data.timeout_seconds must be greater than zero.")
    if not 1 <= config.dashboard.port <= 65535:
        raise ConfigError("dashboard.port must be between 1 and 65535.")
    if config.dashboard.refresh_seconds <= 0:
        raise ConfigError("dashboard.refresh_seconds must be greater than zero.")
    if not 1 <= config.alerts.smtp_port <= 65535:
        raise ConfigError("alerts.smtp_port must be between 1 and 65535.")
    if config.alpaca_sync.refresh_seconds <= 0:
        raise ConfigError("alpaca_sync.refresh_seconds must be greater than zero.")
    if config.alpaca_sync.order_limit <= 0:
        raise ConfigError("alpaca_sync.order_limit must be greater than zero.")
    if config.alpaca_sync.portfolio_history_days <= 0:
        raise ConfigError("alpaca_sync.portfolio_history_days must be greater than zero.")
    return config


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(override=False)


def _mapping(value: Any) -> Mapping[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigError("Configuration sections must be mappings.")
    return value


def _env_bool(name: str, default: bool) -> bool:
    return _as_bool(os.getenv(name, default), name)


def _env_int(name: str, default: int) -> int:
    return _as_int(os.getenv(name, default), name)


def _env_float(name: str, default: float) -> float:
    return _as_float(os.getenv(name, default), name)


def _as_bool(value: Any, name: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    raise ConfigError(f"{name} must be a boolean value.")


def _as_int(value: Any, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer.") from exc


def _as_float(value: Any, name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be a number.") from exc
