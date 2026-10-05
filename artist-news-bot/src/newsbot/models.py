from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class ArticleStatus:
    DISCOVERED = "discovered"  # saved, not yet judged (or AI failed -> retried later)
    REJECTED = "rejected"      # filtered out by rules / AI / user
    CANDIDATE = "candidate"    # a post draft was created
    POSTED = "posted"


class PostStatus:
    CANDIDATE = "candidate"    # draft saved, notification not yet delivered
    NOTIFIED = "notified"      # ntfy delivered, waiting for the user
    APPROVED = "approved"      # user approved; X call in progress (acts as the lock)
    POSTED = "posted"
    FAILED = "failed"          # X definitively rejected the request; safe to approve again
    UNCERTAIN = "uncertain"    # timeout / 5xx: may or may not be on X. Needs manual check
    REJECTED = "rejected"

    # States from which an approval may start a (re)post.
    APPROVABLE = (CANDIDATE, NOTIFIED, FAILED)
    REJECTABLE = (CANDIDATE, NOTIFIED, FAILED)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("artist_key", "url_hash", name="uq_articles_artist_url"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    artist_key: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    source_name: Mapped[str | None] = mapped_column(String(200))
    source_priority: Mapped[int] = mapped_column(Integer, default=9)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    raw_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    relevance_score: Mapped[int | None] = mapped_column(Integer)
    importance_score: Mapped[int | None] = mapped_column(Integer)
    reliability_score: Mapped[int | None] = mapped_column(Integer)
    ai_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=ArticleStatus.DISCOVERED, index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    # unique: one post draft per article, so an article can never be notified twice
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), unique=True)
    generated_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default=PostStatus.CANDIDATE, index=True)
    action_token_hash: Mapped[str | None] = mapped_column(String(64))
    action_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notify_attempts: Mapped[int] = mapped_column(Integer, default=0)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    x_post_id: Mapped[str | None] = mapped_column(String(64))
    x_response: Mapped[str | None] = mapped_column(Text)
    error_message: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
