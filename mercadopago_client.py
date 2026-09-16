"""
Vaka — integración con Mercado Pago (Checkout Pro).

Flujo:
1. El aportante elige "Pagar con Mercado Pago" -> create_preference() arma
   un link de pago (init_point) y lo mandamos a esa URL.
2. Paga ahí (en el sitio de Mercado Pago, no en el nuestro — nunca vemos
   ni tocamos datos de tarjeta).
3. Mercado Pago nos avisa por webhook que hubo un pago.
4. IMPORTANTE (recomendación oficial de MP): nunca confiamos en el
   contenido del webhook a ciegas. Usamos el payment_id que nos manda
   para volver a preguntarle a la API "¿este pago está realmente
   aprobado?" (get_payment) y recién ahí confirmamos en nuestra base.
   Esto evita que alguien falsifique un webhook y confirme un pago falso.

NOTA DE HONESTIDAD: este módulo se escribió siguiendo la documentación
oficial de Mercado Pago, pero no se pudo probar contra la API real en el
entorno donde se desarrolló (sin acceso a internet). Antes de confiar en
esto en producción, hay que probar el flujo completo al menos una vez
con las credenciales de prueba.
"""
import os
import requests

MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
MP_API_BASE = "https://api.mercadopago.com"


class MercadoPagoError(Exception):
    pass


def _headers():
    if not MP_ACCESS_TOKEN:
        raise MercadoPagoError(
            "Falta configurar MP_ACCESS_TOKEN en las variables de entorno."
        )
    return {
        "Authorization": f"Bearer {MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def create_preference(reference_code, title, amount, success_url, failure_url, pending_url, notification_url):
    """
    Crea una preferencia de pago en Mercado Pago y devuelve
    (preference_id, init_point) — init_point es la URL a la que hay
    que mandar al aportante para que pague.

    reference_code: nuestro código interno (VK-XXXXXX). Se manda como
    external_reference para poder identificar el aporte cuando llegue
    el webhook, sin depender de IDs internos de Mercado Pago.
    """
    payload = {
        "items": [
            {
                "title": title,
                "quantity": 1,
                "unit_price": float(amount),
                "currency_id": "UYU",
            }
        ],
        "external_reference": reference_code,
        "back_urls": {
            "success": success_url,
            "failure": failure_url,
            "pending": pending_url,
        },
        "auto_return": "approved",
        "notification_url": notification_url,
    }

    try:
        resp = requests.post(
            f"{MP_API_BASE}/checkout/preferences",
            json=payload,
            headers=_headers(),
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        raise MercadoPagoError(f"No se pudo conectar con Mercado Pago: {e}")

    if resp.status_code not in (200, 201):
        raise MercadoPagoError(
            f"Mercado Pago rechazó la creación de la preferencia "
            f"({resp.status_code}): {resp.text}"
        )
    data = resp.json()
    return data["id"], data["init_point"]


def get_payment(payment_id):
    """Consulta el estado real de un pago directamente en la API de MP
    (nunca confiar solo en lo que dice el webhook)."""
    try:
        resp = requests.get(
            f"{MP_API_BASE}/v1/payments/{payment_id}",
            headers=_headers(),
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        raise MercadoPagoError(f"No se pudo conectar con Mercado Pago: {e}")

    if resp.status_code != 200:
        raise MercadoPagoError(
            f"No se pudo consultar el pago {payment_id} ({resp.status_code}): {resp.text}"
        )
    return resp.json()


def is_configured():
    return bool(MP_ACCESS_TOKEN)
