"""The Brevo email channel (HTTPS): chosen over SMTP when configured, sends the right request, never raises.

Render's free plan blocks outgoing SMTP (2026-11-16: every reset-code email failed with OSError), so the hosted API
sends through Brevo's API. Needs no database and sends nothing: httpx.post is replaced.
"""

from __future__ import annotations

import httpx
import pytest

from data.config import Settings
from workspaces import mailer

KEY = "xkeysib-test-not-real"


def settings(**overrides) -> Settings:
    base = {"brevo_api_key": KEY, "smtp_from": "StratAI <appdev@example.org>", "smtp_host": None}
    return Settings(**{**base, **overrides})


class Recorder:
    def __init__(self, status: int = 201, error: Exception | None = None) -> None:
        self.calls: list[dict] = []
        self.status, self.error = status, error

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if self.error is not None:
            raise self.error
        return httpx.Response(self.status, request=httpx.Request("POST", url), json={"messageId": "m"})


def test_brevo_is_preferred_over_smtp_when_both_are_set():
    assert mailer.email_channel(settings(smtp_host="smtp.gmail.com")) == "brevo"
    assert mailer.email_channel(settings(brevo_api_key=None, smtp_host="smtp.gmail.com")) == "smtp"
    assert mailer.email_channel(settings(smtp_from=None)) is None  # a sender address is required


def test_sends_one_plain_text_email_with_the_key_in_a_header(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(mailer.httpx, "post", recorder)
    assert mailer.send(settings(), to="member@example.org", subject="Code", body="Your code is: 123456") == "brevo"
    (call,) = recorder.calls
    assert call["url"] == mailer.BREVO_SEND_URL
    assert call["headers"]["api-key"] == KEY
    assert call["json"] == {"sender": {"email": "appdev@example.org", "name": "StratAI"},
                            "to": [{"email": "member@example.org"}], "subject": "Code",
                            "textContent": "Your code is: 123456"}
    assert call["timeout"] == mailer.BREVO_TIMEOUT_SECONDS


def test_a_bare_sender_address_has_no_name(monkeypatch):
    recorder = Recorder()
    monkeypatch.setattr(mailer.httpx, "post", recorder)
    mailer.send(settings(smtp_from="appdev@example.org"), to="a@example.org", subject="s", body="b")
    assert recorder.calls[0]["json"]["sender"] == {"email": "appdev@example.org"}


@pytest.mark.parametrize("recorder, logged", [
    (Recorder(status=401), "HTTP 401"),
    (Recorder(status=400), "HTTP 400"),
    (Recorder(error=httpx.ConnectTimeout("timed out")), "ConnectTimeout"),
])
def test_a_failure_is_logged_without_the_body_or_key_and_never_raised(monkeypatch, caplog, recorder, logged):
    monkeypatch.setattr(mailer.httpx, "post", recorder)
    with caplog.at_level("WARNING", logger="workspaces.mailer"):
        assert mailer.send(settings(), to="a@example.org", subject="s", body="Your code is: 654321") is None
    assert logged in caplog.text
    assert "654321" not in caplog.text and KEY not in caplog.text and "a@example.org" not in caplog.text
