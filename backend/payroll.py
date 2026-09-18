"""
The centrepiece: catching ghost workers and ghost pensioners.

Nothing new is built here. It is the same prove-without-revealing check from
gateway.py, asked on a schedule instead of once. Before a ministry pays a
salary or a pension line, SabiID asks one question through the gateway: is this
still the same living person we enrolled as employee or pensioner number X?

The person answers with a fresh face or fingerprint on their phone. The gateway
compares it to the enrolment hash and returns a plain yes or no. No raw
biometric moves. No new record is created. If the answer is no, or nobody
answers, that one line is held back for manual review and the log entry becomes
the reason the money was stopped.
"""
from __future__ import annotations

import secrets

from . import ledger, sources
from .config import GHOST_MISS_THRESHOLD
from .crypto import bio_verify, sha256_b64
from .db import conn, dumps, loads, now
from .simulation import fresh_bio_sample


def roster(ministry_id: str) -> list[dict]:
    rows = conn().execute(
        "SELECT * FROM payroll_roster WHERE ministry_id=? ORDER BY employee_no", (ministry_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _citizen(sid: str | None) -> dict | None:
    if not sid:
        return None
    r = conn().execute("SELECT * FROM citizens WHERE sid=?", (sid,)).fetchone()
    return dict(r) if r else None


def _simulate_response(line: dict, cycle_index: int) -> str | None:
    """
    Stand in for the citizen tapping the prompt on their phone. Returns a fresh
    biometric sample string, or None when nobody answers.
    """
    gt = line["ground_truth"]
    if gt == "active":
        return fresh_bio_sample(line["sid"], matches=True)
    if gt == "bad_network":
        # a real staff member, simply out of signal on the first sweep
        return None if cycle_index == 0 else fresh_bio_sample(line["sid"], matches=True)
    if gt == "impersonation":
        return fresh_bio_sample(line["sid"], matches=False)
    # deceased, relocated, fabricated: no answer
    return None


def run_cycle(ministry_id: str, offline: bool = False, grace: bool = True) -> dict:
    cycle_id = "CYC-" + secrets.token_hex(4).upper()
    lines = roster(ministry_id)
    ran_at = now()
    decisions: list[dict] = []
    released_naira = withheld_naira = 0

    for line in lines:
        emp = line["employee_no"]
        emp_hash = sha256_b64(emp.encode())
        amount = line["monthly_naira"]
        cit = _citizen(line["sid"])

        if offline:
            conn().execute(
                "INSERT INTO payroll_decisions (cycle_id, employee_no, outcome, reason, amount_naira, ledger_seq) "
                "VALUES (?,?,?,?,?,?)",
                (cycle_id, emp, "queued",
                 "The identity sources were unreachable. This line was queued, not paid.",
                 amount, None),
            )
            seq = ledger.append("payroll.queued", actor=ministry_id, subject_sid=line["sid"],
                                detail={"cycle_id": cycle_id, "employee_no_hash": emp_hash,
                                        "amount_naira": amount})
            conn().execute("UPDATE payroll_decisions SET ledger_seq=? WHERE cycle_id=? AND employee_no=?",
                           (seq, cycle_id, emp))
            decisions.append({"employee_no": emp, "display_name": line["display_name"],
                              "outcome": "queued", "reason": "sources offline, queued",
                              "amount_naira": amount, "ledger_seq": seq})
            continue

        # 1. a fabricated line has no identity to check at all
        if not cit:
            outcome, reason = "withheld", ("No NIN record exists for this employee number. "
                                          "This line was never a real person.")
        else:
            # 2. the civil registry answers before we even wait for a phone
            death = None
            try:
                death = sources.lookup_civil_registry(cit["nin"])
            except sources.SourceUnavailable:
                death = None
            if death and death.get("status") == "deceased":
                outcome, reason = "withheld", (
                    f"The Civil Registration service lists this person as deceased since "
                    f"{death['death_date']}. Payment stopped.")
            else:
                # 3. the living-person check
                sample = _simulate_response(line, cycle_index=line["missed_cycles"])
                stored = loads(cit["bio_enrolment"])
                alive_and_present = bool(sample) and bio_verify(sample, stored)

                if alive_and_present:
                    conn().execute("UPDATE payroll_roster SET missed_cycles=0 WHERE employee_no=?", (emp,))
                    outcome, reason = "released", "Confirmed by a fresh living-person check this cycle."
                else:
                    missed = line["missed_cycles"] + 1
                    conn().execute("UPDATE payroll_roster SET missed_cycles=? WHERE employee_no=?", (missed, emp))
                    if sample and not alive_and_present:
                        outcome, reason = "withheld", (
                            "A fresh sample was offered but it did not match the enrolment hash. "
                            "Possible impersonation. Held for manual review.")
                    elif not grace or missed >= GHOST_MISS_THRESHOLD:
                        outcome, reason = "withheld", (
                            f"No living-person confirmation ({missed} cycle(s) missed). "
                            f"Held for manual review. A real staff member out of network signal "
                            f"looks identical to a ghost at this point.")
                    else:
                        outcome, reason = "released", (
                            f"No confirmation this cycle ({missed}/{GHOST_MISS_THRESHOLD}). "
                            f"Paid under grace. Payment stops at {GHOST_MISS_THRESHOLD} missed cycles.")

        if outcome == "released":
            released_naira += amount
        elif outcome == "withheld":
            withheld_naira += amount

        seq = ledger.append(
            "payroll.decision", actor=ministry_id, subject_sid=line["sid"],
            detail={"cycle_id": cycle_id, "employee_no_hash": emp_hash,
                    "outcome": outcome, "reason": reason, "amount_naira": amount},
        )
        conn().execute("UPDATE payroll_roster SET last_status=? WHERE employee_no=?", (outcome, emp))
        conn().execute(
            "INSERT INTO payroll_decisions (cycle_id, employee_no, outcome, reason, amount_naira, ledger_seq) "
            "VALUES (?,?,?,?,?,?)",
            (cycle_id, emp, outcome, reason, amount, seq),
        )
        decisions.append({"employee_no": emp, "display_name": line["display_name"],
                          "outcome": outcome, "reason": reason, "amount_naira": amount,
                          "ledger_seq": seq, "ground_truth": line["ground_truth"]})

    summary = {
        "cycle_id": cycle_id, "ministry_id": ministry_id, "offline": offline, "grace": grace,
        "lines": len(lines),
        "released": sum(1 for d in decisions if d["outcome"] == "released"),
        "withheld": sum(1 for d in decisions if d["outcome"] == "withheld"),
        "queued": sum(1 for d in decisions if d["outcome"] == "queued"),
        "released_naira": released_naira, "withheld_naira": withheld_naira,
    }
    conn().execute(
        "INSERT INTO payroll_cycles (cycle_id, ministry_id, ran_at, offline, summary) VALUES (?,?,?,?,?)",
        (cycle_id, ministry_id, ran_at, int(offline), dumps(summary)),
    )
    conn().commit()
    return {"summary": summary, "decisions": decisions}


def reconcile(cycle_id: str) -> dict:
    """Replay a queued cycle once the sources are back."""
    row = conn().execute("SELECT * FROM payroll_cycles WHERE cycle_id=?", (cycle_id,)).fetchone()
    if not row:
        raise ValueError("no such cycle")
    ministry_id = row["ministry_id"]
    queued = conn().execute(
        "SELECT * FROM payroll_decisions WHERE cycle_id=? AND outcome='queued'", (cycle_id,)
    ).fetchall()
    if not queued:
        return {"reconciled": 0, "note": "nothing was queued for this cycle"}

    was_offline = sources.is_offline()
    sources.set_offline(False)
    try:
        replay = run_cycle(ministry_id, offline=False, grace=True)
    finally:
        sources.set_offline(was_offline)

    for q in queued:
        conn().execute(
            "UPDATE payroll_decisions SET outcome='reconciled', "
            "reason='Replayed after the sources came back. See the reconciling cycle.' "
            "WHERE cycle_id=? AND employee_no=?",
            (cycle_id, q["employee_no"]),
        )
    ledger.append("payroll.reconciled", actor=ministry_id, subject_sid=None,
                  detail={"queued_cycle": cycle_id, "reconciling_cycle": replay["summary"]["cycle_id"],
                          "lines": len(queued)})
    conn().commit()
    return {"reconciled": len(queued), "reconciling_cycle": replay["summary"]["cycle_id"],
            "replay": replay}


def decisions_for(cycle_id: str) -> list[dict]:
    rows = conn().execute(
        "SELECT d.*, r.display_name, r.ground_truth FROM payroll_decisions d "
        "LEFT JOIN payroll_roster r ON r.employee_no=d.employee_no WHERE d.cycle_id=? ORDER BY d.employee_no",
        (cycle_id,),
    ).fetchall()
    return [dict(r) for r in rows]
