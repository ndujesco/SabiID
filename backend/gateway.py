"""
The broker.

A partner asks a narrow question about one SID. The citizen sees the exact list
and approves it field by field. The gateway then evaluates only the approved
predicates against the live source records, signs the answers, writes one line
to the proof-of-check log, and hands back yes/no plus, where a value was
genuinely needed, the single minimised value with an SD-JWT proof.

The underlying record is never returned.
"""
from __future__ import annotations

import re
import secrets
import unicodedata
from datetime import date, datetime

from . import ledger, sources
from .config import ATTESTATION_TTL_SECONDS, LIVENESS_WINDOW_SECONDS
from .crypto import check_presentation, sign_attestation
from .db import conn, dumps, loads, now
from .simulation import enrolment_bio_sample  # only used to detect a stale window
from .crypto import bio_verify

# predicate families a partner kind is allowed to touch at all
FAMILY = {
    "age_over_18": "age", "age_over_21": "age", "age_over_65": "age",
    "is_verified": "identity", "nin_bvn_name_consistency": "kyc_consistency",
    "liveness_present": "liveness",
}


def _family(predicate: str) -> str:
    head = predicate.split(":", 1)[0]
    if head in FAMILY:
        return FAMILY[head]
    if head == "name_matches":
        return "name"
    if head == "state_of_residence_is":
        return "state"
    if head.startswith("reveal"):
        return "identity"
    return "health" if head in {"genotype", "blood_group", "allergies"} else "other"


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s.casefold()


def _age_on(dob_iso: str, ref: date | None = None) -> int:
    ref = ref or date.today()
    d = datetime.strptime(dob_iso, "%Y-%m-%d").date()
    return ref.year - d.year - ((ref.month, ref.day) < (d.month, d.day))


# --------------------------------------------------------------- partner setup

def register_partner(partner_id: str, display_name: str, kind: str, allowed_scope: list[str]) -> None:
    conn().execute(
        "INSERT OR REPLACE INTO partners (partner_id, display_name, kind, allowed_scope) VALUES (?,?,?,?)",
        (partner_id, display_name, kind, dumps(allowed_scope)),
    )
    conn().commit()


def get_partner(partner_id: str) -> dict | None:
    r = conn().execute("SELECT * FROM partners WHERE partner_id=?", (partner_id,)).fetchone()
    return dict(r) | {"allowed_scope": loads(r["allowed_scope"])} if r else None


def list_partners() -> list[dict]:
    rows = conn().execute("SELECT * FROM partners ORDER BY display_name").fetchall()
    return [dict(r) | {"allowed_scope": loads(r["allowed_scope"])} for r in rows]


def is_revoked(sid: str, partner_id: str) -> bool:
    return conn().execute(
        "SELECT 1 FROM revocations WHERE sid=? AND partner_id=?", (sid, partner_id)
    ).fetchone() is not None


def revoke(sid: str, partner_id: str) -> None:
    conn().execute(
        "INSERT OR REPLACE INTO revocations (sid, partner_id, revoked_at) VALUES (?,?,?)",
        (sid, partner_id, now()),
    )
    conn().commit()
    ledger.append("access.revoked", actor=sid, subject_sid=sid,
                  detail={"partner": partner_id})


def unrevoke(sid: str, partner_id: str) -> None:
    conn().execute("DELETE FROM revocations WHERE sid=? AND partner_id=?", (sid, partner_id))
    conn().commit()


# ------------------------------------------------------------- request records

def _citizen(sid: str) -> dict | None:
    r = conn().execute("SELECT * FROM citizens WHERE sid=?", (sid,)).fetchone()
    return dict(r) if r else None


def create_request(partner_id: str, sid: str, purpose: str, scope: list[str]) -> dict:
    partner = get_partner(partner_id)
    if not partner:
        raise ValueError("unknown partner")
    cit = _citizen(sid)
    request_id = "REQ-" + secrets.token_hex(5).upper()

    if not cit:
        status = "rejected"
        conn().execute(
            "INSERT INTO requests (request_id, partner_id, sid, purpose, scope, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (request_id, partner_id, sid, purpose, dumps(scope), status, now()),
        )
        conn().commit()
        ledger.append("request.rejected", actor=partner_id, subject_sid=sid,
                      detail={"request_id": request_id, "reason": "no such enrolled SID",
                              "scope": scope})
        return {"request_id": request_id, "status": status,
                "reason": "That SID is not enrolled with SabiID."}

    if is_revoked(sid, partner_id):
        status = "rejected"
        conn().execute(
            "INSERT INTO requests (request_id, partner_id, sid, purpose, scope, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (request_id, partner_id, sid, purpose, dumps(scope), status, now()),
        )
        conn().commit()
        ledger.append("request.rejected", actor=partner_id, subject_sid=sid,
                      detail={"request_id": request_id, "reason": "citizen has revoked this partner",
                              "scope": scope})
        return {"request_id": request_id, "status": status,
                "reason": "This citizen has revoked your access."}

    disallowed = [p for p in scope if _family(p) not in set(partner["allowed_scope"])]
    if disallowed:
        status = "rejected"
        conn().execute(
            "INSERT INTO requests (request_id, partner_id, sid, purpose, scope, status, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (request_id, partner_id, sid, purpose, dumps(scope), status, now()),
        )
        conn().commit()
        ledger.append("request.rejected", actor=partner_id, subject_sid=sid,
                      detail={"request_id": request_id, "reason": "scope outside partner grant",
                              "disallowed": disallowed})
        return {"request_id": request_id, "status": status,
                "reason": f"Your partner grant does not cover: {', '.join(disallowed)}."}

    conn().execute(
        "INSERT INTO requests (request_id, partner_id, sid, purpose, scope, status, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (request_id, partner_id, sid, purpose, dumps(scope), "pending", now()),
    )
    conn().commit()
    ledger.append("request.created", actor=partner_id, subject_sid=sid,
                  detail={"request_id": request_id, "purpose": purpose, "scope": scope})
    return {"request_id": request_id, "status": "pending"}


def list_pending(sid: str) -> list[dict]:
    rows = conn().execute(
        "SELECT r.*, p.display_name FROM requests r JOIN partners p ON p.partner_id=r.partner_id "
        "WHERE r.sid=? AND r.status='pending' ORDER BY r.created_at DESC",
        (sid,),
    ).fetchall()
    return [
        {"request_id": r["request_id"], "partner_id": r["partner_id"],
         "partner_name": r["display_name"], "purpose": r["purpose"],
         "scope": loads(r["scope"]), "created_at": r["created_at"]}
        for r in rows
    ]


def get_request(request_id: str) -> dict | None:
    r = conn().execute("SELECT * FROM requests WHERE request_id=?", (request_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["scope"] = loads(d["scope"])
    d["approved"] = loads(d["approved"])
    d["result"] = loads(d["result"])
    return d


# ---------------------------------------------------------------- evaluation

def _reveal_claim(cit: dict, claim: str) -> tuple[bool, str, dict | None]:
    """Pull one claim out of the wallet and prove it against the signed credential."""
    disclosures = loads(cit["disclosures"]) or {}
    triple = disclosures.get(claim)
    if not triple:
        return False, "", None
    proof = check_presentation(cit["credential"], [triple])
    if not proof["valid"]:
        return False, "", None
    return True, triple[2], {"sd_jwt_valid": True, "note": proof["reason"]}


def _evaluate(predicate: str, cit: dict, nimc: dict | None, nibss: dict | None,
              bio_sample: str | None, ref_date: date | None) -> dict:
    head, _, arg = predicate.partition(":")

    if head in ("age_over_18", "age_over_21", "age_over_65"):
        threshold = int(head.split("_")[-1])
        if not nimc:
            return {"predicate": predicate, "kind": "yes_no", "outcome": "unverifiable",
                    "explanation": "No NIN record to read a date of birth from."}
        ok, dob, _ = _reveal_claim(cit, "date_of_birth")
        dob = dob or nimc["date_of_birth"]
        val = _age_on(dob, ref_date) >= threshold
        return {"predicate": predicate, "kind": "yes_no", "outcome": bool(val),
                "explanation": f"Checked against the date of birth in the NIN record. "
                               f"The date itself was not shared."}

    if head == "name_matches":
        claimed = _norm_name(arg)
        ok, actual, proof = _reveal_claim(cit, "full_name")
        if not ok:
            return {"predicate": predicate, "kind": "yes_no", "outcome": "unverifiable",
                    "explanation": "No signed name claim in the wallet."}
        val = _norm_name(actual) == claimed
        note = ("" if val else
                " The check is exact after normalising case and spacing. A reversed "
                "name order or a dropped accent will read as a mismatch even for the "
                "same person.")
        return {"predicate": predicate, "kind": "yes_no", "outcome": bool(val),
                "explanation": f"Compared the claimed name to the signed name claim without "
                               f"returning it.{note}"}

    if head == "state_of_residence_is":
        ok, actual, _ = _reveal_claim(cit, "state_of_residence")
        if not ok:
            return {"predicate": predicate, "kind": "yes_no", "outcome": "unverifiable",
                    "explanation": "No signed state-of-residence claim."}
        val = _norm_name(actual) == _norm_name(arg)
        return {"predicate": predicate, "kind": "yes_no", "outcome": bool(val),
                "explanation": "Compared to the signed state claim. The address was not shared."}

    if head == "is_verified":
        return {"predicate": predicate, "kind": "yes_no", "outcome": bool(cit and cit["credential"]),
                "explanation": "True when an enrolled, non-revoked SabiID credential exists."}

    if head == "nin_bvn_name_consistency":
        if not (nimc and nibss):
            return {"predicate": predicate, "kind": "yes_no", "outcome": "unverifiable",
                    "explanation": "Need both a NIN and a BVN record to compare."}
        val = _norm_name(nimc["full_name"]) == _norm_name(nibss["full_name"])
        return {"predicate": predicate, "kind": "yes_no", "outcome": bool(val),
                "explanation": "True when the name on the NIN record and the BVN record agree "
                               "after normalisation."}

    if head == "liveness_present":
        if not cit or not cit["bio_enrolment"]:
            return {"predicate": predicate, "kind": "yes_no", "outcome": "unverifiable",
                    "explanation": "No biometric baseline on file."}
        if not bio_sample:
            return {"predicate": predicate, "kind": "yes_no", "outcome": "false",
                    "explanation": "No fresh sample was offered for this check."}
        stored = loads(cit["bio_enrolment"])
        val = bio_verify(bio_sample, stored)
        return {"predicate": predicate, "kind": "yes_no", "outcome": bool(val),
                "explanation": "A fresh face or fingerprint sample was hashed and compared to "
                               "the enrolment hash. Neither sample is stored."}

    if head.startswith("reveal"):
        claim = arg or head.split("_", 1)[-1]
        ok, value, proof = _reveal_claim(cit, claim)
        if not ok:
            return {"predicate": predicate, "kind": "value", "outcome": "unverifiable",
                    "explanation": f"No signed '{claim}' claim to reveal."}
        return {"predicate": predicate, "kind": "value", "outcome": "disclosed", "value": value,
                "sd_proof": proof,
                "explanation": f"Only '{claim}' was released, and only because it was asked for "
                               f"and approved. It carries an SD-JWT proof back to the signed credential."}

    # anything the federation does not hold
    return {"predicate": predicate, "kind": "value", "outcome": "unverifiable",
            "referral": "Genotype and blood group are held by a hospital, not by NIMC or NIBSS. "
                        "SabiID can carry that fact once a hospital has verified it once.",
            "explanation": "The gateway does not guess. It says plainly that nobody has verified this yet."}


def _confidence(results: list[dict], nimc, nibss, name_consistent: bool | None,
                dob_consistent: bool | None, liveness_fresh: bool | None) -> float:
    score = 0.99
    if not (nimc and nibss):
        score -= 0.25
    if name_consistent is False:
        score -= 0.15
    if dob_consistent is False:
        score -= 0.06
    if liveness_fresh is False:
        score -= 0.10
    if any(r["outcome"] == "unverifiable" for r in results):
        score -= 0.03
    return round(max(0.30, min(0.99, score)), 2)


def consent(request_id: str, approved: list[str], bio_sample: str | None = None,
            otp: str = "", ref_date: date | None = None) -> dict:
    req = get_request(request_id)
    if not req or req["status"] != "pending":
        raise ValueError("no such pending request")
    if not re.fullmatch(r"\d{6}", otp or ""):
        raise ValueError("a six digit OTP is required")  # demo: any six digits stand in for the real OTP

    cit = _citizen(req["sid"])
    nin, bvn = cit["nin"], cit["bvn"]
    nimc = sources.lookup_nimc(nin)
    nibss = sources.lookup_nibss(bvn)

    results = []
    for predicate in req["scope"]:
        if predicate in approved:
            results.append(_evaluate(predicate, cit, nimc, nibss, bio_sample, ref_date))
        else:
            results.append({"predicate": predicate, "kind": "withheld", "outcome": "withheld",
                            "explanation": "The citizen did not approve this field."})

    name_consistent = (_norm_name(nimc["full_name"]) == _norm_name(nibss["full_name"])
                       if (nimc and nibss) else None)
    dob_consistent = (nimc["date_of_birth"] == nibss["date_of_birth"]
                      if (nimc and nibss) else None)
    liveness_fresh = None
    for r in results:
        if r["predicate"].startswith("liveness_present"):
            liveness_fresh = (r["outcome"] is True)

    confidence = _confidence(results, nimc, nibss, name_consistent, dob_consistent, liveness_fresh)
    verified = any(r["outcome"] is True for r in results) and not any(
        r["predicate"].startswith("is_verified") and r["outcome"] is False for r in results
    )

    statement = {
        "sid": req["sid"], "request_id": request_id, "partner": req["partner_id"],
        "results": [{"predicate": r["predicate"], "outcome": r["outcome"]} for r in results],
        "confidence_score": confidence,
    }
    attestation = sign_attestation(statement, ATTESTATION_TTL_SECONDS)

    presentation = {
        "request_id": request_id, "sid": req["sid"], "purpose": req["purpose"],
        "verified": bool(verified), "confidence_score": confidence,
        "results": results, "attestation": attestation,
        "gateway_jwk_url": "/.well-known/jwks.json",
        "issued_at": attestation["payload"]["iat"],
        "expires_at": attestation["payload"]["exp"],
    }

    disclosed = [r["predicate"] for r in results if r["outcome"] not in ("withheld",)]
    seq = ledger.append(
        "verification.completed", actor=req["partner_id"], subject_sid=req["sid"],
        detail={
            "request_id": request_id,
            "purpose": req["purpose"],
            "asked": req["scope"],
            "disclosed": disclosed,
            "withheld": [r["predicate"] for r in results if r["outcome"] == "withheld"],
            "outcomes": {r["predicate"]: r["outcome"] for r in results},
            "confidence_score": confidence,
            "attestation_nonce": attestation["payload"]["nonce"],
        },
    )
    presentation["ledger_seq"] = seq

    conn().execute(
        "UPDATE requests SET status='completed', approved=?, result=?, decided_at=? WHERE request_id=?",
        (dumps(approved), dumps(presentation), now(), request_id),
    )
    conn().commit()
    return presentation
