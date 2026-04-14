from core.shopping_utils import normalize_items
from core.shopping_parser import parse_items


def handle_shopping_v2(state: dict):
    try:
        entities = state.get("entities", {})
        text = state.get("text", "")

        # First try structured entities
        items = normalize_items(entities, text)

        # If only 1 item or weak result → re-parse full text
        if len(items) <= 1:
            parsed = parse_items(text)
            if parsed:
                items = parsed

        if not items:
            return {"response": "No entendí qué querés agregar 🤔"}

        # Deduplicated already via parser
        return {
            "response": f"Agregué: {', '.join(items)} 🛒"
        }

    except Exception as e:
        print("[SHOPPING V2 ERROR]", str(e))
        return {
            "response": "Ocurrió un error procesando tu mensaje. Intentá de nuevo."
        }
