import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.campaigns.router import router as campaigns_router
from app.config import get_settings
from app.db.base import SessionLocal
from app.evidence.router import router as evidence_router
from app.payments.router import router as payments_router
from app.reporting import jobs
from app.reporting.router import router as reporting_router
from app.updates.router import router as updates_router

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

settings = get_settings()


def _run_jobs_once() -> None:
    db = SessionLocal()
    try:
        result = jobs.run_all(db)
        if result.opened or result.reminded or result.overdue:
            log.info("Scheduled jobs: %s", result)
    finally:
        db.close()


async def _scheduler() -> None:
    while True:
        try:
            await asyncio.to_thread(_run_jobs_once)
        except Exception:
            log.exception("Scheduled jobs failed; will retry next interval")
        await asyncio.sleep(settings.scheduler_interval_seconds)


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_scheduler()) if settings.scheduler_enabled else None
    yield
    if task:
        task.cancel()


app = FastAPI(title="NGOLog API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth_router, campaigns_router, payments_router, reporting_router, evidence_router, updates_router, admin_router):
    app.include_router(r)


@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "paypal_configured": settings.paypal_configured,
        "ai_configured": settings.ai_configured,
    }
