from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from newsbot.context import AppContext
from newsbot.pipeline import run_collection

log = logging.getLogger(__name__)


def _tick(ctx: AppContext) -> None:
    try:
        stats = run_collection(ctx)
        log.info("collection tick done", extra={"event": "tick", **stats})
    except Exception:  # noqa: BLE001 - keep the scheduler alive
        log.exception("collection tick crashed", extra={"event": "tick_error"})


def build_scheduler(ctx: AppContext) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    # max_instances=1 + coalesce: a slow tick never overlaps the next one.
    scheduler.add_job(_tick, "interval", minutes=ctx.settings.collect_interval_minutes, args=[ctx],
                      id="collect", max_instances=1, coalesce=True,
                      next_run_time=datetime.now(timezone.utc))  # first tick right after startup
    return scheduler
