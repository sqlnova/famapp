"""Local JSON fallback storage for environments where DB writes fail."""
from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List
from uuid import uuid4

_LOCK = Lock()
_STORE_PATH = Path("server/.local_store.json")


def _read_store() -> Dict[str, Any]:
    if not _STORE_PATH.exists():
        return {"places": [], "routines": []}
    try:
        return json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"places": [], "routines": []}


def _write_store(data: Dict[str, Any]) -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_places() -> List[Dict[str, Any]]:
    with _LOCK:
        return _read_store().get("places", [])


def save_place(row: Dict[str, Any]) -> Dict[str, Any]:
    alias = (row.get("alias") or "").strip().lower()
    if not alias:
        raise ValueError("alias requerido")
    clean = {
        "alias": alias,
        "name": (row.get("name") or alias).strip(),
        "address": (row.get("address") or "").strip(),
        "type": (row.get("type") or "general").strip().lower() or "general",
    }
    with _LOCK:
        data = _read_store()
        places = data.get("places", [])
        places = [p for p in places if (p.get("alias") or "").strip().lower() != alias]
        places.append(clean)
        data["places"] = places
        _write_store(data)
    return clean


def delete_place(alias: str) -> bool:
    key = (alias or "").strip().lower()
    with _LOCK:
        data = _read_store()
        places = data.get("places", [])
        filtered = [p for p in places if (p.get("alias") or "").strip().lower() != key]
        changed = len(filtered) != len(places)
        data["places"] = filtered
        _write_store(data)
    return changed


def list_routines() -> List[Dict[str, Any]]:
    with _LOCK:
        return _read_store().get("routines", [])


def save_routine(row: Dict[str, Any]) -> Dict[str, Any]:
    rid = str(row.get("id") or uuid4())
    clean = {
        "id": rid,
        "title": (row.get("title") or "Nueva rutina").strip(),
        "days": row.get("days") or [],
        "children": row.get("children") or [],
        "outbound_time": row.get("outbound_time"),
        "return_time": row.get("return_time"),
        "outbound_responsible": row.get("outbound_responsible"),
        "return_responsible": row.get("return_responsible"),
        "place_alias": row.get("place_alias"),
        "place_name": row.get("place_name"),
        "is_active": bool(row.get("is_active", True)),
    }
    with _LOCK:
        data = _read_store()
        routines = data.get("routines", [])
        routines = [r for r in routines if str(r.get("id")) != rid]
        routines.append(clean)
        data["routines"] = routines
        _write_store(data)
    return clean
