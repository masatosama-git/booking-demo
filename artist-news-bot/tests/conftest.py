from __future__ import annotations

from datetime import datetime, timedelta, timezone

import os

import pytest

from newsbot.ai import AIError, Analysis
from newsbot.collectors.base import RawArticle
from newsbot.config import ArtistProfile, Settings
from newsbot.context import AppContext
from newsbot.db import init_db, make_engine, make_session_factory
from newsbot.models import Base
from newsbot.notifier import NotifyError
from newsbot.x_client import XPostResult


class FakeAI:
    def __init__(self):
        self.calls = 0
        self.error: Exception | None = None
        self.overrides: dict = {}

    def analyze(self, article, artist, recent_summaries):
        self.calls += 1
        if self.error:
            raise self.error
        data = dict(is_about_artist=True, relevance_score=95, importance_score=90, reliability_score=90,
                    is_rumor_or_gossip=False, is_outdated=False, duplicate_of_recent=False, category="release",
                    summary=article.title, post_body="テストアーティストのニューシングル「テスト曲」が11月18日に発売決定。",
                    reason="official release news")
        data.update(self.overrides)
        return Analysis(**data)


class FakeNotifier:
    def __init__(self):
        self.sent = []
        self.fail = False

    def send(self, n):
        if self.fail:
            raise NotifyError("ntfy down")
        self.sent.append(n)
        return f"msg{len(self.sent)}"

    def last_token(self) -> str:
        for n in reversed(self.sent):
            if n.actions:
                return n.actions[0]["headers"]["Authorization"].removeprefix("Bearer ")
        raise AssertionError("no actionable notification sent")


class FakeX:
    def __init__(self):
        self.posts: list[str] = []
        self.error: Exception | None = None

    def create_post(self, text):
        if self.error:
            raise self.error
        self.posts.append(text)
        return XPostResult(post_id=str(1000 + len(self.posts)), raw_response='{"data":{"id":"1"}}')


@pytest.fixture
def ctx(tmp_path):
    # Default: throwaway SQLite file. Set TEST_DATABASE_URL to run the same tests on PostgreSQL.
    url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{tmp_path / 'test.db'}"
    engine = make_engine(url)
    Base.metadata.drop_all(engine)
    init_db(engine)
    settings = Settings(_env_file=None, database_url="sqlite://", public_base_url="https://bot.test",
                        ntfy_topic="t", x_dry_run=False)
    artist = ArtistProfile(key="test", name="テストアーティスト", aliases=["テスト"], exclude_keywords=["競馬"])
    return AppContext(settings=settings, session_factory=make_session_factory(engine), artists=[artist],
                      ai=FakeAI(), notifier=FakeNotifier(), x_client=FakeX())


@pytest.fixture
def make_raw():
    def _make(url="https://news.example.com/a/1", title="テストアーティスト、新曲「テスト曲」発売決定", **kw):
        defaults = dict(source_name="テストニュース", source_type="music_media",
                        published_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                        text="テストアーティストが11月18日にニューシングル「テスト曲」を発売する。")
        defaults.update(kw)
        return RawArticle(title=title, url=url, **defaults)

    return _make


__all__ = ["AIError"]
