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
    Expense,
    FamilyMember,
    FamilyNote,
    FamilyRoutine,
    HomeworkTask,
    KnownPlace,
    MessageRecord,
    MessageStatus,
    PlanFeedback,
    PreferenceProfile,
    ShoppingItem,
    SupportNetworkMember,
)

logger = structlog.get_logger(__name__)


@lru_cache
def get_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)


# ── Messages ──────────────────────────────────────────────────────────────────

def get_recent_messages_from_sender(from_number: str, limit: int = 3) -> List[Dict[str, Any]]:
    """Return the last N messages from a given sender for conversation context."""
    client = get_supabase()
    result = (
        client.table("messages")
        .select("body, intent, response, created_at")
        .eq("from_number", from_number)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return list(reversed(result.data))  # chronological order


def get_family_member_by_phone(phone: str) -> Optional[FamilyMember]:
    """Look up a family member by their whatsapp number (with or without 'whatsapp:' prefix)."""
    client = get_supabase()
    normalized = phone if phone.startswith("whatsapp:") else f"whatsapp:{phone}"
    result = (
        client.table("family_members")
        .select("*")
        .eq("whatsapp_number", normalized)
        .limit(1)
        .execute()
    )
    return FamilyMember(**result.data[0]) if result.data else None


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


# ── Expenses ──────────────────────────────────────────────────────────────────

def add_expense(expense: Expense) -> Expense:
    client = get_supabase()
    data = expense.model_dump(mode="json", exclude_none=True)
    data.pop("id", None)
    data.pop("created_at", None)
    result = client.table("expenses").insert(data).execute()
    return Expense(**result.data[0])


def get_expenses(days: int = 30, paid_by: Optional[str] = None) -> List[Expense]:
    from datetime import date, timedelta
    client = get_supabase()
    since = (date.today() - timedelta(days=days)).isoformat()
    q = client.table("expenses").select("*").gte("expense_date", since).order("expense_date", desc=True)
    if paid_by:
        q = q.eq("paid_by", paid_by)
    result = q.execute()
    return [Expense(**r) for r in result.data]


# ── Homework ──────────────────────────────────────────────────────────────────

def add_homework_task(task: HomeworkTask) -> HomeworkTask:
    client = get_supabase()
    data = task.model_dump(mode="json", exclude_none=True)
    data.pop("id", None)
    data.pop("created_at", None)
    result = client.table("homework_tasks").insert(data).execute()
    return HomeworkTask(**result.data[0])


def get_pending_homework(child_name: Optional[str] = None) -> List[HomeworkTask]:
    client = get_supabase()
    q = client.table("homework_tasks").select("*").eq("done", False).order("due_date")
    if child_name:
        q = q.ilike("child_name", f"%{child_name.strip()}%")
    result = q.execute()
    return [HomeworkTask(**r) for r in result.data]


def mark_homework_done(task_id: str) -> None:
    client = get_supabase()
    client.table("homework_tasks").update({
        "done": True,
        "done_at": datetime.utcnow().isoformat(),
    }).eq("id", task_id).execute()


def get_due_tasks_today() -> List[Dict[str, Any]]:
    """Return tasks (family_task agent) that are due today and not done/cancelled."""
    from datetime import date
    client = get_supabase()
    today = date.today().isoformat()
    result = (
        client.table("tasks")
        .select("title, assignee, due_date, notes")
        .eq("agent", "family_task")
        .not_.in_("status", ["done", "cancelled"])
        .lte("due_date", today)
        .execute()
    )
    return result.data


# ── Family Memory ─────────────────────────────────────────────────────────────

def add_family_note(note: FamilyNote) -> FamilyNote:
    client = get_supabase()
    data = note.model_dump(mode="json", exclude_none=True)
    data.pop("id", None)
    data.pop("created_at", None)
    result = client.table("family_notes").insert(data).execute()
    return FamilyNote(**result.data[0])


def get_family_notes(subject: Optional[str] = None) -> List[FamilyNote]:
    client = get_supabase()
    q = client.table("family_notes").select("*").order("created_at", desc=True)
    if subject:
        q = q.ilike("subject", f"%{subject.strip()}%")
    result = q.execute()
    return [FamilyNote(**r) for r in result.data]


# ── Planner: Support Network ──────────────────────────────────────────────────

def list_support_members(only_active: bool = True) -> List[SupportNetworkMember]:
    client = get_supabase()
    q = client.table("support_network_members").select("*").order("created_at", desc=True)
    if only_active:
        q = q.eq("is_active", True)
    result = q.execute()
    return [SupportNetworkMember(**r) for r in result.data]


def upsert_support_member(payload: Dict[str, Any]) -> SupportNetworkMember:
    client = get_supabase()
    data = dict(payload)
    data["updated_at"] = datetime.utcnow().isoformat()
    result = client.table("support_network_members").upsert(
        data, on_conflict="nickname"
    ).execute()
    return SupportNetworkMember(**result.data[0])


def deactivate_support_member(member_id: str) -> None:
    client = get_supabase()
    client.table("support_network_members").update({
        "is_active": False,
        "updated_at": datetime.utcnow().isoformat(),
    }).eq("id", member_id).execute()


# ── Planner: Preference Profiles ──────────────────────────────────────────────

def list_preference_profiles() -> List[PreferenceProfile]:
    client = get_supabase()
    result = client.table("preference_profiles").select("*").execute()
    return [PreferenceProfile(**r) for r in result.data]


def upsert_preference_profile(
    *,
    member_nickname: str,
    place_alias: Optional[str],
    block_kind: Optional[str],
    weekday: Optional[int],
    score: float,
    sample_size: int,
) -> PreferenceProfile:
    client = get_supabase()
    payload = {
        "member_nickname": member_nickname,
        "place_alias": place_alias,
        "block_kind": block_kind,
        "weekday": weekday,
        "score": round(score, 3),
        "sample_size": sample_size,
        "last_updated": datetime.utcnow().isoformat(),
    }
    result = client.table("preference_profiles").upsert(
        payload, on_conflict="member_nickname,place_alias,block_kind,weekday"
    ).execute()
    return PreferenceProfile(**result.data[0])


# ── Planner: Feedback ─────────────────────────────────────────────────────────

def record_plan_feedback(
    *,
    plan_date: str,
    block_id: Optional[str],
    user_nickname: str,
    action: str,
    old_responsible: Optional[str] = None,
    new_responsible: Optional[str] = None,
    place_alias: Optional[str] = None,
    block_kind: Optional[str] = None,
    weekday: Optional[int] = None,
    delta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client = get_supabase()
    payload = {
        "plan_date": plan_date,
        "block_id": block_id,
        "user_nickname": user_nickname,
        "action": action,
        "old_responsible": old_responsible,
        "new_responsible": new_responsible,
        "place_alias": place_alias,
        "block_kind": block_kind,
        "weekday": weekday,
        "delta": delta or {},
    }
    result = client.table("plan_feedback").insert(payload).execute()
    return result.data[0]


def list_recent_plan_feedback(days: int = 90) -> List[Dict[str, Any]]:
    """Raw feedback rows para el agregador de preferencias."""
    from datetime import date, timedelta
    client = get_supabase()
    since = (date.today() - timedelta(days=days)).isoformat()
    result = (
        client.table("plan_feedback")
        .select("*")
        .gte("plan_date", since)
        .order("plan_date", desc=False)
        .execute()
    )
    return result.data
