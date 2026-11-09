"""Command-line entry point for the outreach agent.

    python -m outreach import leads.csv          # load leads (skips businesses that have a website)
    python -m outreach send                      # draft pitches to .eml files (dry run)
    python -m outreach send --live               # actually send pitches
    python -m outreach followup [--live]         # one follow-up to pitched leads with no reply
    python -m outreach poll [--live]             # read replies, classify, update statuses
    python -m outreach status                    # counts per status + items needing a human
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path

from . import db, templates, mailer, inbox
from .config import Config, load_config

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_SECONDS_BETWEEN_SENDS = 20  # gentle pacing; cold mail should not be bursty


def import_leads(conn, csv_path: Path) -> dict[str, int]:
    """Load leads from a CSV with columns: business_name,email,category,city,website.

    Rows with a website are skipped (this pitch is for businesses that have none).
    """
    counts = {"added": 0, "has_website": 0, "bad_email": 0, "duplicate": 0, "suppressed": 0}
    with csv_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = (row.get("business_name") or "").strip()
            email = (row.get("email") or "").strip().lower()
            if (row.get("website") or "").strip():
                counts["has_website"] += 1
                continue
            if not name or not EMAIL_RE.match(email):
                counts["bad_email"] += 1
                continue
            if db.is_suppressed(conn, email):
                counts["suppressed"] += 1
                continue
            lead_id = db.add_lead(conn, name, email, (row.get("category") or "").strip(),
                                  (row.get("city") or "").strip())
            counts["added" if lead_id else "duplicate"] += 1
    return counts


def _require_live_config(cfg: Config) -> None:
    missing = cfg.missing_for_live_send()
    if missing:
        sys.exit(f"Live sending needs these environment variables: {', '.join(missing)}")
    if not cfg.company_name:
        sys.exit("Live sending needs OUTREACH_COMPANY_NAME")
    if "@" not in cfg.from_email:
        sys.exit("OUTREACH_FROM_EMAIL must be an email address")


def _fields(cfg: Config, lead) -> dict[str, str]:
    return {
        "business_name": lead["business_name"],
        "city": lead["city"] or "your area",
        "category": lead["category"] or "business",
        "company_name": cfg.company_name or "[Your Company]",
        "sender_name": cfg.sender_name or "[Your Name]",
        "postal_address": cfg.postal_address or "[Your Postal Address]",
        "from_email": cfg.from_email or "[from address]",
    }


def _send_one(cfg: Config, conn, lead, kind: str, live: bool) -> None:
    if kind == "pitch":
        subject_t, body_t = templates.PITCH_SUBJECT, templates.PITCH_BODY
        new_status = "pitched"
    else:
        subject_t, body_t = templates.FOLLOWUP_SUBJECT, templates.FOLLOWUP_BODY
        new_status = "followed_up"

    fields = _fields(cfg, lead)
    subject = templates.render(subject_t, **fields)
    body = templates.render(body_t, **fields)
    msg = mailer.build_message(cfg, lead["email"], subject, body)
    message_id = mailer.send(cfg, msg, live=live)

    db.record_message(conn, lead["id"], "out", kind, subject, body, message_id)
    db.mark_contacted(conn, lead["id"], new_status, followup=(kind == "followup"))
    label = "SENT" if live else "DRAFT"
    print(f"  {label} {kind:8} -> {lead['email']} ({lead['business_name']})")


def cmd_send(cfg: Config, conn, live: bool, kind: str) -> None:
    if live:
        _require_live_config(cfg)
    if not live:
        print(f"Dry run: writing .eml files to {cfg.outbox_dir} (nothing is sent)")

    if kind == "pitch":
        candidates = db.leads_with_status(conn, "new")
    else:
        candidates = db.followups_due(conn, cfg.followup_days)

    queue = []
    for lead in candidates:
        if db.is_suppressed(conn, lead["email"]):
            db.set_status(conn, lead["id"], "unsubscribed")
            continue
        queue.append(lead)
    queue = queue[: cfg.max_per_run]

    if not queue:
        print("Nothing to send.")
        return

    for i, lead in enumerate(queue):
        _send_one(cfg, conn, lead, kind, live)
        if live and i < len(queue) - 1:
            time.sleep(MIN_SECONDS_BETWEEN_SENDS)
    print(f"Done: {len(queue)} {kind} message(s).")


def cmd_poll(cfg: Config, conn, live: bool) -> None:
    missing = cfg.missing_for_inbox()
    if missing:
        sys.exit(f"Reading replies needs these environment variables: {', '.join(missing)}")
    events = inbox.poll(cfg, conn)
    if not events:
        print("No new replies from known leads.")
        return
    for ev in events:
        flag = "NEEDS HUMAN" if ev.intent in ("interested", "question", "other") else ""
        print(f"  [{ev.intent:14}] {ev.business_name}  {flag}")
        print(f"      {ev.body.splitlines()[0] if ev.body.strip() else '(empty)'}")


def cmd_status(conn) -> None:
    rows = conn.execute("SELECT status, COUNT(*) AS n FROM leads GROUP BY status ORDER BY status").fetchall()
    print("Leads by status:")
    for r in rows:
        print(f"  {r['status']:15} {r['n']}")
    for status in ("interested", "question"):
        leads = db.leads_with_status(conn, status)
        if leads:
            print(f"\nNeeds a human reply ({status}):")
            for lead in leads:
                print(f"  {lead['business_name']} <{lead['email']}>")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="outreach", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="load leads from a CSV")
    p.add_argument("csv_path", type=Path)

    for name in ("send", "followup"):
        p = sub.add_parser(name, help="draft (default) or send (--live) emails")
        p.add_argument("--live", action="store_true", help="actually send. Without this, only .eml drafts are written.")

    p = sub.add_parser("poll", help="read and classify replies over IMAP")
    p.add_argument("--live", action="store_true", help="accepted for symmetry; polling never sends mail")

    sub.add_parser("status", help="show lead counts and items needing a human")

    args = parser.parse_args(argv)
    cfg = load_config()
    conn = db.connect(cfg.db_path)

    if args.cmd == "import":
        print(import_leads(conn, args.csv_path))
    elif args.cmd == "send":
        cmd_send(cfg, conn, args.live, kind="pitch")
    elif args.cmd == "followup":
        cmd_send(cfg, conn, args.live, kind="followup")
    elif args.cmd == "poll":
        cmd_poll(cfg, conn, args.live)
    elif args.cmd == "status":
        cmd_status(conn)


if __name__ == "__main__":
    main()
