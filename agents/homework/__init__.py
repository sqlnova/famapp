"""Homework tracking agent – register and query children's school tasks via WhatsApp."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

import structlog

from core.models import HomeworkTask
from core.supabase_client import add_homework_task, get_pending_homework, mark_homework_done
from famapp.monitoring import send_event

logger = structlog.get_logger(__name__)

DAYS_ES = {
    "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
    "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo",
}


def _fmt_date(iso: str) -> str:
    try:
        d = date.fromisoformat(iso)
        today = date.today()
        delta = (d - today).days
        if delta == 0:
            return "hoy"
        if delta == 1:
            return "mañana"
        if delta < 0:
            return f"vencida ({iso})"
        day_name = DAYS_ES.get(d.strftime("%A"), d.strftime("%A"))
        return f"{day_name} {d.day}/{d.month}"
    except ValueError:
        return iso


async def handle_homework_request(
    sender: str,
    entities: Dict[str, Any],
) -> str:
    """Process a homework intent: add a task, list pending ones, or mark one as done."""
    action = (entities.get("action") or "add").strip().lower()
    await send_event("homework", "active", f"action={action}")

    try:
        if action == "list":
            result = await _list_homework(entities)
        elif action == "mark_done":
            result = await _mark_done(entities)
        else:
            result = await _add_homework(sender, entities)
    except Exception as exc:
        await send_event("homework", "error", f"homework failed: {exc}")
        raise
    await send_event("homework", "idle", f"action={action} done")
    return result


async def _add_homework(sender: str, entities: Dict[str, Any]) -> str:
    child_name = (entities.get("child_name") or "").strip()
    description = (entities.get("description") or "").strip()
    subject = (entities.get("subject") or "General").strip()
    due_date_raw = entities.get("due_date")

    if not child_name:
        return "¿Para qué chico es la tarea?"
    if not description:
        return "¿Cuál es la tarea?"
    if not due_date_raw:
        return "¿Para cuándo hay que entregarla?"

    try:
        due_date = str(date.fromisoformat(str(due_date_raw).strip()))
    except ValueError:
        return f"No entendí la fecha '{due_date_raw}'. Usá formato YYYY-MM-DD."

    task = HomeworkTask(
        child_name=child_name,
        subject=subject,
        description=description,
        due_date=due_date,
        added_by=sender,
    )
    try:
        add_homework_task(task)
        date_str = _fmt_date(due_date)
        logger.info("homework_added", child=child_name, subject=subject, due=due_date)
        return f"📚 Anotado para *{child_name}*: {description} ({subject}) — para el *{date_str}*"
    except Exception:
        logger.exception("homework_add_error")
        return "No pude guardar la tarea. Intentá de nuevo."


async def _list_homework(entities: Dict[str, Any]) -> str:
    """List pending homework, optionally filtered by child name."""
    child_name = (entities.get("child_name") or "").strip() or None
    try:
        tasks = get_pending_homework(child_name)
    except Exception:
        return "No pude obtener las tareas."

    if not tasks:
        who = f" de *{child_name}*" if child_name else ""
        return f"No hay tareas pendientes{who}. ✅"

    # Group by child
    by_child: Dict[str, list] = {}
    for t in tasks:
        by_child.setdefault(t.child_name, []).append(t)

    lines = ["📚 *Tareas pendientes:*"]
    for child, child_tasks in sorted(by_child.items()):
        lines.append(f"\n*{child}*")
        for t in sorted(child_tasks, key=lambda x: x.due_date):
            date_str = _fmt_date(t.due_date)
            lines.append(f"  • {t.description} ({t.subject}) — {date_str}")
    return "\n".join(lines)


async def _mark_done(entities: Dict[str, Any]) -> str:
    """Mark homework as done – searches by child name and description keywords."""
    child_name = (entities.get("child_name") or "").strip() or None
    description_kw = (entities.get("description") or "").strip().lower()
    try:
        tasks = get_pending_homework(child_name)
    except Exception:
        return "No pude acceder a las tareas."

    if not tasks:
        return "No hay tareas pendientes."

    # Match by description keyword (partial)
    matches = [
        t for t in tasks
        if not description_kw or description_kw in t.description.lower()
    ]
    if not matches:
        return f"No encontré ninguna tarea que coincida con '{description_kw}'."

    for t in matches:
        mark_homework_done(str(t.id))

    names = ", ".join(f"*{t.description}*" for t in matches[:3])
    extra = f" y {len(matches) - 3} más" if len(matches) > 3 else ""
    return f"✅ Marcada{' s' if len(matches) > 1 else ''} como entregada{' s' if len(matches) > 1 else ''}: {names}{extra}"
