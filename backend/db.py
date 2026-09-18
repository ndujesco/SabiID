"""SQLite schema and a few thin helpers. One file, no ORM."""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from .config import DB_PATH

_LOCAL = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS citizens (
    sid            TEXT PRIMARY KEY,
    nin            TEXT,
    bvn            TEXT,
    credential     TEXT,
    disclosures    TEXT,          -- JSON, wallet-only plaintext
    bio_enrolment  TEXT,          -- JSON {salt, hash}
    enrolled_at    INTEGER
);

CREATE TABLE IF NOT EXISTS partners (
    partner_id   TEXT PRIMARY KEY,
    display_name TEXT,
    kind         TEXT,            -- bank | hospital | payroll
    allowed_scope TEXT            -- JSON list of predicate families
);

CREATE TABLE IF NOT EXISTS revocations (
    sid        TEXT,
    partner_id TEXT,
    revoked_at INTEGER,
    PRIMARY KEY (sid, partner_id)
);

CREATE TABLE IF NOT EXISTS requests (
    request_id   TEXT PRIMARY KEY,
    partner_id   TEXT,
    sid          TEXT,
    purpose      TEXT,
    scope        TEXT,            -- JSON list of predicates asked
    status       TEXT,            -- pending | consented | completed | rejected
    approved     TEXT,            -- JSON list of predicates the citizen allowed
    result       TEXT,            -- JSON presentation
    created_at   INTEGER,
    decided_at   INTEGER
);

CREATE TABLE IF NOT EXISTS ledger (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER,
    event_type  TEXT,
    actor       TEXT,
    subject_sid TEXT,
    detail      TEXT,             -- JSON, no personal data by construction
    prev_hash   TEXT,
    entry_hash  TEXT
);

CREATE TABLE IF NOT EXISTS payroll_roster (
    employee_no    TEXT PRIMARY KEY,
    ministry_id    TEXT,
    sid            TEXT,          -- may be NULL for a fabricated line
    display_name   TEXT,
    monthly_naira  INTEGER,
    ground_truth   TEXT,          -- active | deceased | relocated | fabricated | bad_network
    missed_cycles  INTEGER DEFAULT 0,
    last_status    TEXT
);

CREATE TABLE IF NOT EXISTS payroll_cycles (
    cycle_id    TEXT PRIMARY KEY,
    ministry_id TEXT,
    ran_at      INTEGER,
    offline     INTEGER,
    summary     TEXT              -- JSON
);

CREATE TABLE IF NOT EXISTS payroll_decisions (
    cycle_id       TEXT,
    employee_no    TEXT,
    outcome        TEXT,          -- released | withheld | queued
    reason         TEXT,
    amount_naira   INTEGER,
    ledger_seq     INTEGER
);
"""


def conn() -> sqlite3.Connection:
    c = getattr(_LOCAL, "conn", None)
    if c is None:
        c = sqlite3.connect(DB_PATH, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        _LOCAL.conn = c
    return c


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn().executescript(SCHEMA)
    conn().commit()


def now() -> int:
    return int(time.time())


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def loads(txt):
    return json.loads(txt) if txt else None
