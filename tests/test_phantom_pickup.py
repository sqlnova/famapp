"""Tests para la red de seguridad que descarta Retirar fantasmas del LLM."""
from agents.schedule.nodes import _drop_phantom_pickup


def test_drops_pickup_when_right_after_dropoff_and_no_range():
    events = [
        {"title": "Llevar Gaetano al partido", "time": "10:00", "duration_minutes": 15},
        {"title": "Retirar Gaetano del partido", "time": "10:15", "duration_minutes": 15},
    ]
    result = _drop_phantom_pickup(events, "Agenda partido de Gaetano mañana a las 10 am")
    assert len(result) == 1
    assert result[0]["title"].startswith("Llevar")


def test_keeps_pickup_when_user_gave_range():
    events = [
        {"title": "Llevar Joaquina al fútbol", "time": "10:00", "duration_minutes": 15},
        {"title": "Buscar Joaquina del fútbol", "time": "12:00", "duration_minutes": 15},
    ]
    raw = "Joaquina fútbol de 10 a 12 sábado"
    result = _drop_phantom_pickup(events, raw)
    assert len(result) == 2


def test_keeps_pickup_when_spaced_enough():
    events = [
        {"title": "Llevar Isabella al colegio", "time": "08:30", "duration_minutes": 15},
        {"title": "Retirar Isabella del colegio", "time": "11:45", "duration_minutes": 15},
    ]
    result = _drop_phantom_pickup(events, "Isabella colegio 8:30 lleva mamá")
    assert len(result) == 2


def test_returns_input_when_single_event():
    events = [{"title": "Llevar Gaetano al partido", "time": "10:00", "duration_minutes": 15}]
    assert _drop_phantom_pickup(events, "algo") == events


def test_returns_input_when_empty():
    assert _drop_phantom_pickup([], "algo") == []
