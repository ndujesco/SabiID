# SabiID

**Proving a fact without revealing the whole record.**
ICSC 2026 Universities Hackathon, Track B (Digital Identity, Trust and ICT).
Team Zer0Day Saints.

**Live app:** https://sabi-id-icsc.onrender.com/
**Code:** https://github.com/ndujesco/SabiID

SabiID is a broker that sits between the identity sources (NIN, BVN, the Civil
Registration service) and the businesses that check identity. It answers one
narrow question at a time, such as whether a person is over 18, whether a name
matches, or whether someone is still a living, matching person, signs the
answer, and writes one line to a tamper-evident log, without ever copying
anyone's record. Because there is no master database in the design, there is
no single file to steal.

The centrepiece it is built around is catching ghost workers and ghost
pensioners: the same prove-without-revealing check, asked on a payroll
schedule instead of once.

## How it works

A partner (a bank, a hospital, a ministry payroll unit) sends a scoped request
naming one citizen and a short list of things it needs to know. The citizen
sees the exact list on their own device and approves it field by field.
Anything not approved comes back withheld. The gateway then answers using:

- **Signed attestations.** Every answer is signed with Ed25519 and carries a
  short expiry and a nonce. A partner verifies the signature itself, with no
  call back to the gateway.
- **Selective disclosure.** Citizen credentials are issued as SD-JWTs whose
  signed body holds only salted hashes of each claim. The plain values live
  only in the citizen's own wallet.
- **A hash-chained proof-of-check log.** Every question asked is one line,
  chained to the line before it, so a later edit is detectable. No personal
  data is ever written to it.
- **Hashed biometrics.** A face or fingerprint sample is never stored; only a
  salted, one-way hash of it is kept.

The payroll case reuses the same mechanism on a schedule: before paying, the
gateway asks each line whether it is still the same living person enrolled
against that employee or pension number. A line that cannot confirm this is
held for manual review rather than paid automatically.

## Running it locally

Requires Python 3.10 or newer and the `cryptography` package.

```bash
pip3 install -r requirements.txt          # just: cryptography
python3 -m backend.data_gen               # generate synthetic data, seed the database
python3 -m backend.app                    # serve on http://127.0.0.1:8099
```

Then open <http://127.0.0.1:8099>, or use `./run.sh`.

Run the tests:

```bash
python3 tests/run_tests.py               # uses a throwaway database
```

## What is in here

| Path | What it is |
|---|---|
| `backend/` | The gateway. Python standard library plus `cryptography` for Ed25519. |
| `backend/crypto.py` | Signed attestations, SD-JWT selective disclosure, scrypt biometric hashing. |
| `backend/gateway.py` | Scoped requests, per-field consent, predicate evaluation. |
| `backend/ledger.py` | The hash-chained proof-of-check log and its verifier. |
| `backend/payroll.py` | The ghost worker / ghost pensioner sweep. |
| `backend/data_gen.py` | Generates all synthetic data. Fixed seed. |
| `frontend/` | Four plain HTML pages: citizen, partner, auditor, USSD. No build step. |
| `tests/run_tests.py` | 34 assertions, no framework. |
| `docs/TECHNICAL_WRITEUP.pdf` | The four page write-up. |
| `data/DATA_CARD.md` | Where the synthetic data came from and how it was made. |

## Scope, honestly

This is a three-week prototype of one slice, not a national gateway. The OTP is
simulated, the biometric is a stand-in string, and the identity sources are
local JSON files standing in for NIMC and NIBSS. `docs/TECHNICAL_WRITEUP.pdf`
lists every place it breaks as clearly as where it works.

All data is synthetic. No real person's NIN, BVN or record is used anywhere.
