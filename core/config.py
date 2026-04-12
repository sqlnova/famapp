"""Central configuration – reads from environment / .env file."""
from __future__ import annotations

from functools import lru_cache
from typing import List

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
    openai_api_key: str = Field(..., description="OpenAI API key")
    openai_model: str = Field("gpt-4o-mini", description="Default LLM model")

    # ── Twilio / WhatsApp ─────────────────────────────────────────
    twilio_account_sid: str = Field(...)
    twilio_auth_token: str = Field(...)
    twilio_whatsapp_from: str = Field(...)
    family_phone_numbers: List[str] = Field(
        default_factory=list,
        description="Comma-separated list of whatsapp:+XXXXXXXX numbers",
    )

    # ── Supabase ──────────────────────────────────────────────────
    supabase_url: str = Field(...)
    supabase_service_role_key: str = Field(...)

    # ── Google Calendar ───────────────────────────────────────────
    google_calendar_id: str = Field("primary")
    google_credentials_json: str = Field("./credentials/google_credentials.json")
    google_token_json: str = Field("./credentials/google_token.json")

    # ── Google Maps ───────────────────────────────────────────────
    google_maps_api_key: str = Field(...)

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
