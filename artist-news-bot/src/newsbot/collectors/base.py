from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

# Lower number = more authoritative. Used for ordering and, later, topic grouping.
SOURCE_PRIORITY = {
    "official": 1,
    "agency": 2,
    "label": 3,
    "music_media": 4,
    "broadcaster": 5,
    "event": 6,
    "news_search": 7,
}


@dataclass
class RawArticle:
    title: str
    url: str
    source_name: str | None = None
    source_type: str = "news_search"
    canonical_url: str | None = None
    published_at: datetime | None = None
    text: str | None = None

    @property
    def source_priority(self) -> int:
        return SOURCE_PRIORITY.get(self.source_type, 9)


class Collector(Protocol):
    name: str

    def fetch(self, artist) -> list[RawArticle]: ...
