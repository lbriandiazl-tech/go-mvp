import os
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, abort, flash
import db
import catalog
import mercadopago_client
import resend_client

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-in-production")

with app.app_context():
    db.init_db()


# ---------------------------------------------------------------
# Crear un regalo
# ---------------------------------------------------------------

@app.route("/", methods=["GET"])
def home():
    return render_template("home.html")


@app.route("/crear", methods=["GET", "POST"])
def create_gift():
    if request.method == "POST":
        recipient_name = request.form["recipient_name"].strip()
        occasion = request.form["occasion"].strip()
        organizer_name = request.form["organizer_name"].strip()
        organizer_email = request.form.get("organizer_email", "").strip().lower()
        bank_details = request.form.get("bank_details", "").strip()
        try:
            min_contribution = int(request.form["min_contribution"])
        except (ValueError, KeyError):
            min_contribution = 0

        if not (recipient_name and occasion and organizer_name and organizer_email
                and min_contribution > 0 and bank_details):
            flash("Completá todos los campos, incluidos tu mail y los datos bancarios.")
            return render_template("create_gift.html")

        slug, token = db.create_gift(
            recipient_name, occasion, organizer_name, organizer_email,
            min_contribution, bank_details,
        )

        if resend_client.is_configured():
            organizer_url = url_for("organizer_panel", slug=slug, token=token, _external=True)
            try:
                resend_client.send_organizer_link_email(organizer_email, occasion, organizer_url)
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
                        occasion=g["occasion"],
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

    if request.method == "POST":
        contributor_name = request.form["contributor_name"].strip()
        try:
            amount = int(request.form["amount"])
        except (ValueError, KeyError):
            amount = 0
        payment_method = request.form.get("payment_method", "transfer")

        if not (contributor_name and amount > 0):
            flash("Ingresá tu nombre y un monto válido.")
            return render_template("contribute.html", gift=gift, mp_enabled=mercadopago_client.is_configured(), suggested=suggested)

        if payment_method == "mercadopago" and mercadopago_client.is_configured():
            ref = db.create_contribution(gift["id"], contributor_name, amount, payment_method="mercadopago")
            contribution = db.get_contribution_by_reference(ref)
            try:
                pref_id, init_point = mercadopago_client.create_preference(
                    reference_code=ref,
                    title=f"Aporte para {gift['occasion']} (Vaka)",
                    amount=amount,
                    success_url=url_for("payment_result", slug=slug, result="success", _external=True),
                    failure_url=url_for("payment_result", slug=slug, result="failure", _external=True),
                    pending_url=url_for("payment_result", slug=slug, result="pending", _external=True),
                    notification_url=url_for("mercadopago_webhook", _external=True),
                )
                db.set_mp_preference(contribution["id"], pref_id)
                return redirect(init_point)
            except mercadopago_client.MercadoPagoError as e:
                flash(f"No se pudo iniciar el pago con Mercado Pago ({e}). Probá con transferencia bancaria.")
                return render_template("contribute.html", gift=gift, mp_enabled=mercadopago_client.is_configured(), suggested=suggested)

        ref = db.create_contribution(gift["id"], contributor_name, amount, payment_method="transfer")
        return render_template("contribute_instructions.html", gift=gift, amount=amount, ref=ref)

    return render_template("contribute.html", gift=gift, mp_enabled=mercadopago_client.is_configured(), suggested=suggested)


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
# Panel del organizador — validación manual, ver estado, cerrar
# ---------------------------------------------------------------

@app.route("/organizador/<slug>", methods=["GET"])
def organizer_panel(slug):
    token = request.args.get("token", "")
    gift = db.get_gift_by_token(slug, token)
    if not gift:
        abort(404)
    contributions = db.list_contributions(gift["id"])
    total = db.confirmed_total(gift["id"])
    share_url = url_for("public_gift", slug=slug, _external=True)
    whatsapp_text = (
        f"¡Hola! Estoy juntando un regalo para {gift['occasion']}. "
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


@app.route("/organizador/<slug>/validar/<int:contribution_id>", methods=["POST"])
def validate_contribution(slug, contribution_id):
    token = request.args.get("token", "")
    gift = db.get_gift_by_token(slug, token)
    if not gift:
        abort(404)
    contribution = db.get_contribution(contribution_id)
    if not contribution or contribution["gift_id"] != gift["id"]:
        abort(404)
    db.confirm_contribution(contribution_id)
    return redirect(url_for("organizer_panel", slug=slug, token=token))


@app.route("/organizador/<slug>/cerrar", methods=["POST"])
def close_collection(slug):
    token = request.args.get("token", "")
    gift = db.get_gift_by_token(slug, token)
    if not gift:
        abort(404)
    db.close_gift(gift["id"])
    return redirect(url_for("organizer_panel", slug=slug, token=token))


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
