"""Family memory agent – save and query persistent context notes via WhatsApp.

Examples:
  "Guardá que Gaetano no come mariscos"
  "El pediatra de los chicos es el Dr. Ruiz, 362-4123456"
  "¿Qué recordás de Giuseppe?"
  "¿Tenemos info sobre alergias?"
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import structlog

from core.models import FamilyNote
from core.supabase_client import add_family_note, get_family_notes

logger = structlog.get_logger(__name__)


async def handle_memory_request(
    sender: str,
    sender_nickname: Optional[str],
    entities: Dict[str, Any],
) -> str:
    """Save a family note or query existing ones."""
    action = (entities.get("action") or "save").strip().lower()

    if action == "query":
        return await _query_notes(entities)

    # ── Save note ─────────────────────────────────────────────────────────────
    subject = (entities.get("subject") or "general").strip().lower()
    note_text = (entities.get("note") or "").strip()

    if not note_text:
        return "¿Qué querés que recuerde? Decime algo como: 'Gaetano no come mariscos'."

    note = FamilyNote(
        subject=subject,
        note=note_text,
        added_by=sender_nickname or sender,
    )
    try:
        add_family_note(note)
        subject_label = f"sobre *{subject}*" if subject != "general" else ""
        logger.info("family_note_saved", subject=subject)
        return f"🧠 Guardado {subject_label}: {note_text}"
    except Exception:
        logger.exception("family_note_save_error")
        return "No pude guardar la nota. Intentá de nuevo."


async def _query_notes(entities: Dict[str, Any]) -> str:
    """Return family notes filtered by subject."""
    subject = (entities.get("subject") or "").strip().lower() or None
    try:
        notes = get_family_notes(subject)
    except Exception:
        return "No pude acceder a las notas."

    if not notes:
        who = f" sobre *{subject}*" if subject else ""
        return f"No tengo información guardada{who} todavía."

    # Group by subject
    by_subject: Dict[str, list] = {}
    for n in notes:
        by_subject.setdefault(n.subject, []).append(n.note)

    lines = ["🧠 *Lo que recuerdo:*"]
    for subj, subj_notes in sorted(by_subject.items()):
        lines.append(f"\n*{subj.capitalize()}*")
        for note in subj_notes:
            lines.append(f"  • {note}")
    return "\n".join(lines)
