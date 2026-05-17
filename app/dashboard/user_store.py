"""SQLite-backed dashboard user accounts."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PASSWORD_ITERATIONS = 260_000


@dataclass(frozen=True)
class DashboardUser:
    """Dashboard user account loaded from SQLite."""

    email: str
    password_hash: str
    is_admin: bool
    is_active: bool
    temporary_password: bool
    created_at: str
    updated_at: str
    last_login_at: str | None = None


class DashboardUserStore:
    """Persist and authenticate dashboard user accounts."""

    def __init__(self, sqlite_path: str | Path) -> None:
        self.sqlite_path = Path(sqlite_path)

    def initialize(self) -> None:
        """Create the dashboard user table when missing."""

        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS dashboard_users (
                    email TEXT PRIMARY KEY,
                    password_hash TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    temporary_password INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login_at TEXT
                )
                """
            )

    def list_users(self) -> list[DashboardUser]:
        """Return dashboard users ordered by email."""

        self.initialize()
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM dashboard_users ORDER BY email").fetchall()
        return [_user_from_row(row) for row in rows]

    def get_user(self, email: str) -> DashboardUser | None:
        """Return a user by normalized email."""

        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM dashboard_users WHERE email = ?",
                (_normalize_email(email),),
            ).fetchone()
        return _user_from_row(row) if row else None

    def create_user(
        self,
        email: str,
        password: str,
        is_admin: bool = False,
        temporary_password: bool = True,
    ) -> DashboardUser:
        """Create a dashboard user."""

        normalized_email = _normalize_email(email)
        if not normalized_email:
            raise ValueError("email is required.")
        if not password:
            raise ValueError("password is required.")
        now = _utc_now_iso()
        self.initialize()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO dashboard_users
                (email, password_hash, is_admin, is_active, temporary_password, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    normalized_email,
                    hash_password(password),
                    int(is_admin),
                    int(temporary_password),
                    now,
                    now,
                ),
            )
        user = self.get_user(normalized_email)
        if user is None:
            raise RuntimeError("Failed to create dashboard user.")
        return user

    def ensure_admin_user(self, email: str) -> bool:
        """Ensure an admin user exists for the configured email.

        Returns True when a new inaccessible temporary password was generated.
        Use the CLI reset command to print a replacement password when needed.
        """

        normalized_email = _normalize_email(email)
        if not normalized_email:
            return False
        existing = self.get_user(normalized_email)
        if existing is None:
            self.create_user(
                normalized_email,
                generate_temporary_password(),
                is_admin=True,
                temporary_password=True,
            )
            return True
        if not existing.is_admin:
            self._update_flags(normalized_email, is_admin=True, is_active=existing.is_active)
        return False

    def authenticate(self, email: str, password: str) -> DashboardUser | None:
        """Authenticate an active user and update last login time."""

        user = self.get_user(email)
        if user is None or not user.is_active or not verify_password(password, user.password_hash):
            return None
        with self._connect() as connection:
            connection.execute(
                "UPDATE dashboard_users SET last_login_at = ?, updated_at = ? WHERE email = ?",
                (_utc_now_iso(), _utc_now_iso(), user.email),
            )
        return self.get_user(user.email)

    def change_password(self, email: str, password: str) -> DashboardUser:
        """Set a permanent password and clear temporary password status."""

        if not password:
            raise ValueError("password is required.")
        normalized_email = _normalize_email(email)
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE dashboard_users
                SET password_hash = ?, temporary_password = 0, updated_at = ?
                WHERE email = ?
                """,
                (hash_password(password), _utc_now_iso(), normalized_email),
            )
        user = self.get_user(normalized_email)
        if user is None:
            raise ValueError("User not found.")
        return user

    def reset_temporary_password(self, email: str) -> str:
        """Reset a user password to a generated temporary value and return it once."""

        password = generate_temporary_password()
        normalized_email = _normalize_email(email)
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE dashboard_users
                SET password_hash = ?, temporary_password = 1, updated_at = ?
                WHERE email = ?
                """,
                (hash_password(password), _utc_now_iso(), normalized_email),
            )
        if cursor.rowcount == 0:
            raise ValueError("User not found.")
        return password

    def set_active(self, email: str, is_active: bool) -> None:
        """Activate or deactivate a dashboard user."""

        user = self.get_user(email)
        if user is None:
            raise ValueError("User not found.")
        self._update_flags(user.email, is_admin=user.is_admin, is_active=is_active)

    def _update_flags(self, email: str, is_admin: bool, is_active: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE dashboard_users
                SET is_admin = ?, is_active = ?, updated_at = ?
                WHERE email = ?
                """,
                (int(is_admin), int(is_active), _utc_now_iso(), _normalize_email(email)),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.sqlite_path)
        connection.row_factory = sqlite3.Row
        return connection


def generate_temporary_password() -> str:
    """Generate a strong temporary password for manual delivery."""

    return secrets.token_urlsafe(18)


def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256."""

    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode("ascii"),
        base64.urlsafe_b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against a stored PBKDF2 hash."""

    try:
        algorithm, iterations, salt, expected_digest = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt_bytes = base64.urlsafe_b64decode(salt.encode("ascii"))
        expected_digest_bytes = base64.urlsafe_b64decode(expected_digest.encode("ascii"))
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, int(iterations))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest, expected_digest_bytes)


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def _user_from_row(row: sqlite3.Row) -> DashboardUser:
    return DashboardUser(
        email=row["email"],
        password_hash=row["password_hash"],
        is_admin=bool(row["is_admin"]),
        is_active=bool(row["is_active"]),
        temporary_password=bool(row["temporary_password"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        last_login_at=row["last_login_at"],
    )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
