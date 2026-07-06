"""
Nexus Trinity Plugin — exposes the 7-gate vulnerability verification pipeline
as AgentBus message handlers.

Message types handled:
  nexus.hypothesis   payload: {hypothesis, contract_path, context}
                     → runs Gate 1 (hypothesis formation)
  nexus.pipeline     payload: {hypothesis, contract_path, context, gates}
                     → runs specified gates (default: all 7)
  nexus.gate         payload: {gate_num, hypothesis, evidence, context}
                     → runs a single numbered gate

Message types emitted:
  nexus.gate_result  payload: {gate_num, passed, evidence, notes}
  nexus.finding      payload: {severity, title, description, poc, gates_passed}
  nexus.rejected     payload: {hypothesis, kill_pattern, reason}

Kill patterns (from cantina_submission_lessons.md):
  1. Flash Accounting Net-Zero — delta accumulates, unlock() enforces net-zero
  2. assertTrue(true) PoC — not a real exploit
  3. hex"" Signature PoC — empty sig ≠ bypass
  4. Privileged Role Out of Scope — operator/admin calls excluded
  5. Documented Known Constraint — acknowledged in docs
  6. Custom Simulation PoC — not a fork test against deployed state
"""

import os
import sys

from core.agent import Agent

_KILL_PATTERNS = {
    1: "Flash Accounting Net-Zero — _accountDelta accumulates, unlock() enforces net-zero exit",
    2: "assertTrue(true) PoC — PoC proves nothing without an assertion that can fail",
    3: "hex\"\" Signature PoC — empty calldata is not a signature bypass on guarded functions",
    4: "Privileged Role Out of Scope — operator/admin/owner-initiated paths excluded by scope",
    5: "Documented Known Constraint — team explicitly acknowledges this behavior in docs",
    6: "Custom Simulation PoC — only fork tests against deployed state are accepted",
}

_GATES = [
    "Hypothesis Formation",
    "Evidence Gathering",
    "Simulation / PoC",
    "Historical Replay",
    "Economic Impact",
    "Adversarial Challenge",
    "Reproducibility",
]


class NexusTrinityAgent(Agent):
    def __init__(self):
        super().__init__(name="nexus_trinity")

    def handle(self, message_type, payload):
        if message_type == "nexus.hypothesis":
            self._run_hypothesis(payload)
        elif message_type == "nexus.pipeline":
            self._run_pipeline(payload)
        elif message_type == "nexus.gate":
            self._run_single_gate(payload)

    def _run_hypothesis(self, payload):
        hypothesis = payload.get("hypothesis", "")
        contract = payload.get("contract_path", "")
        print(f"[nexus] Gate 1 — Hypothesis: {hypothesis[:80]}")
        print(f"[nexus] Target: {contract}")
        self._kill_pattern_check(hypothesis)

    def _run_pipeline(self, payload):
        hypothesis = payload.get("hypothesis", "")
        contract = payload.get("contract_path", "")
        gates = payload.get("gates", list(range(1, 8)))
        print(f"\n[nexus] 7-gate pipeline starting")
        print(f"[nexus] Hypothesis: {hypothesis}")
        print(f"[nexus] Contract:   {contract}")
        print(f"[nexus] Running gates: {gates}")

        kill = self._kill_pattern_check(hypothesis)
        if kill:
            print(f"[nexus] REJECTED — kill pattern {kill}: {_KILL_PATTERNS[kill]}")
            return

        for gate_num in gates:
            name = _GATES[gate_num - 1] if gate_num <= len(_GATES) else f"Gate {gate_num}"
            print(f"[nexus] Gate {gate_num} ({name}) — PENDING (wire to SCOUT for execution)")

    def _run_single_gate(self, payload):
        gate_num = payload.get("gate_num", 0)
        hypothesis = payload.get("hypothesis", "")
        name = _GATES[gate_num - 1] if 1 <= gate_num <= len(_GATES) else f"Gate {gate_num}"
        print(f"[nexus] Gate {gate_num} ({name}): {hypothesis[:80]}")

    def _kill_pattern_check(self, hypothesis: str) -> int | None:
        h = hypothesis.lower()
        if "flash" in h and ("net-zero" in h or "delta" in h or "accounting" in h):
            return 1
        if "asserttrue" in h or "assert(true)" in h:
            return 2
        if 'hex""' in h or "empty signature" in h or "empty calldata" in h:
            return 3
        if any(p in h for p in ["admin", "operator", "owner"]) and "out of scope" in h:
            return 4
        if "known" in h and ("documented" in h or "acknowledged" in h):
            return 5
        if "simulation" in h and "custom" in h:
            return 6
        return None


def register(bus):
    agent = NexusTrinityAgent()
    bus.register(agent, subscriptions={"nexus.hypothesis", "nexus.pipeline", "nexus.gate"})
    print("[plugin] nexus_trinity registered")
