from agents.shopping.handler import handle_shopping as robust_handler

async def handle_shopping(state: dict):
    try:
        result = robust_handler({
            "intent": state.get("intent"),
            "entities": state.get("entities", {}),
            "text": state.get("raw_text", "")
        })

        return {
            "response_text": result.get("response"),
            "route_to": "shopping"
        }

    except Exception as e:
        print("[INTAKE SHOPPING ERROR]", str(e))
        return {
            "response_text": "Ocurrió un error procesando tu mensaje. Intentá de nuevo.",
            "route_to": "error"
        }
