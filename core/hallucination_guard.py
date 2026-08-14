# core/hallucination_guard.py
"""
Pre-flight fabrication filter for Nexus Trinity's Gate 3 output.

This is a cheap TEXT-LEVEL heuristic, not a verifier — it exists purely to
reject obviously-fabricated PoC output before spending a real forge fork
test on it (see core/poc_verifier.py for the actual deterministic check).

HARD BOUNDARY, do not violate: this module can only ever REJECT a
candidate early. A low/zero score here is NOT evidence a PoC is real —
absence of an obvious tell is not proof of truth. Only poc_verifier's real
on-chain re-execution can CONFIRM a finding. Wiring this module's output
into anything that marks a finding as passed/confirmed would recreate
exactly the bug this whole system was built to catch: a prior version of
this project (NexusTrinity_Sovereign) had a "detector" whose data-fetch
function was hardcoded to return a mocked stale timestamp — it looked like
real verification and wasn't, and it silently produced fabricated CRITICAL
findings on every run because nothing ever re-checked its claim against
reality. This module's own score must never be treated the same way.

Deliberately stateless (no file writes, no persisted metrics) — the
existing audit ledger (core/audit_store.py, via nexus.rejected messages)
already records every rejection this produces; a second, parallel logging
path would just be another thing that could silently drift or fail.

Most patterns below are not speculative — they were reverse-derived from
real hallucinated findings found in that same repo's memory store (vague,
confident-sounding claims like "SSTORE operation not effectively gated"
that pattern-match opcodes without describing an actual mechanism).
"""
import re

_FABRICATION_KEYWORDS = (
    "0xdeadbeef",
    "mock data",
    "example exploit",
)

_FABRICATION_PATTERNS = (
    re.compile(r"CVE-\d{4}-\d{5,}", re.IGNORECASE),
    re.compile(r"api[_-]?key[:=]\s*[a-zA-Z0-9]{20,}", re.IGNORECASE),
    re.compile(r"(mock|fake|placeholder|simulate the structure)[^\w]{0,10}(data|value|result)", re.IGNORECASE),
    re.compile(r"unauthorized (price update|call) succeeding", re.IGNORECASE),
    re.compile(r"bytecode access path anomaly", re.IGNORECASE),
    re.compile(r"logic leak in the internal dispatch", re.IGNORECASE),
    re.compile(r"SSTORE operation.*not (effectively|properly) gated", re.IGNORECASE),
)


def _confirmed_without_delta_markers(text: str) -> bool:
    """The PoC claims victory without printing anything that could later
    prove a real state change happened — the textual equivalent of "trust
    me". poc_verifier.py's own marker convention (BEFORE_STATE/AFTER_STATE)
    is the thing being checked for here."""
    return "VULNERABILITY_CONFIRMED" in text and not (
        "BEFORE_STATE" in text and "AFTER_STATE" in text
    )


def assess_risk(text: str) -> tuple:
    """Score raw LLM output for fabrication risk. Returns (score 0.0-1.0,
    list of triggered indicator names)."""
    score = 0.0
    indicators = []
    text_lower = text.lower()

    kw_hits = [kw for kw in _FABRICATION_KEYWORDS if kw in text_lower]
    if kw_hits:
        score += 0.2 * len(kw_hits)
        indicators.append(f"fabrication_keywords:{','.join(kw_hits)}")

    pat_hits = sum(1 for p in _FABRICATION_PATTERNS if p.search(text))
    if pat_hits:
        score += 0.6
        indicators.append(f"fabrication_patterns:{pat_hits}")

    if _confirmed_without_delta_markers(text):
        score += 0.5
        indicators.append("confirmed_without_delta_markers")

    return min(score, 1.0), indicators


def should_reject(text: str, threshold: float = 0.3) -> tuple:
    """Returns (reject: bool, score: float, indicators: list[str])."""
    score, indicators = assess_risk(text)
    return score > threshold, score, indicators
