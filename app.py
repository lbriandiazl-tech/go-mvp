import hmac
import os
from datetime import datetime
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, abort, flash
import db
import catalog
import mercadopago_client
import resend_client

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-production")


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
    return render_template("site/demo_gift.html")


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

        if not (recipient_name and occasion and organizer_name and organizer_email
                and min_contribution > 0):
            flash("Completá todos los campos, incluido tu mail.")
            return render_template("create_gift.html")

        slug, token = db.create_gift(
            recipient_name, occasion, organizer_name, organizer_email,
            min_contribution,
        )

        if resend_client.is_configured():
            organizer_url = url_for("organizer_panel", slug=slug, token=token, _external=True)
            try:
                resend_client.send_organizer_link_email(organizer_email, f"{occasion} de {recipient_name}", organizer_url)
            except resend_client.ResendError:
                pass  # no bloqueamos la creación del regalo si el mail falla

        return redirect(url_for("organizer_panel", slug=slug, token=token))

    return render_template("create_gift.html")


@app.route("/recuperar", methods=["GET", "POST"])
def recover_access():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if email and resend_client.is_configured():
            gifts = db.get_gifts_by_organizer_email(email)
            if gifts:
                gifts_for_email = [
                    dict(
                        occasion=event_title(g),
                        organizer_url=url_for(
                            "organizer_panel", slug=g["slug"], token=g["organizer_token"], _external=True
                        ),
                    )
                    for g in gifts
                ]
                try:
                    resend_client.send_recovery_email(email, gifts_for_email)
                except resend_client.ResendError:
                    pass
        # Mismo mensaje exista o no el mail — así nadie puede usar este
        # formulario para averiguar si un mail organizó algo acá.
        return render_template("recover_sent.html")

    return render_template("recover.html", enabled=resend_client.is_configured())


# ---------------------------------------------------------------
# Página pública del regalo — la que se comparte por WhatsApp
# ---------------------------------------------------------------

@app.route("/g/<slug>", methods=["GET"])
def public_gift(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    total = db.confirmed_total(gift["id"])
    return render_template("public_gift.html", gift=gift, total=total)


@app.route("/g/<slug>/aportar", methods=["GET", "POST"])
def contribute(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    if gift["status"] != "open":
        return render_template("closed.html", gift=gift)

    suggested = db.suggested_amounts(gift["min_contribution"])
    mp_enabled = mercadopago_client.is_configured()

    def form(**extra):
        return render_template("contribute.html", gift=gift, mp_enabled=mp_enabled,
                               suggested=suggested, **extra)

    if request.method == "POST":
        contributor_name = request.form["contributor_name"].strip()
        try:
            amount = int(request.form["amount"])
        except (ValueError, KeyError):
            amount = 0
        payment_method = request.form.get("payment_method", "transfer")

        if not (contributor_name and amount > 0):
            flash("Ingresá tu nombre y un monto válido.")
            return form()

        if payment_method == "mercadopago" and mp_enabled:
            ref = db.create_contribution(gift["id"], contributor_name, amount, payment_method="mercadopago")
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

        if not transfer_enabled():
            flash("Por ahora no hay un medio de pago disponible. Probá de nuevo más tarde.")
            return form()

        ref = db.create_contribution(gift["id"], contributor_name, amount, payment_method="transfer")
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
    gift = db.get_gift_by_token(slug, token)
    if not gift:
        abort(404)
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
        "organizer_panel.html",
        gift=gift, contributions=contributions, total=total,
        token=token, share_url=share_url, whatsapp_message=whatsapp_message,
        recipient_url=recipient_url, recipient_whatsapp_message=recipient_whatsapp_message,
    )


@app.route("/organizador/<slug>/cerrar", methods=["POST"])
def close_collection(slug):
    token = request.args.get("token", "")
    gift = db.get_gift_by_token(slug, token)
    if not gift:
        abort(404)
    db.close_gift(gift["id"])
    return redirect(url_for("organizer_panel", slug=slug, token=token))


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
        return render_template("not_ready.html", gift=gift)

    contributors = db.confirmed_contributors(gift["id"])
    total = db.confirmed_total(gift["id"])
    contributors_line = format_contributors(contributors)
    return render_template(
        "recipient_experience.html",
        gift=gift, contributors_line=contributors_line, total=total,
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
        return render_template("not_ready.html", gift=gift)
    categoria = request.args.get("categoria", "")
    items = catalog.get_category(categoria)
    return render_template("catalog.html", gift=gift, categoria=categoria, items=items)


@app.route("/regalo/<slug>/elegir", methods=["POST"])
def catalog_select(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    categoria = request.form["categoria"]
    item_title = request.form["item_title"]
    item = catalog.get_item(categoria, item_title)
    if not item:
        abort(404)
    db.set_selected_item(gift["id"], categoria, item_title)
    return render_template("catalog_confirmed.html", gift=gift, categoria=categoria, item=item)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    app.run(host="0.0.0.0", port=port, debug=False)
