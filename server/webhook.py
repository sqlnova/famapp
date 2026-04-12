"""FastAPI app – Twilio WhatsApp webhook + health endpoints."""
from __future__ import annotations

import asyncio
from typing import Annotated

import structlog
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import PlainTextResponse
from twilio.request_validator import RequestValidator

from core.config import get_settings
from core.models import IncomingWhatsAppMessage, MessageRecord, MessageStatus
from core.supabase_client import upsert_message
from agents.intake.graph import run_intake

logger = structlog.get_logger(__name__)

app = FastAPI(title="FamApp", version="0.1.0")


# ── Twilio signature validation ───────────────────────────────────────────────

def _validate_twilio_signature(request: Request, form_data: dict) -> bool:
    """Validate that the request genuinely comes from Twilio."""
    s = get_settings()
    if s.is_production:
        validator = RequestValidator(s.twilio_auth_token)
        signature = request.headers.get("X-Twilio-Signature", "")
        url = str(request.url)
        return validator.validate(url, form_data, signature)
    # In dev, skip validation
    return True


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "famapp"}


# ── WhatsApp incoming webhook ─────────────────────────────────────────────────

@app.post("/webhook/whatsapp", response_class=PlainTextResponse)
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    # Twilio form fields
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

    # Persist immediately so we don't lose the message
    record = MessageRecord(
        message_sid=msg.message_sid,
        from_number=msg.from_number,
        body=msg.body,
        status=MessageStatus.RECEIVED,
    )
    await upsert_message(record)

    # Process asynchronously so Twilio doesn't timeout (5 s limit)
    background_tasks.add_task(
        run_intake,
        message_sid=msg.message_sid,
        sender=msg.from_number,
        raw_text=msg.body,
    )

    # Twilio expects an empty 200 or TwiML – empty is fine for WhatsApp
    return PlainTextResponse("", status_code=200)
