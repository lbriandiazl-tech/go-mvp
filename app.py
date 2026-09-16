import os
from urllib.parse import quote
from flask import Flask, render_template, request, redirect, url_for, abort, flash
import db
import catalog

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
        try:
            goal_amount = int(request.form["goal_amount"])
        except (ValueError, KeyError):
            goal_amount = 0

        if not (recipient_name and occasion and organizer_name and goal_amount > 0):
            flash("Completá todos los campos para crear el regalo.")
            return render_template("create_gift.html")

        slug, token = db.create_gift(recipient_name, occasion, organizer_name, goal_amount)
        return redirect(url_for("organizer_panel", slug=slug, token=token))

    return render_template("create_gift.html")


# ---------------------------------------------------------------
# Página pública del regalo — la que se comparte por WhatsApp
# ---------------------------------------------------------------

@app.route("/g/<slug>", methods=["GET"])
def public_gift(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    total = db.confirmed_total(gift["id"])
    pct = min(100, int(total / gift["goal_amount"] * 100)) if gift["goal_amount"] else 0
    return render_template("public_gift.html", gift=gift, total=total, pct=pct)


@app.route("/g/<slug>/aportar", methods=["GET", "POST"])
def contribute(slug):
    gift = db.get_gift_by_slug(slug)
    if not gift:
        abort(404)
    if gift["status"] != "open":
        return render_template("closed.html", gift=gift)

    if request.method == "POST":
        contributor_name = request.form["contributor_name"].strip()
        try:
            amount = int(request.form["amount"])
        except (ValueError, KeyError):
            amount = 0

        if not (contributor_name and amount > 0):
            flash("Ingresá tu nombre y un monto válido.")
            return render_template("contribute.html", gift=gift)

        ref = db.create_contribution(gift["id"], contributor_name, amount)
        return render_template("contribute_instructions.html", gift=gift, amount=amount, ref=ref)

    return render_template("contribute.html", gift=gift)


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
    pct = min(100, int(total / gift["goal_amount"] * 100)) if gift["goal_amount"] else 0
    share_url = url_for("public_gift", slug=slug, _external=True)
    whatsapp_text = (
        f"¡Hola! Estoy juntando un regalo para {gift['occasion']}. "
        f"Sumate acá: {share_url}"
    )
    whatsapp_message = quote(whatsapp_text)
    return render_template(
        "organizer_panel.html",
        gift=gift, contributions=contributions, total=total, pct=pct,
        token=token, share_url=share_url, whatsapp_message=whatsapp_message,
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
