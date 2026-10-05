from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import anthropic
from pydantic import ValidationError

from newsbot.ai.base import CATEGORIES, SUBJECTS, AIError, Analysis, ArticleInput
from newsbot.ai.prompts import SYSTEM_PROMPT, build_user_message

log = logging.getLogger(__name__)

MAX_BODY_CHARS = 30_000

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "is_about_artist": {"type": "boolean"},
        "relevance_score": {"type": "integer"},
        "importance_score": {"type": "integer"},
        "reliability_score": {"type": "integer"},
        "is_rumor_or_gossip": {"type": "boolean"},
        "is_outdated": {"type": "boolean"},
        "duplicate_of_recent": {"type": "boolean"},
        "category": {"type": "string", "enum": CATEGORIES},
        "subject": {"type": "string", "enum": SUBJECTS},
        "summary": {"type": "string"},
        "post_body": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "is_about_artist", "relevance_score", "importance_score", "reliability_score",
        "is_rumor_or_gossip", "is_outdated", "duplicate_of_recent", "category", "subject",
        "summary", "post_body", "reason",
    ],
    "additionalProperties": False,
}


class AnthropicAIClient:
    def __init__(self, settings):
        if not settings.anthropic_api_key:
            raise AIError("ANTHROPIC_API_KEY is not set")
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key, timeout=settings.ai_timeout_seconds, max_retries=2
        )
        self._model = settings.ai_model
        self._effort = settings.ai_effort

    def analyze(self, article: ArticleInput, artist, recent_summaries: list[str]) -> Analysis:
        if article.text and len(article.text) > MAX_BODY_CHARS:
            log.warning("article body truncated for AI", extra={"event": "ai_truncate", "url": article.url,
                                                                 "chars": len(article.text)})
            article = ArticleInput(**{**article.__dict__, "text": article.text[:MAX_BODY_CHARS]})
        now_iso = datetime.now(timezone.utc).isoformat(timespec="minutes")
        try:
            response = self._client.beta.messages.create(
                model=self._model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(article, artist, recent_summaries, now_iso)}],
                output_config={
                    "effort": self._effort,
                    "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA},
                },
                # Server-side fallback: on a safety-classifier refusal the API retries on another model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.RateLimitError as e:
            raise AIError(f"rate limited: {e}") from e
        except anthropic.APIStatusError as e:
            raise AIError(f"API error {e.status_code}: {e.message}") from e
        except anthropic.APIConnectionError as e:
            raise AIError(f"connection error: {e}") from e

        if response.stop_reason == "refusal":
            raise AIError("model refused to analyze the article")
        if response.stop_reason == "max_tokens":
            raise AIError("analysis truncated (max_tokens)")
        text = "".join(b.text for b in response.content if b.type == "text")
        try:
            return Analysis(**json.loads(text))
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            raise AIError(f"invalid analysis JSON: {e}") from e
