"""Supabase client singleton."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from supabase import Client, create_client

from core.config import get_settings
from core.models import (
    FamilyMember,
    FamilyRoutine,
    KnownPlace,
    MessageRecord,
    MessageStatus,
    ShoppingItem,
)

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
    result = client.table("shopping_items").select("*").eq("done", False).order("added_at", desc=True).execute()
    return [ShoppingItem(**row) for row in result.data]


async def get_completed_shopping_items(limit: int = 50) -> List[ShoppingItem]:
    client = get_supabase()
    result = (
        client.table("shopping_items")
        .select("*")
        .eq("done", True)
        .order("done_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [ShoppingItem(**row) for row in result.data]


async def mark_shopping_item_done(item_id: UUID) -> None:
    client = get_supabase()
    client.table("shopping_items").update({"done": True, "done_at": datetime.utcnow().isoformat()}).eq("id", str(item_id)).execute()


async def mark_shopping_items_done_by_names(names: List[str]) -> int:
    """Mark items as done using a case-insensitive partial name match. Returns count updated."""
    client = get_supabase()
    total = 0
    for name in names:
        result = (
            client.table("shopping_items")
            .update({"done": True, "done_at": datetime.utcnow().isoformat()})
            .ilike("name", f"%{name.strip()}%")
            .eq("done", False)
            .execute()
        )
        total += len(result.data)
    return total


async def mark_all_pending_shopping_items_done() -> int:
    """Mark every pending shopping item as done. Returns count updated."""
    client = get_supabase()
    pending = client.table("shopping_items").select("id").eq("done", False).execute()
    if not pending.data:
        return 0
    result = (
        client.table("shopping_items")
        .update({"done": True, "done_at": datetime.utcnow().isoformat()})
        .eq("done", False)
        .execute()
    )
    return len(result.data)


# ── Family members ────────────────────────────────────────────────────────────

def get_family_members() -> List[FamilyMember]:
    """Return all registered family members."""
    client = get_supabase()
    result = client.table("family_members").select("*").order("created_at").execute()
    return [FamilyMember(**r) for r in result.data]


def get_minor_members() -> List[FamilyMember]:
    """Return family members marked as minors."""
    client = get_supabase()
    result = client.table("family_members").select("*").eq("is_minor", True).execute()
    return [FamilyMember(**r) for r in result.data]


def get_family_member_by_nickname(nickname: str) -> Optional[FamilyMember]:
    """Look up a family member by their nickname (case-insensitive)."""
    client = get_supabase()
    result = (
        client.table("family_members")
        .select("*")
        .ilike("nickname", nickname.strip())
        .limit(1)
        .execute()
    )
    return FamilyMember(**result.data[0]) if result.data else None


# ── Known places ──────────────────────────────────────────────────────────────

def get_known_places_dict() -> Dict[str, KnownPlace]:
    """Return {alias: KnownPlace} for fast lookup. Aliases are lowercase."""
    client = get_supabase()
    result = client.table("known_places").select("*").order("alias").execute()
    return {r["alias"].lower(): KnownPlace(**r) for r in result.data}


def get_all_known_places() -> List[KnownPlace]:
    """Return all known places ordered by alias."""
    client = get_supabase()
    result = client.table("known_places").select("*").order("alias").execute()
    return [KnownPlace(**r) for r in result.data]


def upsert_known_place(alias: str, name: str, address: str, place_type: str = "general") -> KnownPlace:
    """Insert or update a known place by alias."""
    client = get_supabase()
    result = client.table("known_places").upsert(
        {
            "alias": alias.lower().strip(),
            "name": name.strip(),
            "address": address.strip(),
            "place_type": (place_type or "general").strip().lower(),
        },
        on_conflict="alias",
    ).execute()
    return KnownPlace(**result.data[0])


def delete_known_place(alias: str) -> bool:
    """Delete a known place by alias. Returns True if a row was deleted."""
    client = get_supabase()
    result = client.table("known_places").delete().eq("alias", alias.lower().strip()).execute()
    return len(result.data) > 0


def resolve_place_address(location: str, places: Dict[str, KnownPlace]) -> str:
    """If location matches a known alias, return its address. Otherwise return as-is."""
    if not location:
        return location
    key = location.strip().lower()
    return places[key].address if key in places else location


# ── Routines ──────────────────────────────────────────────────────────────────

def list_family_routines() -> List[FamilyRoutine]:
    client = get_supabase()
    result = client.table("family_routines").select("*").order("created_at", desc=True).execute()
    return [FamilyRoutine(**r) for r in result.data]


def upsert_family_routine(payload: Dict[str, Any]) -> FamilyRoutine:
    client = get_supabase()
    result = client.table("family_routines").upsert(payload).execute()
    return FamilyRoutine(**result.data[0])
