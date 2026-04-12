"""Shopping Agent – manages the family shopping list.

Status: PARTIALLY IMPLEMENTED (basic add/list via Intake tools).

Responsibilities:
- Add items to shopping list (already wired through Intake)
- Mark items as purchased
- Smart grouping by store / category
- Proactive reminders when passing near a supermarket (future: geofencing)
- Weekly summary of frequent items
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from core.models import ShoppingItem
from core.supabase_client import (
    add_shopping_item,
    get_pending_shopping_items,
    mark_shopping_item_done,
)

logger = structlog.get_logger(__name__)


async def handle_shopping_request(
    sender: str,
    entities: Dict[str, Any],
    message_sid: str,
) -> Optional[str]:
    """Entry point called by Intake Agent when intent == 'shopping'."""
    items: List[Dict[str, Any]] = entities.get("items", [])

    if not items:
        return await get_shopping_summary()

    added: List[str] = []
    for item_data in items:
        item = ShoppingItem(
            name=item_data.get("name", ""),
            quantity=item_data.get("quantity") or None,
            unit=item_data.get("unit") or None,
            added_by=sender,
        )
        await add_shopping_item(item)
        added.append(item.name)

    names = ", ".join(added)
    return f"Agregué a la lista: {names}."


async def get_shopping_summary() -> str:
    """Return a formatted summary of pending shopping items."""
    items = await get_pending_shopping_items()
    if not items:
        return "La lista de compras está vacía."
    lines = []
    for i in items:
        qty = f" × {i.quantity}" if i.quantity else ""
        unit = f" {i.unit}" if i.unit else ""
        lines.append(f"• {i.name}{qty}{unit}")
    return "Lista de compras:\n" + "\n".join(lines)
