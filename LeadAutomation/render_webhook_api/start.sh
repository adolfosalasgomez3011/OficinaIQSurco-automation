#!/usr/bin/env bash
set -e
python LeadAutomation/render_webhook_api/init_db.py
exec uvicorn LeadAutomation.render_webhook_api.app:app --host 0.0.0.0 --port ${PORT:-10000}
