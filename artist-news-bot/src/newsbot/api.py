from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse

from newsbot.approval import InvalidToken, PostNotFound, claim_approval, publish_post, reject_post
from newsbot.context import AppContext

log = logging.getLogger(__name__)


def _bearer(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


def create_app(ctx: AppContext, scheduler_factory=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler = scheduler_factory(ctx) if scheduler_factory else None
        if scheduler:
            scheduler.start()
        yield
        if scheduler:
            scheduler.shutdown(wait=False)

    # No interactive docs in production: the API is only meant for ntfy buttons.
    app = FastAPI(title="artist-news-bot", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    def forbidden() -> HTTPException:
        # Same response for unknown post and bad token, so post ids cannot be probed.
        return HTTPException(status_code=403, detail="forbidden")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.post("/api/approve/{post_id}")
    def approve(post_id: str, background: BackgroundTasks, authorization: str | None = Header(default=None)):
        try:
            result = claim_approval(ctx, post_id, _bearer(authorization))
        except (PostNotFound, InvalidToken):
            raise forbidden()
        if not result.changed:
            return {"post_id": post_id, "status": result.status, "message": "already handled"}
        # Respond quickly to the phone; the X call and the result notification happen after.
        background.add_task(publish_post, ctx, post_id)
        return JSONResponse(status_code=202, content={"post_id": post_id, "status": result.status,
                                                      "message": "posting"})

    @app.post("/api/reject/{post_id}")
    def reject(post_id: str, authorization: str | None = Header(default=None)):
        try:
            result = reject_post(ctx, post_id, _bearer(authorization))
        except (PostNotFound, InvalidToken):
            raise forbidden()
        return {"post_id": post_id, "status": result.status,
                "message": "rejected" if result.changed else "already handled"}

    return app


def build_production_app() -> FastAPI:
    """Entry point for `uvicorn newsbot.api:build_production_app --factory`."""
    from newsbot.config import get_settings
    from newsbot.context import build_context
    from newsbot.logging_setup import setup_logging
    from newsbot.scheduler import build_scheduler

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)
    ctx = build_context(settings)
    return create_app(ctx, scheduler_factory=build_scheduler if settings.enable_scheduler else None)
