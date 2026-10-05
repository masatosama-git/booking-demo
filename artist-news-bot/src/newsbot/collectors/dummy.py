"""Phase 1 collector: returns a fixed article so the whole flow can be exercised end to end."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from newsbot.collectors.base import RawArticle


class DummyCollector:
    name = "dummy"

    def __init__(self, url: str | None = None):
        self._url = url

    def fetch(self, artist) -> list[RawArticle]:
        now = datetime.now(timezone.utc)
        return [
            RawArticle(
                title=f"{artist.name}、ニューシングル「サンプルソング」を11月18日に発売決定",
                url=self._url or f"https://example.com/news/{artist.key}/{now:%Y%m%d%H%M}",
                source_name="ダミーニュース",
                source_type="music_media",
                published_at=now - timedelta(minutes=8),
                text=(
                    f"{artist.name}が11月18日にニューシングル「サンプルソング」をリリースすることが発表された。"
                    "表題曲はドラマの主題歌として書き下ろされた楽曲で、初回限定盤にはライブ映像が収録される。"
                ),
            )
        ]
