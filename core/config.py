"""Central configuration – reads from environment / .env file."""
from __future__ import annotations

import base64
import json
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────
    openai_api_key: str = Field(...)
    openai_model: str = Field("gpt-4o-mini")

    # ── Twilio / WhatsApp ─────────────────────────────────────────
    twilio_account_sid: str = Field(...)
    twilio_auth_token: str = Field(...)
    twilio_whatsapp_from: str = Field(...)
    # Stored as plain string; use .phone_list property to get a list
    family_phone_numbers: str = Field(
        default="",
        description="Comma-separated whatsapp:+XXXXXXXX numbers",
    )

    @property
    def phone_list(self) -> List[str]:
        return [p.strip() for p in self.family_phone_numbers.split(",") if p.strip()]

    # ── Supabase ──────────────────────────────────────────────────
    supabase_url: str = Field(...)
    supabase_service_role_key: str = Field(...)
    # Public anon key — safe to embed in the browser (used by the web UI)
    supabase_anon_key: Optional[str] = Field(None)

    # ── Google Calendar ───────────────────────────────────────────
    google_calendar_id: str = Field("primary")
    # File path (Codespace / local) – takes precedence if file exists
    google_credentials_json: str = Field("./credentials/google_credentials.json")
    google_token_json: str = Field("./credentials/google_token.json")
    # Base64-encoded JSON (Railway / CI) – used when file path doesn't exist
    google_credentials_b64: Optional[str] = Field(None)

    def resolve_google_credentials_path(self) -> str:
        """Return a path to the service-account JSON, creating a temp file if needed."""
        path = Path(self.google_credentials_json)
        if path.exists():
            return str(path)
        if self.google_credentials_b64:
            decoded = base64.b64decode(self.google_credentials_b64)
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
            tmp.write(decoded)
            tmp.flush()
            return tmp.name
        raise FileNotFoundError(
            "Google credentials not found. Set GOOGLE_CREDENTIALS_JSON path "
            "or GOOGLE_CREDENTIALS_B64 env var."
        )

    # ── Google Maps ───────────────────────────────────────────────
    google_maps_api_key: Optional[str] = Field(None)

    # ── Logistics ─────────────────────────────────────────────────
    home_address: str = Field(
        "Buenos Aires, Argentina",
        description="Origin address for travel-time calculations",
    )
    # How far ahead to look for calendar events (hours)
    logistics_lookahead_hours: int = Field(3)
    # Buffer added on top of travel time before sending alert (minutes)
    logistics_buffer_minutes: int = Field(15)
    # How often the proactive scheduler polls calendar (minutes)
    scheduler_interval_minutes: int = Field(15)

    # ── App ───────────────────────────────────────────────────────
    app_env: str = Field("development")
    log_level: str = Field("INFO")
    webhook_base_url: str = Field("http://localhost:8000")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
