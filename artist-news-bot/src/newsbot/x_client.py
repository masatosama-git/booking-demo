"""X API v2 client (POST /2/tweets, OAuth 1.0a user context). No browser automation."""
from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass

import requests
from requests_oauthlib import OAuth1

log = logging.getLogger(__name__)

CREATE_POST_URL = "https://api.x.com/2/tweets"


class XPostError(Exception):
    """X answered and the post was definitely NOT created (4xx). Safe to retry after fixing."""

    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class XPostUncertainError(Exception):
    """Timeout / connection reset / 5xx: the post may or may not exist. Never auto-retry."""


@dataclass
class XPostResult:
    post_id: str
    raw_response: str


class XClient:
    def __init__(self, api_key: str, api_secret: str, access_token: str, access_token_secret: str,
                 timeout: float = 20.0, session: requests.Session | None = None):
        if not all([api_key, api_secret, access_token, access_token_secret]):
            raise ValueError("X API credentials are not fully set")
        self._auth = OAuth1(api_key, api_secret, access_token, access_token_secret)
        self._timeout = timeout
        self._session = session or requests.Session()

    def create_post(self, text: str) -> XPostResult:
        try:
            r = self._session.post(CREATE_POST_URL, json={"text": text}, auth=self._auth, timeout=self._timeout)
        except requests.ConnectTimeout as e:
            # The TCP connection was never established, so nothing reached X.
            raise XPostError(f"could not connect to X: {e}") from e
        except (requests.Timeout, requests.ConnectionError) as e:
            raise XPostUncertainError(f"no definitive response from X: {e}") from e
        body = r.text
        if r.status_code >= 500:
            raise XPostUncertainError(f"X server error {r.status_code}: {body[:500]}")
        if r.status_code >= 400:
            raise XPostError(f"X API error {r.status_code}: {body[:500]}", r.status_code, body)
        try:
            post_id = r.json()["data"]["id"]
        except (ValueError, KeyError, TypeError) as e:
            raise XPostUncertainError(f"unexpected X response: {body[:500]}") from e
        return XPostResult(post_id=str(post_id), raw_response=body)


class DryRunXClient:
    """Used while X_DRY_RUN=true: logs instead of posting."""

    def create_post(self, text: str) -> XPostResult:
        post_id = f"dryrun-{uuid.uuid4().hex[:12]}"
        log.info("X dry-run post", extra={"event": "x_dry_run", "x_post_id": post_id, "text": text})
        return XPostResult(post_id=post_id, raw_response=json.dumps({"data": {"id": post_id, "text": text}}))


def build_x_client(settings):
    if settings.x_dry_run:
        return DryRunXClient()
    return XClient(settings.x_api_key, settings.x_api_secret, settings.x_access_token,
                   settings.x_access_token_secret)
