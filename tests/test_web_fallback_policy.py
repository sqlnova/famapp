from types import SimpleNamespace

from server import web


def test_allow_local_fallback_enabled_outside_production(monkeypatch):
    monkeypatch.setattr(web, "get_settings", lambda: SimpleNamespace(is_production=False))
    assert web._allow_local_fallback() is True


def test_allow_local_fallback_disabled_in_production(monkeypatch):
    monkeypatch.setattr(web, "get_settings", lambda: SimpleNamespace(is_production=True))
    assert web._allow_local_fallback() is False

