"""FastAPI app – Twilio WhatsApp webhook + health endpoints."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

import structlog
from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, status
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from twilio.request_validator import RequestValidator
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from core.config import get_settings
from core.models import IncomingWhatsAppMessage, MessageRecord, MessageStatus
from core.privacy import mask_phone, redact_text_meta
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
app.mount("/app/static", StaticFiles(directory="server/static"), name="static")
app.include_router(web_router)


@app.middleware("http")
async def enforce_https(request: Request, call_next):
    """Enforce HTTPS in production environments."""
    s = get_settings()
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").lower()
    is_https = request.url.scheme == "https" or "https" in forwarded_proto.split(",")
    host = request.headers.get("host", "")
    is_local = host.startswith("localhost") or host.startswith("127.0.0.1")
    if s.is_production and not is_https and not is_local:
        https_url = str(request.url).replace("http://", "https://", 1)
        if request.method in {"GET", "HEAD"}:
            return RedirectResponse(url=https_url, status_code=307)
        return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": "HTTPS required"})
    return await call_next(request)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses to reduce information leakage."""
    response = await call_next(request)
    # Prevent MIME sniffing
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Deny framing (clickjacking protection)
    response.headers["X-Frame-Options"] = "DENY"
    # Limit referrer information sent to third parties
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # Disable browser features not used by the app
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # CSP: allow scripts only from trusted CDNs and same-origin; block inline eval()
    # Note: Alpine.js requires 'unsafe-inline' for x-* directives; Tailwind CDN injects styles.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.tailwindcss.com; "
        "style-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self' https://*.supabase.co wss://*.supabase.co; "
        "frame-ancestors 'none';"
    )
    return response


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


@app.get("/", include_in_schema=False)
async def root() -> RedirectResponse:
    """Redirect root domain traffic to the web dashboard."""
    return RedirectResponse(url="/app/")


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

    logger.info(
        "whatsapp_received",
        sid=msg.message_sid,
        from_=mask_phone(msg.from_number),
        body_meta=redact_text_meta(msg.body),
    )

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
