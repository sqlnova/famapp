def normalize_items(entities: dict, text: str):
    """Make shopping extraction robust to LLM variability"""
    if not entities:
        entities = {}

    # Normalize common keys
    if "items" in entities and isinstance(entities["items"], list):
        items = entities["items"]
    elif "item" in entities:
        items = [entities["item"]]
    elif "product" in entities:
        items = [entities["product"]]
    else:
        # fallback: naive extraction from text
        items = [w for w in text.split() if len(w) > 3]

    # clean
    return [i.strip().lower() for i in items if i]


def log_shopping_debug(intent, entities, text):
    print("[SHOPPING DEBUG]")
    print("intent:", intent)
    print("entities:", entities)
    print("text:", text)
