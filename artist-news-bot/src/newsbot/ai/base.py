from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, field_validator

CATEGORIES = ["release", "live", "tv_radio", "interview", "magazine", "mv", "collab", "event", "other"]


class AIError(Exception):
    """Any failure to obtain a usable analysis. The article stays 'discovered' and is retried."""


@dataclass
class ArticleInput:
    title: str
    url: str
    source_name: str | None
    published_at: datetime | None
    text: str | None


class Analysis(BaseModel):
    is_about_artist: bool
    relevance_score: int
    importance_score: int
    reliability_score: int
    is_rumor_or_gossip: bool
    is_outdated: bool
    duplicate_of_recent: bool
    category: str
    summary: str
    post_body: str
    reason: str

    @field_validator("relevance_score", "importance_score", "reliability_score")
    @classmethod
    def _clamp(cls, v: int) -> int:
        return max(0, min(100, int(v)))


class AIClient(Protocol):
    def analyze(self, article: ArticleInput, artist, recent_summaries: list[str]) -> Analysis: ...
