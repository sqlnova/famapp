"""FastAPI app – Twilio WhatsApp webhook + health endpoints."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from twilio.request_validator import RequestValidator
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from core.config import get_settings
from core.models import IncomingWhatsAppMessage, MessageRecord, MessageStatus
from core.supabase_client import upsert_message
from agents.intake.graph import run_intake
from server.web import router as web_router

logger = structlog.get_logger(__name__)


# ── Lifespan: start/stop scheduler ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    scheduler = None
    if s.google_maps_api_key:
        try:
            from agents.logistics.proactive import start_scheduler, stop_scheduler
            scheduler = start_scheduler()
            logger.info("logistics_scheduler_enabled")
        except Exception:
            logger.exception("logistics_scheduler_failed_to_start")
    else:
        logger.info("logistics_scheduler_disabled", reason="GOOGLE_MAPS_API_KEY not set")

    yield  # app is running

    if scheduler:
        from agents.logistics.proactive import stop_scheduler
        stop_scheduler()


app = FastAPI(title="FamApp", version="0.3.0", lifespan=lifespan)
# Trust Railway's reverse proxy headers so request.url uses https://
# This is required for Twilio signature validation to work behind a proxy
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.include_router(web_router)


# ── Twilio signature validation ───────────────────────────────────────────────

def _validate_twilio_signature(request: Request, form_data: dict) -> bool:
    s = get_settings()
    if s.is_production:
        validator = RequestValidator(s.twilio_auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")
        return validator.validate(str(request.url), form_data, signature)
    return True


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "famapp", "version": "0.2.0"}


# ── WhatsApp webhook ──────────────────────────────────────────────────────────

@app.post("/webhook/whatsapp", response_class=PlainTextResponse)
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    MessageSid: Annotated[str, Form()] = "",
    From: Annotated[str, Form()] = "",
    To: Annotated[str, Form()] = "",
    Body: Annotated[str, Form()] = "",
    NumMedia: Annotated[int, Form()] = 0,
    ProfileName: Annotated[str, Form()] = "",
    MediaUrl0: Annotated[str, Form()] = "",
) -> PlainTextResponse:
    form_data = dict(await request.form())

    if not _validate_twilio_signature(request, form_data):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid Twilio signature")

    msg = IncomingWhatsAppMessage(
        MessageSid=MessageSid,
        From=From,
        To=To,
        Body=Body,
        NumMedia=NumMedia,
        ProfileName=ProfileName or None,
        MediaUrl0=MediaUrl0 or None,
    )

    logger.info("whatsapp_received", sid=msg.message_sid, from_=msg.from_number, body=msg.body[:80])

    record = MessageRecord(
        message_sid=msg.message_sid,
        from_number=msg.from_number,
        body=msg.body,
        status=MessageStatus.RECEIVED,
    )
    await upsert_message(record)

    background_tasks.add_task(
        run_intake,
        message_sid=msg.message_sid,
        sender=msg.from_number,
        raw_text=msg.body,
    )

    return PlainTextResponse("", status_code=200)
