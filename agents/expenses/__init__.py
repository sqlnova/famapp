"""Expense tracking agent – register and query family expenses via WhatsApp."""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, Optional

import structlog

from core.models import Expense
from core.supabase_client import add_expense, get_expenses

logger = structlog.get_logger(__name__)

# Category keywords map for expense categorization
_EXPENSE_CATEGORIES: list[tuple[str, list[str]]] = [
    ("Supermercado", ["super", "supermercado", "almacen", "almacén", "carrefour", "dia", "coto", "jumbo", "disco", "vea"]),
    ("Farmacia",     ["farmacia", "farma", "medicamento", "remedio", "drogueria"]),
    ("Combustible",  ["nafta", "combustible", "gasoil", "gas", "shell", "ypf", "axion", "axión"]),
    ("Educación",    ["colegio", "escuela", "cuota", "universidad", "libreria", "librería", "útiles", "utiles"]),
    ("Salud",        ["medico", "médico", "doctor", "clinica", "clínica", "hospital", "turno", "consulta", "dentista"]),
    ("Servicios",    ["luz", "agua", "gas", "internet", "telefono", "teléfono", "expensas", "alquiler"]),
    ("Ropa",         ["ropa", "zapatilla", "zapatillas", "calzado", "indumentaria", "prenda"]),
    ("Ocio",         ["cine", "restaurante", "bar", "pizza", "comida", "delivery", "teatro", "parque"]),
    ("Transporte",   ["taxi", "uber", "remis", "colectivo", "subte", "tren", "peaje", "estacionamiento"]),
]


def _categorize_expense(description: str) -> str:
    desc = (description or "").lower()
    for category, keywords in _EXPENSE_CATEGORIES:
        if any(kw in desc for kw in keywords):
            return category
    return "General"


def _fmt_amount(amount: float) -> str:
    return f"${amount:,.0f}".replace(",", ".")


async def handle_expense_request(
    sender: str,
    sender_nickname: Optional[str],
    entities: Dict[str, Any],
) -> str:
    """Process an expense intent: record a new expense or summarize recent ones."""
    action = (entities.get("action") or "add").strip().lower()

    if action == "list":
        return await _list_expenses(entities)

    # ── Add expense ───────────────────────────────────────────────────────────
    description = (entities.get("description") or "").strip()
    amount_raw = entities.get("amount")
    try:
        amount = float(str(amount_raw).replace(",", ".").replace("$", "").strip())
    except (TypeError, ValueError):
        return "No pude entender el monto. Decime algo como: 'gasté $2500 en el súper'."

    if amount <= 0:
        return "El monto debe ser mayor a cero."

    category = entities.get("category") or _categorize_expense(description)
    paid_by = entities.get("paid_by") or sender_nickname
    expense_date = entities.get("date") or date.today().isoformat()

    expense = Expense(
        description=description or "Gasto sin descripción",
        amount=amount,
        category=category,
        paid_by=paid_by,
        expense_date=expense_date,
    )
    try:
        add_expense(expense)
        paid_note = f" (pagó *{paid_by}*)" if paid_by else ""
        logger.info("expense_added", amount=amount, category=category, paid_by=paid_by)
        return f"💸 Anotado: *{description}* — {_fmt_amount(amount)} · {category}{paid_note}"
    except Exception:
        logger.exception("expense_add_error")
        return "No pude guardar el gasto. Intentá de nuevo."


async def _list_expenses(entities: Dict[str, Any]) -> str:
    """Summarize recent expenses grouped by category."""
    try:
        expenses = get_expenses(days=30)
    except Exception:
        logger.exception("expense_list_error")
        return "No pude obtener el historial de gastos."

    if not expenses:
        return "No hay gastos registrados en los últimos 30 días."

    # Group by category
    by_category: Dict[str, float] = {}
    total = 0.0
    for e in expenses:
        by_category[e.category] = by_category.get(e.category, 0.0) + e.amount
        total += e.amount

    lines = ["💸 *Gastos últimos 30 días:*"]
    for cat, subtotal in sorted(by_category.items(), key=lambda x: -x[1]):
        lines.append(f"• {cat}: {_fmt_amount(subtotal)}")
    lines.append(f"\n*Total: {_fmt_amount(total)}*")
    return "\n".join(lines)
