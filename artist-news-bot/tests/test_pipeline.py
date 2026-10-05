from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from newsbot.ai import AIError
from newsbot.models import Article, ArticleStatus, Post, PostStatus
from newsbot.pipeline import ingest_article, resend_pending_notifications, retry_unjudged_articles


def _posts(ctx):
    with ctx.session_factory() as s:
        return s.scalars(select(Post)).all()


def test_phase1_flow_creates_post_and_notifies(ctx, make_raw):
    assert ingest_article(ctx, "test", make_raw()) == "candidate"
    [post] = _posts(ctx)
    assert post.status == PostStatus.NOTIFIED
    assert post.generated_text.startswith("【テストアーティスト 最新情報】")
    assert "https://news.example.com/a/1" in post.generated_text
    [n] = ctx.notifier.sent
    assert n.title == "テストアーティスト 最新情報"
    assert "情報源：テストニュース" in n.message and "重要度：90" in n.message
    labels = [a["label"] for a in n.actions]
    assert labels == ["承認", "却下", "元記事"]
    assert n.actions[0]["url"] == f"https://bot.test/api/approve/{post.id}"
    # token is never stored in plain text
    assert ctx.notifier.last_token() not in (post.action_token_hash or "")


def test_same_article_twice_is_not_renotified(ctx, make_raw):
    assert ingest_article(ctx, "test", make_raw()) == "candidate"
    assert ingest_article(ctx, "test", make_raw()) == "duplicate"
    # tracking params / trailing slash / http variant are the same article
    assert ingest_article(ctx, "test", make_raw(url="http://NEWS.example.com/a/1/?utm_source=x#top")) == "duplicate"
    # same content under a different URL is remembered but not notified
    assert ingest_article(ctx, "test", make_raw(url="https://mirror.example.net/copy")) == "duplicate"
    assert len(ctx.notifier.sent) == 1
    assert ctx.ai.calls == 1
    assert len(_posts(ctx)) == 1


def test_rule_filters_skip_ai(ctx, make_raw):
    assert ingest_article(ctx, "test", make_raw(url="https://e.com/1", title="競馬 テストアーティスト号が勝利")) == "rejected"
    assert ingest_article(ctx, "test", make_raw(url="https://e.com/2", title="無関係なニュース", text="別の話題")) == "rejected"
    old = datetime.now(timezone.utc) - timedelta(days=30)
    assert ingest_article(ctx, "test", make_raw(url="https://e.com/3", title="テストアーティスト 古い記事",
                                               text="古い", published_at=old)) == "rejected"
    assert ctx.ai.calls == 0
    assert ctx.notifier.sent == []


def test_ai_thresholds_reject(ctx, make_raw):
    ctx.ai.overrides = {"relevance_score": 40}
    assert ingest_article(ctx, "test", make_raw()) == "rejected"
    ctx.ai.overrides = {"is_rumor_or_gossip": True}
    assert ingest_article(ctx, "test", make_raw(url="https://e.com/r", text="噂")) == "rejected"
    assert ctx.notifier.sent == []


def test_ai_error_does_not_crash_and_is_retried(ctx, make_raw):
    ctx.ai.error = AIError("529 overloaded")
    assert ingest_article(ctx, "test", make_raw()) == "ai_error"
    with ctx.session_factory() as s:
        art = s.scalars(select(Article)).one()
        assert art.status == ArticleStatus.DISCOVERED and "overloaded" in art.error_message
    assert ctx.notifier.sent == []

    ctx.ai.error = None
    assert retry_unjudged_articles(ctx) == 1
    assert len(ctx.notifier.sent) == 1
    # a re-fetch of the same URL is still a duplicate
    assert ingest_article(ctx, "test", make_raw()) == "duplicate"


def test_ntfy_error_can_be_resent(ctx, make_raw):
    ctx.notifier.fail = True
    assert ingest_article(ctx, "test", make_raw()) == "candidate"
    [post] = _posts(ctx)
    assert post.status == PostStatus.CANDIDATE and "ntfy down" in post.error_message

    ctx.notifier.fail = False
    assert resend_pending_notifications(ctx) == 1
    [post] = _posts(ctx)
    assert post.status == PostStatus.NOTIFIED and post.error_message is None
    # nothing left to resend
    assert resend_pending_notifications(ctx) == 0
    assert len(ctx.notifier.sent) == 1
