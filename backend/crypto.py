"""
The cryptographic core of SabiID.

Three primitives, nothing exotic:

1. Ed25519 signed attestations. The gateway holds one long-lived key pair.
   When it answers a yes/no question it signs a small statement. A verifier
   checks that signature against the gateway's published public key and never
   has to trust the transport or call back.

2. SD-JWT style selective disclosure. At enrolment the gateway issues a
   credential whose body carries only salted hashes of each claim. The plain
   values live in the citizen's wallet. A presentation reveals a chosen subset
   of values; the verifier recomputes the hashes and checks they were in the
   signed credential.

3. Scrypt biometric hashing. A face or fingerprint sample is never stored. Only
   a salted one-way hash is kept, and a later sample is checked against it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.exceptions import InvalidSignature

from .config import GATEWAY_ISSUER, GATEWAY_KEY_PATH


def b64u(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64u_decode(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode(txt + pad)


def canonical(obj) -> bytes:
    """Deterministic JSON so a signature or hash is reproducible anywhere."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_b64(raw: bytes) -> str:
    return b64u(hashlib.sha256(raw).digest())


# --------------------------------------------------------------------------- keys

def load_or_create_gateway_key() -> Ed25519PrivateKey:
    if GATEWAY_KEY_PATH.exists():
        raw = b64u_decode(GATEWAY_KEY_PATH.read_text().strip())
        return Ed25519PrivateKey.from_private_bytes(raw)
    key = Ed25519PrivateKey.generate()
    raw = key.private_bytes_raw()
    GATEWAY_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    GATEWAY_KEY_PATH.write_text(b64u(raw))
    os.chmod(GATEWAY_KEY_PATH, 0o600)
    return key


_GATEWAY_KEY = load_or_create_gateway_key()
_GATEWAY_PUB_B64 = b64u(_GATEWAY_KEY.public_key().public_bytes_raw())


def gateway_public_jwk() -> dict:
    """What a partner downloads once and pins."""
    return {
        "kty": "OKP",
        "crv": "Ed25519",
        "alg": "EdDSA",
        "use": "sig",
        "kid": GATEWAY_ISSUER + "-1",
        "x": _GATEWAY_PUB_B64,
    }


# ----------------------------------------------------------------- attestations

def sign_attestation(statement: dict, ttl_seconds: int) -> dict:
    """
    statement is the plain claim, for example
        {"sid": "SID-NG-8xxxx", "predicate": "age_over_18", "result": true}
    The gateway wraps it with issuer, timing and a nonce, then signs the whole
    thing. A stolen attestation expires within ttl_seconds and cannot be widened
    to anything the citizen did not approve.
    """
    now = int(time.time())
    payload = {
        "iss": GATEWAY_ISSUER,
        "iat": now,
        "exp": now + ttl_seconds,
        "nonce": b64u(secrets.token_bytes(12)),
        "statement": statement,
    }
    sig = _GATEWAY_KEY.sign(canonical(payload))
    return {"payload": payload, "sig": b64u(sig), "kid": GATEWAY_ISSUER + "-1"}


def verify_attestation(att: dict, public_key_b64: str | None = None) -> dict:
    """
    Returns {"valid": bool, "reason": str}. A partner runs this locally.
    """
    pub_b64 = public_key_b64 or _GATEWAY_PUB_B64
    try:
        pub = Ed25519PublicKey.from_public_bytes(b64u_decode(pub_b64))
        pub.verify(b64u_decode(att["sig"]), canonical(att["payload"]))
    except (InvalidSignature, KeyError, ValueError):
        return {"valid": False, "reason": "signature does not check out"}
    if att["payload"].get("iss") != GATEWAY_ISSUER:
        return {"valid": False, "reason": "wrong issuer"}
    if int(time.time()) > int(att["payload"]["exp"]):
        return {"valid": False, "reason": "expired"}
    return {"valid": True, "reason": "signature valid, issued by the gateway, not expired"}


# ------------------------------------------------------- SD-JWT style credential

def issue_sd_credential(sid: str, claims: dict) -> dict:
    """
    claims is the full plaintext, for example
        {"full_name": "...", "date_of_birth": "1999-04-02", "state_of_residence": "Lagos"}
    Returns:
        credential  -> signed, carries only salted hashes, safe to store anywhere
        disclosures -> {claim_name: [salt, name, value]}, kept only in the wallet
    """
    disclosures: dict[str, list] = {}
    digests: list[str] = []
    for name, value in sorted(claims.items()):
        salt = b64u(secrets.token_bytes(16))
        disclosure = [salt, name, value]
        digests.append(sha256_b64(canonical(disclosure)))
        disclosures[name] = disclosure

    now = int(time.time())
    header = {"alg": "EdDSA", "typ": "sd-jwt", "kid": GATEWAY_ISSUER + "-1"}
    body = {
        "iss": GATEWAY_ISSUER,
        "sub": sid,
        "iat": now,
        "_sd_alg": "sha-256",
        "_sd": sorted(digests),
    }
    signing_input = b64u(canonical(header)) + "." + b64u(canonical(body))
    sig = _GATEWAY_KEY.sign(signing_input.encode("ascii"))
    credential = signing_input + "." + b64u(sig)
    return {"credential": credential, "disclosures": disclosures}


def verify_credential_signature(credential: str, public_key_b64: str | None = None) -> bool:
    pub_b64 = public_key_b64 or _GATEWAY_PUB_B64
    try:
        h_b64, b_b64, s_b64 = credential.split(".")
        pub = Ed25519PublicKey.from_public_bytes(b64u_decode(pub_b64))
        pub.verify(b64u_decode(s_b64), (h_b64 + "." + b_b64).encode("ascii"))
        return True
    except (InvalidSignature, ValueError):
        return False


def check_presentation(credential: str, revealed: list[list]) -> dict:
    """
    A verifier is handed the signed credential plus a few disclosure triples.
    It confirms the credential signature, then that every revealed claim's hash
    was actually inside the signed set. Nothing else about the record is learnt.
    """
    if not verify_credential_signature(credential):
        return {"valid": False, "reason": "credential signature invalid", "claims": {}}
    _, b_b64, _ = credential.split(".")
    body = json.loads(b64u_decode(b_b64))
    signed = set(body.get("_sd", []))
    claims = {}
    for disclosure in revealed:
        digest = sha256_b64(canonical(disclosure))
        if digest not in signed:
            return {
                "valid": False,
                "reason": f"claim '{disclosure[1]}' was not in the signed credential",
                "claims": {},
            }
        claims[disclosure[1]] = disclosure[2]
    return {"valid": True, "reason": "every revealed claim traces back to the signed credential", "claims": claims}


# ----------------------------------------------------------- biometric hashing

def bio_hash(sample: str, salt_b64: str | None = None) -> dict:
    """
    sample stands in for a face or fingerprint template. We keep only the hash.
    scrypt is deliberately slow so a stolen hash file is expensive to brute.
    """
    salt = b64u_decode(salt_b64) if salt_b64 else secrets.token_bytes(16)
    digest = hashlib.scrypt(sample.encode("utf-8"), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return {"salt": b64u(salt), "hash": b64u(digest)}


def bio_verify(sample: str, stored: dict) -> bool:
    trial = bio_hash(sample, stored["salt"])
    return hmac.compare_digest(trial["hash"], stored["hash"])
