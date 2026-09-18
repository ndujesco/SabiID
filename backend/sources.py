"""
Stand-ins for the real identity sources.

NIMC holds the NIN record. NIBSS holds the BVN record. The Civil Registration
service holds deaths. SabiID never copies these. It asks them a question at the
moment it needs an answer and forgets the record afterward. That is the whole
point: there is no master file to steal.

`set_offline(True)` makes every lookup raise SourceUnavailable, so the
power-cut and network-cut behaviour can be shown on demand.
"""
from __future__ import annotations

import json

from .config import SOURCES_DIR

_OFFLINE = False


class SourceUnavailable(RuntimeError):
    pass


def set_offline(value: bool) -> None:
    global _OFFLINE
    _OFFLINE = bool(value)


def is_offline() -> bool:
    return _OFFLINE


def _load(name: str) -> dict:
    if _OFFLINE:
        raise SourceUnavailable(f"{name} is not reachable right now")
    path = SOURCES_DIR / name
    return json.loads(path.read_text())


def lookup_nimc(nin: str) -> dict | None:
    return _load("nimc.json").get(nin)


def lookup_nibss(bvn: str) -> dict | None:
    return _load("nibss.json").get(bvn)


def lookup_civil_registry(nin: str) -> dict | None:
    return _load("civil_registry.json").get(nin)
