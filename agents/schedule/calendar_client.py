"""Google Calendar client using service account credentials."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from core.config import get_settings
from core.models import CalendarEvent

logger = structlog.get_logger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_service():
    s = get_settings()
    creds_path = s.resolve_google_credentials_path()
    credentials = service_account.Credentials.from_service_account_file(
        creds_path, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


def _to_utc_rfc3339(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _parse_event(raw: dict) -> CalendarEvent:
    """Parse a raw Google Calendar API event dict into a CalendarEvent."""
    start_raw = raw.get("start", {})
    end_raw = raw.get("end", {})

    def parse_dt(d: dict) -> datetime:
        if "dateTime" in d:
            return datetime.fromisoformat(d["dateTime"])
        # All-day event
        return datetime.fromisoformat(d["date"] + "T00:00:00+00:00")

    return CalendarEvent(
        id=raw.get("id"),
        title=raw.get("summary", "(sin título)"),
        start=parse_dt(start_raw),
        end=parse_dt(end_raw),
        location=raw.get("location"),
        description=raw.get("description"),
        attendees=[
            a["email"] for a in raw.get("attendees", []) if not a.get("self")
        ],
    )


# ── Public API ────────────────────────────────────────────────────────────────

def list_upcoming_events(
    days: int = 7,
    max_results: int = 20,
) -> List[CalendarEvent]:
    """Return upcoming events for the next `days` days."""
    s = get_settings()
    service = _get_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(days=days)

    try:
        result = (
            service.events()
            .list(
                calendarId=s.google_calendar_id,
                timeMin=_to_utc_rfc3339(now),
                timeMax=_to_utc_rfc3339(time_max),
                maxResults=max_results,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = [_parse_event(e) for e in result.get("items", [])]
        logger.info("calendar_events_fetched", count=len(events), days=days)
        return events
    except HttpError as e:
        logger.error("calendar_list_error", error=str(e))
        raise


def get_events_in_window(
    hours_ahead: int = 3,
) -> List[CalendarEvent]:
    """Return events starting in the next `hours_ahead` hours that have a location."""
    s = get_settings()
    service = _get_service()
    now = datetime.now(timezone.utc)
    time_max = now + timedelta(hours=hours_ahead)

    try:
        result = (
            service.events()
            .list(
                calendarId=s.google_calendar_id,
                timeMin=_to_utc_rfc3339(now),
                timeMax=_to_utc_rfc3339(time_max),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        events = [
            _parse_event(e)
            for e in result.get("items", [])
            if e.get("location")  # only events with a location
        ]
        logger.info("calendar_window_events", count=len(events), hours=hours_ahead)
        return events
    except HttpError as e:
        logger.error("calendar_window_error", error=str(e))
        raise


def create_event(event: CalendarEvent) -> CalendarEvent:
    """Create a new calendar event. Returns the created event with its ID."""
    s = get_settings()
    service = _get_service()

    body: dict = {
        "summary": event.title,
        "start": {"dateTime": _to_utc_rfc3339(event.start), "timeZone": "America/Argentina/Buenos_Aires"},
        "end":   {"dateTime": _to_utc_rfc3339(event.end),   "timeZone": "America/Argentina/Buenos_Aires"},
    }
    if event.location:
        body["location"] = event.location
    if event.description:
        body["description"] = event.description
    if event.attendees:
        body["attendees"] = [{"email": a} for a in event.attendees]

    try:
        created = service.events().insert(calendarId=s.google_calendar_id, body=body).execute()
        logger.info("calendar_event_created", title=event.title, id=created.get("id"))
        return _parse_event(created)
    except HttpError as e:
        logger.error("calendar_create_error", error=str(e))
        raise


def format_events_for_whatsapp(events: List[CalendarEvent]) -> str:
    """Format a list of events into a readable WhatsApp message."""
    if not events:
        return "No tenés eventos próximos en el calendario."

    lines = []
    for e in events:
        local_start = e.start.astimezone()
        date_str = local_start.strftime("%-d/%-m")
        time_str = local_start.strftime("%H:%M")
        line = f"• *{e.title}* – {date_str} a las {time_str}"
        if e.location:
            line += f"\n  📍 {e.location}"
        lines.append(line)

    return "📅 Próximos eventos:\n\n" + "\n\n".join(lines)
