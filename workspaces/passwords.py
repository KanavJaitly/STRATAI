"""Password hashing and the password policy.

Hashing is scrypt from the standard library (no new dependency), at one of OWASP's recommended scrypt settings:
N=2^15, r=8, p=3 (32 MiB per hash). Each stored hash names its own parameters ("scrypt$15$8$3$salt$hash"), so the
cost can be raised later without invalidating existing passwords: needs_rehash() says when to re-hash at the next
successful login. Comparison is constant-time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from workspaces.errors import invalid_input

SCHEME = "scrypt"
LOG2_N, BLOCK_SIZE, PARALLELISM = 15, 8, 3
SALT_BYTES, KEY_BYTES = 16, 32
MAX_MEMORY_BYTES = 128 * 1024 * 1024

MIN_PASSWORD_LENGTH, MAX_PASSWORD_LENGTH = 12, 256
# The most common long passwords; the length rule already rules out every shorter one.
COMMON_PASSWORDS = frozenset({
    "123456789012", "1234567890123", "12345678901234", "password1234", "password12345", "passwordpassword",
    "qwertyuiopas", "qwerty123456", "111111111111", "000000000000", "abcdefghijkl", "abc123abc123",
    "iloveyou1234", "letmeinletmein", "welcome12345", "administrator", "changemenow1", "robotics1234",
    "frcrobotics1", "firstrobotics", "stratai12345", "scouting1234",
})


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _derive(password: str, salt: bytes, log2_n: int, block_size: int, parallelism: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2 ** log2_n, r=block_size, p=parallelism,
                          maxmem=MAX_MEMORY_BYTES, dklen=KEY_BYTES)


def hash_password(password: str) -> str:
    """A new salted hash of password, in the self-describing stored format."""
    salt = secrets.token_bytes(SALT_BYTES)
    key = _derive(password, salt, LOG2_N, BLOCK_SIZE, PARALLELISM)
    return f"{SCHEME}${LOG2_N}${BLOCK_SIZE}${PARALLELISM}${_b64(salt)}${_b64(key)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Whether password matches stored. A missing or malformed hash never matches."""
    if not stored:
        return False
    try:
        scheme, log2_n, block_size, parallelism, salt, key = stored.split("$")
        if scheme != SCHEME:
            return False
        derived = _derive(password, _unb64(salt), int(log2_n), int(block_size), int(parallelism))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, _unb64(key))


def needs_rehash(stored: str) -> bool:
    """True when stored was made with other parameters than today's, so it should be re-hashed."""
    return not stored.startswith(f"{SCHEME}${LOG2_N}${BLOCK_SIZE}${PARALLELISM}$")


_DUMMY_HASH: str | None = None


def burn_verification_time(password: str) -> None:
    """Spend the time of one real verification. Called when there is no account to check, so a failed login takes
    as long whether or not the account exists (no timing oracle for which emails have accounts)."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password(secrets.token_urlsafe(16))
    verify_password(password, _DUMMY_HASH)


def check_password_policy(password: str, *, email: str | None = None) -> None:
    """Refuse a password that is too short, too long, very common, or the account's own email address."""
    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        raise invalid_input(f"Passwords must have at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise invalid_input(f"Passwords may have at most {MAX_PASSWORD_LENGTH} characters.")
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS or len(set(password)) < 4:
        raise invalid_input("That password is too common or too simple. Choose a longer, less predictable one.")
    if email and lowered == email.lower():
        raise invalid_input("Your password must not be your email address.")
