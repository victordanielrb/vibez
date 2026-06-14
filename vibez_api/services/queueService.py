import asyncio
import json
import logging

import redis.asyncio as aioredis
from bullmq import Queue, Worker

import services.audioService as audio
import services.aiService as ai
import services.dbService as db

logger = logging.getLogger(__name__)

_REDIS_OPTS = {
    "host": __import__("os").getenv("REDIS_HOST", "localhost"),
    "port": int(__import__("os").getenv("REDIS_PORT", "6379")),
}

_redis = aioredis.Redis(**_REDIS_OPTS)
queue = Queue("vibez-ingest", {"connection": _REDIS_OPTS})


async def _pub(job_id: str, event: dict) -> None:
    await _redis.publish(f"job:{job_id}", json.dumps(event))


async def _process(job, token) -> None:
    data = job.data
    job_id: str = data["job_id"]
    playlist_url: str = data["playlist_url"]
    client_ip: str = data["client_ip"]

    logger.info("[queue:%s] started", job_id)

    try:
        video_ids = await asyncio.to_thread(audio.get_urls_from_playlist, playlist_url)
    except Exception as exc:
        logger.error("[queue:%s] failed to fetch playlist: %s", job_id, exc)
        db.fail_job(job_id, f"Could not fetch playlist: {exc}")
        await _pub(job_id, {"type": "error", "error": str(exc)})
        return

    total = len(video_ids)
    if not total:
        db.fail_job(job_id, "No videos found in playlist")
        await _pub(job_id, {"type": "error", "error": "No videos found in playlist"})
        return

    db.update_job_progress(job_id, 0, total)
    await _pub(job_id, {"type": "start", "total": total})

    for i, video_id in enumerate(video_ids, 1):
        try:
            per_chunk = await asyncio.to_thread(audio.process_video, video_id)

            chunks_with_emb = []
            for c in per_chunk:
                emb = await asyncio.to_thread(ai.embed_text, c["description"], client_ip)
                db.log_usage(client_ip, "track_ingest", "")
                chunks_with_emb.append({**c, "embedding": emb})

            first = per_chunk[0]
            db.insert_track_chunks(
                name=first.get("title", video_id),
                author=first.get("author", "unknown"),
                url=first["input_url"],
                chunks=chunks_with_emb,
            )
            logger.info("[queue:%s] [%d/%d] saved %s", job_id, i, total, first.get("title", video_id))
            await _pub(job_id, {
                "type": "progress",
                "processed": i,
                "total": total,
                "track": first.get("title", video_id),
            })
        except Exception as exc:
            logger.warning("[queue:%s] [%d/%d] skipped %s — %s", job_id, i, total, video_id, exc)
            await _pub(job_id, {
                "type": "track_error",
                "processed": i,
                "total": total,
                "video_id": video_id,
                "error": str(exc),
            })
        db.update_job_progress(job_id, i, total)

    db.finish_job(job_id)
    await _pub(job_id, {"type": "done", "processed": total, "total": total})
    logger.info("[queue:%s] done", job_id)


worker = Worker("vibez-ingest", _process, {"connection": _REDIS_OPTS})


def start_playlist_job(
    playlist_url: str,
    client_ip: str = "system",
    callback_url: str | None = None,
) -> str:
    job_id = db.create_job(playlist_url, callback_url)
    asyncio.create_task(
        queue.add("ingest", {"job_id": job_id, "playlist_url": playlist_url, "client_ip": client_ip})
    )
    return job_id
