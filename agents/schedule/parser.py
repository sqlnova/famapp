import re

DAYS_MAP = {
    "lunes": "MO",
    "martes": "TU",
    "miercoles": "WE",
    "miércoles": "WE",
    "jueves": "TH",
    "viernes": "FR"
}


def extract_names(text):
    parts = text.split(" y ")
    return [p.strip().title() for p in parts if p.strip()]


def parse_schedule_block(block: str):
    lines = [l.strip().lower() for l in block.split("\n") if l.strip()]

    names_line = lines[0]
    names = extract_names(names_line.split("colegio")[0])

    days = ["MO","TU","WE","TH","FR"] if "lunes a viernes" in block else []

    time_match = re.search(r"(\d{1,2}[.:]\d{2}).*(\d{1,2}[.:]\d{2})", block)
    start, end = None, None
    if time_match:
        start = time_match.group(1).replace(":", ".")
        end = time_match.group(2).replace(":", ".")

    dropoff = None
    pickup = None

    if "lleva" in block:
        m = re.search(r"lleva\s+(\w+)", block)
        if m:
            dropoff = m.group(1).title()

    if "busca" in block:
        m = re.search(r"busca\s+(\w+)", block)
        if m:
            pickup = m.group(1).title()

    return {
        "children": names,
        "days": days,
        "start": start,
        "end": end,
        "dropoff_by": dropoff,
        "pickup_by": pickup,
        "type": "school"
    }


def parse_full_schedule(text: str):
    blocks = text.split("\n\n")
    return [parse_schedule_block(b) for b in blocks if b.strip()]
