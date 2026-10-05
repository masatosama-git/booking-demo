"""RSS/Atom collector. Polite polling: conditional GET (ETag / Last-Modified) and one fetch per tick."""
from __future__ import annotations

import calendar
import html
import logging
import re
import time
from datetime import datetime, timezone

import feedparser
import httpx

from newsbot.collectors.base import RawArticle

log = logging.getLogger(__name__)

USER_AGENT = "artist-news-bot/0.1 (+RSS reader; polite polling)"
_TAG_RE = re.compile(r"<[^>]+>")
# Re-use one download for every artist within the same tick.
_REUSE_SECONDS = 60


def strip_html(text: str | None) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", text or "")).split())


def _entry_time(entry) -> datetime | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    # feedparser normalizes to UTC struct_time
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc) if parsed else None


class RssCollector:
    def __init__(self, source, client: httpx.Client | None = None):
        self.source = source
        self.name = f"rss:{source.name}"
        self._client = client or httpx.Client(timeout=15, follow_redirects=True,
                                              headers={"User-Agent": USER_AGENT})
        self._etag: str | None = None
        self._last_modified: str | None = None
        self._entries: list = []
        self._fetched_at = 0.0

    def _download(self) -> list:
        if time.monotonic() - self._fetched_at < _REUSE_SECONDS:
            return self._entries
        headers = {}
        if self._etag:
            headers["If-None-Match"] = self._etag
        if self._last_modified:
            headers["If-Modified-Since"] = self._last_modified
        r = self._client.get(self.source.url, headers=headers)
        self._fetched_at = time.monotonic()
        if r.status_code == 304:
            self._entries = []  # nothing new since last poll
            return self._entries
        r.raise_for_status()
        feed = feedparser.parse(r.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"not a valid feed: {feed.bozo_exception}")
        self._etag = r.headers.get("ETag")
        self._last_modified = r.headers.get("Last-Modified")
        self._entries = list(feed.entries)
        return self._entries

    def fetch(self, artist) -> list[RawArticle]:
        items = []
        for e in self._download():
            title = strip_html(e.get("title"))
            summary = strip_html(e.get("summary"))
            link = e.get("link")
            if not title or not link or not artist.mentions(f"{title}\n{summary}"):
                continue
            # Aggregators (e.g. Google News) carry the publisher in <source>.
            publisher = (e.get("source") or {}).get("title")
            items.append(RawArticle(
                title=title, url=link, source_name=publisher or self.source.name,
                source_type=self.source.type, published_at=_entry_time(e), text=summary or None,
            ))
        return items
