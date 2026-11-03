"""Secret tokens (sessions, invitations, password resets) and how they are stored.

A token is 32 random bytes (256 bits), URL-safe. Only its SHA-256 is stored, so a copy of the database does not
hold a single usable session, invitation or reset link. SHA-256 without a salt is enough here because the token is
itself uniformly random and long: there is nothing to guess or precompute.
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def subject_hash(scope: str, subject: str) -> str:
    """The stored form of a rate-limit subject (an IP address, or a team number and email)."""
    return hashlib.sha256(f"{scope}\x00{subject}".encode("utf-8")).hexdigest()
