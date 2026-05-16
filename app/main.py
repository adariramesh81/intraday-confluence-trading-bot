"""Application entrypoint for bootstrapping paper trading infrastructure."""

from __future__ import annotations

from app.config import load_config
from app.execution.alpaca_client import AlpacaCredentialsError, AlpacaExecutionClient, LiveTradingSafetyError
from app.execution.paper_trader import PaperTrader
from app.utils.logger import configure_logging


def main() -> None:
    """Load configuration, initialize logging, and verify paper trading components."""

    config = load_config()
    logger = configure_logging(config.logging)
    logger.info(
        "Starting intraday confluence trading bot.",
        extra={"env": config.env, "live_trading": config.trading.live_trading},
    )

    alpaca_client = AlpacaExecutionClient(config=config, logger=logger)
    try:
        alpaca_client.connect()
        PaperTrader(client=alpaca_client, logger=logger)
        logger.info("Paper trading execution engine initialized.")
    except AlpacaCredentialsError:
        logger.warning("Alpaca credentials are not configured; skipping API connection during startup.")
    except LiveTradingSafetyError:
        logger.exception("Live trading is disabled for this execution phase.")
        raise


if __name__ == "__main__":
    main()
