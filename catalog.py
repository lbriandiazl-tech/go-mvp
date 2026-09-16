"""
Vaka — catálogo de experiencias.

Cargado a mano para el MVP (según lo definido: catálogo reducido,
curado). Cuando esto crezca, se reemplaza por una tabla en la base
con proveedores reales conectados — la estructura ya queda lista
para ese salto, cada item ya tiene los mismos campos que necesitaría
una fila de base de datos.
"""

CATALOG = {
    "Viajes": [
        {
            "title": "Fin de semana en Punta del Este",
            "description": "2 noches para dos personas en apart-hotel frente al mar.",
            "price_from": 8000,
            "icon": "viajes",
        },
        {
            "title": "Escapada a Colonia del Sacramento",
            "description": "Noche en posada boutique del casco histórico + cena.",
            "price_from": 5500,
            "icon": "viajes",
        },
        {
            "title": "Termas en Salto",
            "description": "Día completo de acceso a termas + almuerzo.",
            "price_from": 3200,
            "icon": "viajes",
        },
    ],
    "Indumentaria": [
        {
            "title": "Vale en tienda de ropa (a elección)",
            "description": "Para canjear en comercios adheridos de Montevideo.",
            "price_from": 2000,
            "icon": "indumentaria",
        },
        {
            "title": "Zapatillas a elección",
            "description": "Vale para canjear en tiendas deportivas asociadas.",
            "price_from": 3500,
            "icon": "indumentaria",
        },
    ],
    "Gastronomía": [
        {
            "title": "Cena para dos en restaurant de autor",
            "description": "Menú degustación en restaurante seleccionado de Montevideo.",
            "price_from": 4500,
            "icon": "gastronomia",
        },
        {
            "title": "Clase de cocina + cena",
            "description": "Experiencia gastronómica grupal con chef local.",
            "price_from": 3800,
            "icon": "gastronomia",
        },
        {
            "title": "Vale en parrilla tradicional",
            "description": "Para canjear en asadores asociados.",
            "price_from": 2500,
            "icon": "gastronomia",
        },
    ],
    "Espectáculos": [
        {
            "title": "Entradas para show en vivo",
            "description": "Dos entradas para el próximo show disponible en la cartelera.",
            "price_from": 2200,
            "icon": "espectaculos",
        },
        {
            "title": "Cine + snacks",
            "description": "Dos entradas de cine con combo incluido.",
            "price_from": 900,
            "icon": "espectaculos",
        },
    ],
}


def get_category(name):
    return CATALOG.get(name, [])


def get_item(category, title):
    for item in CATALOG.get(category, []):
        if item["title"] == title:
            return item
    return None
