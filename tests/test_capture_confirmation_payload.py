from core.capture_agent import CaptureResult


def test_capture_result_schema_defaults():
    result = CaptureResult()
    assert result.classification == "unknown"
    assert result.events == []
    assert result.tasks == []
