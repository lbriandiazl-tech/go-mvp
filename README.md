# Vaka — MVP

Plataforma de regalos grupales. Flask + SQLAlchemy (SQLite en local,
Postgres en producción).

## Correr en local

```
pip install -r requirements.txt
python3 app.py
```

Abre en http://localhost:5050 — usa SQLite automáticamente (`go.db`),
no hace falta configurar nada más.

## Deploy en producción (Render — recomendado)

1. **Crear cuenta en [render.com](https://render.com)** (gratis para empezar).
2. Subir este código a un repo de GitHub (Render se conecta a GitHub directo).
3. En Render: **New > PostgreSQL** — crear una base, plan gratuito.
   Copiar la "Internal Database URL" que te da.
4. En Render: **New > Web Service**, conectar el repo.
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app` (ya está en el `Procfile`, Render lo detecta solo)
5. En la sección **Environment** del Web Service, agregar:
   - `DATABASE_URL` = la URL que copiaste del paso 3
   - `SECRET_KEY` = generar con `python3 -c "import secrets; print(secrets.token_hex(32))"`
6. Deploy. Render te da una URL tipo `go-mvp.onrender.com` con HTTPS ya activado.
7. **Dominio propio**: comprar el dominio (Namecheap, GoDaddy, o donde prefieran)
   y en Render, Settings > Custom Domain, seguir las instrucciones para apuntar
   el DNS. Render genera el certificado HTTPS solo.

## Flujo implementado

1. `/` → `/crear` — el organizador crea el regalo (destinatario, ocasión, meta)
2. `/g/<slug>` — página pública para compartir (WhatsApp)
3. `/g/<slug>/aportar` — el participante aporta y recibe una referencia
   bancaria única para poner en el concepto de la transferencia
4. `/organizador/<slug>?token=...` — panel privado: ver aportes, confirmar
   manualmente cada transferencia, cerrar la colecta
5. `/regalo/<slug>` — experiencia del destinatario: abre la caja (interactivo,
   no automático) y elige una categoría del catálogo

## Mercado Pago (pago automático)

Si configurás `MP_ACCESS_TOKEN` (Render > Environment), el formulario de
aportar ofrece "Pagar con Mercado Pago" además de transferencia bancaria.
Los pagos se confirman solos vía webhook — nadie tiene que revisar el
banco a mano para esos.

**Antes de usar credenciales de producción**: probá primero con las
credenciales de PRUEBA de Mercado Pago (Developers > Credenciales de
prueba) y el flujo completo de un aporte de punta a punta. Esta
integración se escribió siguiendo la documentación oficial pero no se
pudo probar contra la API real en el entorno de desarrollo (sin acceso
a internet) — lo que sí se probó fue toda la lógica interna: qué pasa
si Mercado Pago no responde (cae a transferencia con un aviso, no
rompe), y que el webhook confirma el aporte correctamente y no se
duplica si llega dos veces.

## Lo que falta para producción

- Catálogo real (hoy `/regalo/<slug>/catalogo` es un placeholder)
- Integración de pago real (Mercado Pago / tarjetas) en vez de solo
  transferencia + validación manual
- Autenticación real del organizador (hoy es un token en la URL, suficiente
  para MVP pero no para escalar)
- Envío de emails reales para los recordatorios (hoy no existe)
- Rate limiting / protección básica contra abuso en `/crear` y `/aportar`

## Nota sobre este cambio (SQLite → SQLAlchemy/Postgres)

Este cambio se escribió pero **no se pudo probar en vivo** en el entorno
donde se desarrolló (sin acceso a internet para instalar SQLAlchemy).
Antes de deployar: correlo en local primero (`pip install -r requirements.txt`
y `python3 app.py`) y probá el flujo completo una vez para confirmar que
todo sigue andando igual que con SQLite puro.
