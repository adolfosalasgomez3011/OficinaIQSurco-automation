# IQ Surco Lead Automation Blueprint

## What exists today

The current workspace already contains the essential commercial facts and WhatsApp copy for a manual funnel:
- office facts and pricing in `SurcoOffices_mktplan.txt`
- short WhatsApp message patterns in `SocialNetworkMaterial/whatsapp_messages_es.txt`
- social assets designed to push traffic into WhatsApp

That means the cheapest first automation is not a full CRM rebuild. It is a controlled reply-assist workflow that helps classify leads, draft the next message, and log the opportunity consistently.

## Recommended rollout

### Phase 1: Skill-first

Use the workspace skill at `.github/skills/iq-surco-lead-automation/` to do 4 things:
- classify each incoming conversation
- draft the next reply in Spanish
- identify missing qualification data
- produce a compact CRM update line

This is the fastest option because it does not require API keys, Meta app review, or WhatsApp Cloud API setup.

### Phase 2: Hybrid workflow

Add a simple lead tracker and a human approval step.

Suggested flow:
1. Copy the lead message or thread into chat.
2. Use the skill to generate the next reply and CRM update.
3. Save the CRM line in a tracker.
4. Send the message manually from WhatsApp Business or Messenger.

This keeps response quality high while avoiding risky full automation early in the funnel.

### Phase 3: MCP server

Build an MCP server when you want connected automation across channels.

Best candidates:
- Meta Lead Ads forms
- Facebook Page inbox or Messenger data source
- WhatsApp Cloud API
- Google Sheets or Airtable as lightweight CRM
- Gmail for visit confirmations

## Proposed MCP responsibilities

The MCP server should not be only a message sender. It should be the lead operations layer.

### Core tools

- `surco_list_new_leads`
  - Pull unread or recent leads from Meta, WhatsApp, Sheets, or Airtable.

- `surco_get_lead_context`
  - Return the transcript, source, current stage, and previous actions.

- `surco_classify_lead`
  - Normalize the lead into stage, interest type, office preference, priority, and next action.

- `surco_draft_reply`
  - Generate a WhatsApp or Messenger reply using the same logic as the skill.

- `surco_log_lead_update`
  - Save stage changes, notes, follow-up date, and owner.

- `surco_send_approved_reply`
  - Send the message only after human approval.

- `surco_schedule_followup`
  - Create a reminder for the next contact attempt.

### Safety rules

- keep human approval for outbound messages in the first version
- never auto-send pricing changes without approval
- log every outbound message
- separate draft generation from message sending

## Suggested data model

Minimum lead record:
- `lead_id`
- `name`
- `phone_or_profile`
- `source_channel`
- `campaign`
- `first_contact_at`
- `last_contact_at`
- `stage`
- `interest_type`
- `office_preference`
- `budget_signal`
- `timing_signal`
- `objection`
- `next_action`
- `followup_at`
- `owner`
- `priority`

## Recommended stack

If you build the MCP now, use Python because the workspace already includes Python scripts.

Suggested components:
- FastMCP server
- Google Sheets or Airtable as CRM store
- WhatsApp Cloud API for outbound approved messages
- Meta lead webhook or CSV export ingestion

## Practical recommendation

For this workspace, use both, but in sequence:
- start with the skill immediately
- add the MCP when you have the channel credentials and want direct ingestion plus logging

That gives you value now and avoids building infrastructure before the lead volume justifies it.