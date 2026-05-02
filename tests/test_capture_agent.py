from core.capture_agent import run_capture_agent


def test_capture_agent_extracts_event_and_tasks():
    text = "El viernes a las 18 cumple de Sofi en Kids Park. Comprar regalo y llevar medias."
    result = run_capture_agent(text, {"members": [{"name": "Sofi", "is_minor": True}]}, input_type="text")
    assert result.classification in {"event", "mixed"}
    assert any("Cumple" in e.title for e in result.events)
    titles = [t.title.lower() for t in result.tasks]
    assert any("comprar" in t for t in titles)
