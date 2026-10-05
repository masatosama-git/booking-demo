import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from newsbot.api import create_app
from newsbot.approval import claim_approval, publish_post
from newsbot.models import Article, ArticleStatus, Post, PostStatus
from newsbot.pipeline import ingest_article
from newsbot.x_client import XPostError, XPostUncertainError


@pytest.fixture
def client(ctx):
    return TestClient(create_app(ctx))


@pytest.fixture
def candidate(ctx, make_raw):
    ingest_article(ctx, "test", make_raw())
    with ctx.session_factory() as s:
        post_id = s.scalars(select(Post.id)).one()
    return post_id, ctx.notifier.last_token()


def _post(ctx, post_id):
    with ctx.session_factory() as s:
        return s.get(Post, post_id)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_approve_posts_to_x_and_records_result(ctx, client, candidate):
    post_id, token = candidate
    r = client.post(f"/api/approve/{post_id}", headers=_auth(token))
    assert r.status_code == 202
    post = _post(ctx, post_id)
    assert post.status == PostStatus.POSTED
    assert post.x_post_id == "1001" and post.posted_at and post.approved_at and post.x_response
    assert ctx.x_client.posts == [post.generated_text]
    assert ctx.notifier.sent[-1].title == "✅ 投稿完了"
    with ctx.session_factory() as s:
        assert s.get(Article, post.article_id).status == ArticleStatus.POSTED


def test_double_approve_posts_once(ctx, client, candidate):
    post_id, token = candidate
    assert client.post(f"/api/approve/{post_id}", headers=_auth(token)).status_code == 202
    r = client.post(f"/api/approve/{post_id}", headers=_auth(token))
    assert r.status_code == 200 and r.json()["status"] == PostStatus.POSTED
    assert len(ctx.x_client.posts) == 1


def test_concurrent_approve_claims_once(ctx, candidate):
    post_id, token = candidate
    results, barrier = [], threading.Barrier(8)

    def tap():
        barrier.wait()
        results.append(claim_approval(ctx, post_id, token).changed)

    threads = [threading.Thread(target=tap) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert results.count(True) == 1
    publish_post(ctx, post_id)
    publish_post(ctx, post_id)  # a stray second publish is a no-op
    assert len(ctx.x_client.posts) == 1


@pytest.mark.parametrize("headers", [{}, _auth("wrong"), {"Authorization": "token-without-bearer"}])
def test_invalid_token_cannot_post(ctx, client, candidate, headers):
    post_id, _ = candidate
    assert client.post(f"/api/approve/{post_id}", headers=headers).status_code == 403
    assert client.post(f"/api/reject/{post_id}", headers=headers).status_code == 403
    assert _post(ctx, post_id).status == PostStatus.NOTIFIED
    assert ctx.x_client.posts == []


def test_unknown_post_and_other_posts_token_forbidden(ctx, client, candidate, make_raw):
    post_id, token = candidate
    assert client.post("/api/approve/00000000-0000-0000-0000-000000000000", headers=_auth(token)).status_code == 403
    ingest_article(ctx, "test", make_raw(url="https://e.com/other", text="テストアーティスト別記事"))
    with ctx.session_factory() as s:
        other = s.scalars(select(Post.id).where(Post.id != post_id)).one()
    assert client.post(f"/api/approve/{other}", headers=_auth(token)).status_code == 403
    assert ctx.x_client.posts == []


def test_expired_token_rejected(ctx, client, candidate):
    post_id, token = candidate
    with ctx.session_factory() as s:
        s.execute(update(Post).where(Post.id == post_id)
                  .values(action_token_expires_at=datetime.now(timezone.utc) - timedelta(minutes=1)))
        s.commit()
    assert client.post(f"/api/approve/{post_id}", headers=_auth(token)).status_code == 403
    assert ctx.x_client.posts == []


def test_x_api_error_marks_failed_and_allows_retry(ctx, client, candidate):
    post_id, token = candidate
    ctx.x_client.error = XPostError("X API error 403: duplicate content", 403, '{"detail":"dup"}')
    assert client.post(f"/api/approve/{post_id}", headers=_auth(token)).status_code == 202
    post = _post(ctx, post_id)
    assert post.status == PostStatus.FAILED and "403" in post.error_message
    assert post.x_post_id is None and post.posted_at is None
    assert ctx.notifier.sent[-1].title.startswith("❌")

    # the failure notification carries a fresh token; the old one no longer works
    new_token = ctx.notifier.last_token()
    assert new_token != token
    ctx.x_client.error = None
    assert client.post(f"/api/approve/{post_id}", headers=_auth(token)).status_code == 403
    assert client.post(f"/api/approve/{post_id}", headers=_auth(new_token)).status_code == 202
    assert _post(ctx, post_id).status == PostStatus.POSTED
    assert len(ctx.x_client.posts) == 1


def test_uncertain_x_result_is_never_auto_retried(ctx, client, candidate):
    post_id, token = candidate
    ctx.x_client.error = XPostUncertainError("read timeout")
    client.post(f"/api/approve/{post_id}", headers=_auth(token))
    assert _post(ctx, post_id).status == PostStatus.UNCERTAIN
    ctx.x_client.error = None
    r = client.post(f"/api/approve/{post_id}", headers=_auth(token))
    assert r.status_code == 200 and r.json()["status"] == PostStatus.UNCERTAIN
    assert ctx.x_client.posts == []


def test_reject_marks_rejected_and_blocks_approval(ctx, client, candidate, make_raw):
    post_id, token = candidate
    r = client.post(f"/api/reject/{post_id}", headers=_auth(token))
    assert r.status_code == 200 and r.json()["status"] == PostStatus.REJECTED
    assert client.post(f"/api/approve/{post_id}", headers=_auth(token)).json()["status"] == PostStatus.REJECTED
    assert ctx.x_client.posts == []
    with ctx.session_factory() as s:
        assert s.get(Article, _post(ctx, post_id).article_id).status == ArticleStatus.REJECTED
    # the same article is not notified again
    sent = len(ctx.notifier.sent)
    assert ingest_article(ctx, "test", make_raw()) == "duplicate"
    assert len(ctx.notifier.sent) == sent
