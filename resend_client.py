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


def send_email(to, subject, html):
    if not RESEND_API_KEY:
        raise ResendError("Falta configurar RESEND_API_KEY en las variables de entorno.")

    try:
        resp = requests.post(
            f"{RESEND_API_BASE}/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": FROM_EMAIL,
                "to": [to] if isinstance(to, str) else to,
                "subject": subject,
                "html": html,
            },
            timeout=10,
        )
    except requests.exceptions.RequestException as e:
        raise ResendError(f"No se pudo conectar con Resend: {e}")

    if resp.status_code not in (200, 201):
        raise ResendError(f"Resend rechazó el envío ({resp.status_code}): {resp.text}")
    return resp.json()


def _email_wrapper(inner_html):
    """Envoltorio simple con la identidad de marca, para no repetir
    el mismo HTML en cada mail que mandemos."""
    return f"""
    <div style="font-family:sans-serif; background:#EFEAE0; padding:32px 16px;">
      <div style="max-width:480px; margin:0 auto; background:#101B26; padding:32px 24px; border-radius:4px;">
        <p style="text-align:center; color:#D8B872; letter-spacing:4px; font-size:12px; font-weight:700; margin:0 0 24px;">VAKA</p>
        {inner_html}
      </div>
    </div>
    """


def send_organizer_link_email(to_email, gift_occasion, organizer_url):
    subject = f"Tu link de organizador — {gift_occasion}"
    html = _email_wrapper(f"""
        <h1 style="color:#F4EFE4; font-size:20px; margin:0 0 12px;">Guardá este mail</h1>
        <p style="color:rgba(244,239,228,0.75); font-size:14px; line-height:1.6;">
          Este es el link para administrar tu colecta de "{gift_occasion}" —
          confirmar aportes, cerrarla, y todo lo demás. Es la única forma de
          volver a entrar, así que guardá este mail.
        </p>
        <a href="{organizer_url}" style="display:inline-block; margin-top:16px; background:#B98D34; color:#0A131C; padding:12px 24px; text-decoration:none; font-weight:700; border-radius:2px;">
          Ir a mi panel
        </a>
    """)
    return send_email(to_email, subject, html)


def send_recovery_email(to_email, gifts):
    """gifts: lista de dicts con 'occasion' y 'organizer_url'."""
    rows = "".join(
        f'<p style="margin:8px 0;"><a href="{g["organizer_url"]}" style="color:#D8B872;">{g["occasion"]}</a></p>'
        for g in gifts
    )
    subject = "Tus regalos en Vaka"
    html = _email_wrapper(f"""
        <h1 style="color:#F4EFE4; font-size:20px; margin:0 0 12px;">Acá están tus links</h1>
        <p style="color:rgba(244,239,228,0.75); font-size:14px; line-height:1.6; margin:0 0 16px;">
          Encontramos estos regalos organizados con este mail:
        </p>
        {rows}
    """)
    return send_email(to_email, subject, html)
