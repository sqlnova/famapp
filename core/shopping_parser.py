import re

SEPARATORS = [",", " y ", " e ", ";"]


def split_items(text: str):
    text = text.lower()
    for sep in SEPARATORS:
        text = text.replace(sep, ",")
    parts = [p.strip() for p in text.split(",")]
    return [p for p in parts if p]


def deduplicate(items: list[str]):
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def parse_items(text: str):
    items = split_items(text)
    items = deduplicate(items)
    return items
