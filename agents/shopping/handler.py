from core.shopping_utils import normalize_items, log_shopping_debug


def handle_shopping(state: dict):
    """Robust shopping handler integrated with Intake"""
    try:
        intent = state.get("intent")
        entities = state.get("entities", {})
        text = state.get("text", "")

        log_shopping_debug(intent, entities, text)

        items = normalize_items(entities, text)

        if not items:
            return {"response": "No entendí qué querés agregar 🤔"}

        # TODO: replace with Supabase insert
        added = []
        for item in items:
            added.append(item)

        return {
            "response": f"Agregué: {', '.join(added)} 🛒"
        }

    except Exception as e:
        print("[SHOPPING ERROR]", str(e))
        return {
            "response": "Ocurrió un error procesando tu mensaje. Intentá de nuevo."
        }
