from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx

from newsbot.collectors.rss import RssCollector
from newsbot.config import ArtistProfile, FeedSource
from newsbot.pipeline import run_collection

ARTIST = ArtistProfile(key="mutoh-jun", name="武藤潤", group="原因は自分にある。", group_aliases=["ゲンジブ"])


def _rss(items):
    parts = []
    for title, link, desc, minutes_ago, src in items:
        pub = format_datetime(datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
        source = f'<source url="https://pub.example">{src}</source>' if src else ""
        parts.append(f"<item><title>{title}</title><link>{link}</link><description>{desc}</description>"
                     f"<pubDate>{pub}</pubDate>{source}</item>")
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>f</title>'
            + "".join(parts) + "</channel></rss>")


FEED = _rss([
    ("武藤 潤、ドラマ出演決定", "https://news.example/1", "&lt;p&gt;武藤潤が出演&lt;/p&gt;", 5, "音楽ナタリー"),
    ("原因は自分にある。新曲MV公開", "https://news.example/2", "グループの新曲", 30, None),
    ("無関係なアーティストのニュース", "https://news.example/3", "別の話題", 10, None),
])


def _collector(handler, url="https://feed.example/rss"):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return RssCollector(FeedSource(name="テストフィード", url=url, type="music_media"), client)


def test_rss_filters_by_artist_and_group_terms():
    items = _collector(lambda r: httpx.Response(200, text=FEED)).fetch(ARTIST)
    assert [i.url for i in items] == ["https://news.example/1", "https://news.example/2"]
    first = items[0]
    assert first.source_name == "音楽ナタリー"  # publisher from <source> wins over feed name
    assert first.text == "武藤潤が出演"         # HTML stripped
    assert first.source_type == "music_media" and first.source_priority == 4
    assert datetime.now(timezone.utc) - first.published_at < timedelta(minutes=6)
    assert items[1].source_name == "テストフィード"


def test_group_news_excluded_when_disabled():
    solo = ARTIST.model_copy(update={"include_group_news": False})
    items = _collector(lambda r: httpx.Response(200, text=FEED)).fetch(solo)
    assert [i.url for i in items] == ["https://news.example/1"]


def test_conditional_get_and_304():
    calls = []

    def handler(r):
        calls.append(dict(r.headers))
        if r.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        return httpx.Response(200, text=FEED, headers={"ETag": '"v1"'})

    c = _collector(handler)
    assert len(c.fetch(ARTIST)) == 2
    assert len(c.fetch(ARTIST)) == 2   # same tick: reused, no second request
    assert len(calls) == 1
    c._fetched_at = 0                  # next tick
    assert c.fetch(ARTIST) == []
    assert calls[1]["if-none-match"] == '"v1"'


def test_scheduled_collection_end_to_end_without_renotify(ctx):
    ctx.artists = [ARTIST]
    ctx.ai.overrides = {"post_body": "武藤潤のドラマ出演が決定。"}
    ctx.collectors = [_collector(lambda r: httpx.Response(200, text=FEED))]
    stats = run_collection(ctx)
    assert stats["fetched"] == 2 and stats["candidate"] == 2
    assert len(ctx.notifier.sent) == 2
    assert ctx.notifier.sent[0].title == "武藤潤 最新情報"

    ctx.collectors[0]._fetched_at = 0
    stats = run_collection(ctx)
    assert stats["duplicate"] == 2 and stats["new"] == 0
    assert len(ctx.notifier.sent) == 2


def test_broken_feed_does_not_stop_others(ctx):
    ctx.artists = [ARTIST]
    bad = _collector(lambda r: httpx.Response(503), url="https://bad.example/rss")
    good = _collector(lambda r: httpx.Response(200, text=FEED))
    ctx.collectors = [bad, good]
    assert run_collection(ctx)["candidate"] == 2


def test_name_matching_ignores_spaces():
    assert ARTIST.mentions("武藤　潤（原因は自分にある。）")
    assert ARTIST.mentions("ゲンジブ新曲")
    assert not ARTIST.mentions("武藤さんの新曲")
