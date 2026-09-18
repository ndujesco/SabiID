"""
Helpers that only exist because this is a demo with no real phones attached.

In a real deployment the citizen taps a prompt on their phone and their device
captures a fresh face or fingerprint sample. Here we stand that in with a
deterministic string per SID, so an "active" person can be made to answer
correctly and a "ghost" can be made to never answer.
"""
from __future__ import annotations


def enrolment_bio_sample(sid: str) -> str:
    """The sample captured once at enrolment. Only its hash is ever stored."""
    return f"live-capture::{sid}::baseline"


def fresh_bio_sample(sid: str, matches: bool = True) -> str:
    """
    A new sample offered during a check. If matches is False we return a
    different string, standing in for a wrong person holding the phone.
    """
    return enrolment_bio_sample(sid) if matches else f"live-capture::{sid}::mismatch"
