from pathlib import Path

import pytest

from app.data.account_store import AccountDataStore
from app.utils.validators import DataValidationError


def test_watchlist_store_seeds_from_default_when_empty(tmp_path: Path) -> None:
    store = AccountDataStore(tmp_path / "bot.sqlite3")

    symbols = store.get_watchlist(("spy", "qqq"))

    assert symbols == ["SPY", "QQQ"]
    assert store.get_watchlist(("AAPL",)) == ["SPY", "QQQ"]


def test_watchlist_store_persists_normalized_deduped_symbols(tmp_path: Path) -> None:
    store = AccountDataStore(tmp_path / "bot.sqlite3")

    saved = store.save_watchlist(["spy", "QQQ", "spy", "BRK.B"])

    assert saved == ["SPY", "QQQ", "BRK.B"]
    assert store.get_watchlist(("AAPL",)) == ["SPY", "QQQ", "BRK.B"]


def test_watchlist_store_rejects_invalid_or_empty_symbols(tmp_path: Path) -> None:
    store = AccountDataStore(tmp_path / "bot.sqlite3")

    with pytest.raises(DataValidationError):
        store.save_watchlist([])
    with pytest.raises(DataValidationError):
        store.save_watchlist(["123BAD"])
