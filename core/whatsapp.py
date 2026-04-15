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


def broadcast_whatsapp_message(body: str, recipients: Optional[List[str]] = None) -> List[str]:
    """Send a message to multiple family members.  Returns list of SIDs."""
    s = get_settings()
    targets = recipients or s.phone_list
    sids: List[str] = []
    for to in targets:
        try:
            sid = send_whatsapp_message(to, body)
            sids.append(sid)
        except Exception:
            logger.exception("whatsapp_broadcast_error", to=mask_phone(to))
    return sids
