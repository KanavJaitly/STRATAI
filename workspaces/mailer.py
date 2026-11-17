"""Outgoing email: password-reset codes.

Four outcomes, reported to the caller so the interface can say what happened:
- "brevo": sent through Brevo's HTTPS email API (BREVO_API_KEY and SMTP_FROM, the sender address). Preferred over SMTP
  when both are set: Render's free plan blocks outgoing SMTP connections (2026-11-16: every send failed with OSError),
  and HTTPS is not blocked. The sender address must be verified in Brevo.
- "smtp": sent through the configured SMTP server (SMTP_HOST and SMTP_FROM, optionally SMTP_USERNAME/PASSWORD).
- "dev_outbox": ENV=development and DEV_OUTBOX_DIR is set, so the message was written there as a .eml file
  instead (for local testing; never honoured outside development).
- None: no email is configured. Nothing is sent, so a forgotten password cannot be reset by email (an administrator
  can still change the person's role or remove them; there is no administrator-issued reset).

Message bodies are never logged: they contain single-use codes.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Literal

import httpx

from data.config import Settings
from workspaces.tokens import new_token

logger = logging.getLogger(__name__)

Channel = Literal["brevo", "smtp", "dev_outbox"]
SMTP_TIMEOUT_SECONDS = 10
BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_TIMEOUT_SECONDS = 10


def email_channel(settings: Settings) -> Channel | None:
    """How email would be delivered under settings, or None if it would not be."""
    if settings.brevo_api_key is not None and settings.smtp_from:
        return "brevo"
    if settings.smtp_host and settings.smtp_from:
        return "smtp"
    if settings.env == "development" and settings.dev_outbox_dir:
        return "dev_outbox"
    return None


def send(settings: Settings, *, to: str, subject: str, body: str) -> Channel | None:
    """Deliver one plain-text email. Returns the channel used, or None if email is not configured or failed.

    A delivery failure is logged (without the body) and reported as None rather than raised: the request that
    caused it has already succeeded, and its answer must not reveal whether an email was sent."""
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
        if channel == "brevo":
            _send_brevo(settings, to=to, subject=subject, body=body)
            return channel
        with smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS) as smtp:
            if settings.smtp_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(message)
        return channel
    except httpx.HTTPStatusError as exc:
        # The status says what is wrong (401: bad key; 400: sender not verified) without logging the request.
        logger.warning("email to one recipient was not delivered via %s: HTTP %s", channel, exc.response.status_code)
        return None
    except (OSError, smtplib.SMTPException, httpx.HTTPError) as exc:
        logger.warning("email to one recipient was not delivered via %s: %s", channel, type(exc).__name__)
        return None


def _send_brevo(settings: Settings, *, to: str, subject: str, body: str) -> None:
    """One plain-text email through Brevo's transactional API. Raises httpx errors; send() logs them."""
    assert settings.brevo_api_key is not None and settings.smtp_from
    name, address = parseaddr(settings.smtp_from)
    sender = {"email": address, **({"name": name} if name else {})}
    response = httpx.post(
        BREVO_SEND_URL, timeout=BREVO_TIMEOUT_SECONDS,
        headers={"api-key": settings.brevo_api_key.get_secret_value(), "accept": "application/json"},
        json={"sender": sender, "to": [{"email": to}], "subject": subject, "textContent": body})
    response.raise_for_status()
