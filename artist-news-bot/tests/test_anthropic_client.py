import json

import anthropic
import httpx2 as httpx  # anthropic SDK 1.x is built on httpx2
import pytest

from newsbot.ai import AIError, ArticleInput
from newsbot.ai.anthropic_client import AnthropicAIClient
from newsbot.config import ArtistProfile, Settings

ANALYSIS = dict(is_about_artist=True, relevance_score=120, importance_score=80, reliability_score=90,
                is_rumor_or_gossip=False, is_outdated=False, duplicate_of_recent=False, category="tv_radio",
                summary="出演決定", post_body="〇〇が10月12日放送の「△△」に出演決定。", reason="official")


def _message(stop_reason="end_turn", text=json.dumps(ANALYSIS)):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": text}], "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10}}


def _client(handler):
    c = AnthropicAIClient(Settings(_env_file=None, anthropic_api_key="test"))
    c._client = anthropic.Anthropic(api_key="test", max_retries=0,
                                    http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return c


ART = ArticleInput(title="〇〇 出演決定", url="https://e.com", source_name="s", published_at=None, text="本文")
ARTIST = ArtistProfile(key="a", name="〇〇")


def test_parses_structured_output_and_sends_expected_request():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["beta"] = req.headers.get("anthropic-beta")
        return httpx.Response(200, json=_message())

    result = _client(handler).analyze(ART, ARTIST, ["前回の要約"])
    assert result.relevance_score == 100  # clamped
    assert result.category == "tv_radio"
    body = seen["body"]
    assert body["model"] == "claude-opus-5-5"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in seen["beta"]
    assert "前回の要約" in body["messages"][0]["content"]


@pytest.mark.parametrize("response", [
    httpx.Response(200, json=_message(stop_reason="refusal")),
    httpx.Response(200, json=_message(text="not json")),
    httpx.Response(529, json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}}),
    httpx.Response(400, json={"type": "error", "error": {"type": "invalid_request_error", "message": "x"}}),
])
def test_failures_become_ai_error(response):
    with pytest.raises(AIError):
        _client(lambda req: response).analyze(ART, ARTIST, [])
