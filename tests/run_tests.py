"""
Plain assert tests, no framework. Run from the project root:

    python tests/run_tests.py

Uses a throwaway database so it never touches the demo data.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# point every module at a temp DB before anything imports db
_tmp = tempfile.mkdtemp()
import backend.config as cfg
cfg.DB_PATH = Path(_tmp) / "test.db"

from backend import data_gen, gateway, ledger, payroll, sources  # noqa: E402
from backend.crypto import (  # noqa: E402
    sign_attestation, verify_attestation, issue_sd_credential, check_presentation,
    bio_hash, bio_verify,
)

PASS = 0
FAIL = 0


def check(label, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {label}")
    else:
        FAIL += 1
        print(f"  FAIL {label}")


def section(name):
    print(f"\n== {name}")


# --------------------------------------------------------------------- crypto
section("crypto: signed attestations")
att = sign_attestation({"sid": "SID-NG-1", "predicate": "age_over_18", "result": True}, 900)
check("valid signature verifies", verify_attestation(att)["valid"] is True)

bad = {"payload": dict(att["payload"]), "sig": att["sig"], "kid": att["kid"]}
bad["payload"]["statement"] = {"sid": "SID-NG-1", "predicate": "age_over_18", "result": False}
check("flipped result fails verification", verify_attestation(bad)["valid"] is False)

expired = sign_attestation({"x": 1}, -1)
check("expired attestation is rejected", verify_attestation(expired)["valid"] is False)

section("crypto: SD-JWT selective disclosure")
cred = issue_sd_credential("SID-NG-2", {"full_name": "Ada Test", "date_of_birth": "1990-01-01",
                                        "state_of_residence": "Lagos"})
only_name = [cred["disclosures"]["full_name"]]
pres = check_presentation(cred["credential"], only_name)
check("revealing one claim verifies", pres["valid"] and pres["claims"] == {"full_name": "Ada Test"})
check("date of birth stays hidden", "date_of_birth" not in pres["claims"])

forged = check_presentation(cred["credential"], [["saltx", "full_name", "Someone Else"]])
check("a made-up claim value is rejected", forged["valid"] is False)

section("crypto: biometric hashing")
h = bio_hash("live-capture::demo::baseline")
check("right sample matches the hash", bio_verify("live-capture::demo::baseline", h))
check("wrong sample does not match", not bio_verify("live-capture::demo::other", h))
check("raw sample is never in the stored object", "live-capture" not in str(h))

# --------------------------------------------------------------------- ledger
section("ledger: hash chain")
data_gen.seed_db()
base = ledger.verify_chain()
check("seeded chain verifies", base["ok"])

recs = __import__("json").loads((cfg.DATA_DIR / "synthetic_citizens.json").read_text())
sid15 = recs[15]["sid"]
r = gateway.create_request("bank-firsttrust", sid15, "Open account",
                           ["is_verified", "age_over_18"])
gateway.consent(r["request_id"], ["is_verified", "age_over_18"], otp="123456")
check("chain still verifies after a check", ledger.verify_chain()["ok"])

from backend.db import conn
import json as _j
row = conn().execute("SELECT seq, detail FROM ledger WHERE event_type='verification.completed' "
                     "ORDER BY seq LIMIT 1").fetchone()
d = _j.loads(row["detail"])
d["outcomes"] = {k: "true" for k in d.get("outcomes", {})}
d["confidence_score"] = 1.0
conn().execute("UPDATE ledger SET detail=? WHERE seq=?", (_j.dumps(d), row["seq"]))
conn().commit()
v = ledger.verify_chain()
check("editing a past line breaks the chain at that line", (not v["ok"]) and v["broken_at"] == row["seq"])

data_gen.seed_db()
for _ in range(3):
    rr = gateway.create_request("bank-firsttrust", sid15, "x", ["is_verified"])
    gateway.consent(rr["request_id"], ["is_verified"], otp="123456")
mid = conn().execute("SELECT seq FROM ledger ORDER BY seq").fetchall()[3]["seq"]
noted_head = ledger.head()["seq"]
conn().execute("DELETE FROM ledger WHERE seq=?", (mid,))
conn().commit()
v = ledger.verify_chain()
check("deleting a middle line is detected as a gap", (not v["ok"]) and v["broken_at"] == mid)

conn().execute("DELETE FROM ledger WHERE seq >= ?", (noted_head - 1,))
conn().commit()
v = ledger.verify_chain(expected_head_seq=noted_head)
check("truncating the tail is caught against a noted head", not v["ok"])

# -------------------------------------------------------------------- gateway
section("gateway: consent and scope")
data_gen.seed_db()
sid15 = recs[15]["sid"]
r = gateway.create_request("bank-firsttrust", sid15, "Open account",
                           ["is_verified", "age_over_18", "name_matches:Adaeze Chioma Nwosu",
                            "reveal:full_name"])
pres = gateway.consent(r["request_id"],
                       ["is_verified", "age_over_18", "name_matches:Adaeze Chioma Nwosu"],
                       otp="654321")
outs = {x["predicate"]: x["outcome"] for x in pres["results"]}
check("is_verified is true", outs["is_verified"] is True)
check("age_over_18 is true for a 1996 birth", outs["age_over_18"] is True)
check("correct name matches", outs["name_matches:Adaeze Chioma Nwosu"] is True)
check("un-approved field is withheld", outs["reveal:full_name"] == "withheld")
check("no date of birth anywhere in the response", "1996-03-14" not in str(pres))
check("attestation on the response verifies", verify_attestation(pres["attestation"])["valid"])

r = gateway.create_request("bank-firsttrust", sid15, "x", ["name_matches:Nwosu Adaeze Chioma"])
pres = gateway.consent(r["request_id"], ["name_matches:Nwosu Adaeze Chioma"], otp="111111")
check("reversed name order reads as a mismatch (known limitation)",
      pres["results"][0]["outcome"] is False)

r = gateway.create_request("hosp-lasg", sid15, "Admit", ["genotype"])
pres = gateway.consent(r["request_id"], ["genotype"], otp="121212")
check("unheld attribute returns unverifiable with a referral",
      pres["results"][0]["outcome"] == "unverifiable" and "referral" in pres["results"][0])

rej = gateway.create_request("hosp-lasg", sid15, "x", ["age_over_18"])
check("partner cannot ask outside its grant", rej["status"] == "rejected")

gateway.revoke(sid15, "bank-firsttrust")
rej = gateway.create_request("bank-firsttrust", sid15, "x", ["is_verified"])
check("a revoked partner is turned away", rej["status"] == "rejected")

# -------------------------------------------------------------------- payroll
section("payroll: ghost detection")
data_gen.seed_db()
out = payroll.run_cycle("payroll-fmw", offline=False, grace=False)
s = out["summary"]
check("twelve lines on the run", s["lines"] == 12)
check("seven real staff are paid", s["released"] == 7)
check("five lines are held back", s["withheld"] == 5)
by = {d["employee_no"]: d for d in out["decisions"]}
check("the deceased line is caught by the civil registry",
      "deceased" in by["FMW-2210"]["reason"].lower())
check("the fabricated line has no identity to check",
      "never a real person" in by["FMW-9001"]["reason"])
check("a wrong sample is flagged as possible impersonation",
      "impersonation" in by["FMW-2211"]["reason"].lower())
gt = {d["employee_no"]: d.get("ground_truth") for d in out["decisions"]}
false_withholds = [e for e, d in by.items()
                   if d["outcome"] == "withheld" and gt[e] == "bad_network"]
check("the honest cost is visible: one real staffer on a bad network is held",
      len(false_withholds) == 1)

section("payroll: power and network cut")
data_gen.seed_db()
sources.set_offline(True)
off = payroll.run_cycle("payroll-fmw", offline=True)
check("nothing auto-pays while the sources are unreachable",
      off["summary"]["queued"] == 12 and off["summary"]["released"] == 0)
sources.set_offline(False)
rec = payroll.reconcile(off["summary"]["cycle_id"])
check("the queue replays once the link is back", rec["reconciled"] == 12)
check("the chain still verifies after an outage and a reconcile", ledger.verify_chain()["ok"])

# ---------------------------------------------------------------------- done
print(f"\n{PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
