# Meta Leads To WhatsApp Workflow

## What this does

This workflow uses the existing Meta Ads workbook at `FacebookAdsCampaing/CRMIQSurcov1.xlsx` as the source of truth for new leads.

When you run `sync_meta_leads.py`, it will:
- read the `Clients` sheet
- ignore test leads
- normalize phone numbers
- auto-flag duplicated phone numbers already contacted
- create or update a follow-up tracker CSV
- generate a WhatsApp queue workbook with a ready message and one-click WhatsApp link for each pending lead

## Files created

- `LeadAutomation/lead_followup_tracker.csv`
  - operational tracker you should edit (source of truth for status)

- `LeadAutomation/WhatsAppFollowupQueue.xlsx`
  - clickable send queue generated from tracker and Meta leads (do not use as source of truth)

## Which file should I edit?

- Edit this file: `LeadAutomation/lead_followup_tracker.csv`
- Use this file to send quickly: `LeadAutomation/WhatsAppFollowupQueue.xlsx`

When you send a message, set `outbound_status` in `lead_followup_tracker.csv` to `sent` (or `replied`, `qualified`, etc.).

On the next sync run, if `last_contact_at` is empty and status is contacted, the script auto-fills `last_contact_at` with today's date.

## Recommended workflow

1. Let Meta continue updating `CRMIQSurcov1.xlsx`.
2. Run the sync script.
3. Open `WhatsAppFollowupQueue.xlsx`.
4. Click `Abrir WhatsApp` for each pending lead.
5. After sending, change `outbound_status` in `lead_followup_tracker.csv` from `pending` to `sent`.
6. Run the script again whenever new leads arrive.

## Status values

Use these in `lead_followup_tracker.csv`:
- `pending`
- `drafted`
- `sent`
- `replied`
- `qualified`
- `scheduled`
- `closed`
- `already_contacted` (auto-created when the same phone submits again)

## Duplicate protection

If a new Meta lead arrives with a phone number that already has a contacted status (`sent`, `replied`, `qualified`, `scheduled`, `closed`), the new row is auto-marked as:
- `outbound_status = already_contacted`
- `next_action = Revisar duplicado por telefono`

Those rows are excluded from the send queue, so you do not message the same person twice by mistake.

## How to run

From the workspace root:

```bash
python LeadAutomation/sync_meta_leads.py
```

Or on Windows, run:

```bat
LeadAutomation\run_meta_sync.bat
```

## Practical note

This is the highest-value automation available right now without WhatsApp Cloud API credentials.

If you later add WhatsApp Cloud API access, this same tracker can become the approval layer for an MCP server that drafts and sends approved messages automatically.

## WhatsApp Cloud API Auto-Send

You can now send directly from the tracker using the Cloud API script:

1. Copy `LeadAutomation/.env.example` to `LeadAutomation/.env`
2. Fill these values in `.env`:
  - `WHATSAPP_ACCESS_TOKEN`
  - `WHATSAPP_PHONE_NUMBER_ID`
  - `WHATSAPP_BUSINESS_ACCOUNT_ID`
3. Keep `WHATSAPP_DRY_RUN=true` for the first test.

Run a safe simulation first:

```bash
python LeadAutomation/send_whatsapp_cloud.py --limit 2
```

If logs look correct, run live mode:

```bash
python LeadAutomation/send_whatsapp_cloud.py --send-live --limit 2
```

For controlled testing, target only selected records:

```bash
python LeadAutomation/send_whatsapp_cloud.py --send-live --only-lead-ids l:4475137326038637
python LeadAutomation/send_whatsapp_cloud.py --send-live --only-phones 51971152829
```

Behavior:
- Reads `lead_followup_tracker.csv`
- Sends only rows with status in `WHATSAPP_ALLOWED_STATUSES` (default `pending,drafted`)
- Optional filters: `--only-lead-ids` and `--only-phones`
- On success, sets `outbound_status=sent` and stamps `last_contact_at` (if enabled)
- Appends `wa_message_id` or error info to `notes`

Important:
- Keep `.env` private and never commit it.
- Meta may reject free-text outbound messages in some scenarios unless you use approved templates.

---

## Click-to-WhatsApp Lead Capture (Webhook)

Leads from Click-to-WhatsApp ads go directly to your WhatsApp inbox — they are NOT saved in CRMIQSurcov1.xlsx. The webhook listener auto-adds these contacts to the tracker the moment they message you.

### One-time setup (5 minutes)

**Step 1 — Install ngrok (free)**

Download from https://ngrok.com/download and unzip it anywhere (e.g. `C:\ngrok\ngrok.exe`).
Create a free account and run once to authenticate:
```
ngrok config add-authtoken <your_ngrok_token>
```

**Step 2 — Start the webhook listener**

```bat
LeadAutomation\run_webhook.bat
```

Or manually:
```bash
python LeadAutomation/webhook_listener.py --port 8080
```

**Step 3 — Expose it with ngrok** (in a second terminal)

```bash
ngrok http 8080
```

Copy the `https://xxxx.ngrok-free.app` URL shown.

**Step 4 — Register the webhook in Meta**

1. Go to https://developers.facebook.com → App: S&S_LeadManager → WhatsApp → Configuration
2. Paste `https://xxxx.ngrok-free.app/webhook` as the Callback URL
3. Set Verify Token to: `iqsurco_webhook_2026`  (matches `WHATSAPP_WEBHOOK_VERIFY_TOKEN` in `.env`)
4. Subscribe to the **messages** field
5. Click Verify and Save

From that point on, every new WhatsApp message received by the business number is automatically checked. If the sender is NOT already in the tracker, they are added with `outbound_status=pending` and a draft follow-up message ready to send.

### Daily use

- Keep `run_webhook.bat` + ngrok running while you're working.
- After a lead messages in, run `sync_meta_leads.py` (or just check the tracker CSV) to see the new row.
- Use `send_whatsapp_cloud.py` normally to send the follow-up.

---

## Production Setup (Render + Postgres)

This removes the need for local terminals and ngrok.

### 1) Create database

- Create a Neon Postgres (or Render Postgres) database.
- Copy the `DATABASE_URL` connection string.

### 2) Deploy webhook API to Render

- Push this repository to GitHub.
- In Render, create Blueprint from repo root (uses `render.yaml`) or create a Web Service manually.
- Build command:

```bash
pip install -r LeadAutomation/render_webhook_api/requirements.txt
```

- Start command:

```bash
bash LeadAutomation/render_webhook_api/start.sh
```

- Set env vars in Render:
  - `DATABASE_URL`
  - `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
  - `LEAD_DEFAULT_OWNER` (optional)
  - `LEAD_DEFAULT_PRIORITY` (optional)
  - `LEAD_DEFAULT_CAMPAIGN` (optional)

The app auto-runs schema initialization at startup via `init_db.py`.

### 3) Register webhook in Meta

- Callback URL: `https://<your-render-service>.onrender.com/webhook`
- Verify token: same value as `WHATSAPP_WEBHOOK_VERIFY_TOKEN`
- Object: `whatsapp_business_account`
- Field subscription: `messages`

### 4) Verify service

- Open `https://<your-render-service>.onrender.com/health`
- Expect JSON with `"ok": true`.

After this, inbound WhatsApp messages are captured in database tables:
- `leads`
- `messages`
- `webhook_events`