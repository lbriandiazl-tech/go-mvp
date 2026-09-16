"""
GO — capa de datos.

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

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///go.db")

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
    goal_amount INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'UYU',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    selected_category TEXT,
    selected_item TEXT
);

CREATE TABLE IF NOT EXISTS contributions (
    id {_PK},
    gift_id INTEGER NOT NULL REFERENCES gifts(id),
    contributor_name TEXT NOT NULL,
    amount INTEGER NOT NULL,
    reference_code TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
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
    return "GO-" + _random_code(6, string.ascii_uppercase + string.digits)


def _now():
    return datetime.now(timezone.utc).isoformat()


# ---------- regalos ----------

def create_gift(recipient_name, occasion, organizer_name, goal_amount, currency="UYU"):
    slug = new_slug(recipient_name)
    token = new_token()
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO gifts
                   (slug, organizer_token, recipient_name, occasion, organizer_name,
                    goal_amount, currency, status, created_at)
                   VALUES (:slug, :token, :recipient_name, :occasion, :organizer_name,
                           :goal_amount, :currency, 'open', :created_at)"""),
            dict(slug=slug, token=token, recipient_name=recipient_name, occasion=occasion,
                 organizer_name=organizer_name, goal_amount=goal_amount, currency=currency,
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
        conn.execute(text("UPDATE gifts SET status = 'closed' WHERE id = :id"), dict(id=gift_id))


# ---------- aportes ----------

def create_contribution(gift_id, contributor_name, amount):
    ref = new_reference_code()
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO contributions
                   (gift_id, contributor_name, amount, reference_code, status, created_at)
                   VALUES (:gift_id, :contributor_name, :amount, :ref, 'pending', :created_at)"""),
            dict(gift_id=gift_id, contributor_name=contributor_name, amount=amount,
                 ref=ref, created_at=_now()),
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
            text("UPDATE contributions SET status = 'confirmed', confirmed_at = :now WHERE id = :id"),
            dict(now=_now(), id=contribution_id),
        )


def get_contribution(contribution_id):
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT * FROM contributions WHERE id = :id"), dict(id=contribution_id)
        )
        return _row(result)


def set_selected_item(gift_id, category, item_title):
    with engine.begin() as conn:
        conn.execute(
            text("UPDATE gifts SET selected_category = :cat, selected_item = :item WHERE id = :id"),
            dict(cat=category, item=item_title, id=gift_id),
        )
