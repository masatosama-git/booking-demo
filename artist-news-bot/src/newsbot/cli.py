"""Command line entry: `python -m newsbot <command>`."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select, update

from newsbot.config import get_settings
from newsbot.logging_setup import setup_logging


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="newsbot")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db", help="create tables")
    d = sub.add_parser("ingest-dummy", help="Phase 1: run one dummy article through the pipeline")
    d.add_argument("--artist", help="artist key (default: first in config)")
    d.add_argument("--url", help="fixed article URL (re-running with the same URL tests dedupe)")
    sub.add_parser("collect", help="run one collection tick now")
    sub.add_parser("resend", help="resend notifications that failed to deliver")
    ls = sub.add_parser("list", help="list recent posts")
    ls.add_argument("--status")
    ls.add_argument("--limit", type=int, default=20)
    r = sub.add_parser("resolve", help="settle an 'uncertain' post after checking X manually")
    r.add_argument("post_id")
    g = r.add_mutually_exclusive_group(required=True)
    g.add_argument("--posted", metavar="X_POST_ID", help="it is on X with this id")
    g.add_argument("--not-posted", action="store_true", help="it is not on X (allows re-approval)")
    s = sub.add_parser("serve", help="run the approval API (and scheduler if ENABLE_SCHEDULER=true)")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8000)
    args = p.parse_args(argv)

    settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("newsbot.api:build_production_app", factory=True, host=args.host, port=args.port)
        return

    from newsbot.context import build_context
    from newsbot.models import Article, Post, PostStatus, utcnow
    from newsbot.pipeline import ingest_article, resend_pending_notifications, run_collection

    ctx = build_context(settings)
    if args.cmd == "init-db":
        print("tables ready")
    elif args.cmd == "ingest-dummy":
        from newsbot.collectors.dummy import DummyCollector

        artist = ctx.artist(args.artist) if args.artist else ctx.artists[0]
        for raw in DummyCollector(args.url).fetch(artist):
            print(ingest_article(ctx, artist.key, raw))
    elif args.cmd == "collect":
        print(json.dumps(run_collection(ctx)))
    elif args.cmd == "resend":
        print(f"resent: {resend_pending_notifications(ctx)}")
    elif args.cmd == "list":
        with ctx.session_factory() as s:
            q = select(Post, Article).join(Article, Post.article_id == Article.id).order_by(Post.created_at.desc())
            if args.status:
                q = q.where(Post.status == args.status)
            for post, art in s.execute(q.limit(args.limit)):
                print(f"{post.id}  {post.status:<9}  imp={art.importance_score}  {art.title[:40]}"
                      + (f"  x={post.x_post_id}" if post.x_post_id else "")
                      + (f"  err={post.error_message[:60]}" if post.error_message else ""))
    elif args.cmd == "resolve":
        values = ({"status": PostStatus.POSTED, "x_post_id": args.posted, "posted_at": utcnow()}
                  if args.posted else {"status": PostStatus.FAILED})
        with ctx.session_factory() as s:
            res = s.execute(update(Post).where(Post.id == args.post_id,
                                               Post.status.in_([PostStatus.UNCERTAIN, PostStatus.APPROVED]))
                            .values(**values))
            s.commit()
        if res.rowcount and args.not_posted:
            from newsbot.approval import _notify_retry

            _notify_retry(ctx, args.post_id, "手動確認でX未投稿と判定")  # gives the user a fresh approve button
        print("updated" if res.rowcount else "not updated (post must be uncertain/approved)")


if __name__ == "__main__":
    main()
