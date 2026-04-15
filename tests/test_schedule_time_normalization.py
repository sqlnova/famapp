from agents.schedule.nodes import (
    _build_fallback_title,
    _canonicalize_responsible,
    _extract_time_range,
    _has_explicit_start_date,
    _minutes_between,
    _normalize_time_str,
)


def test_normalize_time_str_accepts_whatsapp_variants():
    assert _normalize_time_str("7.30 am") == "07:30"
    assert _normalize_time_str("11.45") == "11:45"
    assert _normalize_time_str("12pm") == "12:00"
    assert _normalize_time_str("14hs") == "14:00"
    assert _normalize_time_str("17 hs") == "17:00"


def test_normalize_time_str_fallbacks_to_default():
    assert _normalize_time_str("31:99", default="09:00") == "09:00"
    assert _normalize_time_str(None, default="09:00") == "09:00"


def test_fallback_title_is_intuitive_for_dropoff_and_pickup():
    raw = (
        "Giuseppe y Gaetano van al colegio de lunes a viernes, ingresan 7.30 am.\n"
        "Giuseppe y Gaetano salen del colegio 12pm, retira mamá."
    )
    assert _build_fallback_title(raw, "07:30", "Colegio Don Bosco", ["Giuseppe", "Gaetano"]).startswith("Llevar")
    assert _build_fallback_title(raw, "12:00", "Colegio Don Bosco", ["Giuseppe", "Gaetano"]).startswith("Buscar")


def test_has_explicit_start_date_detection():
    assert _has_explicit_start_date("desde el 2026-04-14")
    assert _has_explicit_start_date("arranca 14/04/26")
    assert not _has_explicit_start_date("de lunes a viernes")


def test_canonicalize_responsible_aliases():
    aliases = {"mama": "julieta", "papa": "mauro", "julieta": "julieta", "mauro": "mauro"}
    assert _canonicalize_responsible("mamá", aliases) == "julieta"
    assert _canonicalize_responsible("Papa", aliases) == "mauro"


def test_extract_time_range_handles_hs_and_dash_variants():
    assert _extract_time_range("Sábado 18 de abril de 14hs a 18hs") == ("14:00", "18:00")
    assert _extract_time_range("Evento 9:30-11:15 en el club") == ("09:30", "11:15")


def test_minutes_between_returns_positive_duration():
    assert _minutes_between("14:00", "18:00") == 240
    assert _minutes_between("18:00", "14:00") == 60
