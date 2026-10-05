"""Deterministic stand-in for local runs without an API key (AI_PROVIDER=fake)."""
from __future__ import annotations

from newsbot.ai.base import Analysis, ArticleInput


class FakeAIClient:
    def analyze(self, article: ArticleInput, artist, recent_summaries: list[str]) -> Analysis:
        haystack = f"{article.title}\n{article.text or ''}"
        related = artist.mentions(haystack)
        return Analysis(
            is_about_artist=related,
            relevance_score=90 if related else 10,
            importance_score=80,
            reliability_score=80,
            is_rumor_or_gossip=False,
            is_outdated=False,
            duplicate_of_recent=False,
            category="other",
            summary=article.title,
            post_body=f"{article.title}。" if related else "",
            reason="fake provider",
        )
