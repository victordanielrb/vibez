import logging
import threading

import services.audioService as audio_extractor
import services.dbService as db_service
import services.aiService as gemini_service

logger = logging.getLogger(__name__)


def start_playlist_job(playlist_url: str, client_ip: str = "system") -> str:
    job_id = db_service.create_job(playlist_url)
    logger.info("[job:%s] created — playlist: %s", job_id, playlist_url)
    thread = threading.Thread(target=_run_job, args=(job_id, playlist_url, client_ip), daemon=True)
    thread.start()
    return job_id


def _run_job(job_id: str, playlist_url: str, client_ip: str = "system") -> None:
    logger.info("[job:%s] worker started", job_id)
    try:
        try:
            video_ids = audio_extractor.get_urls_from_playlist(playlist_url)
        except Exception as exc:
            logger.error("[job:%s] failed to fetch playlist: %s", job_id, exc)
            db_service.fail_job(job_id, f"Could not fetch playlist: {exc}")
            return

        total = len(video_ids)
        if not total:
            logger.warning("[job:%s] no videos found in playlist", job_id)
            db_service.fail_job(job_id, "No videos found in playlist")
            return

        logger.info("[job:%s] %d video(s) to process", job_id, total)
        db_service.update_job_progress(job_id, 0, total)

        for index, video_id in enumerate(video_ids, start=1):
            logger.debug("[job:%s] [%d/%d] processing video_id=%s", job_id, index, total, video_id)
            try:
                features = audio_extractor.process_video(video_id)
                embedding = gemini_service.embed_text(features["description"], client_ip=client_ip)
                db_service.log_usage(client_ip, "track_ingest", "")
                db_service.insert_track(
                    name=features.get("title", video_id),
                    author=features.get("author", "unknown"),
                    url=features["input_url"],
                    embedding=embedding,
                    description=features.get("description"),
                )
                logger.info(
                    "[job:%s] [%d/%d] saved — %s (BPM %s, key %s %s)",
                    job_id, index, total,
                    features.get("title", video_id),
                    features.get("bpm", "?"),
                    features.get("key", "?"),
                    features.get("scale", ""),
                )
            except Exception as exc:
                logger.warning(
                    "[job:%s] [%d/%d] skipped video_id=%s — %s: %s",
                    job_id, index, total, video_id,
                    type(exc).__name__, exc,
                    exc_info=True,
                )
            finally:
                db_service.update_job_progress(job_id, index, total)

        db_service.finish_job(job_id)
        logger.info("[job:%s] done", job_id)

    except Exception as exc:
        logger.exception("[job:%s] unexpected error: %s", job_id, exc)
        db_service.fail_job(job_id, str(exc))
