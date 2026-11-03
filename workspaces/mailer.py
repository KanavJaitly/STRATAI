"""Outgoing email for invitations and password resets.

Three outcomes, reported to the caller so the interface can say what happened:
- "smtp": sent through the configured SMTP server (SMTP_HOST and SMTP_FROM, optionally SMTP_USERNAME/PASSWORD).
- "dev_outbox": ENV=development and DEV_OUTBOX_DIR is set, so the message was written there as a .eml file
  instead (for local testing; never honoured outside development).
- None: no email is configured. Nothing is sent. An invitation's link is still returned to the administrator who
  created it, to deliver themselves.
Links in emails need PUBLIC_APP_URL (the web app's address); without it no email is sent.

Message bodies are never logged: they contain single-use links.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Literal

from data.config import Settings
from workspaces.tokens import new_token

logger = logging.getLogger(__name__)

Channel = Literal["smtp", "dev_outbox"]
SMTP_TIMEOUT_SECONDS = 10


def email_channel(settings: Settings) -> Channel | None:
    """How email would be delivered under settings, or None if it would not be."""
    if not settings.public_app_url:
        return None
    if settings.smtp_host and settings.smtp_from:
        return "smtp"
    if settings.env == "development" and settings.dev_outbox_dir:
        return "dev_outbox"
    return None


def absolute_link(settings: Settings, path: str) -> str:
    """path ("/auth/invite#token=...") under PUBLIC_APP_URL, or path itself when that is not configured (the web
    app then prefixes its own origin)."""
    if not settings.public_app_url:
        return path
    return settings.public_app_url.rstrip("/") + path


def send(settings: Settings, *, to: str, subject: str, body: str) -> Channel | None:
    """Deliver one plain-text email. Returns the channel used, or None if email is not configured or failed.

    A delivery failure is logged (without the body) and reported as None rather than raised: the request that
    caused it has already succeeded, and the administrator can still copy the link."""
    channel = email_channel(settings)
    if channel is None:
        return None
    message = EmailMessage()
    message["From"] = settings.smtp_from or "stratai@localhost"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    try:
        if channel == "dev_outbox":
            outbox = Path(settings.dev_outbox_dir or "")
            outbox.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
            (outbox / f"{stamp}_{new_token()[:8]}.eml").write_bytes(bytes(message))
            return channel
        with smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
        return channel
    except (OSError, smtplib.SMTPException) as exc:
        logger.warning("email to one recipient was not delivered via %s: %s", channel, type(exc).__name__)
        return None
