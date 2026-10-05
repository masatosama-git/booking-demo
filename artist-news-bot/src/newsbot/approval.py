"""Approve / reject. Idempotency comes from a conditional UPDATE that only one caller can win."""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy import update

from newsbot.context import AppContext
from newsbot.models import Article, ArticleStatus, Post, PostStatus, utcnow
from newsbot.notifier import Notification, NotifyError, candidate_notification
from newsbot.tokens import as_utc, issue_token, verify_token
from newsbot.x_client import XPostError, XPostUncertainError

log = logging.getLogger(__name__)


class PostNotFound(Exception):
    pass


class InvalidToken(Exception):
    pass


@dataclass
class ActionResult:
    post_id: str
    status: str
    changed: bool  # False when this call was a no-op (double tap, already handled)
    detail: str = ""


def _check(ctx: AppContext, post_id: str, token: str | None) -> Post:
    with ctx.session_factory() as s:
        post = s.get(Post, post_id)
    # The API maps both errors to the same 403 so post ids cannot be probed.
    if post is None:
        raise PostNotFound(post_id)
    if not verify_token(token, post.action_token_hash, post.action_token_expires_at):
        log.warning("invalid action token", extra={"event": "auth_failed", "post_id": post_id})
        raise InvalidToken(post_id)
    return post


def claim_approval(ctx: AppContext, post_id: str, token: str | None) -> ActionResult:
    """Validate the token and atomically move the post to 'approved'.

    Exactly one concurrent caller gets changed=True; that caller must then call publish_post().
    """
    _check(ctx, post_id, token)
    with ctx.session_factory() as s:
        res = s.execute(
            update(Post).where(Post.id == post_id, Post.status.in_(PostStatus.APPROVABLE))
            .values(status=PostStatus.APPROVED, approved_at=utcnow(), error_message=None)
        )
        s.commit()
        current = s.get(Post, post_id).status
    if res.rowcount != 1:
        log.info("approval ignored", extra={"event": "approve_noop", "post_id": post_id, "status": current})
        return ActionResult(post_id, current, changed=False, detail="already handled")
    log.info("user approved", extra={"event": "approved", "post_id": post_id})
    return ActionResult(post_id, PostStatus.APPROVED, changed=True)


def publish_post(ctx: AppContext, post_id: str) -> ActionResult:
    """Send an 'approved' post to X and record the outcome. Never posts twice for one claim."""
    with ctx.session_factory() as s:
        post = s.get(Post, post_id)
        if post is None or post.status != PostStatus.APPROVED:
            return ActionResult(post_id, post.status if post else "missing", changed=False)
        text = post.generated_text
        article_id = post.article_id

    try:
        if ctx.x_client is None:
            raise XPostError("X client not configured")
        result = ctx.x_client.create_post(text)
    except XPostError as e:
        _finish(ctx, post_id, PostStatus.FAILED, error=str(e), x_response=getattr(e, "body", None))
        log.error("X post failed", extra={"event": "x_error", "post_id": post_id, "error": str(e)})
        _notify_retry(ctx, post_id, str(e))
        return ActionResult(post_id, PostStatus.FAILED, changed=True, detail=str(e))
    except XPostUncertainError as e:
        _finish(ctx, post_id, PostStatus.UNCERTAIN, error=str(e))
        log.error("X post uncertain", extra={"event": "x_uncertain", "post_id": post_id, "error": str(e)})
        _notify(ctx, "⚠️ X投稿の結果が不明",
                f"{e}\n\n二重投稿を避けるため自動再試行しません。Xで投稿有無を確認してください。", ["warning"])
        return ActionResult(post_id, PostStatus.UNCERTAIN, changed=True, detail=str(e))

    _finish(ctx, post_id, PostStatus.POSTED, x_post_id=result.post_id, x_response=result.raw_response)
    with ctx.session_factory() as s:
        s.execute(update(Article).where(Article.id == article_id).values(status=ArticleStatus.POSTED))
        s.commit()
    log.info("posted to X", extra={"event": "x_posted", "post_id": post_id, "x_post_id": result.post_id})
    _notify(ctx, "✅ 投稿完了", text, ["white_check_mark"], click=f"https://x.com/i/web/status/{result.post_id}")
    return ActionResult(post_id, PostStatus.POSTED, changed=True, detail=result.post_id)


def _finish(ctx: AppContext, post_id: str, status: str, *, error: str | None = None,
            x_post_id: str | None = None, x_response: str | None = None) -> None:
    values = {"status": status, "error_message": error, "x_response": x_response}
    if status == PostStatus.POSTED:
        values.update(x_post_id=x_post_id, posted_at=utcnow())
    with ctx.session_factory() as s:
        # Guarded by status=approved so a late writer can never overwrite a final state.
        s.execute(update(Post).where(Post.id == post_id, Post.status == PostStatus.APPROVED).values(**values))
        s.commit()


def reject_post(ctx: AppContext, post_id: str, token: str | None) -> ActionResult:
    post = _check(ctx, post_id, token)
    with ctx.session_factory() as s:
        res = s.execute(
            update(Post).where(Post.id == post_id, Post.status.in_(PostStatus.REJECTABLE))
            .values(status=PostStatus.REJECTED, rejected_at=utcnow())
        )
        if res.rowcount == 1:
            s.execute(update(Article).where(Article.id == post.article_id)
                      .values(status=ArticleStatus.REJECTED, ai_reason="rejected by user"))
        s.commit()
        current = s.get(Post, post_id).status
    if res.rowcount != 1:
        return ActionResult(post_id, current, changed=False, detail="already handled")
    log.info("user rejected", extra={"event": "rejected", "post_id": post_id})
    return ActionResult(post_id, PostStatus.REJECTED, changed=True)


def _notify(ctx: AppContext, title: str, message: str, tags: list[str], click: str | None = None) -> None:
    if ctx.notifier is None:
        return
    try:
        ctx.notifier.send(Notification(title=title, message=message, tags=tags, click=click))
    except NotifyError as e:
        # The DB already holds the truth; a lost status notification is not fatal.
        log.error("ntfy result notification failed", extra={"event": "ntfy_error", "error": str(e)})


def _notify_retry(ctx: AppContext, post_id: str, error: str) -> None:
    """After a definite failure, send a fresh notification so the user can retry or reject."""
    token, token_hash, expires = issue_token(ctx.settings.action_token_ttl_hours)
    with ctx.session_factory() as s:
        post = s.get(Post, post_id)
        post.action_token_hash = token_hash
        post.action_token_expires_at = expires
        s.commit()
        article = s.get(Article, post.article_id)
        artist = ctx.artist(article.artist_key)
        n = candidate_notification(
            artist_name=artist.name, article_title=article.title, source_name=article.source_name,
            published_at=as_utc(article.published_at), importance=article.importance_score,
            post_text=post.generated_text, article_url=article.url,
            approve_url=ctx.approve_url(post_id), reject_url=ctx.reject_url(post_id), token=token,
            title="❌ X投稿失敗（再試行できます）", note=f"エラー: {error[:300]}",
        )
    if ctx.notifier is None:
        return
    try:
        ctx.notifier.send(n)
    except NotifyError as e:
        log.error("ntfy retry notification failed", extra={"event": "ntfy_error", "post_id": post_id,
                                                           "error": str(e)})
