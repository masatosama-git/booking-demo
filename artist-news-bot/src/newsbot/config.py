from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Secrets come only from environment / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "sqlite:///./newsbot.db"
    artists_config: str = "config/artists.yaml"
    log_level: str = "INFO"
    log_file: str = ""

    ai_provider: str = "anthropic"
    anthropic_api_key: str = ""
    ai_model: str = "claude-opus-5-5"
    ai_effort: str = "medium"
    ai_timeout_seconds: float = 60

    min_relevance_score: int = 70
    min_importance_score: int = 50
    min_reliability_score: int = 60
    max_article_age_hours: int = 72

    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str = ""
    ntfy_token: str = ""

    public_base_url: str = "http://localhost:8000"
    action_token_ttl_hours: int = 48

    x_api_key: str = ""
    x_api_secret: str = ""
    x_access_token: str = ""
    x_access_token_secret: str = ""
    x_dry_run: bool = True

    enable_scheduler: bool = False
    collect_interval_minutes: int = 10


def _squash(text: str) -> str:
    # "武藤 潤" / "武藤　潤" / "武藤潤" all match the same way.
    return "".join(text.split())


class ArtistProfile(BaseModel):
    key: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    group: str | None = None
    group_aliases: list[str] = Field(default_factory=list)
    # Treat group news (no individual name in the text) as news about this artist.
    include_group_news: bool = True
    search_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    official_site: str | None = None
    official_sns: dict[str, str] = Field(default_factory=dict)
    hashtags: list[str] = Field(default_factory=list)

    @property
    def match_terms(self) -> list[str]:
        """Names whose presence in an article suggests it is about this artist."""
        terms = [self.name, *self.aliases]
        if self.include_group_news:
            terms += [self.group or "", *self.group_aliases]
        return [t for t in terms if t]

    def heading(self, subject: str = "individual") -> str:
        """Post / notification heading. Group news is labelled with the group, not the member,
        so a group announcement is never presented as the member's personal news."""
        label = self.group if subject == "group" and self.group else self.name
        # "原因は自分にある。" already ends with punctuation, so no space before 最新情報
        sep = "" if label.endswith(("。", "！", "!", "？", "?")) else " "
        return f"{label}{sep}最新情報"

    def mentions(self, text: str) -> bool:
        squashed = _squash(text)
        return any(_squash(t) in squashed for t in self.match_terms)


class FeedSource(BaseModel):
    """An RSS/Atom feed. Only feeds the publisher offers are used; no HTML scraping."""

    name: str
    url: str
    type: str = "news_search"  # official | agency | label | music_media | broadcaster | event | news_search
    enabled: bool = True


def _load_yaml(path: str | Path) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def load_artists(path: str | Path) -> list[ArtistProfile]:
    return [ArtistProfile(**a) for a in _load_yaml(path).get("artists", [])]


def load_sources(path: str | Path) -> list[FeedSource]:
    return [FeedSource(**src) for src in _load_yaml(path).get("sources", [])]


@lru_cache
def get_settings() -> Settings:
    return Settings()
