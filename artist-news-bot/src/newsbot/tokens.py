"""One-time action tokens embedded in ntfy buttons.

Only the SHA-256 hash is stored, so a DB leak does not let anyone approve posts.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_token(ttl_hours: int) -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    return token, hash_token(token), datetime.now(timezone.utc) + timedelta(hours=ttl_hours)


def as_utc(dt: datetime | None) -> datetime | None:
    # SQLite returns naive datetimes even for timezone=True columns; we always store UTC.
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=timezone.utc)


def verify_token(token: str | None, stored_hash: str | None, expires_at: datetime | None) -> bool:
    if not token or not stored_hash:
        return False
    if not hmac.compare_digest(hash_token(token), stored_hash):
        return False
    exp = as_utc(expires_at)
    return exp is None or exp > datetime.now(timezone.utc)
