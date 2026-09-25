from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.advisory.router import router as advisory_router
from app.core.config import get_settings
from app.dispatch.router import router as dispatch_router
from app.exposure.router import router as exposure_router
from app.hazard.router import router as hazard_router
from app.impact.router import router as impact_router
from app.insurance.router import router as insurance_router
from app.risk.router import router as risk_router

app = FastAPI(title="Tempest API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_router = APIRouter(prefix="/api")
for r in (
    hazard_router,
    exposure_router,
    impact_router,
    risk_router,
    advisory_router,
    dispatch_router,
    insurance_router,
):
    api_router.include_router(r)
app.include_router(api_router)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "demo_mode": s.DEMO_MODE,
        "configured": {
            "gemini_api_key": bool(s.GEMINI_API_KEY),
            "gee_service_account": bool(s.GEE_SERVICE_ACCOUNT),
            # Existence check only; the key file is never read.
            "gee_key_path": s.gee_key_file is not None and s.gee_key_file.is_file(),
            "telegram_bot_token": bool(s.TELEGRAM_BOT_TOKEN),
            "telegram_chat_id": bool(s.TELEGRAM_CHAT_ID),
            "resend_api_key": bool(s.RESEND_API_KEY),
        },
    }
