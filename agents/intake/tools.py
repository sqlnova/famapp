"""Tools available to the Intake Agent."""
from __future__ import annotations

from typing import List

import structlog
from langchain_core.tools import tool

from core.supabase_client import (
    add_shopping_item,
    get_pending_shopping_items,
    mark_all_pending_shopping_items_done,
    mark_shopping_items_done_by_names,
)
from core.models import ShoppingItem

logger = structlog.get_logger(__name__)


@tool
async def add_item_to_shopping_list(name: str, quantity: str = "", unit: str = "", added_by: str = "") -> str:
    """Add an item to the family shopping list in Supabase.

    Args:
        name: Name of the product (e.g. "leche", "pan").
        quantity: Optional quantity (e.g. "2", "1 litro").
        unit: Optional unit of measure (e.g. "kg", "unidades").
        added_by: Phone number of the person who requested it.
    """
    item = ShoppingItem(name=name, quantity=quantity or None, unit=unit or None, added_by=added_by or None)
    await add_shopping_item(item)
    logger.info("shopping_item_added", item=name)
    return f"Agregué *{name}* a la lista. 🛒"


@tool
async def list_shopping_items() -> str:
    """Return all pending items in the family shopping list."""
    items = await get_pending_shopping_items()
    if not items:
        return "La lista de compras está vacía. 🎉"
    lines = []
    for i, item in enumerate(items, 1):
        line = f"{i}. {item.name}"
        if item.quantity:
            unit_str = f" {item.unit}" if item.unit else ""
            line += f" ({item.quantity}{unit_str})"
        lines.append(line)
    return "🛒 *Lista de compras:*\n" + "\n".join(lines)


@tool
async def mark_items_done(names: List[str]) -> str:
    """Mark one or more shopping items as purchased/done.

    Args:
        names: List of item names to mark as done (e.g. ["leche", "pan"]).
               Uses a case-insensitive partial match.
    """
    if not names:
        return "¿Qué ítem querés tachar de la lista?"
    count = await mark_shopping_items_done_by_names(names)
    done_str = ", ".join(f"*{n}*" for n in names)
    if count == 0:
        return f"No encontré {done_str} en la lista pendiente. ¿Ya estaba tachado?"
    return f"✅ Listo, tachê {done_str} de la lista."


@tool
async def mark_all_items_done() -> str:
    """Mark all pending shopping list items as purchased/done."""
    count = await mark_all_pending_shopping_items_done()
    if count == 0:
        return "La lista ya estaba vacía o todo ya estaba tachado. ✅"
    return f"✅ Listo, taché todos los items pendientes ({count})."
