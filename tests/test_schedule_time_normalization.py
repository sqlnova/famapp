from agents.schedule.nodes import _normalize_time_str


def test_normalize_time_str_accepts_whatsapp_variants():
    assert _normalize_time_str("7.30 am") == "07:30"
    assert _normalize_time_str("11.45") == "11:45"
    assert _normalize_time_str("12pm") == "12:00"
    assert _normalize_time_str("14hs") == "14:00"
    assert _normalize_time_str("17 hs") == "17:00"


def test_normalize_time_str_fallbacks_to_default():
    assert _normalize_time_str("31:99", default="09:00") == "09:00"
    assert _normalize_time_str(None, default="09:00") == "09:00"
