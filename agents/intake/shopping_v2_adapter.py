from agents.shopping.handler_v2 import handle_shopping_v2

async def handle_shopping(state: dict):
    try:
        result = handle_shopping_v2({
            "entities": state.get("entities", {}),
            "text": state.get("raw_text", "")
        })

        return {
            "response_text": result.get("response"),
            "route_to": "shopping"
        }

    except Exception as e:
        print("[SHOPPING FINAL ERROR]", str(e))
        return {
            "response_text": "Ocurrió un error procesando tu mensaje. Intentá de nuevo."
        }
