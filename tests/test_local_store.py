from pathlib import Path

from server import local_store


def test_local_store_places_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(local_store, "_STORE_PATH", tmp_path / "store.json")
    saved = local_store.save_place({"alias": "Colegio", "name": "Colegio Don Bosco", "address": "Av. 123", "type": "school"})
    assert saved["alias"] == "colegio"
    rows = local_store.list_places()
    assert len(rows) == 1
    assert rows[0]["address"] == "Av. 123"
    assert local_store.delete_place("colegio")
    assert local_store.list_places() == []


def test_local_store_routines_roundtrip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(local_store, "_STORE_PATH", tmp_path / "store.json")
    saved = local_store.save_routine(
        {
            "title": "Colegio",
            "days": ["lun", "mar"],
            "children": ["Giuseppe"],
            "outbound_time": "07:30",
            "return_time": "12:00",
            "outbound_responsible": "mauro",
            "return_responsible": "julieta",
            "place_name": "Colegio",
            "is_active": True,
        }
    )
    assert saved["id"]
    rows = local_store.list_routines()
    assert len(rows) == 1
    assert rows[0]["children"] == ["Giuseppe"]
