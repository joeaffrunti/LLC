"""SQLite storage for leads, every message in or out, and the suppression list."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

# Lead lifecycle:
#   new            imported, not yet pitched
#   pitched        first pitch sent, waiting for a reply
#   followed_up    one follow-up sent, waiting for a reply (no further automatic mail)
#   interested     replied positively; needs a human
#   question       replied with a question; needs a human
#   not_interested replied no; closed
#   unsubscribed   asked to stop; suppressed forever
#   bounced        address rejected; closed
#   closed         ran out of follow-ups with no reply
STATUSES = {
    "new", "pitched", "followed_up", "interested", "question",
    "not_interested", "unsubscribed", "bounced", "closed",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id              INTEGER PRIMARY KEY,
    business_name   TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category        TEXT NOT NULL DEFAULT '',
    city            TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'new',
    last_contacted  REAL,
    followups_sent  INTEGER NOT NULL DEFAULT 0,
    created         REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY,
    lead_id     INTEGER NOT NULL REFERENCES leads(id),
    direction   TEXT NOT NULL CHECK (direction IN ('out', 'in')),
    kind        TEXT NOT NULL,          -- pitch | followup | reply | bounce
    subject     TEXT NOT NULL DEFAULT '',
    body        TEXT NOT NULL DEFAULT '',
    message_id  TEXT UNIQUE,
    intent      TEXT,
    created     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS suppression (
    email    TEXT PRIMARY KEY COLLATE NOCASE,
    reason   TEXT NOT NULL,
    created  REAL NOT NULL
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def now() -> float:
    return time.time()


# ---- leads -----------------------------------------------------------------

def add_lead(conn, business_name: str, email: str, category: str = "", city: str = "") -> int | None:
    """Insert a lead. Returns the new id, or None if the email already exists."""
    try:
        cur = conn.execute(
            "INSERT INTO leads (business_name, email, category, city, created) VALUES (?, ?, ?, ?, ?)",
            (business_name, email, category, city, now()),
        )
    except sqlite3.IntegrityError:
        return None
    conn.commit()
    return cur.lastrowid


def get_lead_by_email(conn, email: str):
    return conn.execute("SELECT * FROM leads WHERE email = ?", (email,)).fetchone()


def get_lead(conn, lead_id: int):
    return conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def leads_with_status(conn, status: str, limit: int | None = None):
    sql = "SELECT * FROM leads WHERE status = ? ORDER BY id"
    params: tuple = (status,)
    if limit is not None:
        sql += " LIMIT ?"
        params += (limit,)
    return conn.execute(sql, params).fetchall()


def set_status(conn, lead_id: int, status: str) -> None:
    if status not in STATUSES:
        raise ValueError(f"unknown status: {status}")
    conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
    conn.commit()


def mark_contacted(conn, lead_id: int, status: str, followup: bool = False) -> None:
    conn.execute(
        "UPDATE leads SET status = ?, last_contacted = ?, followups_sent = followups_sent + ? WHERE id = ?",
        (status, now(), 1 if followup else 0, lead_id),
    )
    conn.commit()


def followups_due(conn, days: int):
    cutoff = now() - days * 86400
    return conn.execute(
        "SELECT * FROM leads WHERE status = 'pitched' AND followups_sent = 0 "
        "AND last_contacted IS NOT NULL AND last_contacted <= ? ORDER BY id",
        (cutoff,),
    ).fetchall()


# ---- messages --------------------------------------------------------------

def record_message(conn, lead_id: int, direction: str, kind: str, subject: str = "",
                   body: str = "", message_id: str | None = None, intent: str | None = None) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO messages (lead_id, direction, kind, subject, body, message_id, intent, created) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (lead_id, direction, kind, subject, body, message_id, intent, now()),
    )
    conn.commit()


def find_lead_for_message_id(conn, message_id: str):
    """Return the lead we sent a message to, given a Message-ID we generated."""
    row = conn.execute(
        "SELECT lead_id FROM messages WHERE direction = 'out' AND message_id = ?", (message_id,)
    ).fetchone()
    return get_lead(conn, row["lead_id"]) if row else None


def messages_for_lead(conn, lead_id: int):
    return conn.execute("SELECT * FROM messages WHERE lead_id = ? ORDER BY created", (lead_id,)).fetchall()


# ---- suppression -----------------------------------------------------------

def suppress(conn, email: str, reason: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO suppression (email, reason, created) VALUES (?, ?, ?)",
        (email, reason, now()),
    )
    conn.commit()


def is_suppressed(conn, email: str) -> bool:
    return conn.execute("SELECT 1 FROM suppression WHERE email = ?", (email,)).fetchone() is not None
