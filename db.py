"""
Vaka — capa de datos.

Usa SQLAlchemy Core como capa fina sobre SQL crudo: el mismo código
funciona contra SQLite (desarrollo local, sin nada que instalar) y
contra Postgres (producción, vía la variable de entorno DATABASE_URL).

Por qué así y no el ORM completo: el esquema es chico (2 tablas) y
el equipo que lo lea después no necesita aprenderse un ORM para
entender qué hace cada función — es SQL explícito con portabilidad
de motor, nada más.
"""
import os
import secrets
import string
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///vaka.db")

# Render/Heroku entregan la URL como "postgres://...";
# SQLAlchemy 2.x exige el prefijo "postgresql://".
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

IS_SQLITE = DATABASE_URL.startswith("sqlite")

# AUTOINCREMENT es sintaxis de SQLite; Postgres usa SERIAL/IDENTITY.
_PK = "INTEGER PRIMARY KEY AUTOINCREMENT" if IS_SQLITE else "SERIAL PRIMARY KEY"

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS gifts (
    id {_PK},
    slug TEXT UNIQUE NOT NULL,
    organizer_token TEXT UNIQUE NOT NULL,
    recipient_name TEXT NOT NULL,
    occasion TEXT NOT NULL,
    organizer_name TEXT NOT NULL,
    organizer_email TEXT NOT NULL DEFAULT '',
    min_contribution INTEGER NOT NULL,
    bank_details TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'UYU',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    selected_category TEXT,
    selected_item TEXT,
    closed_at TEXT,
    selected_at TEXT,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS contributions (
    id {_PK},
    gift_id INTEGER NOT NULL REFERENCES gifts(id),
    contributor_name TEXT NOT NULL,
    amount INTEGER NOT NULL,
    reference_code TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    payment_method TEXT NOT NULL DEFAULT 'transfer',
    mp_preference_id TEXT,
    mp_payment_id TEXT,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);
"""


def init_db():
    with engine.begin() as conn:
        for statement in SCHEMA.strip().split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))
    _migrate()


def _migrate():
    """Agrega columnas que puedan faltar en una base creada con una
    versión anterior del esquema, sin perder los datos existentes.

    Por qué hace falta esto: CREATE TABLE IF NOT EXISTS no toca una
    tabla que ya existe, así que si el código cambia (se agrega una
    columna, se renombra un campo) la base real en producción se
    queda atrás hasta que alguien la migre a mano. Esto lo hace
    solo, cada vez que arranca el servidor."""
    additions = [
        ("gifts", "min_contribution", "INTEGER"),
        ("gifts", "selected_category", "TEXT"),
        ("gifts", "selected_item", "TEXT"),
        ("gifts", "bank_details", "TEXT NOT NULL DEFAULT ''"),
        ("gifts", "organizer_email", "TEXT NOT NULL DEFAULT ''"),
        ("gifts", "closed_at", "TEXT"),
        ("gifts", "selected_at", "TEXT"),
        ("gifts", "delivered_at", "TEXT"),
        ("contributions", "payment_method", "TEXT NOT NULL DEFAULT 'transfer'"),
        ("contributions", "mp_preference_id", "TEXT"),
        ("contributions", "mp_payment_id", "TEXT"),
    ]
    for table, column, coltype in additions:
        try:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
        except Exception:
            pass  # la columna ya existe — nada que hacer


def _row(result):
    row = result.fetchone()
    return dict(row._mapping) if row else None


def _rows(result):
    return [dict(r._mapping) for r in result.fetchall()]


def _random_code(length, alphabet):
    return "".join(secrets.choice(alphabet) for _ in range(length))


def new_slug(recipient_name):
    normalized = unicodedata.normalize("NFKD", recipient_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    base = "".join(c.lower() if c.isalnum() else "-" for c in ascii_name).strip("-")
    base = "-".join(filter(None, base.split("-")))[:24] or "regalo"
    suffix = _random_code(6, string.ascii_lowercase + string.digits)
    return f"{base}-{suffix}"


def new_token():
    return _random_code(24, string.ascii_letters + string.digits)


def new_reference_code():
    return "VK-" + _random_code(6, string.ascii_uppercase + string.digits)


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------- regalos ----------

def create_gift(recipient_name, occasion, organizer_name, organizer_email, min_contribution, bank_details="", currency="UYU"):
    # bank_details queda en la tabla solo por compatibilidad con regalos
    # viejos: con el modelo de custodia la cuenta es siempre la de Vaka
    # (variable de entorno VAKA_BANK_DETAILS), no la del organizador.
    slug = new_slug(recipient_name)
    token = new_token()
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO gifts
                   (slug, organizer_token, recipient_name, occasion, organizer_name, organizer_email,
                    min_contribution, bank_details, currency, status, created_at)
                   VALUES (:slug, :token, :recipient_name, :occasion, :organizer_name, :organizer_email,
                           :min_contribution, :bank_details, :currency, 'open', :created_at)"""),
            dict(slug=slug, token=token, recipient_name=recipient_name, occasion=occasion,
                 organizer_name=organizer_name, organizer_email=organizer_email,
                 min_contribution=min_contribution,
                 bank_details=bank_details, currency=currency,
                 created_at=_now()),
        )
    return slug, token


def get_gift_by_slug(slug):
    with engine.connect() as conn:
        result = conn.execute(text("SELECT * FROM gifts WHERE slug = :slug"), dict(slug=slug))
        return _row(result)


def get_gift_by_token(slug, token):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM gifts WHERE slug = :slug AND organizer_token = :token"),
            dict(slug=slug, token=token),
        )
        return _row(result)


def close_gift(gift_id):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE gifts SET status = 'closed', closed_at = :now WHERE id = :id AND status = 'open'"),
            dict(now=_now(), id=gift_id),
        )


# ---------- aportes ----------

def create_contribution(gift_id, contributor_name, amount, payment_method="transfer"):
    ref = new_reference_code()
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO contributions
                   (gift_id, contributor_name, amount, reference_code, status,
                    payment_method, created_at)
                   VALUES (:gift_id, :contributor_name, :amount, :ref, 'pending',
                           :payment_method, :created_at)"""),
            dict(gift_id=gift_id, contributor_name=contributor_name, amount=amount,
                 ref=ref, payment_method=payment_method, created_at=_now()),
        )
    return ref


def list_contributions(gift_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM contributions WHERE gift_id = :gift_id ORDER BY created_at DESC"),
            dict(gift_id=gift_id),
        )
        return _rows(result)


def confirmed_total(gift_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("""SELECT COALESCE(SUM(amount),0) AS total FROM contributions
                   WHERE gift_id = :gift_id AND status = 'confirmed'"""),
            dict(gift_id=gift_id),
        )
        return _row(result)["total"]


def confirmed_contributors(gift_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("""SELECT contributor_name FROM contributions
                   WHERE gift_id = :gift_id AND status = 'confirmed' ORDER BY confirmed_at"""),
            dict(gift_id=gift_id),
        )
        return [r["contributor_name"] for r in _rows(result)]


def confirm_contribution(contribution_id):
    with engine.begin() as conn:
        conn.execute(
            text("""UPDATE contributions SET status = 'confirmed', confirmed_at = :now
                   WHERE id = :id AND status != 'confirmed'"""),
            dict(now=_now(), id=contribution_id),
        )


def get_contribution(contribution_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM contributions WHERE id = :id"), dict(id=contribution_id)
        )
        return _row(result)


def get_contribution_by_reference(reference_code):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM contributions WHERE reference_code = :ref"),
            dict(ref=reference_code),
        )
        return _row(result)


def set_mp_preference(contribution_id, preference_id):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE contributions SET mp_preference_id = :pid WHERE id = :id"),
            dict(pid=preference_id, id=contribution_id),
        )


def confirm_contribution_by_mp(reference_code, mp_payment_id):
    """Confirma un aporte automáticamente a partir del webhook de Mercado Pago.
    Idempotente: si ya estaba confirmado, no hace nada (un webhook puede
    llegar más de una vez para el mismo pago — es normal en MP)."""
    with engine.begin() as conn:
        conn.execute(
            text("""UPDATE contributions
                   SET status = 'confirmed', confirmed_at = :now, mp_payment_id = :pid
                   WHERE reference_code = :ref AND status != 'confirmed'"""),
            dict(now=_now(), pid=mp_payment_id, ref=reference_code),
        )


def set_selected_item(gift_id, category, item_title):
    with engine.begin() as conn:
        conn.execute(
            text("""UPDATE gifts SET selected_category = :cat, selected_item = :item,
                   selected_at = :now WHERE id = :id"""),
            dict(cat=category, item=item_title, now=_now(), id=gift_id),
        )


def suggested_amounts(min_contribution):
    """4 montos sugeridos a partir del mínimo, para mostrar como botones
    en vez de que la gente tenga que escribir un número.
    Con $400 de mínimo da: 400, 600, 1000, 2000 — la misma progresión
    que usan formularios de donación (ancla baja, media, alta, generosa)."""
    multipliers = [1, 1.5, 2.5, 5]
    amounts = []
    for m in multipliers:
        raw = min_contribution * m
        rounded = round(raw / 100) * 100
        amounts.append(int(rounded))
    return amounts


def get_gifts_by_organizer_email(email):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM gifts WHERE organizer_email = :email ORDER BY created_at DESC"),
            dict(email=email.strip().lower()),
        )
        return _rows(result)


# ---------- panel de Vaka (admin) ----------

def list_pending_transfers():
    """Transferencias que esperan que Vaka las vea en su cuenta y las
    confirme. Incluye regalos ya cerrados: si la plata llegó tarde,
    igual entró a la cuenta de Vaka y hay que registrarla."""
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT c.id, c.contributor_name, c.amount, c.reference_code, c.created_at,
                   g.slug, g.recipient_name, g.occasion, g.status AS gift_status
            FROM contributions c JOIN gifts g ON g.id = c.gift_id
            WHERE c.status = 'pending' AND c.payment_method = 'transfer'
            ORDER BY c.created_at ASC"""))
        return _rows(result)


def list_gifts_with_totals():
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT g.*,
                   COALESCE(SUM(CASE WHEN c.status = 'confirmed' THEN c.amount END), 0) AS total,
                   COUNT(CASE WHEN c.status = 'confirmed' THEN 1 END) AS confirmed_count,
                   COUNT(CASE WHEN c.status = 'pending' THEN 1 END) AS pending_count
            FROM gifts g LEFT JOIN contributions c ON c.gift_id = g.id
            GROUP BY g.id
            ORDER BY g.created_at DESC"""))
        return _rows(result)


def mark_delivered(gift_id):
    with engine.begin() as conn:
        conn.execute(
            text("""UPDATE gifts SET delivered_at = :now
                   WHERE id = :id AND status = 'closed' AND delivered_at IS NULL"""),
            dict(now=_now(), id=gift_id),
        )


def admin_stats():
    """Los números del objetivo actual: 10 vaquitas reales de punta a punta."""
    gifts = list_gifts_with_totals()
    delivered = [g for g in gifts if g["delivered_at"]]
    hours = []
    for g in delivered:
        if g["closed_at"]:
            try:
                delta = datetime.fromisoformat(g["delivered_at"]) - datetime.fromisoformat(g["closed_at"])
                hours.append(delta.total_seconds() / 3600)
            except ValueError:
                pass
    with engine.connect() as conn:
        by_method = _rows(conn.execute(text("""
            SELECT payment_method, COUNT(*) AS n FROM contributions
            WHERE status = 'confirmed' GROUP BY payment_method""")))
    methods = {r["payment_method"]: r["n"] for r in by_method}
    return dict(
        created=len(gifts),
        open=sum(1 for g in gifts if g["status"] == "open"),
        closed=sum(1 for g in gifts if g["status"] == "closed"),
        delivered=len(delivered),
        collected=sum(g["total"] for g in gifts),
        avg_hours_to_deliver=(sum(hours) / len(hours)) if hours else None,
        mp_count=methods.get("mercadopago", 0),
        transfer_count=methods.get("transfer", 0),
    )
