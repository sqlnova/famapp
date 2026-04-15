from core.privacy import mask_phone, redact_text_meta


def test_mask_phone_keeps_only_last_digits():
    assert mask_phone("whatsapp:+5491100000000").startswith("whatsapp:+")
    assert mask_phone("whatsapp:+5491100000000").endswith("0000")
    assert "*" in mask_phone("whatsapp:+5491100000000")


def test_mask_phone_handles_plain_numbers_and_empty():
    assert mask_phone("+14155238886").endswith("8886")
    assert mask_phone("") == ""


def test_redact_text_meta_only_exposes_length():
    assert redact_text_meta("hola mundo") == "len=10"
    assert redact_text_meta("") == "len=0"

