import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import AlertConfig, AppConfig, DashboardConfig, StorageConfig
from app.dashboard.schemas import (
    BacktestMetricsView,
    HealthStatus,
    PortfolioView,
    PositionView,
    SignalView,
    TradeView,
)
from app.dashboard.server import create_app
from app.dashboard.state_manager import DashboardStateManager
from app.dashboard.user_store import DashboardUserStore
from app.utils.alert_manager import AlertManager


def _state_manager() -> DashboardStateManager:
    state = DashboardStateManager()
    state.update_health(
        HealthStatus(
            status="ok",
            environment="test",
            paper_trading=True,
            live_trading_enabled=False,
            messages=["ready"],
        )
    )
    state.update_portfolio(
        PortfolioView(
            equity=100_000,
            cash=50_000,
            buying_power=150_000,
            portfolio_value=101_000,
            daily_pl=500,
            daily_pl_pct=0.005,
        ),
        positions=[
            PositionView(
                symbol="SPY",
                quantity=10,
                market_value=1010,
                average_entry_price=100,
                current_price=101,
                unrealized_pl=10,
                unrealized_plpc=0.01,
            )
        ],
    )
    state.update_trades(
        [
            TradeView(
                symbol="SPY",
                side="BUY",
                quantity=10,
                entry_price=100,
                exit_price=102,
                opened_at=datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
                closed_at=datetime(2026, 5, 15, 10, 30, tzinfo=ZoneInfo("America/New_York")),
                realized_pl=20,
            )
        ]
    )
    state.add_signal(
        SignalView(
            symbol="SPY",
            side="BUY",
            signal_type="PULLBACK",
            score=100,
            should_trade=True,
            timestamp=datetime(2026, 5, 15, 10, 0, tzinfo=ZoneInfo("America/New_York")),
        )
    )
    state.update_backtest_metrics(
        BacktestMetricsView(
            win_rate=0.6,
            profit_factor=1.8,
            drawdown=0.04,
            sharpe_ratio=1.2,
            expectancy=45,
            total_trades=50,
        )
    )
    return state


def _auth_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        dashboard=DashboardConfig(
            title="Test Dashboard",
            auth_enabled=True,
            session_secret="test-session-secret",
            admin_email="admin@example.com",
        ),
        storage=StorageConfig(sqlite_path=tmp_path / "dashboard.sqlite3"),
    )


def _user_store(config: AppConfig) -> DashboardUserStore:
    store = DashboardUserStore(config.storage.sqlite_path)
    store.initialize()
    return store


def _auth_app(
    tmp_path: Path,
    email: str = "admin@example.com",
    password: str = "secret-password",
    is_admin: bool = True,
    temporary_password: bool = False,
) -> tuple[TestClient, DashboardUserStore]:
    config = _auth_config(tmp_path)
    store = _user_store(config)
    store.create_user(email, password, is_admin=is_admin, temporary_password=temporary_password)
    app = create_app(config=config, state_manager=_state_manager(), user_store=store)
    return TestClient(app), store


def _login(client: TestClient, email: str = "admin@example.com", password: str = "secret-password"):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_dashboard_api_returns_read_only_snapshot() -> None:
    app = create_app(
        config=AppConfig(dashboard=DashboardConfig(title="Test Dashboard")),
        state_manager=_state_manager(),
    )
    client = TestClient(app)

    response = client.get("/api/snapshot")

    assert response.status_code == 200
    payload = response.json()
    assert payload["portfolio"]["equity"] == 100_000
    assert payload["positions"][0]["symbol"] == "SPY"
    assert payload["signals"][0]["score"] == 100


def test_dashboard_auth_redirects_unauthenticated_page_and_blocks_snapshot(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    page_response = client.get("/", follow_redirects=False)
    snapshot_response = client.get("/api/snapshot")

    assert page_response.status_code == 303
    assert page_response.headers["location"] == "/login"
    assert snapshot_response.status_code == 401
    assert snapshot_response.json()["detail"] == "Authentication required."


def test_login_page_renders_before_dashboard(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    response = client.get("/login")

    assert response.status_code == 200
    assert "Sign in to view the read-only trading dashboard." in response.text
    assert 'name="email"' in response.text
    assert 'name="password"' in response.text


def test_login_sets_session_cookie_and_allows_dashboard_access(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    login_response = _login(client)
    page_response = client.get("/")
    snapshot_response = client.get("/api/snapshot")

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/"
    assert "dashboard_session=" in login_response.headers["set-cookie"]
    assert page_response.status_code == 200
    assert "Logout" in page_response.text
    assert snapshot_response.status_code == 200
    assert snapshot_response.json()["portfolio"]["cash"] == 50_000


def test_startup_bootstrap_admin_password_allows_login(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DASHBOARD_ADMIN_BOOTSTRAP_PASSWORD", "bootstrap-secret")
    config = _auth_config(tmp_path)
    store = _user_store(config)
    app = create_app(config=config, state_manager=_state_manager(), user_store=store)
    client = TestClient(app)

    login_response = _login(client, password="bootstrap-secret")
    user = store.get_user("admin@example.com")

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/"
    assert user.is_admin is True
    assert user.is_active is True
    assert user.temporary_password is False


def test_login_rejects_invalid_credentials_without_session_cookie(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    response = _login(client, password="wrong")

    assert response.status_code == 401
    assert "Invalid username or password." in response.text
    assert "dashboard_session=" not in response.headers.get("set-cookie", "")


def test_user_store_hashes_passwords_and_blocks_inactive_users(tmp_path: Path) -> None:
    config = _auth_config(tmp_path)
    store = _user_store(config)

    user = store.create_user("friend@example.com", "temporary-secret", temporary_password=True)
    store.set_active(user.email, False)

    assert "temporary-secret" not in user.password_hash
    assert store.authenticate("friend@example.com", "temporary-secret") is None


def test_temporary_password_user_must_change_password(tmp_path: Path) -> None:
    client, store = _auth_app(tmp_path, temporary_password=True)

    login_response = _login(client)
    dashboard_response = client.get("/", follow_redirects=False)
    blocked_snapshot = client.get("/api/snapshot")
    change_response = client.post(
        "/change-password",
        data={"password": "new-secret-password", "confirm_password": "new-secret-password"},
        follow_redirects=False,
    )
    dashboard_after_change = client.get("/")

    assert login_response.status_code == 303
    assert login_response.headers["location"] == "/change-password"
    assert dashboard_response.status_code == 303
    assert dashboard_response.headers["location"] == "/change-password"
    assert blocked_snapshot.status_code == 403
    assert change_response.status_code == 303
    assert change_response.headers["location"] == "/"
    assert store.get_user("admin@example.com").temporary_password is False
    assert dashboard_after_change.status_code == 200


def test_logout_clears_session_and_returns_to_login(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    _login(client)
    logout_response = client.get("/logout", follow_redirects=False)
    page_response = client.get("/", follow_redirects=False)

    assert logout_response.status_code == 303
    assert logout_response.headers["location"] == "/login"
    assert "dashboard_session=" in logout_response.headers["set-cookie"]
    assert page_response.status_code == 303
    assert page_response.headers["location"] == "/login"


def test_dashboard_auth_fails_closed_when_credentials_missing() -> None:
    app = create_app(
        config=AppConfig(dashboard=DashboardConfig(auth_enabled=True)),
        state_manager=_state_manager(),
    )
    client = TestClient(app)

    response = client.get("/api/snapshot")

    assert response.status_code == 401


def test_healthz_stays_public_and_non_sensitive_with_auth_enabled(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "portfolio" not in response.text
    assert "cash" not in response.text


def test_admin_can_manage_dashboard_users(tmp_path: Path) -> None:
    client, store = _auth_app(tmp_path)

    _login(client)
    page = client.get("/admin/users")
    create_response = client.post(
        "/admin/users",
        data={"action": "create", "email": "friend@example.com"},
    )
    generated_match = re.search(r"<strong>([^<]+)</strong>", create_response.text)
    assert generated_match is not None
    assert store.authenticate("friend@example.com", generated_match.group(1)) is not None
    reset_response = client.post(
        "/admin/users",
        data={"action": "reset", "email": "friend@example.com"},
    )
    deactivate_response = client.post(
        "/admin/users",
        data={"action": "deactivate", "email": "friend@example.com"},
    )
    inactive_user = store.get_user("friend@example.com")
    activate_response = client.post(
        "/admin/users",
        data={"action": "activate", "email": "friend@example.com"},
    )

    assert page.status_code == 200
    assert "Dashboard Users" in page.text
    assert create_response.status_code == 200
    assert "Temporary Password" in create_response.text
    assert "friend@example.com" in create_response.text
    assert reset_response.status_code == 200
    assert "Temporary Password" in reset_response.text
    assert deactivate_response.status_code == 200
    assert inactive_user.is_active is False
    assert activate_response.status_code == 200
    assert store.get_user("friend@example.com").is_active is True


def test_non_admin_cannot_access_user_admin(tmp_path: Path) -> None:
    client, _ = _auth_app(
        tmp_path,
        email="friend@example.com",
        password="friend-secret",
        is_admin=False,
    )

    _login(client, email="friend@example.com", password="friend-secret")
    response = client.get("/admin/users")

    assert response.status_code == 403


def test_dashboard_api_exposes_expected_read_only_routes() -> None:
    app = create_app(config=AppConfig(), state_manager=_state_manager())
    route_methods = {
        route.path: route.methods
        for route in app.routes
        if route.path.startswith("/api")
    }

    assert route_methods["/api/health"] == {"GET"}
    assert route_methods["/api/portfolio"] == {"GET"}
    assert route_methods["/api/positions"] == {"GET"}
    assert route_methods["/api/trades"] == {"GET"}
    assert route_methods["/api/signals"] == {"GET"}
    assert route_methods["/api/backtests"] == {"GET"}
    assert route_methods["/api/snapshot"] == {"GET"}


def test_dashboard_page_renders_without_trading_controls() -> None:
    app = create_app(config=AppConfig(), state_manager=_state_manager())
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Open Positions" in response.text
    assert "Trade History" in response.text
    assert "submit_order" not in response.text
    assert "LIVE_TRADING" not in response.text


def test_dashboard_websocket_sends_initial_snapshot() -> None:
    app = create_app(config=AppConfig(), state_manager=_state_manager())
    client = TestClient(app)

    with client.websocket_connect("/ws/dashboard") as websocket:
        payload = websocket.receive_json()

    assert payload["health"]["status"] == "ok"
    assert payload["portfolio"]["cash"] == 50_000


def test_dashboard_websocket_rejects_unauthenticated_connection(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/dashboard"):
            pass


def test_dashboard_websocket_allows_valid_session_cookie(tmp_path: Path) -> None:
    client, _ = _auth_app(tmp_path)

    _login(client)
    with client.websocket_connect("/ws/dashboard") as websocket:
        payload = websocket.receive_json()

    assert payload["portfolio"]["cash"] == 50_000


def test_state_manager_keeps_latest_signal_first_and_caps_history() -> None:
    state = DashboardStateManager()

    for index in range(105):
        state.add_signal(
            SignalView(
                symbol=f"T{index}",
                side="BUY",
                signal_type="BREAKOUT",
                score=index,
                should_trade=True,
            )
        )

    snapshot = state.snapshot()
    assert len(snapshot.signals) == 100
    assert snapshot.signals[0].symbol == "T104"


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps({"ok": True}).encode("utf-8")


class FakeSMTP:
    def __init__(self, host, port, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.messages = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def starttls(self):
        return None

    def login(self, username, password):
        self.username = username
        self.password = password

    def send_message(self, message):
        self.messages.append(message)


def test_alert_manager_skips_when_disabled() -> None:
    result = AlertManager(AlertConfig(enabled=False)).send_alert("Signal", "BUY SPY")

    assert result.skipped is True
    assert result.delivered is False


def test_alert_manager_sends_telegram_and_email_without_network() -> None:
    requests = []
    smtp_instances = []

    def fake_urlopen(request, timeout=10):
        requests.append(request)
        return FakeResponse()

    def fake_smtp(host, port, timeout=10):
        smtp = FakeSMTP(host, port, timeout)
        smtp_instances.append(smtp)
        return smtp

    manager = AlertManager(
        AlertConfig(
            enabled=True,
            telegram_bot_token="token",
            telegram_chat_id="chat",
            email_enabled=True,
            smtp_host="smtp.example.com",
            smtp_username="user",
            smtp_password="pass",
            email_from="bot@example.com",
            email_to="desk@example.com",
        ),
        urlopen=fake_urlopen,
        smtp_factory=fake_smtp,
    )

    result = manager.send_alert("Risk", "Daily drawdown warning", severity="warning")

    assert result.delivered is True
    assert result.channels == ["telegram", "email"]
    assert requests
    assert smtp_instances[0].messages
