# Outreach agent

Sends a short pitch to local businesses that **don't have a website**, asking whether they'd like one, then reads and sorts their replies.

It is deliberately conservative:

- **Dry run by default.** `send` and `followup` write `.eml` files to `outreach/outbox/` for you to read. Nothing goes out until you add `--live`.
- **Human in the loop for replies.** The agent classifies replies and updates the lead's status. It never auto-answers a real conversation. `interested` and `question` replies are listed for you to respond to.
- **Opt-outs are automatic and permanent.** An unsubscribe request, or a bounce, adds the address to a suppression list that every future run checks.
- **One follow-up at most**, after `OUTREACH_FOLLOWUP_DAYS` with no reply.
- **Only businesses without a website.** Any lead row with a `website` value is skipped on import.

## Setup

No third-party packages are needed (Python 3.10+, standard library only).

Set these environment variables in your shell. Don't commit them.

| Variable | Purpose |
| --- | --- |
| `OUTREACH_FROM_EMAIL` | Address pitches come from, e.g. your Feeling Swell Media address |
| `OUTREACH_SENDER_NAME` | Your name for the signature |
| `OUTREACH_POSTAL_ADDRESS` | Physical mailing address. Required by CAN-SPAM for commercial email; live sending refuses to run without it. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | Outbound mail server |
| `IMAP_HOST`, `IMAP_PORT`, `IMAP_USER`, `IMAP_PASSWORD` | Inbox to read replies from (often the same mailbox) |
| `OUTREACH_MAX_PER_RUN` | Cap per run (default 25). Keep this low while you warm up a new sending domain. |
| `OUTREACH_FOLLOWUP_DAYS` | Days before a follow-up (default 7) |
| `OUTREACH_DB`, `OUTREACH_OUTBOX` | Optional paths for the database and draft folder |

## Usage

```bash
# 1. Load leads (CSV columns: business_name,email,category,city,website)
python -m outreach import outreach/leads.example.csv

# 2. Draft the first pitches and review the .eml files in outreach/outbox/
python -m outreach send

# 3. When you're happy with the copy and the list, send for real
python -m outreach send --live

# 4. Periodically: read replies, then follow up on silent leads once
python -m outreach poll
python -m outreach followup            # draft
python -m outreach followup --live

# 5. See what needs a human
python -m outreach status
```

Run `poll` on a schedule (cron, or a scheduled task) so replies are handled while you're away.

## Lead statuses

| Status | Meaning |
| --- | --- |
| `new` | Imported, not pitched |
| `pitched` | First pitch sent, waiting |
| `followed_up` | Follow-up sent, waiting. No more automatic mail. |
| `interested` / `question` | Replied. **Needs you.** |
| `not_interested` | Said no. Closed. |
| `unsubscribed` / `bounced` | Suppressed forever |
| `closed` | Reserved for manual closing |

## Reply classification

`classify.py` uses keyword rules and ignores quoted history. Priority order: unsubscribe, out-of-office, not interested, interested, question, other. Anything ambiguous becomes `other` for a human to read. Edit the patterns there. If you later want a model to classify replies, replace `classify()` and keep the same return values.

## Compliance checklist before going live

- Confirm the list is businesses you have a reasonable basis to contact, and that you're following the rules in your jurisdiction (CAN-SPAM in the US; PECR/GDPR in the UK/EU, which are stricter about cold B2B email).
- Keep the postal address and working unsubscribe line in every email (the templates include both).
- Set up SPF, DKIM, and DMARC for the sending domain, and start with a small `OUTREACH_MAX_PER_RUN`.
- Honor opt-outs promptly. The suppression list is checked on every send.

## Tests

```bash
python -m unittest discover -s outreach/tests -t .
```

## Files

- `agent.py`: CLI and workflow
- `db.py`: SQLite schema and queries (`outreach/data/outreach.db`, gitignored)
- `templates.py`: email copy
- `mailer.py`: builds messages, sends via SMTP or writes drafts
- `inbox.py`: reads IMAP, matches replies by threading headers and sender, handles bounces
- `classify.py`: reply intent rules
- `leads.example.csv`: sample input
