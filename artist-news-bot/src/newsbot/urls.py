from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Query parameters that never change the article itself.
_TRACKING_PREFIXES = ("utm_",)
_TRACKING_KEYS = {"fbclid", "gclid", "yclid", "mc_cid", "mc_eid", "ref", "ref_src", "spm", "igshid"}


def normalize_url(url: str) -> str:
    """Canonical form used for duplicate detection (not for display)."""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    if scheme == "http":
        scheme = "https"
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    path = parts.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING_PREFIXES) and k.lower() not in _TRACKING_KEYS
    ]
    return urlunsplit((scheme, host, path, urlencode(sorted(query)), ""))


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()


def content_hash(title: str, text: str | None) -> str:
    """Hash of whitespace-collapsed title+body, to catch the same article under different URLs."""
    joined = " ".join(f"{title}\n{text or ''}".split())
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
