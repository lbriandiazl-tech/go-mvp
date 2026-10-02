"""
Vaka — envío de mails transaccionales vía Resend.

NOTA DE HONESTIDAD: igual que con Mercado Pago, este módulo se escribió
siguiendo la documentación oficial de Resend, pero no se pudo probar
contra la API real en el entorno donde se desarrolló (sin acceso a
internet). Antes de confiar en esto en producción, probar al menos un
envío real y confirmar que llega (revisar también la carpeta de spam
la primera vez).

Nota sobre el remitente: sin un dominio propio verificado en Resend,
solo se puede mandar desde su dominio de prueba (onboarding@resend.dev)
y puede que Resend limite a quién le llega en ese modo. Cuando Vaka
tenga su propio dominio, hay que verificarlo en Resend y cambiar
RESEND_FROM_EMAIL a algo como "Vaka <hola@vaka.com.uy>".
"""
import os
import requests

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_API_BASE = "https://api.resend.com"
FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "Vaka <onboarding@resend.dev>")


class ResendError(Exception):
    pass


def is_configured():
    return bool(RESEND_API_KEY)


REPLY_TO = os.environ.get("CONTACT_EMAIL", "hola@vaka.uy")


def send_email(to, subject, html, reply_to=None, text=None):
    if not RESEND_API_KEY:
        raise ResendError("Falta configurar RESEND_API_KEY en las variables de entorno.")

    payload = {
        "from": FROM_EMAIL,
        "to": [to] if isinstance(to, str) else to,
        "subject": subject,
        "html": html,
        "reply_to": reply_to or REPLY_TO,
    }
    if text:
        payload["text"] = text
    try:
        resp = requests.post(
            f"{RESEND_API_BASE}/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        raise ResendError(f"No se pudo conectar con Resend: {e}")

    if resp.status_code not in (200, 201):
        raise ResendError(f"Resend rechazó el envío ({resp.status_code}): {resp.text}")
    return resp.json()


# ---------------------------------------------------------------
# Los mails son deliberadamente simples: texto, como una carta, con
# links comunes y versión en texto plano. Los mails con mucho diseño
# (fondos de color, botones grandes, imágenes) son los que Gmail manda
# a "Promociones"; los que parecen escritos por una persona van a
# "Principal".
# ---------------------------------------------------------------

def _compose(lines):
    """lines: lista de párrafos. Un párrafo puede ser un str o una tupla
    (texto_del_link, url). Devuelve (html, texto_plano)."""
    html_parts, text_parts = [], []
    for line in lines:
        if isinstance(line, tuple):
            label, url = line
            html_parts.append(f'<p style="margin:0 0 16px;"><a href="{url}" style="color:#7A5A1E; font-weight:bold;">{label}</a></p>')
            text_parts.append(f"{label}: {url}")
        else:
            html_parts.append(f'<p style="margin:0 0 16px;">{line}</p>')
            text_parts.append(line.replace("<b>", "").replace("</b>", "").replace("<br>", "\n"))
    html_parts.append('<p style="margin:24px 0 0; color:#666666;">Vaka<br><a href="https://vaka.uy" style="color:#666666;">vaka.uy</a></p>')
    text_parts.append("Vaka\nvaka.uy")
    html = ('<div style="font-family:Arial,Helvetica,sans-serif; font-size:15px; line-height:1.55; color:#222222; max-width:560px;">'
            + "".join(html_parts) + "</div>")
    return html, "\n\n".join(text_parts)


def _send(to, subject, lines, reply_to=None):
    html, text = _compose(lines)
    return send_email(to, subject, html, reply_to=reply_to, text=text)


def _first(name):
    return (name or "").split(" ")[0]


def send_gift_created_email(to_email, organizer_name, gift_title, panel_url, share_url):
    return _send(to_email, f"Tu regalo: {gift_title}", [
        f"Hola {_first(organizer_name)}:",
        f"Ya está creado el regalo <b>{gift_title}</b>.",
        "Este es el link para compartir con el grupo, así cada persona se suma:",
        (share_url, share_url),
        "Y desde acá ves quiénes se sumaron y cerrás el regalo cuando quieras:",
        ("Ver mi regalo", panel_url),
        "Para volver más adelante, entrá a vaka.uy, tocá \"Mis regalos\" e ingresá con este email.",
    ])


def send_login_email(to_email, login_url):
    return _send(to_email, "Tu acceso a Vaka", [
        "Hola:",
        "Con este link ingresás a tus regalos en Vaka. Vale por una hora.",
        ("Ingresar a Vaka", login_url),
        "Si no pediste este acceso, podés ignorar este mensaje.",
    ])


def send_gift_chosen_emails(vaka_email, organizer_email, organizer_name, recipient_name, recipient_email,
                            gift_title, category, item_title, total):
    """Avisa a Vaka (para coordinar la entrega) y a quien organizó."""
    _send(vaka_email, f"Regalo elegido: {gift_title}", [
        f"<b>{recipient_name}</b> eligió <b>{item_title}</b> ({category}).",
        f"Total del regalo: ${total}<br>Contacto de quien recibe: {recipient_email}<br>Organiza: {organizer_name} ({organizer_email})",
    ], reply_to=recipient_email)
    if organizer_email:
        _send(organizer_email, f"{recipient_name} ya eligió su regalo", [
            f"Hola {_first(organizer_name)}:",
            f"{recipient_name} abrió el regalo de <b>{gift_title}</b> y eligió <b>{item_title}</b>.",
            "Nos encargamos de coordinar la entrega.",
        ])


# Compatibilidad con llamadas anteriores.
def send_organizer_link_email(to_email, gift_occasion, organizer_url):
    return _send(to_email, f"Tu regalo: {gift_occasion}", [
        f"Este es el link para administrar tu regalo <b>{gift_occasion}</b>:",
        ("Ver mi regalo", organizer_url),
    ])


def send_recovery_email(to_email, gifts):
    return _send(to_email, "Tus regalos en Vaka",
                 ["Estos son los regalos que organizaste:"] + [(g["occasion"], g["organizer_url"]) for g in gifts])
