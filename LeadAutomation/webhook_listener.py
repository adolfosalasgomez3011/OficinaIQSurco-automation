"""
webhook_listener.py
-------------------
Local HTTP server that receives WhatsApp Cloud API webhook events.
When a new message arrives from an UNKNOWN number, the contact is
automatically added to lead_followup_tracker.csv as a Click-to-WhatsApp
lead (lead_id prefix: wa:).

Usage
-----
    python LeadAutomation/webhook_listener.py [--port 8080]

Then expose it with ngrok:
    ngrok http 8080

Register https://<ngrok-url>/webhook as your Meta webhook URL.
Verify token must match WHATSAPP_WEBHOOK_VERIFY_TOKEN in .env
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent.parent
TRACKER_CSV = BASE_DIR / "LeadAutomation" / "lead_followup_tracker.csv"
ENV_PATH = BASE_DIR / "LeadAutomation" / ".env"
LOG_PATH = BASE_DIR / "LeadAutomation" / "webhook.log"

OWNER = "Adolfo Salas"
DEFAULT_PRIORITY = "media"
DEFAULT_CAMPAIGN = "SASA - IQ Surco - Click-to-WA"
PLATFORM = "fb_wa"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


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


def normalize_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    return digits


def load_tracker_phones() -> set:
    if not TRACKER_CSV.exists():
        return set()
    with TRACKER_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return {normalize_phone(r.get("phone_number", "")) for r in csv.DictReader(f)}


def append_lead(phone: str, name: str, wa_id: str, timestamp: str) -> None:
    """Append a new Click-to-WhatsApp lead to the tracker CSV."""
    is_new = not TRACKER_CSV.exists()

    fieldnames = [
        "lead_id", "created_time", "full_name", "phone_number", "email",
        "platform", "campaign_name", "stage", "intent", "outbound_status",
        "last_message_draft", "last_contact_at", "next_action",
        "followup_at", "owner", "priority", "notes",
    ]

    # Convert epoch timestamp to ISO if needed
    try:
        ts_int = int(timestamp)
        created = datetime.utcfromtimestamp(ts_int).strftime("%Y-%m-%dT%H:%M:%S-05:00")
    except (ValueError, TypeError):
        created = datetime.now().strftime("%Y-%m-%dT%H:%M:%S-05:00")

    lead_id = f"wa:{phone}"
    draft = build_draft(name)

    row: Dict[str, str] = {
        "lead_id": lead_id,
        "created_time": created,
        "full_name": name or phone,
        "phone_number": phone,
        "email": "",
        "platform": PLATFORM,
        "campaign_name": DEFAULT_CAMPAIGN,
        "stage": "New inbound",
        "intent": "no claro",
        "outbound_status": "pending",
        "last_message_draft": draft,
        "last_contact_at": "",
        "next_action": "Enviar primer WhatsApp",
        "followup_at": "",
        "owner": OWNER,
        "priority": DEFAULT_PRIORITY,
        "notes": "canal=click-to-whatsapp",
    }

    with TRACKER_CSV.open("a", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            writer.writeheader()
        writer.writerow(row)

    log.info("NEW LEAD ADDED  name=%s  phone=%s  lead_id=%s", name, phone, lead_id)


# ---------------------------------------------------------------------------
# Webhook handler
# ---------------------------------------------------------------------------

class WebhookHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress default access log; we use our own logger
        pass

    # ------------------------------------------------------------------
    # GET  /webhook  → Meta verification challenge
    # ------------------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path != "/webhook":
            self._send(404, "Not found")
            return

        params = parse_qs(parsed.query)
        mode = params.get("hub.mode", [""])[0]
        token = params.get("hub.verify_token", [""])[0]
        challenge = params.get("hub.challenge", [""])[0]

        expected = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")

        if mode == "subscribe" and token == expected:
            log.info("Webhook verified by Meta.")
            self.send_response(200)
            self.end_headers()
            self.wfile.write(challenge.encode())
        else:
            log.warning("Webhook verification FAILED (token mismatch or wrong mode).")
            self._send(403, "Forbidden")

    # ------------------------------------------------------------------
    # POST /webhook  → incoming message events
    # ------------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/webhook":
            self._send(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        # Always respond 200 immediately (Meta requires it within 20 s)
        self._send(200, "OK")

        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            log.warning("Non-JSON POST body received.")
            return

        self._process_payload(payload)

    # ------------------------------------------------------------------
    # Payload processing
    # ------------------------------------------------------------------
    def _process_payload(self, payload: dict) -> None:
        if payload.get("object") != "whatsapp_business_account":
            return

        known_phones = load_tracker_phones()

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                if change.get("field") != "messages":
                    continue

                messages = value.get("messages", [])
                contacts = {c["wa_id"]: c.get("profile", {}).get("name", "")
                            for c in value.get("contacts", [])}

                for msg in messages:
                    sender_wa_id = msg.get("from", "")
                    sender_phone = normalize_phone(sender_wa_id)
                    sender_name = contacts.get(sender_wa_id, "") or sender_wa_id
                    timestamp = msg.get("timestamp", "")
                    msg_type = msg.get("type", "")
                    body_text = ""
                    if msg_type == "text":
                        body_text = msg.get("text", {}).get("body", "")

                    log.info(
                        "INCOMING  from=%s  name=%s  type=%s  body=%r",
                        sender_phone, sender_name, msg_type,
                        body_text[:80] if body_text else "(non-text)",
                    )

                    if sender_phone and sender_phone not in known_phones:
                        append_lead(sender_phone, sender_name, sender_wa_id, timestamp)
                        known_phones.add(sender_phone)
                    else:
                        log.info("Already in tracker (or empty phone), skipping add.")

    # ------------------------------------------------------------------
    def _send(self, code: int, body: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(body.encode())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="WhatsApp Cloud API webhook listener")
    parser.add_argument("--port", type=int, default=8080, help="Port to listen on (default: 8080)")
    args = parser.parse_args()

    load_env_file(ENV_PATH)

    verify_token = os.environ.get("WHATSAPP_WEBHOOK_VERIFY_TOKEN", "")
    if not verify_token:
        log.warning("WHATSAPP_WEBHOOK_VERIFY_TOKEN not set in .env — Meta verification will fail.")

    server = HTTPServer(("0.0.0.0", args.port), WebhookHandler)
    log.info("Webhook listener started on port %d", args.port)
    log.info("Register this URL on Meta:  https://<ngrok-url>/webhook")
    log.info("Verify token: %s", verify_token or "(NOT SET)")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Webhook listener stopped.")


if __name__ == "__main__":
    main()
