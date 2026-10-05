from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import sessionmaker

from newsbot.config import ArtistProfile, Settings


@dataclass
class AppContext:
    """Everything the pipeline needs; built once and injected (tests swap in fakes)."""

    settings: Settings
    session_factory: sessionmaker
    artists: list[ArtistProfile]
    ai: object | None = None          # AIClient; None means "AI unavailable" (articles wait for retry)
    notifier: object | None = None    # NtfyNotifier
    x_client: object | None = None    # XClient / DryRunXClient
    collectors: list = field(default_factory=list)

    def artist(self, key: str) -> ArtistProfile:
        for a in self.artists:
            if a.key == key:
                return a
        raise KeyError(key)

    def approve_url(self, post_id: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/api/approve/{post_id}"

    def reject_url(self, post_id: str) -> str:
        return f"{self.settings.public_base_url.rstrip('/')}/api/reject/{post_id}"


def build_context(settings: Settings) -> AppContext:
    """Production wiring. Missing optional services are logged, not fatal, so the API still starts."""
    import logging

    from newsbot.ai import build_ai_client
    from newsbot.collectors.rss import RssCollector
    from newsbot.config import load_artists, load_sources
    from newsbot.db import init_db, make_engine, make_session_factory
    from newsbot.notifier import NtfyNotifier
    from newsbot.x_client import build_x_client

    log = logging.getLogger(__name__)
    engine = make_engine(settings.database_url)
    init_db(engine)
    ctx = AppContext(settings=settings, session_factory=make_session_factory(engine),
                     artists=load_artists(settings.artists_config))
    for attr, factory in (("ai", lambda: build_ai_client(settings)),
                          ("notifier", lambda: NtfyNotifier(settings.ntfy_server, settings.ntfy_topic,
                                                            settings.ntfy_token)),
                          ("x_client", lambda: build_x_client(settings))):
        try:
            setattr(ctx, attr, factory())
        except Exception as e:  # noqa: BLE001 - surface config problems without crashing the server
            log.error("service not configured", extra={"event": "config_error", "service": attr, "error": str(e)})
    # The dummy collector is CLI-only (ingest-dummy); scheduled runs use the configured feeds.
    ctx.collectors = [RssCollector(src) for src in load_sources(settings.artists_config) if src.enabled]
    return ctx
