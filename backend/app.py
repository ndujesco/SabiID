"""
A small HTTP server on the standard library only.

No web framework. One dependency in the whole backend, `cryptography`, for the
Ed25519 signatures. Everything else, the routing, JSON, storage, hashing, is
Python as it ships. That keeps the prototype easy to read and easy to run on a
laptop with nothing installed.

    python -m backend.app          # starts on http://127.0.0.1:8099
"""
from __future__ import annotations

import json
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from . import gateway, ledger, payroll, sources
from .config import FRONTEND_DIR, HOST, PORT, PRODUCT_NAME
from .crypto import gateway_public_jwk
from .db import conn, init_db, loads

# original ledger rows kept so the auditor demo can undo its own tampering
_TAMPER_BACKUP: dict[int, tuple] = {}

PAGES = {"/": "index.html", "/citizen": "citizen.html", "/partner": "partner.html",
         "/auditor": "auditor.html", "/ussd": "ussd.html"}

CONTENT_TYPES = {".html": "text/html", ".css": "text/css", ".js": "application/javascript",
                 ".svg": "image/svg+xml", ".json": "application/json"}


def _citizen_label(rec) -> dict:
    return {"sid": rec["sid"], "nin_tail": rec["nin"][-4:]}


class Handler(BaseHTTPRequestHandler):
    server_version = f"{PRODUCT_NAME}/0.1"

    def log_message(self, fmt, *args):  # quieter console
        pass

    # ------------------------------------------------------------------ helpers
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, name):
        path = FRONTEND_DIR / name
        if not path.exists():
            self._send_json({"error": "not found"}, 404)
            return
        data = path.read_bytes()
        ext = path.suffix
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}

    # --------------------------------------------------------------------- GET
    def do_GET(self):
        u = urlparse(self.path)
        p = u.path
        q = parse_qs(u.query)

        if p in PAGES:
            return self._send_file(PAGES[p])
        if p.startswith("/static/"):
            return self._send_file(p[1:])
        if p == "/.well-known/jwks.json":
            return self._send_json({"keys": [gateway_public_jwk()]})

        if p == "/api/citizens":
            rows = conn().execute("SELECT sid, nin FROM citizens ORDER BY sid").fetchall()
            return self._send_json([_citizen_label(r) for r in rows])

        m = re.fullmatch(r"/api/citizen/(SID-NG-\d+)", p)
        if m:
            return self._send_json(self._citizen_view(m.group(1)))

        if p == "/api/partners":
            return self._send_json(gateway.list_partners())

        if p == "/api/requests/pending":
            sid = (q.get("sid") or [""])[0]
            return self._send_json(gateway.list_pending(sid))

        m = re.fullmatch(r"/api/requests/(REQ-[0-9A-F]+)", p)
        if m:
            r = gateway.get_request(m.group(1))
            return self._send_json(r or {"error": "not found"}, 200 if r else 404)

        if p == "/api/ledger":
            return self._send_json(ledger.entries(limit=int((q.get("limit") or ["300"])[0])))
        if p == "/api/ledger/verify":
            return self._send_json(ledger.verify_chain())
        m = re.fullmatch(r"/api/ledger/entry/(\d+)", p)
        if m:
            rows = [e for e in ledger.entries(limit=10_000) if e["seq"] == int(m.group(1))]
            return self._send_json(rows[0] if rows else {"error": "not found"}, 200 if rows else 404)

        if p == "/api/payroll/roster":
            ministry = (q.get("ministry") or ["payroll-fmw"])[0]
            return self._send_json(payroll.roster(ministry))
        m = re.fullmatch(r"/api/payroll/cycle/(CYC-[0-9A-F]+)", p)
        if m:
            return self._send_json(payroll.decisions_for(m.group(1)))

        if p == "/api/sources/status":
            return self._send_json({"offline": sources.is_offline()})

        return self._send_json({"error": f"no route for GET {p}"}, 404)

    # -------------------------------------------------------------------- POST
    def do_POST(self):
        p = urlparse(self.path).path
        b = self._body()
        try:
            if p == "/api/requests":
                return self._send_json(gateway.create_request(
                    b["partner_id"], b["sid"], b.get("purpose", ""), b.get("scope", [])))

            m = re.fullmatch(r"/api/requests/(REQ-[0-9A-F]+)/consent", p)
            if m:
                pres = gateway.consent(m.group(1), b.get("approved", []),
                                       b.get("bio_sample"), b.get("otp", ""))
                return self._send_json(pres)

            m = re.fullmatch(r"/api/partners/([a-z0-9-]+)/(revoke|unrevoke)", p)
            if m:
                pid, verb = m.group(1), m.group(2)
                (gateway.revoke if verb == "revoke" else gateway.unrevoke)(b["sid"], pid)
                return self._send_json({"ok": True})

            if p == "/api/payroll/cycle":
                return self._send_json(payroll.run_cycle(
                    b.get("ministry_id", "payroll-fmw"),
                    offline=bool(b.get("offline")), grace=bool(b.get("grace", False))))
            if p == "/api/payroll/reconcile":
                return self._send_json(payroll.reconcile(b["cycle_id"]))

            if p == "/api/sources/offline":
                sources.set_offline(bool(b.get("value")))
                return self._send_json({"offline": sources.is_offline()})

            if p == "/api/dev/tamper":
                return self._send_json(self._tamper(b))
            if p == "/api/dev/restore":
                return self._send_json(self._restore())
            if p == "/api/reseed":
                from .data_gen import seed_db
                _TAMPER_BACKUP.clear()
                seed_db()
                return self._send_json({"ok": True})

            if p == "/api/ussd":
                return self._send_json(self._ussd(b))

        except KeyError as e:
            return self._send_json({"error": f"missing field {e}"}, 400)
        except ValueError as e:
            return self._send_json({"error": str(e)}, 400)
        except sources.SourceUnavailable as e:
            return self._send_json({"error": str(e), "kind": "source_unavailable"}, 503)

        return self._send_json({"error": f"no route for POST {p}"}, 404)

    # -------------------------------------------------------------- view logic
    def _citizen_view(self, sid: str) -> dict:
        row = conn().execute("SELECT * FROM citizens WHERE sid=?", (sid,)).fetchone()
        if not row:
            return {"error": "unknown sid"}
        disclosures = loads(row["disclosures"]) or {}
        claims = {name: triple[2] for name, triple in disclosures.items()}
        activity = [e for e in ledger.entries(limit=10_000) if e["subject_sid"] == sid]
        revs = conn().execute("SELECT partner_id, revoked_at FROM revocations WHERE sid=?", (sid,)).fetchall()
        return {
            "sid": sid,
            "nin_tail": row["nin"][-4:],
            "claim_names": sorted(disclosures.keys()),
            "claims": claims,  # the wallet holds the plaintext; this is the citizen's own view
            "pending": gateway.list_pending(sid),
            "activity": activity[-25:],
            "revoked_partners": [r["partner_id"] for r in revs],
        }

    def _tamper(self, b: dict) -> dict:
        seq = b.get("seq")
        rows = conn().execute(
            "SELECT * FROM ledger WHERE event_type IN ('verification.completed','payroll.decision') "
            "ORDER BY seq"
        ).fetchall()
        if not rows:
            return {"error": "nothing worth tampering yet, run a check first"}
        target = next((r for r in rows if r["seq"] == seq), rows[len(rows) // 2])
        _TAMPER_BACKUP[target["seq"]] = (target["detail"], target["entry_hash"], target["prev_hash"])
        detail = loads(target["detail"])
        if "outcomes" in detail:
            for k in list(detail["outcomes"]):
                detail["outcomes"][k] = "true" if detail["outcomes"][k] != "true" else "false"
        elif "outcome" in detail:
            detail["outcome"] = "released"
            detail["reason"] = "quietly edited after the fact"
        conn().execute("UPDATE ledger SET detail=? WHERE seq=?",
                       (json.dumps(detail, ensure_ascii=False), target["seq"]))
        conn().commit()
        return {"tampered_seq": target["seq"],
                "note": "changed the stored outcome on this line without touching its hash"}

    def _restore(self) -> dict:
        if not _TAMPER_BACKUP:
            return {"note": "nothing to restore"}
        for seq, (detail, entry_hash, prev_hash) in _TAMPER_BACKUP.items():
            conn().execute("UPDATE ledger SET detail=?, entry_hash=?, prev_hash=? WHERE seq=?",
                           (detail, entry_hash, prev_hash, seq))
        conn().commit()
        n = len(_TAMPER_BACKUP)
        _TAMPER_BACKUP.clear()
        return {"restored": n}

    def _ussd(self, b: dict) -> dict:
        sid = b.get("sid", "")
        action = b.get("action", "menu")
        row = conn().execute("SELECT sid FROM citizens WHERE sid=?", (sid,)).fetchone()
        if not row:
            return {"screen": "END  That ID is not enrolled."}
        if action == "menu":
            pend = gateway.list_pending(sid)
            return {"screen": f"SabiID (*737*5#)\n{len(pend)} check(s) waiting.\n"
                              f"1. Approve a check\n2. Last 3 checks\n3. Freeze my ID",
                    "pending": pend}
        if action == "approve":
            pend = gateway.list_pending(sid)
            if not pend:
                return {"screen": "END  No check is waiting."}
            req = pend[0]
            allowed = [s for s in req["scope"] if not s.startswith("liveness")]
            pres = gateway.consent(req["request_id"], allowed, bio_sample=None, otp="000000")
            skipped = [s for s in req["scope"] if s.startswith("liveness")]
            tail = ("\nFace check skipped: needs the app." if skipped else "")
            return {"screen": f"END  Approved for {req['partner_name']}.\n"
                              f"Shared: {', '.join(allowed) or 'nothing'}.{tail}",
                    "presentation": pres}
        if action == "history":
            acts = [e for e in ledger.entries(limit=10_000)
                    if e["subject_sid"] == sid and e["event_type"] == "verification.completed"][-3:]
            lines = [f"- {e['detail'].get('purpose', 'check')} ({', '.join(e['detail'].get('disclosed', []))})"
                     for e in acts] or ["- none yet"]
            return {"screen": "END  Last checks:\n" + "\n".join(lines)}
        if action == "freeze":
            for pr in gateway.list_partners():
                gateway.revoke(sid, pr["partner_id"])
            return {"screen": "END  Your ID is frozen. Every partner must ask again."}
        return {"screen": "END  Unknown option."}


def main():
    init_db()
    # if the DB has no citizens yet, seed it
    if not conn().execute("SELECT 1 FROM citizens LIMIT 1").fetchone():
        from .data_gen import seed_db
        seed_db()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"{PRODUCT_NAME} on http://{HOST}:{PORT}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
