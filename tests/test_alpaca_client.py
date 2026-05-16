from app.config import AlpacaConfig, AppConfig, TradingConfig
from app.execution.alpaca_client import AlpacaCredentialsError, AlpacaExecutionClient


class _FakeResponse:
    def __init__(self, payload: list[dict[str, str]]) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> list[dict[str, str]]:
        return self.payload


def test_alpaca_client_requires_credentials_before_connecting() -> None:
    config = AppConfig()
    client = AlpacaExecutionClient(config)

    try:
        client.connect()
    except AlpacaCredentialsError:
        return

    raise AssertionError("Expected missing credentials to block Alpaca connection.")


def test_paper_mode_remains_enabled_when_live_trading_is_false() -> None:
    config = AppConfig(
        alpaca=AlpacaConfig(api_key="key", secret_key="secret", paper=False),
        trading=TradingConfig(live_trading=False),
    )
    client = AlpacaExecutionClient(config, trading_client=object())

    assert client.is_paper_trading() is True


def test_account_activities_paginates_with_alpaca_page_size_cap(monkeypatch) -> None:
    config = AppConfig(alpaca=AlpacaConfig(api_key="key", secret_key="secret"))
    client = AlpacaExecutionClient(config)
    calls: list[dict[str, object]] = []

    def fake_get(endpoint: str, headers: dict[str, str], params: dict[str, object], timeout: int) -> _FakeResponse:
        calls.append(params.copy())
        if len(calls) == 1:
            return _FakeResponse([{"id": f"activity-{index}"} for index in range(100)])
        return _FakeResponse([{"id": f"activity-{index}"} for index in range(100, 120)])

    monkeypatch.setattr("app.execution.alpaca_client.requests.get", fake_get)

    activities = client.get_account_activities(limit=120)

    assert len(activities) == 120
    assert calls[0]["page_size"] == 100
    assert calls[1]["page_size"] == 20
    assert calls[1]["page_token"] == "activity-99"
