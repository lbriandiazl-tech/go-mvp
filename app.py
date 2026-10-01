import hmac
import os
from datetime import datetime
from urllib.parse import quote
from datetime import timedelta
from flask import Flask, render_template, request, redirect, url_for, abort, flash, session
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import db
import catalog
import mercadopago_client
import resend_client

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-production")
app.permanent_session_lifetime = timedelta(days=90)
app.config.update(SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
_login_signer = URLSafeTimedSerializer(app.secret_key, salt="vaka-login")
LOGIN_LINK_MAX_AGE = 60 * 60  # 1 hora


# ---------------------------------------------------------------
# Cuentas sin contraseña: se entra con un link que llega por mail.
#   session["email"] -> mail verificado (ve todos sus regalos)
#   session["gifts"] -> regalos creados en este navegador
# ---------------------------------------------------------------

def current_email():
    return session.get("email")


def remember_gift(slug):
    gifts = list(session.get("gifts", []))
    if slug not in gifts:
        gifts.insert(0, slug)
    session["gifts"] = gifts[:20]
    session.permanent = True


def can_manage(gift):
    if not gift:
        return False
    email = current_email()
    if email and email == (gift["organizer_email"] or "").lower():
        return True
    return gift["slug"] in session.get("gifts", [])


def login_link(email, next_url=None):
    token = _login_signer.dumps({"e": email, "n": next_url or ""})
    return url_for("login_verify", t=token, _external=True)


app.jinja_env.globals["current_email"] = current_email


def event_title(gift):
    """Combina la ocasión con el nombre del homenajeado, sin depender
    de que el organizador se haya acordado de escribirlo completo en
    '¿Qué se festeja?'. 'Cumpleaños' + 'Sofía' -> 'Cumpleaños de Sofía'."""
    return f"{gift['occasion']} de {gift['recipient_name']}"


app.jinja_env.globals["event_title"] = event_title


# ---------------------------------------------------------------
# Custodia: toda la plata entra a cuentas de Vaka, no del organizador.
#   VAKA_BANK_DETAILS -> datos de la cuenta bancaria de Vaka (se muestran
#                        a quien elige transferencia). Sin esta variable,
#                        la opción de transferencia no aparece.
#   ADMIN_TOKEN       -> clave del panel /admin, donde Vaka confirma
#                        transferencias y marca experiencias entregadas.
#                        Sin esta variable, /admin no existe (404).
# ---------------------------------------------------------------

def vaka_bank_details():
    return os.environ.get("VAKA_BANK_DETAILS", "").strip()


def transfer_enabled():
    return bool(vaka_bank_details())


def _is_admin(token):
    expected = os.environ.get("ADMIN_TOKEN", "")
    return bool(expected) and hmac.compare_digest(token or "", expected)


def fmt_money(n):
    return "{:,}".format(int(n or 0)).replace(",", ".")


def fmt_date(iso):
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m %H:%M")
    except ValueError:
        return iso


app.jinja_env.globals["transfer_enabled"] = transfer_enabled
app.jinja_env.filters["money"] = fmt_money
app.jinja_env.filters["fdate"] = fmt_date

_DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
_MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "setiembre", "octubre", "noviembre", "diciembre"]


def fmt_long_date(iso):
    """'2026-10-09' -> 'viernes 9 de octubre'."""
    try:
        d = datetime.strptime((iso or "")[:10], "%Y-%m-%d")
    except ValueError:
        return ""
    return f"{_DIAS[d.weekday()]} {d.day} de {_MESES[d.month - 1]}"


app.jinja_env.filters["fecha"] = fmt_long_date

with app.app_context():
    db.init_db()


# ---------------------------------------------------------------
# Crear un regalo
# ---------------------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return render_template("site/home.html")


# ---------------------------------------------------------------
# Sitio institucional
# ---------------------------------------------------------------

CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "hola@vaka.uy")
app.jinja_env.globals["CONTACT_EMAIL"] = CONTACT_EMAIL


@app.route("/como-funciona")
def page_how():
    return render_template("site/how.html")


@app.route("/demo/grupo")
def demo_group():
    return render_template("site/demo_group.html")


@app.route("/demo/regalo")
def demo_gift():
    return render_template("site/demo_gift.html", categories=catalog.categories())


@app.route("/ocasiones")
def page_occasions():
    return render_template("site/occasions.html")


@app.route("/empresas", methods=["GET", "POST"])
def page_business():
    sent, error = handle_contact_form("Empresas")
    return render_template("site/business.html", sent=sent, error=error)


@app.route("/comercios", methods=["GET", "POST"])
def page_merchants():
    sent, error = handle_contact_form("Comercios")
    return render_template("site/merchants.html", sent=sent, error=error)


@app.route("/nosotros")
def page_about():
    return render_template("site/about.html")


@app.route("/terminos")
def page_terms():
    return render_template("site/terms.html")


@app.route("/privacidad")
def page_privacy():
    return render_template("site/privacy.html")


def handle_contact_form(default_topic):
    """Procesa los formularios de contacto del sitio (ayuda, empresas,
    comercios) y los reenvía por mail a CONTACT_EMAIL vía Resend."""
    if request.method != "POST":
        return False, None
    if request.form.get("website"):  # honeypot anti-spam
        return True, None
    name = request.form.get("name", "").strip()[:120]
    email = request.form.get("email", "").strip()[:200]
    company = request.form.get("company", "").strip()[:160]
    topic = (request.form.get("topic", "").strip() or default_topic)[:60]
    message = request.form.get("message", "").strip()[:4000]
    if not (name and "@" in email and message):
        return False, "Completá tu nombre, tu email y el mensaje."
    if not resend_client.is_configured():
        return False, f"El formulario no está disponible en este momento. Escribinos a {CONTACT_EMAIL}."
    from html import escape
    html = (f"<p><b>{escape(name)}</b> &lt;{escape(email)}&gt;</p>"
            + (f"<p>Empresa: {escape(company)}</p>" if company else "")
            + f"<p>Tema: {escape(topic)}</p><p>{escape(message).replace(chr(10), '<br>')}</p>")
    try:
        resend_client.send_email(CONTACT_EMAIL, f"[Web · {topic}] {name}", html, reply_to=email)
    except resend_client.ResendError:
        return False, f"No pudimos enviar el mensaje. Escribinos a {CONTACT_EMAIL}."
    return True, None


SITE_URL = os.environ.get("SITE_URL", "https://vaka.uy").rstrip("/")
app.jinja_env.globals["SITE_URL"] = SITE_URL
SITEMAP_ENDPOINTS = ["home", "page_how", "demo_group", "demo_gift", "page_occasions",
                     "page_business", "page_merchants", "page_help", "page_about",
                     "create_gift", "page_terms", "page_privacy"]


@app.route("/robots.txt")
def robots_txt():
    body = ("User-agent: *\n"
            "Disallow: /admin\n"
            "Disallow: /organizador/\n"
            "Disallow: /g/\n"
            "Disallow: /regalo/\n"
            "Disallow: /webhooks/\n"
            f"Sitemap: {SITE_URL}/sitemap.xml\n")
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


@app.route("/sitemap.xml")
def sitemap_xml():
    urls = "".join(f"<url><loc>{SITE_URL}{url_for(e)}</loc></url>" for e in SITEMAP_ENDPOINTS)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + '</urlset>')
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


@app.route("/ayuda", methods=["GET", "POST"])
def page_help():
    sent, error = handle_contact_form("Consulta")
    return render_template("site/help.html", sent=sent, error=error)


@app.route("/crear", methods=["GET", "POST"])
def create_gift():
    if request.method == "POST":
        recipient_name = request.form["recipient_name"].strip()
        occasion = request.form["occasion"].strip()
        organizer_name = request.form["organizer_name"].strip()
        organizer_email = request.form.get("organizer_email", "").strip().lower()
        try:
            min_contribution = int(request.form["min_contribution"])
        except (ValueError, KeyError):
            min_contribution = 0

        closes_on = request.form.get("closes_on", "").strip()[:10]
        if closes_on and not fmt_long_date(closes_on):
            closes_on = ""

        if not (recipient_name and occasion and organizer_name and organizer_email
                and min_contribution > 0):
            flash("Completá todos los campos, incluido tu mail.")
            return render_template("site/create.html")

        slug, token = db.create_gift(
            recipient_name, occasion, organizer_name, organizer_email,
            min_contribution, closes_on=closes_on,
        )
        remember_gift(slug)

        if resend_client.is_configured():
            panel_url = login_link(organizer_email, url_for("organizer_panel", slug=slug))
            try:
                resend_client.send_gift_created_email(
                    organizer_email, organizer_name, f"{occasion} de {recipient_name}",
                    panel_url, url_for("public_gift", slug=slug, _external=True))
            except resend_client.ResendError:
                pass  # no bloqueamos la creación del regalo si el mail falla

        return redirect(url_for("organizer_panel", slug=slug, nuevo=1))

    return render_template("site/create.html")


@app.route("/entrar", methods=["GET", "POST"])
def recover_access():
    """Mis regalos / ingresar: se pide el mail y se envía un link de acceso."""
    if current_email() and request.method == "GET":
        return redirect(url_for("my_gifts"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if "@" in email and resend_client.is_configured():
            try:
                resend_client.send_login_email(email, login_link(email, request.form.get("next") or None))
            except resend_client.ResendError:
                pass
        # Mismo mensaje exista o no la cuenta.
        return render_template("site/login_sent.html", email=email)
    return render_template("site/login.html", enabled=resend_client.is_configured(),
                           next=request.args.get("next", ""))


@app.route("/recuperar")
def recover_legacy():
    return redirect(url_for("recover_access"), 301)


@app.route("/entrar/verificar")
def login_verify():
    try:
        data = _login_signer.loads(request.args.get("t", ""), max_age=LOGIN_LINK_MAX_AGE)
    except SignatureExpired:
        return render_template("site/login.html", enabled=resend_client.is_configured(), next="",
                               error="El link de acceso venció. Pedí uno nuevo.")
    except BadSignature:
        abort(404)
    session["email"] = data["e"]
    session.permanent = True
    nxt = data.get("n") or ""
    if not nxt.startswith("/"):
        nxt = url_for("my_gifts")
    return redirect(nxt)


@app.route("/mis-regalos")
def my_gifts():
    email = current_email()
    if not email:
        return redirect(url_for("recover_access"))
    gifts = [dict(g, total=db.confirmed_total(g["id"]),
                  count=len(db.confirmed_contributors(g["id"])))
             for g in db.get_gifts_by_organizer_email(email)]
    return render_template("site/my_gifts.html", gifts=gifts, email=email)


@app.route("/salir", methods=["POST"])
def logout():
    session.pop("email", None)
    session.pop("gifts", None)
    return redirect(url_for("home"))


# ---------------------------------------------------------------
# Página pública del regalo — la que se comparte por WhatsApp
# ---------------------------------------------------------------

@app.route("/g/<slug>", methods=["GET"])
def public_gift(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    total = db.confirmed_total(gift["id"])
    people = db.confirmed_contributors(gift["id"])
    return render_template("site/gift.html", gift=gift, total=total, people=people)


@app.route("/g/<slug>/aportar", methods=["GET", "POST"])
def contribute(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    if gift["status"] != "open":
        return render_template("site/gift.html", gift=gift, total=db.confirmed_total(gift["id"]), people=db.confirmed_contributors(gift["id"]))

    suggested = db.suggested_amounts(gift["min_contribution"])
    mp_enabled = mercadopago_client.is_configured()

    pay_enabled = mp_enabled or transfer_enabled()

    def form(**extra):
        return render_template("site/contribute.html", gift=gift, mp_enabled=mp_enabled,
                               pay_enabled=pay_enabled, suggested=suggested, **extra)

    if request.method == "POST":
        contributor_name = request.form.get("contributor_name", "").strip()[:80]
        contributor_email = request.form.get("contributor_email", "").strip().lower()[:200]
        message = request.form.get("message", "").strip()[:500]
        try:
            amount = int(request.form["amount"])
        except (ValueError, KeyError):
            amount = 0
        payment_method = request.form.get("payment_method", "transfer")

        if not (contributor_name and amount > 0):
            flash("Ingresá tu nombre y un monto válido.")
            return form()

        if not pay_enabled:
            # Sin procesador de pagos activo: se registra el aporte y se
            # completa el pago más adelante con el link que enviamos por mail.
            if "@" not in contributor_email:
                flash("Ingresá tu email para enviarte el link de pago.")
                return form()
            db.create_contribution(gift["id"], contributor_name, amount, payment_method="pledge",
                                   contributor_email=contributor_email, message=message)
            return render_template("site/contribute_done.html", gift=gift, amount=amount,
                                   name=contributor_name, email=contributor_email)

        if payment_method == "mercadopago" and mp_enabled:
            ref = db.create_contribution(gift["id"], contributor_name, amount, payment_method="mercadopago",
                                         contributor_email=contributor_email, message=message)
            contribution = db.get_contribution_by_reference(ref)
            try:
                pref_id, init_point = mercadopago_client.create_preference(
                    reference_code=ref,
                    title=f"Aporte para {event_title(gift)} (Vaka)",
                    amount=amount,
                    success_url=url_for("payment_result", slug=slug, result="success", _external=True),
                    failure_url=url_for("payment_result", slug=slug, result="failure", _external=True),
                    pending_url=url_for("payment_result", slug=slug, result="pending", _external=True),
                    notification_url=url_for("mercadopago_webhook", _external=True),
                )
                db.set_mp_preference(contribution["id"], pref_id)
                return redirect(init_point)
            except mercadopago_client.MercadoPagoError as e:
                if transfer_enabled():
                    flash(f"No se pudo iniciar el pago con Mercado Pago ({e}). Probá con transferencia bancaria.")
                else:
                    flash(f"No se pudo iniciar el pago con Mercado Pago ({e}). Probá de nuevo en unos minutos.")
                return form()

        ref = db.create_contribution(gift["id"], contributor_name, amount, payment_method="transfer",
                                     contributor_email=contributor_email, message=message)
        return render_template("contribute_instructions.html", gift=gift, amount=amount, ref=ref,
                               bank_details=vaka_bank_details())

    return form()


@app.route("/g/<slug>/pago/<result>", methods=["GET"])
def payment_result(slug, result):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    return render_template("payment_result.html", gift=gift, result=result)


@app.route("/webhooks/mercadopago", methods=["POST"])
def mercadopago_webhook():
    """Mercado Pago llama acá cuando cambia el estado de un pago.
    Por seguridad, NO confiamos en el contenido de esta notificación:
    volvemos a preguntarle a la API de MP el estado real del pago antes
    de confirmar nada en nuestra base."""
    payment_id = request.args.get("data.id") or (request.get_json(silent=True) or {}).get("data", {}).get("id")
    topic = request.args.get("type") or (request.get_json(silent=True) or {}).get("type")

    if topic != "payment" or not payment_id:
        return "", 200  # ignoramos otros tipos de notificación

    try:
        payment = mercadopago_client.get_payment(payment_id)
    except mercadopago_client.MercadoPagoError:
        # Devolvemos 200 igual: si le devolvemos error, MP reintenta
        # infinitamente. Mejor loguear y seguir (no tenemos logging
        # todavía — próximo paso).
        return "", 200

    if payment.get("status") == "approved":
        reference_code = payment.get("external_reference")
        if reference_code:
            db.confirm_contribution_by_mp(reference_code, payment_id)

    return "", 200


# ---------------------------------------------------------------
# Panel del organizador — ver estado (sin montos individuales), cerrar
# ---------------------------------------------------------------

@app.route("/organizador/<slug>", methods=["GET"])
def organizer_panel(slug):
    token = request.args.get("token", "")
    if token:
        # Links viejos con token: dan acceso y se redirige a la URL limpia.
        if db.get_gift_by_token(slug, token):
            remember_gift(slug)
            return redirect(url_for("organizer_panel", slug=slug))
        abort(404)
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    if not can_manage(gift):
        return redirect(url_for("recover_access", next=url_for("organizer_panel", slug=slug)))
    # Solo nombre, medio y estado: el monto individual NO sale del
    # servidor hacia el organizador (lo prometemos en la landing).
    contributions = [
        dict(contributor_name=c["contributor_name"], payment_method=c["payment_method"],
             status=c["status"])
        for c in db.list_contributions(gift["id"])
    ]
    total = db.confirmed_total(gift["id"])
    share_url = url_for("public_gift", slug=slug, _external=True)
    whatsapp_text = (
        f"¡Hola! Estoy juntando un regalo para {event_title(gift)}. "
        f"Sumate acá: {share_url}"
    )
    whatsapp_message = quote(whatsapp_text)

    recipient_url = url_for("recipient_experience", slug=slug, _external=True)
    recipient_whatsapp_text = (
        f"¡Feliz {gift['occasion']}! 🎁 Tenés un regalo esperándote, entrá acá para abrirlo: {recipient_url}"
    )
    recipient_whatsapp_message = quote(recipient_whatsapp_text)

    return render_template(
        "site/organizer.html",
        gift=gift, contributions=contributions, total=total,
        share_url=share_url, whatsapp_message=whatsapp_message, is_new=bool(request.args.get("nuevo")),
        recipient_url=recipient_url, recipient_whatsapp_message=recipient_whatsapp_message,
    )


@app.route("/organizador/<slug>/cerrar", methods=["POST"])
def close_collection(slug):
    gift = db.get_gift_by_slug(slug)
    if not can_manage(gift):
        abort(404)
    db.close_gift(gift["id"])
    return redirect(url_for("organizer_panel", slug=slug))


# ---------------------------------------------------------------
# Panel de Vaka (admin) — confirmar transferencias, entregar regalos
# ---------------------------------------------------------------

@app.route("/admin", methods=["GET"])
def admin_panel():
    token = request.args.get("token", "")
    if not _is_admin(token):
        abort(404)
    gifts = db.list_gifts_with_totals()
    return render_template(
        "admin.html",
        token=token,
        pending=db.list_pending_transfers(),
        pledges=db.list_pledges(),
        to_deliver=[g for g in gifts if g["status"] == "closed" and not g["delivered_at"]],
        gifts=gifts,
        stats=db.admin_stats(),
        transfer_ok=transfer_enabled(),
        mp_ok=mercadopago_client.is_configured(),
    )


@app.route("/admin/confirmar/<int:contribution_id>", methods=["POST"])
def admin_confirm_contribution(contribution_id):
    token = request.args.get("token", "")
    if not _is_admin(token):
        abort(404)
    contribution = db.get_contribution(contribution_id)
    if not contribution:
        abort(404)
    db.confirm_contribution(contribution_id)
    flash(f"Confirmado: {contribution['reference_code']} · ${fmt_money(contribution['amount'])}")
    return redirect(url_for("admin_panel", token=token))


@app.route("/admin/entregado/<int:gift_id>", methods=["POST"])
def admin_mark_delivered(gift_id):
    token = request.args.get("token", "")
    if not _is_admin(token):
        abort(404)
    db.mark_delivered(gift_id)
    flash("Regalo marcado como entregado.")
    return redirect(url_for("admin_panel", token=token))


# ---------------------------------------------------------------
# Experiencia del destinatario — la apertura del regalo
# ---------------------------------------------------------------

@app.route("/regalo/<slug>", methods=["GET"])
def recipient_experience(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    if gift["status"] != "closed":
        return render_template("site/recipient_wait.html", gift=gift)
    if gift["selected_item"]:
        item = catalog.get_item(gift["selected_category"], gift["selected_item"]) or \
            dict(title=gift["selected_item"], description="")
        return render_template("site/recipient_done.html", gift=gift, item=item,
                               categoria=gift["selected_category"])

    contributors = db.confirmed_contributors(gift["id"])
    return render_template(
        "site/recipient.html",
        gift=gift, contributors=contributors, total=db.confirmed_total(gift["id"]),
        messages=db.confirmed_messages(gift["id"]), categories=catalog.categories(),
    )


def format_contributors(names):
    if not names:
        return "tus amigos"
    if len(names) <= 3:
        if len(names) == 1:
            return names[0]
        return ", ".join(names[:-1]) + " y " + names[-1]
    first_three = ", ".join(names[:3])
    rest = len(names) - 3
    return f"{first_three} y {rest} persona{'s' if rest != 1 else ''} más"


@app.route("/regalo/<slug>/catalogo", methods=["GET"])
def catalog_view(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    if gift["status"] != "closed":
        return render_template("site/recipient_wait.html", gift=gift)
    categoria = request.args.get("categoria", "")
    items = catalog.get_category(categoria)
    if not items:
        return redirect(url_for("recipient_experience", slug=slug))
    return render_template("site/recipient_catalog.html", gift=gift, categoria=categoria, items=items,
                           meta=catalog.category_meta(categoria), total=db.confirmed_total(gift["id"]))


@app.route("/regalo/<slug>/elegir", methods=["POST"])
def catalog_select(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift or gift["status"] != "closed":
        abort(404)
    categoria = request.form.get("categoria", "")
    item_title = request.form.get("item_title", "")
    email = request.form.get("recipient_email", "").strip().lower()[:200]
    item = catalog.get_item(categoria, item_title)
    if not item:
        abort(404)
    if "@" not in email:
        flash("Ingresá tu email para coordinar la entrega.")
        return redirect(url_for("catalog_view", slug=slug, categoria=categoria))
    db.set_selected_item(gift["id"], categoria, item_title, recipient_email=email)
    if resend_client.is_configured():
        try:
            resend_client.send_gift_chosen_emails(
                vaka_email=CONTACT_EMAIL, organizer_email=gift["organizer_email"],
                organizer_name=gift["organizer_name"], recipient_name=gift["recipient_name"],
                recipient_email=email, gift_title=event_title(gift),
                category=categoria, item_title=item_title, total=fmt_money(db.confirmed_total(gift["id"])))
        except resend_client.ResendError:
            pass
    return render_template("site/recipient_done.html", gift=db.get_gift_by_slug(slug), item=item,
                           categoria=categoria)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
