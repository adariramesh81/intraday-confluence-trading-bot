"""Telegram and email alert delivery."""

from __future__ import annotations

import json
import smtplib
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Callable

from app.config import AlertConfig


@dataclass(frozen=True)
class AlertResult:
    """Alert delivery result."""

    delivered: bool
    channels: list[str] = field(default_factory=list)
    skipped: bool = False
    errors: list[str] = field(default_factory=list)


class AlertManager:
    """Send monitoring alerts through configured Telegram and email channels."""

    def __init__(
        self,
        config: AlertConfig,
        urlopen: Callable | None = None,
        smtp_factory: Callable[..., smtplib.SMTP] | None = None,
    ) -> None:
        self.config = config
        self._urlopen = urlopen or urllib.request.urlopen
        self._smtp_factory = smtp_factory or smtplib.SMTP

    def send_alert(self, subject: str, message: str, severity: str = "info") -> AlertResult:
        """Send an alert to every enabled channel."""

        if not self.config.enabled:
            return AlertResult(delivered=False, skipped=True)

        channels: list[str] = []
        errors: list[str] = []
        formatted_message = f"[{severity.upper()}] {subject}\n{message}"

        if self.config.telegram_bot_token and self.config.telegram_chat_id:
            try:
                self.send_telegram_alert(formatted_message)
                channels.append("telegram")
            except Exception as exc:
                errors.append(f"telegram: {exc}")

        if self.config.email_enabled:
            try:
                self.send_email_alert(subject=subject, message=formatted_message)
                channels.append("email")
            except Exception as exc:
                errors.append(f"email: {exc}")

        return AlertResult(delivered=bool(channels), channels=channels, errors=errors)

    def send_telegram_alert(self, message: str) -> None:
        """Send a Telegram alert using the Bot API."""

        if not self.config.telegram_bot_token or not self.config.telegram_chat_id:
            raise ValueError("Telegram bot token and chat id are required.")

        endpoint = f"https://api.telegram.org/bot{self.config.telegram_bot_token}/sendMessage"
        payload = urllib.parse.urlencode(
            {
                "chat_id": self.config.telegram_chat_id,
                "text": message,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with self._urlopen(request, timeout=10) as response:
            body = response.read()
            if getattr(response, "status", 200) >= 400:
                raise RuntimeError(f"Telegram alert failed with status {response.status}.")
            if body:
                parsed = json.loads(body.decode("utf-8"))
                if not parsed.get("ok", True):
                    raise RuntimeError("Telegram alert response was not ok.")

    def send_email_alert(self, subject: str, message: str) -> None:
        """Send an email alert through the configured SMTP server."""

        required = [self.config.smtp_host, self.config.email_from, self.config.email_to]
        if not all(required):
            raise ValueError("SMTP host, email_from, and email_to are required.")

        email = EmailMessage()
        email["Subject"] = subject
        email["From"] = self.config.email_from
        email["To"] = self.config.email_to
        email.set_content(message)

        with self._smtp_factory(self.config.smtp_host, self.config.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if self.config.smtp_username and self.config.smtp_password:
                smtp.login(self.config.smtp_username, self.config.smtp_password)
            smtp.send_message(email)
