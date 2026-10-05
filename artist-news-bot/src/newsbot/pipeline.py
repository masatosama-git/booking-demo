"""Collect -> filter -> dedupe -> AI review -> draft -> save -> notify."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from newsbot.ai import AIError, ArticleInput
from newsbot.collectors.base import RawArticle
from newsbot.context import AppContext
from newsbot.models import Article, ArticleStatus, Post, PostStatus, utcnow
from newsbot.notifier import NotifyError, candidate_notification
from newsbot.text import compose_post
from newsbot.tokens import as_utc, issue_token
from newsbot.urls import content_hash, normalize_url, url_hash

log = logging.getLogger(__name__)

MAX_NOTIFY_ATTEMPTS = 5


def run_collection(ctx: AppContext) -> dict:
    """One scheduler tick: run every collector for every artist, then retry pending work."""
    stats = {"fetched": 0, "new": 0, "duplicate": 0, "rejected": 0, "candidate": 0, "ai_error": 0}
    for artist in ctx.artists:
        for collector in ctx.collectors:
            try:
                items = collector.fetch(artist)
            except Exception as e:  # noqa: BLE001 - one broken source must not stop the others
                log.error("collector failed", extra={"event": "collect_error", "collector": collector.name,
                                                     "artist": artist.key, "error": str(e)})
                continue
            log.info("collector ran", extra={"event": "collect", "collector": collector.name,
                                             "artist": artist.key, "count": len(items)})
            stats["fetched"] += len(items)
            for raw in items:
                result = ingest_article(ctx, artist.key, raw)
                stats[result] += 1
                if result != "duplicate":
                    stats["new"] += 1
    retry_unjudged_articles(ctx)
    resend_pending_notifications(ctx)
    return stats


def ingest_article(ctx: AppContext, artist_key: str, raw: RawArticle) -> str:
    """Process one fetched article. Returns duplicate | rejected | candidate | ai_error."""
    artist = ctx.artist(artist_key)
    canonical = normalize_url(raw.canonical_url or raw.url)
    u_hash = url_hash(canonical)
    c_hash = content_hash(raw.title, raw.text)

    with ctx.session_factory() as s:
        exists = s.scalar(select(Article.id).where(Article.artist_key == artist_key, Article.url_hash == u_hash))
        if exists:
            log.info("duplicate url", extra={"event": "dedupe", "reason": "url", "url": raw.url, "article_id": exists})
            return "duplicate"
        same_content = s.scalar(select(Article.id).where(Article.artist_key == artist_key,
                                                         Article.content_hash == c_hash))
        article = Article(
            artist_key=artist_key, title=raw.title, url=raw.url, canonical_url=canonical, url_hash=u_hash,
            content_hash=c_hash, source_name=raw.source_name, source_priority=raw.source_priority,
            published_at=raw.published_at, raw_text=raw.text, status=ArticleStatus.DISCOVERED,
        )
        if same_content:
            # Keep the row so the URL is remembered, but never notify it.
            article.status = ArticleStatus.REJECTED
            article.error_message = f"duplicate content of {same_content}"
        s.add(article)
        try:
            s.commit()
        except IntegrityError:
            # Another worker inserted the same URL between our check and insert.
            s.rollback()
            log.info("duplicate url (race)", extra={"event": "dedupe", "reason": "url_race", "url": raw.url})
            return "duplicate"
        article_id = article.id

    log.info("article discovered", extra={"event": "discovered", "article_id": article_id, "url": raw.url,
                                          "title": raw.title, "source": raw.source_name})
    if same_content:
        log.info("duplicate content", extra={"event": "dedupe", "reason": "content", "article_id": article_id})
        return "duplicate"
    return judge_article(ctx, article_id)


def _rule_rejection(ctx: AppContext, artist, article: Article) -> str | None:
    """Cheap checks before spending an AI call."""
    haystack = f"{article.title}\n{article.raw_text or ''}"
    for kw in artist.exclude_keywords:
        if kw and kw in haystack:
            return f"exclude keyword: {kw}"
    if not any(t in haystack for t in artist.match_terms):
        return "artist name not found"
    published = as_utc(article.published_at)
    max_age = timedelta(hours=ctx.settings.max_article_age_hours)
    if published and datetime.now(timezone.utc) - published > max_age:
        return f"too old: published {published.isoformat()}"
    return None


def _recent_summaries(s, artist_key: str, exclude_id: str, limit: int = 20) -> list[str]:
    since = utcnow() - timedelta(days=14)
    rows = s.scalars(
        select(Article.summary)
        .where(Article.artist_key == artist_key, Article.status.in_([ArticleStatus.CANDIDATE, ArticleStatus.POSTED]),
               Article.summary.is_not(None), Article.discovered_at >= since, Article.id != exclude_id)
        .order_by(Article.discovered_at.desc()).limit(limit)
    ).all()
    return list(rows)


def judge_article(ctx: AppContext, article_id: str) -> str:
    with ctx.session_factory() as s:
        article = s.get(Article, article_id)
        artist = ctx.artist(article.artist_key)
        if article.status != ArticleStatus.DISCOVERED:
            return article.status

        reason = _rule_rejection(ctx, artist, article)
        if reason:
            article.status = ArticleStatus.REJECTED
            article.ai_reason = reason
            s.commit()
            log.info("rule rejected", extra={"event": "judge", "article_id": article_id, "result": "rejected",
                                             "reason": reason})
            return "rejected"

        if ctx.ai is None:
            article.error_message = "AI client not configured"
            s.commit()
            return "ai_error"
        try:
            analysis = ctx.ai.analyze(
                ArticleInput(title=article.title, url=article.url, source_name=article.source_name,
                             published_at=as_utc(article.published_at), text=article.raw_text),
                artist,
                _recent_summaries(s, article.artist_key, article.id),
            )
        except AIError as e:
            # Leave status=discovered so retry_unjudged_articles() picks it up next tick.
            article.error_message = f"AI: {e}"
            s.commit()
            log.error("AI analysis failed", extra={"event": "ai_error", "article_id": article_id, "error": str(e)})
            return "ai_error"

        article.summary = analysis.summary
        article.relevance_score = analysis.relevance_score
        article.importance_score = analysis.importance_score
        article.reliability_score = analysis.reliability_score
        article.ai_reason = analysis.reason
        article.error_message = None

        st = ctx.settings
        failures = [
            msg for cond, msg in [
                (not analysis.is_about_artist, "not about artist"),
                (analysis.relevance_score < st.min_relevance_score, "low relevance"),
                (analysis.importance_score < st.min_importance_score, "low importance"),
                (analysis.reliability_score < st.min_reliability_score, "low reliability"),
                (analysis.is_rumor_or_gossip, "rumor/gossip"),
                (analysis.is_outdated, "outdated"),
                (analysis.duplicate_of_recent, "duplicate of recent post"),
                (not analysis.post_body.strip(), "empty post body"),
            ] if cond
        ]
        log_extra = {"event": "judge", "article_id": article_id, "relevance": analysis.relevance_score,
                     "importance": analysis.importance_score, "reliability": analysis.reliability_score,
                     "category": analysis.category, "ai_reason": analysis.reason}
        if failures:
            article.status = ArticleStatus.REJECTED
            article.ai_reason = f"{'; '.join(failures)} | {analysis.reason}"
            s.commit()
            log.info("AI rejected", extra={**log_extra, "result": "rejected", "failures": failures})
            return "rejected"

        post = Post(article_id=article.id, status=PostStatus.CANDIDATE,
                    generated_text=compose_post(artist.name, analysis.post_body, article.url, artist.hashtags))
        article.status = ArticleStatus.CANDIDATE
        s.add(post)
        s.commit()
        post_id = post.id
        log.info("post candidate created", extra={**log_extra, "result": "candidate", "post_id": post_id})

    notify_post(ctx, post_id)
    return "candidate"


def notify_post(ctx: AppContext, post_id: str) -> bool:
    """Send (or resend) the approval notification. A fresh token is issued on every send."""
    with ctx.session_factory() as s:
        post = s.get(Post, post_id)
        if post is None or post.status != PostStatus.CANDIDATE:
            return False
        article = s.get(Article, post.article_id)
        artist = ctx.artist(article.artist_key)
        token, token_hash, expires = issue_token(ctx.settings.action_token_ttl_hours)
        post.action_token_hash = token_hash
        post.action_token_expires_at = expires
        post.notify_attempts += 1
        s.commit()

        try:
            if ctx.notifier is None:
                raise NotifyError("ntfy notifier not configured")
            ctx.notifier.send(candidate_notification(
                artist_name=artist.name, article_title=article.title, source_name=article.source_name,
                published_at=as_utc(article.published_at), importance=article.importance_score,
                post_text=post.generated_text, article_url=article.url,
                approve_url=ctx.approve_url(post.id), reject_url=ctx.reject_url(post.id), token=token,
            ))
        except NotifyError as e:
            post.error_message = f"ntfy: {e}"
            s.commit()
            log.error("ntfy failed", extra={"event": "ntfy_error", "post_id": post_id, "error": str(e),
                                            "attempt": post.notify_attempts})
            return False

        # Conditional update: if the user already acted on the post meanwhile, leave it alone.
        s.execute(update(Post).where(Post.id == post_id, Post.status == PostStatus.CANDIDATE)
                  .values(status=PostStatus.NOTIFIED, notified_at=utcnow(), error_message=None))
        s.commit()
        log.info("candidate notified", extra={"event": "notified", "post_id": post_id})
        return True


def resend_pending_notifications(ctx: AppContext) -> int:
    with ctx.session_factory() as s:
        ids = s.scalars(select(Post.id).where(Post.status == PostStatus.CANDIDATE,
                                              Post.notify_attempts < MAX_NOTIFY_ATTEMPTS)).all()
    return sum(1 for pid in ids if notify_post(ctx, pid))


def retry_unjudged_articles(ctx: AppContext, max_age_hours: int = 24) -> int:
    """Articles left in 'discovered' (e.g. AI outage) are judged again."""
    since = utcnow() - timedelta(hours=max_age_hours)
    with ctx.session_factory() as s:
        ids = s.scalars(select(Article.id).where(Article.status == ArticleStatus.DISCOVERED,
                                                 Article.discovered_at >= since)).all()
    return sum(1 for aid in ids if judge_article(ctx, aid) == "candidate")
