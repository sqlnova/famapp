from core.supabase_client import get_all_known_places

# Placeholder for family context (extend with DB later)

def get_family_roles():
    return {
        "julieta": "mother",
        "mauro": "father"
    }


def resolve_person(name: str):
    roles = get_family_roles()
    return roles.get(name.lower(), "unknown")


def get_place(alias: str):
    places = get_all_known_places()
    for p in places:
        if p.alias == alias:
            return p
    return None
