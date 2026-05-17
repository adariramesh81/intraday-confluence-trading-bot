"""CLI helpers for dashboard user administration."""

from __future__ import annotations

import argparse

from app.config import load_config
from app.dashboard.user_store import DashboardUserStore, generate_temporary_password


def main() -> None:
    """Run dashboard user administration commands."""

    parser = argparse.ArgumentParser(description="Manage dashboard user accounts.")
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_admin = subparsers.add_parser("create-admin", help="Create or reset an admin account.")
    create_admin.add_argument("--email", required=True, help="Admin email address.")

    args = parser.parse_args()
    config = load_config(args.config)
    store = DashboardUserStore(config.storage.sqlite_path)
    store.initialize()

    if args.command == "create-admin":
        password = generate_temporary_password()
        existing = store.get_user(args.email)
        if existing is None:
            store.create_user(args.email, password, is_admin=True, temporary_password=True)
            action = "created"
        else:
            password = store.reset_temporary_password(args.email)
            if not existing.is_admin:
                store.ensure_admin_user(args.email)
            action = "reset"
        print(f"Admin {action}: {args.email.strip().lower()}")
        print(f"Temporary password: {password}")
        print("This password is shown once. Store it safely and change it after login.")


if __name__ == "__main__":
    main()
