"""Supabase client singleton."""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from supabase import Client, create_client

from core.config import get_settings
from core.models import MessageRecord, MessageStatus, ShoppingItem

logger = structlog.get_logger(__name__)


@lru_cache
def get_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)


# ── Messages ──────────────────────────────────────────────────────────────────

async def upsert_message(record: MessageRecord) -> MessageRecord:
    client = get_supabase()
    data = record.model_dump(mode="json", exclude_none=True)
    result = client.table("messages").upsert(data).execute()
    return MessageRecord(**result.data[0])


async def update_message_status(
    message_sid: str,
    status: MessageStatus,
    response: Optional[str] = None,
    intent: Optional[str] = None,
    entities: Optional[Dict[str, Any]] = None,
) -> None:
    client = get_supabase()
    payload: Dict[str, Any] = {"status": status.value}
    if response is not None:
        payload["response"] = response
    if intent is not None:
        payload["intent"] = intent
    if entities is not None:
        payload["entities"] = entities
    client.table("messages").update(payload).eq("message_sid", message_sid).execute()


# ── Shopping list ─────────────────────────────────────────────────────────────

async def add_shopping_item(item: ShoppingItem) -> ShoppingItem:
    client = get_supabase()
    data = item.model_dump(mode="json", exclude_none=True)
    result = client.table("shopping_items").insert(data).execute()
    return ShoppingItem(**result.data[0])


async def get_pending_shopping_items() -> List[ShoppingItem]:
    client = get_supabase()
    result = client.table("shopping_items").select("*").eq("done", False).execute()
    return [ShoppingItem(**row) for row in result.data]


async def mark_shopping_item_done(item_id: UUID) -> None:
    client = get_supabase()
    client.table("shopping_items").update({"done": True}).eq("id", str(item_id)).execute()


async def mark_shopping_items_done_by_names(names: List[str]) -> int:
    """Mark items as done using a case-insensitive partial name match. Returns count updated."""
    client = get_supabase()
    total = 0
    for name in names:
        result = (
            client.table("shopping_items")
            .update({"done": True})
            .ilike("name", f"%{name.strip()}%")
            .eq("done", False)
            .execute()
        )
        total += len(result.data)
    return total
