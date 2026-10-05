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


class ArtistProfile(BaseModel):
    key: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    group: str | None = None
    search_keywords: list[str] = Field(default_factory=list)
    exclude_keywords: list[str] = Field(default_factory=list)
    official_site: str | None = None
    official_sns: dict[str, str] = Field(default_factory=dict)
    hashtags: list[str] = Field(default_factory=list)

    @property
    def match_terms(self) -> list[str]:
        """Names whose presence in an article suggests it is about this artist."""
        return [t for t in [self.name, *self.aliases] if t]


def load_artists(path: str | Path) -> list[ArtistProfile]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return [ArtistProfile(**a) for a in data.get("artists", [])]


@lru_cache
def get_settings() -> Settings:
    return Settings()
