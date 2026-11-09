"""Build and send pitch emails. Dry-run writes .eml files instead of sending."""

from __future__ import annotations

import smtplib
import time
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from .config import Config


def build_message(cfg: Config, to_email: str, subject: str, body: str) -> EmailMessage:
    domain = cfg.from_email.split("@")[-1] if "@" in cfg.from_email else "localhost"
    msg = EmailMessage()
    msg["From"] = f"{cfg.sender_name} <{cfg.from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=domain)
    # One-click-style unsubscribe hint for mail clients; replies are also honored.
    msg["List-Unsubscribe"] = f"<mailto:{cfg.from_email}?subject=unsubscribe>"
    msg.set_content(body)
    return msg


def send(cfg: Config, msg: EmailMessage, live: bool) -> str:
    """Send the message (live) or write it to the outbox (dry run). Returns the Message-ID."""
    message_id = msg["Message-ID"]
    if not live:
        cfg.outbox_dir.mkdir(parents=True, exist_ok=True)
        safe_to = msg["To"].replace("@", "_at_")
        path = cfg.outbox_dir / f"{int(time.time() * 1000)}_{safe_to}.eml"
        path.write_bytes(bytes(msg))
        return message_id

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
        smtp.starttls()
        smtp.login(cfg.smtp_user, cfg.smtp_password)
        smtp.send_message(msg)
    return message_id
