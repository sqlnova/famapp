SHOPPING_KEYWORDS = [
    "comprar", "compra", "agrega", "agrega", "lista", "super", "supermercado",
    "leche", "yogurt", "pan", "huevos", "galletitas", "aceite", "banana", "bananas"
]

SCHEDULE_KEYWORDS = [
    "que tengo", "qué tengo", "agenda", "calendario", "mañana", "hoy", "evento", "eventos"
]


def detect_fallback_route(text: str) -> str | None:
    normalized = (text or "").strip().lower()

    if any(k in normalized for k in SHOPPING_KEYWORDS):
        return "shopping"

    if any(k in normalized for k in SCHEDULE_KEYWORDS):
        return "schedule"

    return None
