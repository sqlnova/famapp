"""Shopping item categorization – keyword-based, no extra LLM call needed."""
from __future__ import annotations

# Ordered dict: first match wins. Keys are category names, values are keyword lists.
# Keywords are matched against the item name (lowercase, normalized).
_CATEGORY_KEYWORDS: list[tuple[str, list[str]]] = [
    ("Farmacia", [
        "aspirina", "ibuprofeno", "paracetamol", "medicamento", "remedio", "vitamina",
        "antihistaminico", "jarabe", "crema dental", "dentifrico", "hilo dental",
        "algodon", "alcohol en gel", "protector solar", "sunscreen", "anticonceptivo",
        "pastilla", "comprimido", "ampolla", "suero", "termometro", "curitas", "venda",
    ]),
    ("Higiene", [
        "shampoo", "champu", "acondicionador", "gel", "desodorante", "jabon de baño",
        "jabon liquido", "toallita", "panal", "pañal", "toalla femenina",
        "papel higienico", "rollo de papel", "servilleta", "pañuelo descartable",
        "maquillaje", "crema hidratante", "afeitadora",
    ]),
    ("Lácteos", [
        "leche", "yogur", "yogurt", "queso", "manteca", "crema de leche",
        "crema", "huevo", "huevos", "ricota", "dulce de leche", "creme fraiche",
        "queso crema", "muzarela", "mozzarella",
    ]),
    ("Frutas y Verduras", [
        "manzana", "naranja", "banana", "pera", "uva", "frutilla", "durazno",
        "ciruela", "mango", "kiwi", "limon", "pomelo", "mandarina",
        "tomate", "lechuga", "zanahoria", "papa", "cebolla", "ajo", "zapallo",
        "choclo", "pepino", "apio", "puerro", "acelga", "espinaca", "brocoli",
        "coliflor", "berenjena", "morrón", "morron", "remolacha", "nabo",
        "verdura", "fruta", "hongos", "champiñones",
    ]),
    ("Carnes", [
        "carne", "pollo", "pescado", "milanesa", "bife", "asado", "chorizo",
        "salchicha", "hamburguesa", "cerdo", "cordero", "lomo", "vacio",
        "matambre", "morcilla", "panceta", "salmon", "atun", "anchoa",
        "calamar", "langostino", "fiambre", "jamon", "salame", "mortadela",
    ]),
    ("Panadería", [
        "pan", "factura", "medialunas", "bizcocho", "tostadas", "pan rallado",
        "croissant", "baguette", "pan de molde", "pan lactal", "pan dulce",
        "galleta", "oblea",
    ]),
    ("Limpieza", [
        "detergente", "lavandina", "jabon en polvo", "suavizante", "limpiador",
        "desodorante de ambiente", "trapo", "esponja", "escoba", "trapeador",
        "bolsa de basura", "guantes", "desinfectante", "lustramuebles",
        "limpiavidrios", "sapolio", "ajax", "cif", "pinesol",
    ]),
    ("Bebidas", [
        "agua", "gaseosa", "jugo", "cerveza", "vino", "soda", "fernet",
        "whisky", "tonica", "agua mineral", "cola", "sprite", "fanta",
        "energy drink", "mate cocido",
    ]),
    ("Almacén", [
        "arroz", "aceite", "sal", "azucar", "harina", "pasta", "fideos",
        "legumbre", "lenteja", "garbanzo", "porotos", "conserva", "lata",
        "mermelada", "miel", "cafe", "te", "yerba", "mate", "galletita",
        "cacao", "chocolate", "maicena", "vinagre", "mayonesa", "ketchup",
        "mostaza", "salsa", "sardina", "atun en lata", "pure de tomate",
        "caldo", "dados", "especias", "pimienta", "oregano", "aji molido",
        "curcuma", "canela", "levadura", "polvo para hornear", "vainilla",
        "mantequilla de mani", "crema de cacahuate", "cereal", "avena",
        "granola", "snack", "papa frita",
    ]),
]

_DEFAULT_CATEGORY = "Otros"


def categorize_item(name: str) -> str:
    """Return the category that best matches a shopping item name.

    Uses simple keyword matching – no LLM call needed.
    Matching is case-insensitive and handles partial words.
    """
    if not name:
        return _DEFAULT_CATEGORY

    name_lower = name.lower().strip()
    # Remove common quantity words that might confuse matching
    for word in ("kilo", "kg", "gr", "litro", "lts", "pack", "caja", "docena"):
        name_lower = name_lower.replace(word, "")
    name_lower = name_lower.strip()

    for category, keywords in _CATEGORY_KEYWORDS:
        for kw in keywords:
            if kw in name_lower:
                return category

    return _DEFAULT_CATEGORY
