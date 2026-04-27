from __future__ import annotations

import argparse
import csv
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
TRACKER_CSV = BASE_DIR / "LeadAutomation" / "lead_followup_tracker.csv"
DEFAULT_ENV_PATH = BASE_DIR / "LeadAutomation" / ".env"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def normalize_phone(raw_phone: str, default_country_code: str) -> str:
    digits = re.sub(r"\D", "", raw_phone or "")
    if not digits:
        return ""

    if digits.startswith("00"):
        digits = digits[2:]

    if digits.startswith("+"):
        digits = digits[1:]

    if default_country_code and not digits.startswith(default_country_code):
        if len(digits) == 9:
            digits = f"{default_country_code}{digits}"

    return digits


def read_tracker_rows(path: Path) -> Tuple[List[Dict[str, str]], List[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        return rows, reader.fieldnames or []


def write_tracker_rows(path: Path, rows: List[Dict[str, str]], fieldnames: List[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def send_text_message(api_version: str, phone_number_id: str, access_token: str, to_phone: str, body: str) -> Tuple[bool, str]:
    endpoint = f"https://graph.facebook.com/{api_version}/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_phone,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }

    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body_text = response.read().decode("utf-8")
            response_json = json.loads(body_text)
            messages = response_json.get("messages") or []
            wa_message_id = messages[0].get("id", "") if messages else ""
            return True, wa_message_id
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        return False, f"HTTP {exc.code}: {error_text}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send WhatsApp Cloud API messages from tracker rows.")
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_PATH, help="Path to .env file")
    parser.add_argument("--tracker", type=Path, default=TRACKER_CSV, help="Path to lead tracker CSV")
    parser.add_argument("--limit", type=int, default=0, help="Maximum messages to process (0 = all)")
    parser.add_argument(
        "--send-live",
        action="store_true",
        help="Actually send messages. Without this flag, the script runs in dry-run mode.",
    )
    parser.add_argument(
        "--only-lead-ids",
        default="",
        help="Comma-separated lead_id values to process. Empty means no lead_id filter.",
    )
    parser.add_argument(
        "--only-phones",
        default="",
        help="Comma-separated phone numbers to process. Empty means no phone filter.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_env_file(args.env)

    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    api_version = os.getenv("WHATSAPP_API_VERSION", "v23.0")
    default_country_code = os.getenv("WHATSAPP_DEFAULT_COUNTRY_CODE", "51")
    mark_sent = (os.getenv("WHATSAPP_MARK_SENT_ON_SUCCESS", "true").strip().lower() == "true")

    statuses_raw = os.getenv("WHATSAPP_ALLOWED_STATUSES", "pending,drafted")
    allowed_statuses = {item.strip().lower() for item in statuses_raw.split(",") if item.strip()}

    only_lead_ids = {item.strip() for item in args.only_lead_ids.split(",") if item.strip()}
    only_phones_raw = {item.strip() for item in args.only_phones.split(",") if item.strip()}
    only_phones = {normalize_phone(phone, default_country_code) for phone in only_phones_raw}

    dry_run_from_env = os.getenv("WHATSAPP_DRY_RUN", "true").strip().lower() == "true"
    # Safety-first behavior: never send unless explicitly requested with --send-live.
    dry_run = not args.send_live

    if not args.tracker.exists():
        raise FileNotFoundError(f"Tracker not found: {args.tracker}")

    if not dry_run and (not access_token or not phone_number_id):
        raise RuntimeError("Missing WHATSAPP_ACCESS_TOKEN or WHATSAPP_PHONE_NUMBER_ID in environment")

    rows, fieldnames = read_tracker_rows(args.tracker)
    today_iso = datetime.now().strftime("%Y-%m-%d")

    attempted = 0
    sent = 0
    failed = 0

    for row in rows:
        if args.limit and attempted >= args.limit:
            break

        outbound_status = (row.get("outbound_status") or "").strip().lower()
        if outbound_status not in allowed_statuses:
            continue

        if only_lead_ids and (row.get("lead_id") or "") not in only_lead_ids:
            continue

        message = (row.get("last_message_draft") or "").strip()
        raw_phone = row.get("phone_number") or ""
        to_phone = normalize_phone(raw_phone, default_country_code)

        if only_phones and to_phone not in only_phones:
            continue

        if not message or not to_phone:
            failed += 1
            row["notes"] = (row.get("notes") or "") + " | Auto-send skipped: missing phone or message"
            continue

        attempted += 1
        if dry_run:
            print(f"[DRY-RUN] lead_id={row.get('lead_id','')} to={to_phone} message_len={len(message)}")
            continue

        ok, result = send_text_message(api_version, phone_number_id, access_token, to_phone, message)
        if ok:
            sent += 1
            if mark_sent:
                row["outbound_status"] = "sent"
                row["last_contact_at"] = row.get("last_contact_at") or today_iso
            existing_notes = (row.get("notes") or "").strip()
            suffix = f"wa_message_id={result}" if result else "wa_message_id=unknown"
            row["notes"] = f"{existing_notes} | {suffix}".strip(" |")
            print(f"[SENT] lead_id={row.get('lead_id','')} to={to_phone}")
        else:
            failed += 1
            existing_notes = (row.get("notes") or "").strip()
            row["notes"] = f"{existing_notes} | Auto-send error: {result}".strip(" |")
            print(f"[ERROR] lead_id={row.get('lead_id','')} to={to_phone} -> {result}")

    if not dry_run:
        write_tracker_rows(args.tracker, rows, fieldnames)

    mode_label = "DRY-RUN" if dry_run else "LIVE"
    if dry_run_from_env and args.send_live:
        print("Note: --send-live overrides WHATSAPP_DRY_RUN=true.")
    print(
        f"Completed {mode_label}. Attempted: {attempted}. Sent: {sent}. Failed: {failed}. "
        f"Tracker updated: {'no' if dry_run else 'yes'}."
    )


if __name__ == "__main__":
    main()
