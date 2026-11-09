"""Runtime configuration, read from environment variables.

Nothing secret lives in the repo. Set these in your shell or a local .env you
load yourself (never commit credentials).

Required for --live sending:
  OUTREACH_FROM_EMAIL     address the pitches come from, e.g. you@yourdomain.com
  OUTREACH_COMPANY_NAME   your business name, as it appears in the pitch
  OUTREACH_SENDER_NAME    your name as it should appear in the signature
  OUTREACH_POSTAL_ADDRESS physical mailing address (required by CAN-SPAM in every commercial email)
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD

Required for reply handling (`poll`):
  IMAP_HOST, IMAP_PORT, IMAP_USER, IMAP_PASSWORD  (often the same mailbox as SMTP)

Optional:
  OUTREACH_DB             path to the SQLite database (default outreach/data/outreach.db)
  OUTREACH_OUTBOX         folder where dry-run .eml files are written (default outreach/outbox)
  OUTREACH_MAX_PER_RUN    max pitches/follow-ups sent in one run (default 25)
  OUTREACH_FOLLOWUP_DAYS  days to wait before a single follow-up (default 7)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent


@dataclass
class Config:
    db_path: Path
    outbox_dir: Path
    from_email: str
    company_name: str
    sender_name: str
    postal_address: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    imap_host: str
    imap_port: int
    imap_user: str
    imap_password: str
    max_per_run: int
    followup_days: int

    def missing_for_live_send(self) -> list[str]:
        required = {
            "OUTREACH_FROM_EMAIL": self.from_email,
            "OUTREACH_COMPANY_NAME": self.company_name,
            "OUTREACH_SENDER_NAME": self.sender_name,
            "OUTREACH_POSTAL_ADDRESS": self.postal_address,
            "SMTP_HOST": self.smtp_host,
            "SMTP_USER": self.smtp_user,
            "SMTP_PASSWORD": self.smtp_password,
        }
        return [name for name, value in required.items() if not value]

    def missing_for_inbox(self) -> list[str]:
        required = {
            "IMAP_HOST": self.imap_host,
            "IMAP_USER": self.imap_user,
            "IMAP_PASSWORD": self.imap_password,
        }
        return [name for name, value in required.items() if not value]


def load_config(env: dict[str, str] | None = None) -> Config:
    env = dict(os.environ if env is None else env)
    return Config(
        db_path=Path(env.get("OUTREACH_DB", PACKAGE_DIR / "data" / "outreach.db")),
        outbox_dir=Path(env.get("OUTREACH_OUTBOX", PACKAGE_DIR / "outbox")),
        from_email=env.get("OUTREACH_FROM_EMAIL", ""),
        company_name=env.get("OUTREACH_COMPANY_NAME", ""),
        sender_name=env.get("OUTREACH_SENDER_NAME", ""),
        postal_address=env.get("OUTREACH_POSTAL_ADDRESS", ""),
        smtp_host=env.get("SMTP_HOST", ""),
        smtp_port=int(env.get("SMTP_PORT", "587")),
        smtp_user=env.get("SMTP_USER", ""),
        smtp_password=env.get("SMTP_PASSWORD", ""),
        imap_host=env.get("IMAP_HOST", ""),
        imap_port=int(env.get("IMAP_PORT", "993")),
        imap_user=env.get("IMAP_USER", ""),
        imap_password=env.get("IMAP_PASSWORD", ""),
        max_per_run=int(env.get("OUTREACH_MAX_PER_RUN", "25")),
        followup_days=int(env.get("OUTREACH_FOLLOWUP_DAYS", "7")),
    )
