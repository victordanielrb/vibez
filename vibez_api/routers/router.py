import json
import logging
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response as FastAPIResponse
from pydantic import BaseModel
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from sse_starlette.sse import EventSourceResponse
import redis.asyncio as aioredis
import controllers.ai_controller as ai_controller
import services.dbService as db_service
import services.aiService as ai_service
import services.agentService as agent_service
import services.queueService as queue_service

logger = logging.getLogger(__name__)

router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class ExtractRequest(BaseModel):
    playlistUrl: str
    callbackUrl: str | None = None


@router.post("/extract", status_code=202)
async def extract(body: ExtractRequest, request: Request) -> dict:
    client_ip = _client_ip(request)
    _check_global_limits()
    usage = db_service.get_daily_usage(client_ip)
    if usage["tracks_ingested"] >= db_service.TRACK_INGEST_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit", "message": "Daily track ingest limit reached.", "retry_after": "tomorrow UTC"},
        )
    job_id = queue_service.start_playlist_job(body.playlistUrl, client_ip, body.callbackUrl)
    return {"jobId": job_id, "status": "queued"}


@router.get("/jobs")
def list_jobs() -> dict:
    return {"jobs": db_service.list_jobs()}


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = db_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/jobs/{job_id}/stream")
async def job_stream(job_id: str):
    """SSE stream: subscribes to Redis pub/sub and forwards events to the client."""
    redis_opts = queue_service._REDIS_OPTS

    async def generator():
        r = aioredis.Redis(**redis_opts)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"job:{job_id}")
        try:
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                event = json.loads(message["data"])
                yield {"data": json.dumps(event)}
                if event.get("type") in ("done", "error"):
                    break
        finally:
            await pubsub.unsubscribe(f"job:{job_id}")
            await r.aclose()

    return EventSourceResponse(generator())


def _check_global_limits() -> None:
    """Raise 429 if any global Gemini API limit is exceeded."""
    rpm = db_service.get_rpm()
    if rpm >= db_service.GLOBAL_RPM_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"error": "global_rate_limit", "limit": "rpm",
                    "message": f"Global RPM limit reached ({rpm}/{db_service.GLOBAL_RPM_LIMIT}). Try again in a moment."},
        )
    tpm = db_service.get_global_tpm()
    if tpm >= db_service.GLOBAL_TPM_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"error": "global_rate_limit", "limit": "tpm",
                    "message": f"Global TPM limit reached ({tpm}/{db_service.GLOBAL_TPM_LIMIT}). Try again in a moment."},
        )
    rpd = db_service.get_global_rpd()
    if rpd >= db_service.GLOBAL_RPD_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"error": "global_rate_limit", "limit": "rpd",
                    "message": f"Global RPD limit reached ({rpd}/{db_service.GLOBAL_RPD_LIMIT}). Try again tomorrow."},
        )


@router.post("/image-embedding")
async def image_processing(body: dict, request: Request) -> dict:
    client_ip = _client_ip(request)
    _check_global_limits()
    usage = db_service.get_daily_usage(client_ip)
    if usage["image_searches"] >= db_service.IMAGE_SEARCH_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit", "message": "Daily image search limit reached.", "retry_after": "tomorrow UTC"},
        )
    if usage["tokens_used"] >= db_service.TOKEN_DAILY_LIMIT:
        raise HTTPException(
            status_code=429,
            detail={"error": "rate_limit", "message": "Daily token limit reached.", "retry_after": "tomorrow UTC"},
        )

    image_base64 = body.get("imageBase64", "")
    top_n = int(body.get("topN", 5))

    _, data_uri = ai_controller.process_image(image_base64, client_ip=client_ip)

    description = await agent_service.describe_image(data_uri, client_ip=client_ip)
    logger.info("[image-description] %s", description)

    text_embedding = ai_service.embed_text(description, client_ip=client_ip)
    candidates = db_service.search_by_embedding(text_embedding, limit=10)
    reranked = await agent_service.rerank_by_vibe_image(data_uri, candidates, top_n=top_n, image_description=description, client_ip=client_ip)

    db_service.log_usage(client_ip, "image_search", "")
    search_id = db_service.save_search(data_uri, description, reranked)
    return {"searchId": search_id, "description": description, "searchResults": reranked}


@router.get("/searches")
def list_searches(limit: int = 20) -> dict:
    return {"searches": db_service.get_searches(limit=limit)}


_RPM_LIMIT = int(os.getenv("RPM_LIMIT", "10"))  # conservative: embedding model is the bottleneck at 10 RPM free tier


@router.get("/quota")
def get_quota(request: Request) -> dict:
    client_ip = _client_ip(request)
    today = db_service.get_daily_usage(client_ip)
    limits = {
        "image_searches_per_day": db_service.IMAGE_SEARCH_LIMIT,
        "tracks_per_day": db_service.TRACK_INGEST_LIMIT,
        "tokens_per_day": db_service.TOKEN_DAILY_LIMIT,
        "rpm": _RPM_LIMIT,
    }
    pct_tokens = round(today["tokens_used"] / db_service.TOKEN_DAILY_LIMIT * 100, 1)
    return {
        "client_ip": client_ip,
        "today": today,
        "limits": limits,
        "pct_tokens": min(pct_tokens, 100.0),
        "rpm_used": today["rpm"],
        "pct_rpm": round(today["rpm"] / _RPM_LIMIT * 100, 1),
    }


@router.get("/quota/global")
def get_global_quota() -> dict:
    today = db_service.get_global_daily_usage()
    rpm_used = db_service.get_rpm()
    tpm_used = db_service.get_global_tpm()
    rpd_used = db_service.get_global_rpd()
    gemini_limits = {
        "rpm": db_service.GLOBAL_RPM_LIMIT,
        "tpm": db_service.GLOBAL_TPM_LIMIT,
        "rpd": db_service.GLOBAL_RPD_LIMIT,
    }
    return {
        "today": today,
        "limits": {
            "tokens_per_day": db_service.TOKEN_DAILY_LIMIT,
            "rpm": _RPM_LIMIT,
        },
        "gemini": {
            "model": "gemini-3.1-flash-lite",
            "limits": gemini_limits,
            "used": {"rpm": rpm_used, "tpm": tpm_used, "rpd": rpd_used},
            "pct": {
                "rpm": round(rpm_used / db_service.GLOBAL_RPM_LIMIT * 100, 1),
                "tpm": round(tpm_used / db_service.GLOBAL_TPM_LIMIT * 100, 1),
                "rpd": round(rpd_used / db_service.GLOBAL_RPD_LIMIT * 100, 1),
            },
        },
    }


@router.get("/metrics/ops")
def get_metrics_ops() -> dict:
    rpm_used = db_service.get_rpm()
    tpm_used = db_service.get_global_tpm()
    rpd_used = db_service.get_global_rpd()
    return {
        "ops_breakdown": db_service.get_ops_breakdown(),
        "hourly": db_service.get_hourly_usage(24),
        "global_today": db_service.get_global_daily_usage(),
        "gemini": {
            "model": "gemini-3.1-flash-lite",
            "limits": {
                "rpm": db_service.GLOBAL_RPM_LIMIT,
                "tpm": db_service.GLOBAL_TPM_LIMIT,
                "rpd": db_service.GLOBAL_RPD_LIMIT,
            },
            "used": {"rpm": rpm_used, "tpm": tpm_used, "rpd": rpd_used},
        },
    }


@router.get("/otel-metrics")
def prometheus_metrics():
    """Expose ADK OTel metrics in Prometheus text format."""
    return FastAPIResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
