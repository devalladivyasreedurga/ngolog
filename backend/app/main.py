import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin.router import router as admin_router
from app.auth.router import router as auth_router
from app.campaigns.router import router as campaigns_router
from app.config import get_settings
from app.evidence.router import router as evidence_router
from app.payments.router import router as payments_router
from app.reporting.router import router as reporting_router
from app.updates.router import router as updates_router

logging.basicConfig(level=logging.INFO)

settings = get_settings()
app = FastAPI(title="NGOLog API", version="0.1.0")
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
