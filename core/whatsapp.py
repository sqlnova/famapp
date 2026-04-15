"""Twilio WhatsApp wrapper – send and receive messages."""
from __future__ import annotations

from typing import List, Optional

import structlog
from twilio.rest import Client as TwilioClient

from core.config import get_settings
from core.privacy import mask_phone, redact_text_meta

logger = structlog.get_logger(__name__)

_client: Optional[TwilioClient] = None


def get_twilio_client() -> TwilioClient:
    global _client
    if _client is None:
        s = get_settings()
        _client = TwilioClient(s.twilio_account_sid, s.twilio_auth_token)
    return _client


def send_whatsapp_message(to: str, body: str) -> str:
    """Send a WhatsApp message.  Returns the Twilio message SID."""
    s = get_settings()
    client = get_twilio_client()

    # Ensure 'whatsapp:' prefix
    to_wa = to if to.startswith("whatsapp:") else f"whatsapp:{to}"
    from_wa = s.twilio_whatsapp_from

    msg = client.messages.create(body=body, from_=from_wa, to=to_wa)
    logger.info(
        "whatsapp_sent",
        to=mask_phone(to_wa),
        sid=msg.sid,
        status=msg.status,
        body_meta=redact_text_meta(body),
    )
    return msg.sid


def _get_broadcast_recipients() -> List[str]:
    """Return WhatsApp numbers for all adult family members from DB, falling back to config."""
    try:
        from core.supabase_client import get_family_members
        members = get_family_members()
        numbers = [m.whatsapp_number for m in members if not m.is_minor and m.whatsapp_number]
        if numbers:
            return numbers
    except Exception:
        logger.warning("whatsapp_broadcast_db_fallback")
    return get_settings().phone_list


def broadcast_whatsapp_message(body: str, recipients: Optional[List[str]] = None) -> List[str]:
    """Send a message to multiple family members.  Returns list of SIDs.

    If recipients is None, sends to all adult members in the family_members DB
    (falls back to FAMILY_PHONE_NUMBERS env var if the DB is unavailable).
    """
    targets = recipients if recipients is not None else _get_broadcast_recipients()
    sids: List[str] = []
    for to in targets:
        try:
            sid = send_whatsapp_message(to, body)
            sids.append(sid)
        except Exception:
            logger.exception("whatsapp_broadcast_error", to=mask_phone(to))
    return sids
