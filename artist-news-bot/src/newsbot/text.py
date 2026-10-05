"""X post composition and length checks.

X counts text with "weighted length" (twitter-text v3): most CJK characters and emoji
count as 2, Latin characters as 1, and every URL as 23 regardless of its real length.
The limit for non-Premium accounts is 280 weighted characters (= 140 Japanese characters).
"""
from __future__ import annotations

import re

MAX_WEIGHTED_LENGTH = 280
URL_WEIGHT = 23
_URL_RE = re.compile(r"https?://\S+")
# Code point ranges weighted as 1 (twitter-text v3 config); everything else weighs 2.
_LIGHT_RANGES = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))


def _char_weight(ch: str) -> int:
    cp = ord(ch)
    return 1 if any(lo <= cp <= hi for lo, hi in _LIGHT_RANGES) else 2


def weighted_length(text: str) -> int:
    total = 0
    pos = 0
    for m in _URL_RE.finditer(text):
        total += sum(_char_weight(c) for c in text[pos : m.start()]) + URL_WEIGHT
        pos = m.end()
    return total + sum(_char_weight(c) for c in text[pos:])


def strip_urls(text: str) -> str:
    """AI output must never introduce links; the only link is the source URL we append."""
    return _URL_RE.sub("", text).strip()


def compose_post(heading: str, body: str, url: str, hashtags: list[str] | None = None) -> str:
    """Build the final post. The source URL is always included and never comes from the AI."""
    tags = " ".join(f"#{t.lstrip('#')}" for t in (hashtags or []))
    body = strip_urls(body)

    def render(b: str) -> str:
        parts = [f"【{heading}】", b, f"詳細👇\n{url}"]
        if tags:
            parts.append(tags)
        return "\n\n".join(p for p in parts if p)

    if weighted_length(render(body)) <= MAX_WEIGHTED_LENGTH:
        return render(body)
    # Too long: drop whole trailing sentences first so we never cut a fact in half.
    sentences = [s for s in re.split(r"(?<=[。！？!?])\s*", body) if s]
    while len(sentences) > 1:
        sentences.pop()
        candidate = "".join(sentences)
        if weighted_length(render(candidate)) <= MAX_WEIGHTED_LENGTH:
            return render(candidate)
    # A single sentence that still doesn't fit: hard truncate with an ellipsis.
    cut = body
    while cut and weighted_length(render(cut + "…")) > MAX_WEIGHTED_LENGTH:
        cut = cut[:-1]
    return render(cut + "…")
