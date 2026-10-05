"""ntfy publisher. Uses JSON publishing so Japanese text and action headers are sent safely."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

log = logging.getLogger(__name__)


class NotifyError(Exception):
    pass


@dataclass
class Notification:
    title: str
    message: str
    priority: int = 3
    tags: list[str] = field(default_factory=list)
    click: str | None = None
    actions: list[dict] = field(default_factory=list)


class NtfyNotifier:
    def __init__(self, server: str, topic: str, token: str = "", timeout: float = 10.0,
                 transport: httpx.BaseTransport | None = None):
        if not topic:
            raise NotifyError("NTFY_TOPIC is not set")
        self._url = server.rstrip("/") + "/"
        self._topic = topic
        self._headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(timeout=timeout, transport=transport)

    def send(self, n: Notification) -> str:
        payload = {
            "topic": self._topic,
            "title": n.title,
            "message": n.message,
            "priority": n.priority,
            "tags": n.tags,
            "actions": n.actions[:3],  # ntfy allows at most 3 actions
        }
        if n.click:
            payload["click"] = n.click
        try:
            r = self._client.post(self._url, json=payload, headers=self._headers)
            r.raise_for_status()
        except httpx.HTTPError as e:
            raise NotifyError(f"ntfy publish failed: {e}") from e
        msg_id = r.json().get("id", "")
        log.info("ntfy sent", extra={"event": "ntfy_sent", "ntfy_id": msg_id, "title": n.title})
        return msg_id


def humanize_age(published_at: datetime | None) -> str:
    if not published_at:
        return "不明"
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    minutes = int((datetime.now(timezone.utc) - published_at).total_seconds() // 60)
    if minutes < 1:
        return "たった今"
    if minutes < 60:
        return f"{minutes}分前"
    if minutes < 48 * 60:
        return f"{minutes // 60}時間前"
    return f"{minutes // 1440}日前"


def candidate_notification(*, heading: str, article_title: str, source_name: str | None,
                           published_at: datetime | None, importance: int | None, post_text: str,
                           article_url: str, approve_url: str, reject_url: str, token: str,
                           title: str | None = None, note: str | None = None) -> Notification:
    auth = {"Authorization": f"Bearer {token}"}
    message = (
        (f"{note}\n\n" if note else "")
        + f"「{article_title}」\n\n"
        f"情報源：{source_name or '不明'}\n"
        f"公開：{humanize_age(published_at)}\n"
        f"重要度：{importance if importance is not None else '-'}\n\n"
        f"投稿予定：\n{post_text}"
    )
    return Notification(
        title=title or heading,
        message=message,
        priority=4 if (importance or 0) >= 80 else 3,
        tags=["newspaper"],
        actions=[
            {"action": "http", "label": "承認", "url": approve_url, "method": "POST",
             "headers": auth, "clear": True},
            {"action": "http", "label": "却下", "url": reject_url, "method": "POST",
             "headers": auth, "clear": True},
            {"action": "view", "label": "元記事", "url": article_url},
        ],
    )
