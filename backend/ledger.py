"""
The proof-of-check log.

Every question asked through the gateway is written here as one line. Each line
carries the SHA-256 hash of the line before it, so the whole file is a chain. If
anyone edits or deletes a past line, every hash from that point on stops
matching and the break points straight at the tampered row.

By construction a line holds no personal data: a pseudonymous SID, the partner
id, the names of the predicates asked, the yes/no outcomes, and hashes. It never
holds a date of birth, an address, or a raw biometric.
"""
from __future__ import annotations

import hashlib

from .crypto import canonical
from .db import conn, dumps, loads, now

GENESIS = "0" * 64


def _hash_row(seq: int, ts: int, event_type: str, actor: str,
              subject_sid: str | None, detail: dict, prev_hash: str) -> str:
    body = canonical({
        "seq": seq, "ts": ts, "event_type": event_type, "actor": actor,
        "subject_sid": subject_sid, "detail": detail,
    })
    return hashlib.sha256((prev_hash + "\n").encode() + body).hexdigest()


def append(event_type: str, actor: str, detail: dict,
           subject_sid: str | None = None, ts: int | None = None) -> int:
    c = conn()
    row = c.execute("SELECT seq, entry_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    prev_hash = row["entry_hash"] if row else GENESIS
    seq = (row["seq"] + 1) if row else 1
    ts = ts if ts is not None else now()
    entry_hash = _hash_row(seq, ts, event_type, actor, subject_sid, detail, prev_hash)
    c.execute(
        "INSERT INTO ledger (seq, ts, event_type, actor, subject_sid, detail, prev_hash, entry_hash) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (seq, ts, event_type, actor, subject_sid, dumps(detail), prev_hash, entry_hash),
    )
    c.commit()
    return seq


def entries(limit: int = 200) -> list[dict]:
    rows = conn().execute(
        "SELECT * FROM ledger ORDER BY seq ASC LIMIT ?", (limit,)
    ).fetchall()
    return [
        {
            "seq": r["seq"], "ts": r["ts"], "event_type": r["event_type"],
            "actor": r["actor"], "subject_sid": r["subject_sid"],
            "detail": loads(r["detail"]), "prev_hash": r["prev_hash"],
            "entry_hash": r["entry_hash"],
        }
        for r in rows
    ]


def head() -> dict:
    """The tip of the chain. An auditor notes this out of band so that later
    truncation, which a pure hash chain cannot see on its own, becomes visible."""
    r = conn().execute("SELECT seq, entry_hash FROM ledger ORDER BY seq DESC LIMIT 1").fetchone()
    return {"seq": r["seq"], "entry_hash": r["entry_hash"]} if r else {"seq": 0, "entry_hash": GENESIS}


def verify_chain(expected_head_seq: int | None = None) -> dict:
    rows = conn().execute("SELECT * FROM ledger ORDER BY seq ASC").fetchall()
    prev_hash = GENESIS
    expected_seq = 1
    if expected_head_seq is not None and (not rows or rows[-1]["seq"] < expected_head_seq):
        return {"ok": False, "broken_at": expected_head_seq,
                "detail": f"the chain has been cut short: last noted line was {expected_head_seq}, "
                          f"now ends at {rows[-1]['seq'] if rows else 0}",
                "checked": len(rows)}
    for r in rows:
        if r["seq"] != expected_seq:
            return {
                "ok": False,
                "broken_at": expected_seq,
                "detail": f"a line is missing: expected seq {expected_seq}, found {r['seq']}",
                "checked": expected_seq - 1,
            }
        recomputed = _hash_row(
            r["seq"], r["ts"], r["event_type"], r["actor"], r["subject_sid"],
            loads(r["detail"]), prev_hash,
        )
        if r["prev_hash"] != prev_hash:
            return {
                "ok": False, "broken_at": r["seq"],
                "detail": f"line {r['seq']} does not point at the line before it",
                "checked": r["seq"] - 1,
            }
        if recomputed != r["entry_hash"]:
            return {
                "ok": False, "broken_at": r["seq"],
                "detail": f"line {r['seq']} was changed after it was written",
                "checked": r["seq"] - 1,
            }
        prev_hash = r["entry_hash"]
        expected_seq += 1
    return {"ok": True, "broken_at": None, "detail": "every line checks out", "checked": len(rows)}
