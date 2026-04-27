from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

import psycopg
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

APP_NAME = "iq-surco-webhook-api"
VERIFY_TOKEN_ENV = "WHATSAPP_WEBHOOK_VERIFY_TOKEN"
DATABASE_URL_ENV = "DATABASE_URL"
DEFAULT_OWNER = os.getenv("LEAD_DEFAULT_OWNER", "Adolfo Salas")
DEFAULT_PRIORITY = os.getenv("LEAD_DEFAULT_PRIORITY", "media")
DEFAULT_CAMPAIGN = os.getenv("LEAD_DEFAULT_CAMPAIGN", "SASA - IQ Surco - Click-to-WA")
logger = logging.getLogger("uvicorn.error")

app = FastAPI(title=APP_NAME)


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def first_name(full_name: str) -> str:
    parts = (full_name or "").strip().split()
    return parts[0].title() if parts else "allí"


def build_draft(full_name: str) -> str:
    nombre = first_name(full_name)
    return (
        f"Hola {nombre}, gracias por tu interés en las oficinas de IQ Surco. "
        "Tengo disponibles opciones en Av. La Encalada y te puedo compartir "
        "video, precios y horarios de visita. Me confirmas si estás buscando "
        "alquiler, compra o ambas opciones?"
    )


def db_conn() -> psycopg.Connection:
    dsn = os.getenv(DATABASE_URL_ENV, "").strip()
    if not dsn:
        raise RuntimeError(f"Missing required env var: {DATABASE_URL_ENV}")
    return psycopg.connect(dsn)


def ensure_db_available() -> None:
    with db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")


def save_event(conn: psycopg.Connection, payload: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
                logger.info(
                    "webhook_received object=%s entry_count=%s",
                    payload.get("object"),
                    len(payload.get("entry", [])),
                )
            INSERT INTO webhook_events(provider, event_type, payload, received_at)
            VALUES (%s, %s, %s::jsonb, NOW())
            """,
            (
                "whatsapp",
                    logger.info("webhook_ignored unexpected_object=%s", payload.get("object"))
                "messages",
                json.dumps(payload, ensure_ascii=False),
            ),
        )


def upsert_lead(conn: psycopg.Connection, phone: str, full_name: str) -> int:
    draft = build_draft(full_name)
    with conn.cursor() as cur:
        cur.execute(
            """
                            metadata = value.get("metadata", {})
                            logger.info(
                                "webhook_change field=%s phone_number_id=%s display_phone=%s messages=%s statuses=%s contacts=%s",
                                change.get("field"),
                                metadata.get("phone_number_id"),
                                metadata.get("display_phone_number"),
                                len(value.get("messages", [])),
                                len(value.get("statuses", [])),
                                len(value.get("contacts", [])),
                            )
            INSERT INTO leads (
                lead_external_id,
                full_name,
                phone,
                email,
                source,
                campaign_name,
                stage,
                intent,
                outbound_status,
                owner,
                priority,
                last_message_draft,
                notes,
                created_at,
                updated_at
            )
            VALUES (
                %s,
                %s,
                %s,
                '',
                'fb_wa',
                %s,
                'New inbound',
                'no claro',
                'pending',
                %s,

                                logger.info(
                                    "webhook_message_saved lead_id=%s from=%s type=%s wa_message_id=%s",
                                    lead_id,
                                    phone,
                                    msg_type,
                                    msg.get("id", ""),
                                )
                %s,
                %s,
                'canal=click-to-whatsapp',
                NOW(),
                NOW()
            )
            ON CONFLICT (phone)
            DO UPDATE SET
                full_name = EXCLUDED.full_name,
                updated_at = NOW()
            RETURNING id
            """,
            (f"wa:{phone}", full_name, phone, DEFAULT_CAMPAIGN, DEFAULT_OWNER, DEFAULT_PRIORITY, draft),
        )
        return int(cur.fetchone()[0])


def insert_inbound_message(
    conn: psycopg.Connection,
    lead_id: int,
    wa_message_id: str,
    msg_type: str,
    text_body: str,
    sent_at_epoch: str,
    payload: dict[str, Any],
) -> None:
    sent_at = None
    try:
        if sent_at_epoch:
            sent_at = datetime.fromtimestamp(int(sent_at_epoch), tz=timezone.utc)
    except (TypeError, ValueError):
        sent_at = None

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO messages(
                lead_id,
                direction,
                channel,
                message_type,
                text_body,
                wa_message_id,
                provider_payload,
                sent_at,
                created_at
            )
            VALUES (%s, 'inbound', 'whatsapp', %s, %s, %s, %s::jsonb, %s, NOW())
            ON CONFLICT (wa_message_id) DO NOTHING
            """,
            (
                lead_id,
                msg_type,
                text_body,
                wa_message_id or None,
                json.dumps(payload, ensure_ascii=False),
                sent_at,
            ),
        )


@app.get("/health")
def health() -> JSONResponse:
    try:
        ensure_db_available()
        return JSONResponse({"ok": True, "service": APP_NAME})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.get("/webhook")
def verify_webhook(
    mode: str = Query(default="", alias="hub.mode"),
    challenge: str = Query(default="", alias="hub.challenge"),
    verify_token: str = Query(default="", alias="hub.verify_token"),
) -> PlainTextResponse:
    expected = os.getenv(VERIFY_TOKEN_ENV, "")

    if mode == "subscribe" and verify_token == expected:
        return PlainTextResponse(challenge, status_code=200)
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@app.get("/")
def root() -> JSONResponse:
    return JSONResponse({"service": APP_NAME, "status": "running"})


@app.get("/privacy")
def privacy_policy():
    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><title>Política de Privacidad – IQ Surco</title></head>
<body style="font-family:Arial,sans-serif;max-width:800px;margin:40px auto;padding:0 20px;">
<h1>Política de Privacidad</h1>
<p><strong>IQ Surco / S&amp;S Lead Manager</strong></p>
<p>Esta aplicación recibe notificaciones de mensajes de WhatsApp enviados voluntariamente por usuarios
interesados en las oficinas IQ Surco. Los datos recopilados (nombre, teléfono, contenido del mensaje)
se usan exclusivamente para dar seguimiento comercial interno.</p>
<h2>Datos recopilados</h2>
<ul>
  <li>Número de teléfono del remitente</li>
  <li>Nombre asociado a la cuenta de WhatsApp</li>
  <li>Contenido del mensaje recibido</li>
</ul>
<h2>Uso de los datos</h2>
<p>Los datos se almacenan en una base de datos privada y se usan únicamente para contactar al prospecto
en el contexto de la consulta realizada. No se comparten con terceros.</p>
<h2>Contacto</h2>
<p>Para cualquier consulta sobre privacidad: <a href="mailto:adolfosalasgomez@gmail.com">adolfosalasgomez@gmail.com</a></p>
<p><em>Última actualización: Abril 2026</em></p>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=200)


@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"received": False, "error": f"invalid_json: {exc}"}, status_code=400)

    # Always ACK quickly so Meta does not retry due to timeout.
    response = JSONResponse({"received": True}, status_code=200)

    if payload.get("object") != "whatsapp_business_account":
        return response

    with db_conn() as conn:
        save_event(conn, payload)

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                if change.get("field") != "messages":
                    continue

                value = change.get("value", {})
                contacts = {
                    c.get("wa_id", ""): c.get("profile", {}).get("name", "")
                    for c in value.get("contacts", [])
                }

                for msg in value.get("messages", []):
                    wa_from = msg.get("from", "")
                    phone = normalize_phone(wa_from)
                    if not phone:
                        continue

                    name = contacts.get(wa_from, "").strip() or wa_from
                    lead_id = upsert_lead(conn, phone, name)

                    msg_type = msg.get("type", "unknown")
                    text_body = ""
                    if msg_type == "text":
                        text_body = msg.get("text", {}).get("body", "")

                    insert_inbound_message(
                        conn=conn,
                        lead_id=lead_id,
                        wa_message_id=msg.get("id", ""),
                        msg_type=msg_type,
                        text_body=text_body,
                        sent_at_epoch=msg.get("timestamp", ""),
                        payload=msg,
                    )

        conn.commit()

    return response
