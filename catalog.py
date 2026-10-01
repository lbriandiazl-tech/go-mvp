"""
Vaka — catálogo de regalos.

Cargado a mano por ahora (opciones genéricas por categoría). Cuando haya
comercios adheridos, se reemplaza por una tabla en la base: cada item ya
tiene los mismos campos que necesitaría una fila.

CATEGORIES mantiene el orden y los datos de presentación (ícono del sprite
del sitio y una línea descriptiva). CATALOG guarda los items.
"""

CATEGORIES = [
    ("Viajes y escapadas", "i-plane", "Pasajes, hoteles y fines de semana"),
    ("Gastronomía", "i-dine", "Restaurantes y experiencias para compartir"),
    ("Bienestar", "i-spa", "Spa, masajes y días de descanso"),
    ("Moda", "i-shirt", "Ropa, calzado y accesorios"),
    ("Deporte", "i-bike", "Equipamiento y actividades"),
    ("Espectáculos", "i-ticket", "Teatro, música en vivo y cine"),
    ("Supermercado", "i-cart", "Compras para la casa"),
    ("Hogar y deco", "i-plant", "Para renovar los espacios"),
    ("Libros", "i-book", "Librerías y lectura"),
    ("Tecnología y juegos", "i-gamepad", "Electrónica, consolas y juegos"),
    ("Vinos y cafés", "i-wine", "Bodegas, vinotecas y cafeterías"),
    ("Gift card", "i-card", "Para usar donde prefieras"),
]

CATALOG = {
    "Viajes y escapadas": [
        {"title": "Fin de semana en la costa", "description": "Dos noches para dos personas, con desayuno.", "price_from": 8000},
        {"title": "Escapada a Colonia", "description": "Una noche en posada del casco histórico, con cena.", "price_from": 5500},
        {"title": "Día de termas", "description": "Acceso de día completo a termas, con almuerzo.", "price_from": 3200},
        {"title": "Crédito para pasajes", "description": "Saldo para usar en pasajes aéreos o paquetes.", "price_from": 5000},
    ],
    "Gastronomía": [
        {"title": "Cena para dos", "description": "Menú de pasos en restaurante de autor.", "price_from": 4500},
        {"title": "Clase de cocina", "description": "Experiencia con chef, con cena incluida.", "price_from": 3800},
        {"title": "Parrilla para compartir", "description": "Gift card para parrillas tradicionales.", "price_from": 2500},
        {"title": "Brunch para dos", "description": "Brunch completo en cafetería de especialidad.", "price_from": 1800},
    ],
    "Bienestar": [
        {"title": "Día de spa", "description": "Circuito de aguas y masaje relajante.", "price_from": 3500},
        {"title": "Masaje descontracturante", "description": "Sesión de 60 minutos.", "price_from": 1800},
        {"title": "Pase de yoga o pilates", "description": "Un mes de clases.", "price_from": 2500},
    ],
    "Moda": [
        {"title": "Gift card de indumentaria", "description": "Para elegir ropa en la tienda que prefieras.", "price_from": 2000},
        {"title": "Calzado a elección", "description": "Gift card para zapaterías y tiendas deportivas.", "price_from": 3500},
        {"title": "Accesorios y carteras", "description": "Gift card para marroquinería y accesorios.", "price_from": 2500},
    ],
    "Deporte": [
        {"title": "Gift card deportiva", "description": "Indumentaria y equipamiento deportivo.", "price_from": 2500},
        {"title": "Bicicleta y accesorios", "description": "Crédito para bicicleterías.", "price_from": 5000},
        {"title": "Membresía de gimnasio", "description": "Cuota mensual o trimestral.", "price_from": 2200},
    ],
    "Espectáculos": [
        {"title": "Entradas para un show", "description": "Dos entradas para música en vivo.", "price_from": 2200},
        {"title": "Noche de teatro", "description": "Dos entradas para la obra que elijas.", "price_from": 1600},
        {"title": "Cine para dos", "description": "Dos entradas con combo incluido.", "price_from": 900},
    ],
    "Supermercado": [
        {"title": "Gift card de supermercado", "description": "Saldo para las compras de la casa.", "price_from": 2000},
        {"title": "Canasta gourmet", "description": "Selección de productos para regalar.", "price_from": 2800},
    ],
    "Hogar y deco": [
        {"title": "Gift card de hogar", "description": "Decoración, bazar y muebles.", "price_from": 2500},
        {"title": "Plantas y jardín", "description": "Gift card para viveros.", "price_from": 1500},
        {"title": "Electrodomésticos", "description": "Crédito para pequeños electrodomésticos.", "price_from": 4000},
    ],
    "Libros": [
        {"title": "Gift card de librería", "description": "Para elegir los libros que quieras.", "price_from": 1200},
        {"title": "Suscripción de lectura", "description": "Tres meses de libros seleccionados.", "price_from": 2400},
    ],
    "Tecnología y juegos": [
        {"title": "Gift card de tecnología", "description": "Electrónica, audio y accesorios.", "price_from": 3000},
        {"title": "Crédito para videojuegos", "description": "Saldo para consolas y tiendas digitales.", "price_from": 1500},
        {"title": "Auriculares", "description": "Crédito para audio y accesorios.", "price_from": 3500},
    ],
    "Vinos y cafés": [
        {"title": "Visita a bodega", "description": "Recorrido y degustación para dos.", "price_from": 3200},
        {"title": "Selección de vinos", "description": "Caja de vinos elegidos por sommelier.", "price_from": 2800},
        {"title": "Café de especialidad", "description": "Gift card para cafeterías.", "price_from": 1200},
    ],
    "Gift card": [
        {"title": "Gift card para usar donde quieras", "description": "El total de tu regalo, para usar libremente.", "price_from": 0},
    ],
}

_META = {name: {"icon": icon, "tagline": tagline} for name, icon, tagline in CATEGORIES}


def categories():
    return [dict(name=name, icon=icon, tagline=tagline, count=len(CATALOG.get(name, [])))
            for name, icon, tagline in CATEGORIES]


def category_meta(name):
    return _META.get(name, {"icon": "box", "tagline": ""})


def get_category(name):
    return CATALOG.get(name, [])


def get_item(category, title):
    for item in CATALOG.get(category, []):
        if item["title"] == title:
            return item
    return None
