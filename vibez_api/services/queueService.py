import asyncio
import json
import logging

import redis.asyncio as aioredis
from bullmq import Queue, Worker

import services.audioService as audio
import services.aiService as ai
import services.dbService as db

logger = logging.getLogger(__name__)

import os as _os
_REDIS_OPTS = {
    "host": _os.getenv("REDIS_HOST", "localhost"),
    "port": int(_os.getenv("REDIS_PORT", "6379")),
    **( {"password": _os.getenv("REDIS_PASSWORD")} if _os.getenv("REDIS_PASSWORD") else {} ),
}

_redis = aioredis.Redis(**_REDIS_OPTS)
queue = Queue("vibez-ingest", {"connection": _REDIS_OPTS})


async def _pub(playlist_id: str, event: dict) -> None:
    await _redis.publish(f"job:{playlist_id}", json.dumps(event))


async def _process_track(job, token) -> None:
    data       = job.data
    playlist_id = data["playlist_id"]
    video_id   = data["video_id"]
    title      = data["title"]
    author     = data["author"]
    client_ip  = data["client_ip"]
    total      = data["total"]

    try:
        usage = db.get_daily_usage(client_ip)
        if usage["tracks_ingested"] >= db.TRACK_INGEST_LIMIT:
            processed = db.increment_job_processed(playlist_id)
            await _pub(playlist_id, {
                "type": "rate_limit",
                "track": title,
                "processed": processed,
                "total": total,
                "limit": db.TRACK_INGEST_LIMIT,
            })
            _maybe_finish(playlist_id, processed, total)
            return

        per_chunk = await asyncio.to_thread(audio.process_video, video_id, title, author)

        chunks_with_emb = []
        for c in per_chunk:
            emb = await asyncio.to_thread(ai.embed_text, c["description"], client_ip)
            db.log_usage(client_ip, "track_ingest", "")
            chunks_with_emb.append({**c, "embedding": emb})

        db.insert_track_chunks(
            name=title,
            author=author,
            url=f"https://www.youtube.com/watch?v={video_id}",
            chunks=chunks_with_emb,
        )

        processed = db.increment_job_processed(playlist_id)
        logger.info("[track:%s] [%d/%d] saved %s", playlist_id, processed, total, title)
        await _pub(playlist_id, {
            "type": "progress",
            "track": title,
            "processed": processed,
            "total": total,
        })

    except Exception as exc:
        processed = db.increment_job_processed(playlist_id)
        logger.warning("[track:%s] [%d/%d] skipped %s — %s", playlist_id, processed, total, title, exc)
        await _pub(playlist_id, {
            "type": "track_error",
            "track": title,
            "error": str(exc),
            "processed": processed,
            "total": total,
        })

    _maybe_finish(playlist_id, processed, total)


def _maybe_finish(playlist_id: str, processed: int, total: int) -> None:
    if processed >= total:
        db.finish_job(playlist_id)
        asyncio.create_task(_pub(playlist_id, {
            "type": "done",
            "processed": processed,
            "total": total,
        }))
        logger.info("[playlist:%s] done (%d/%d)", playlist_id, processed, total)


worker = Worker("vibez-ingest", _process_track, {"connection": _REDIS_OPTS})


def start_playlist_job(
    playlist_url: str,
    client_ip: str = "system",
    callback_url: str | None = None,
) -> tuple[str, int]:
    entries = audio.get_urls_from_playlist(playlist_url)
    total = len(entries)
    job_id = db.create_job(playlist_url, callback_url, total=total)

    async def _enqueue():
        for video_id, title, author in entries:
            await queue.add("ingest-track", {
                "playlist_id": job_id,
                "video_id": video_id,
                "title": title,
                "author": author,
                "client_ip": client_ip,
                "total": total,
            })

    asyncio.create_task(_enqueue())
    logger.info("[playlist:%s] queued %d tracks", job_id, total)
    return job_id, total
