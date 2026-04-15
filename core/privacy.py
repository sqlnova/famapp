"""Privacy helpers for safer logs and metadata handling."""
from __future__ import annotations


def mask_phone(value: str) -> str:
    """Mask phone-like values keeping only last 4 digits."""
    text = (value or "").strip()
    if not text:
        return ""
    prefix = "whatsapp:" if text.startswith("whatsapp:") else ""
    raw = text.replace("whatsapp:", "")
    digits = "".join(ch for ch in raw if ch.isdigit())
    if len(digits) <= 4:
        masked = "*" * len(digits)
    else:
        masked = f"{'*' * (len(digits) - 4)}{digits[-4:]}"
    return f"{prefix}+{masked}" if masked else f"{prefix}***"


def redact_text_meta(value: str) -> str:
    """Return non-sensitive metadata about a text payload."""
    text = (value or "").strip()
    if not text:
        return "len=0"
    return f"len={len(text)}"

