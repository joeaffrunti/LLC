"""Read replies over IMAP and apply them to the lead database."""

from __future__ import annotations

import email
import imaplib
import re
from dataclasses import dataclass
from email.message import Message
from email.utils import parseaddr

from . import db
from .classify import classify
from .config import Config

_BOUNCE_SENDERS = re.compile(r"mailer-daemon|postmaster", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass
class Event:
    lead_id: int
    business_name: str
    kind: str          # reply | bounce
    intent: str
    subject: str
    body: str


def _body_text(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                payload = part.get_payload(decode=True) or b""
                return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        return ""
    payload = msg.get_payload(decode=True) or b""
    return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")


def _referenced_message_ids(msg: Message) -> list[str]:
    refs = " ".join(filter(None, [msg.get("In-Reply-To", ""), msg.get("References", "")]))
    return re.findall(r"<[^>]+>", refs)


def handle_message(conn, raw: Message) -> Event | None:
    """Apply one inbound message to the database. Returns an Event, or None if unrelated."""
    subject = raw.get("Subject", "")
    sender = parseaddr(raw.get("From", ""))[1].lower()
    body = _body_text(raw)

    # Skip messages we have already processed (IMAP may re-deliver them).
    if raw.get("Message-ID") and db.message_seen(conn, raw["Message-ID"]):
        return None

    # 1) Bounces: find the original recipient address inside the DSN body.
    if _BOUNCE_SENDERS.search(sender):
        for candidate in _EMAIL_RE.findall(body):
            lead = db.get_lead_by_email(conn, candidate.lower())
            if lead:
                db.set_status(conn, lead["id"], "bounced")
                db.suppress(conn, lead["email"], "bounced")
                db.record_message(conn, lead["id"], "in", "bounce", subject, body[:2000],
                                  raw.get("Message-ID"), "bounce")
                return Event(lead["id"], lead["business_name"], "bounce", "bounce", subject, body[:500])
        return None

    # 2) Replies: match by threading headers first, then by sender address.
    lead = None
    for mid in _referenced_message_ids(raw):
        lead = db.find_lead_for_message_id(conn, mid)
        if lead:
            break
    if lead is None and sender:
        lead = db.get_lead_by_email(conn, sender)
    if lead is None:
        return None

    intent = classify(body)
    db.record_message(conn, lead["id"], "in", "reply", subject, body, raw.get("Message-ID"), intent)

    if intent == "unsubscribe":
        db.suppress(conn, lead["email"], "unsubscribe reply")
        db.set_status(conn, lead["id"], "unsubscribed")
    elif intent == "not_interested":
        db.set_status(conn, lead["id"], "not_interested")
    elif intent in ("interested", "question"):
        db.set_status(conn, lead["id"], intent)
    # out_of_office and other: leave status alone so a human (or the next follow-up pass) sees it.

    return Event(lead["id"], lead["business_name"], "reply", intent, subject, body[:500])


def poll(cfg: Config, conn) -> list[Event]:
    """Fetch unseen messages from the inbox and process them."""
    events: list[Event] = []
    imap = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
    try:
        imap.login(cfg.imap_user, cfg.imap_password)
        imap.select("INBOX")
        _, data = imap.search(None, "UNSEEN")
        for num in data[0].split():
            _, fetched = imap.fetch(num, "(RFC822)")
            raw = email.message_from_bytes(fetched[0][1])
            event = handle_message(conn, raw)
            if event:
                events.append(event)
    finally:
        try:
            imap.logout()
        except imaplib.IMAP4.error:
            pass
    return events
