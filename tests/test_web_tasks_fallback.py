from server import web


class _FakeQuery:
    def __init__(self, rows, inserts):
        self._rows = rows
        self._inserts = inserts
        self._agent = None
        self._status = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, key, value):
        if key == "agent":
            self._agent = value
        if key == "status":
            self._status = value
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload):
        self._inserts.append(payload)
        return self

    def execute(self):
        if self._inserts:
            return type("R", (), {"data": [self._inserts[-1]]})()
        data = [r for r in self._rows if (self._agent is None or r.get("agent") == self._agent)]
        if self._status is not None:
            data = [r for r in data if r.get("status") == self._status]
        return type("R", (), {"data": data})()


class _FakeClient:
    def __init__(self, rows, inserts):
        self.rows = rows
        self.inserts = inserts

    def table(self, _name):
        return _FakeQuery(self.rows, self.inserts)


def test_places_tasks_store_roundtrip(monkeypatch):
    rows = []
    inserts = []
    monkeypatch.setattr(web, "get_supabase", lambda: _FakeClient(rows, inserts))

    saved = web._save_place_to_tasks_store("Colegio", "Colegio Don Bosco", "Av 123", "school")
    assert saved["alias"] == "colegio"
    assert inserts[-1]["agent"] == "known_place"


def test_routines_tasks_store_list_dedup(monkeypatch):
    rows = [
        {
            "agent": "family_routine",
            "status": "done",
            "triggered_by": "id-1",
            "payload": {"title": "Colegio", "days": ["lun"], "children": ["Giuseppe"], "is_active": True},
        },
        {
            "agent": "family_routine",
            "status": "done",
            "triggered_by": "id-1",
            "payload": {"title": "Viejo", "days": [], "children": [], "is_active": True},
        },
    ]
    inserts = []
    monkeypatch.setattr(web, "get_supabase", lambda: _FakeClient(rows, inserts))

    out = web._list_routines_from_tasks_store()
    assert len(out) == 1
    assert out[0]["id"] == "id-1"
    assert out[0]["title"] == "Colegio"

