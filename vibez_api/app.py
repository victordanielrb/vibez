import asyncio
import os
import logging
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

# Set up Prometheus-backed OTel MeterProvider BEFORE any ADK import
# so ADK's meter (created at module level) attaches to this provider.
from opentelemetry import metrics as otel_metrics
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.sdk.metrics import MeterProvider as SdkMeterProvider

_prometheus_reader = PrometheusMetricReader()
otel_metrics.set_meter_provider(SdkMeterProvider(metric_readers=[_prometheus_reader]))

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG") else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import router
import services.dbService as db_service

app = FastAPI(title="vibez-api")


@app.on_event("startup")
async def _on_startup() -> None:
    dead = db_service.mark_stale_jobs_dead()
    if dead:
        logging.getLogger("app").warning("Marked %d stale job(s) as dead on startup", dead)
    import services.queueService as qs  # noqa: F401
    asyncio.create_task(qs.worker.run())

_origins = os.getenv("FRONTEND_URL", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[_origins] if _origins != "*" else ["*"],
    allow_credentials=_origins != "*",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router=router.router)


@app.get("/health")
def health():
    return {"status": "ok"}
