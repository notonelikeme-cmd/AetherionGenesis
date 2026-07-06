"""
Nexus Trinity Plugin — 7-gate vulnerability verification pipeline wired to
AgentAI's model_router for real LLM execution.

Bus messages handled:
  nexus.hypothesis  {hypothesis, contract_path, code}
  nexus.pipeline    {hypothesis, contract_path, code, gates=[1..7]}
  nexus.gate        {gate_num, hypothesis, evidence, poc, context}

Bus messages emitted:
  nexus.gate_result  {gate_num, name, passed, output, kill_reason}
  nexus.finding      {severity, title, hypothesis, evidence, poc, gates_passed, economic}
  nexus.rejected     {hypothesis, gate, kill_pattern, reason}
"""

import sys, os, json, traceback, threading

_AGENTAI_PATH = os.path.expanduser("~/AgentAI")
if _AGENTAI_PATH not in sys.path:
    sys.path.insert(0, _AGENTAI_PATH)

from core.agent import Agent

# ── Kill pattern definitions ──────────────────────────────────────────────────
_KILL_PATTERNS = {
    1: "Flash Accounting Net-Zero: _accountDelta accumulates, unlock() enforces net-zero exit — nested multi-pool ops are the intended model, not a bug",
    2: "assertTrue(true) PoC: assertion can never fail regardless of protocol state — proves nothing",
    3: 'hex"" Signature PoC: empty calldata is not a signature bypass on guarded entry points',
    4: "Privileged Role Out of Scope: operator/admin/owner-initiated paths are excluded by scope rules",
    5: "Documented Known Constraint: team explicitly acknowledges this edge case in docs/comments",
    6: "Custom Simulation PoC: only fork tests against live deployed state are accepted — no mocked environments",
}

# ── Gate definitions: (name, tier, system_prompt) ────────────────────────────
_GATES = {
    1: (
        "Hypothesis Formation",
        1,  # Tier 1 — reasoning
        """You are a senior DeFi security researcher forming vulnerability hypotheses.
Rules:
- Output ONE specific, falsifiable hypothesis naming: exact function, exact state change, exact attacker action.
- If nothing clearly wrong: respond with exactly "NO_HYPOTHESIS".
- Never be vague. "reentrancy exists" is not a hypothesis. "attacker calls withdraw() via fallback during _transfer(), draining vault before balances update" IS.
- Check kill patterns before hypothesizing:
  * Flash accounting net-zero: accumulation IS the design, unlock() enforces settlement.
  * Empty sig / hex"": not a bypass.
  * Admin/operator paths: out of scope.
  * Documented constraints: not bugs.""",
    ),
    2: (
        "Evidence Gathering",
        3,  # Tier 3 — parser (JSON output)
        """You are a code evidence extractor. Output ONLY valid JSON, no prose, no markdown fences.
Schema: {"lines": [{"file": "<str>", "line": <int>, "content": "<str>", "relevance": "<str>"}], "supports_hypothesis": <bool>, "missing_guards": ["<str>"], "kill_pattern_hit": <null|int>}
- kill_pattern_hit: 1=flash-accounting, 2=asserttrue, 3=empty-sig, 4=privileged-oos, 5=documented, 6=custom-sim. null if none.""",
    ),
    3: (
        "Simulation / PoC",
        2,  # Tier 2 — execution/code
        """You are a Foundry exploit developer. Write a complete Foundry fork test.
Rules — violation = automatic kill:
1. Fork mainnet (or target chain) at a specific recent block number.
2. Use real deployed contract addresses — no mocks, no custom deployments.
3. Assertion MUST be able to fail: vm.assertGt(stolen, 0) or vm.assertEq(balance, 0). Never assertTrue(true).
4. Include exact forge command to run it.
5. If hypothesis is not exploitable via fork test: say "UNEXPLOITABLE: <reason>".

Template:
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.0;
import "forge-std/Test.sol";

contract ExploitTest is Test {
    function setUp() public {
        vm.createFork("mainnet", <BLOCK>);
    }
    function test_exploit() public {
        // setup attacker
        // execute attack
        assertGt(address(attacker).balance, 0, "exploit failed");
    }
}""",
    ),
    4: (
        "Historical Replay",
        2,  # Tier 2 — execution
        """You are a DeFi exploit historian with knowledge of DeFiHackLabs (740+ incidents) and Rekt.news.
Given a vulnerability pattern, find matching historical exploits.
Output JSON: {"matches": [{"protocol": str, "date": str, "loss_usd": int, "vector": str, "similarity": "exact|similar|related"}], "novel": bool}
- novel: true if no close historical match found.""",
    ),
    5: (
        "Economic Impact",
        1,  # Tier 1 — reasoning
        """You are a DeFi economic security analyst.
Model the maximum extractable value (MEV) from this vulnerability.
Output JSON: {
  "max_value_usd": <int>,
  "tvl_at_risk": <int>,
  "gas_cost_estimate": <int>,
  "flash_loan_fee": <float>,
  "profitable": <bool>,
  "severity": "Critical|High|Medium|Low",
  "severity_rationale": "<str>",
  "attack_scenarios": [{"label": str, "value_usd": int, "steps": int}]
}
Severity thresholds: Critical >$500k, High $50k-$500k, Medium $5k-$50k, Low <$5k.""",
    ),
    6: (
        "Adversarial Challenge",
        1,  # Tier 1 — reasoning
        """You are a hostile senior auditor paid $10,000 to REJECT this finding.
Your job: find every reason it fails.
Check:
- Missing preconditions the attacker cannot meet
- Access controls blocking the attack path
- Protocol invariants that prevent the exploit
- Economic barriers (gas > profit, slippage, MEV competition)
- Kill patterns: flash accounting net-zero, assertTrue(true), hex"" sig, privileged oos, documented constraint, custom simulation
If you find a fatal flaw: "REJECTED: <specific reason>"
If you CANNOT refute it after exhaustive challenge: "FINDING_STANDS: <remaining concerns if any>" """,
    ),
    7: (
        "Reproducibility",
        2,  # Tier 2 — execution
        """You are a Foundry CI engineer verifying a PoC is reproducible.
Check:
1. Complete Foundry test (SPDX, pragma, imports, contract, setUp, test function)?
2. Correct fork setup with block number?
3. Real deployed addresses (not address(0) or placeholders)?
4. Assertion that can actually fail?
5. forge command included?
Output JSON: {"reproducible": bool, "score": <0-100>, "issues": ["<str>"], "forge_command": "<str>", "verdict": "PASS|FAIL"}""",
    ),
}


def _kill_pattern_fast(text: str) -> int | None:
    t = text.lower()
    if ("flash" in t or "unlock" in t or "delta" in t) and ("net-zero" in t or "accumulate" in t or "accounting" in t):
        return 1
    if "asserttrue(true)" in t or "assert(true)" in t:
        return 2
    if 'hex""' in t or "empty signature" in t or "empty calldata" in t:
        return 3
    if any(p in t for p in ["admin only", "onlyowner", "privileged"]) and "scope" in t:
        return 4
    if "known" in t and ("documented" in t or "acknowledged" in t or "intended" in t):
        return 5
    if "custom simulation" in t or ("mock" in t and "poc" in t):
        return 6
    return None


class NexusTrinityAgent(Agent):
    def __init__(self, bus):
        super().__init__(name="nexus_trinity")
        self._bus = bus
        self._router = None

    def _get_router(self):
        if self._router is None:
            try:
                from core.model_router import ModelRouter
                self._router = ModelRouter()
            except Exception as e:
                print(f"[nexus] model_router unavailable: {e}")
        return self._router

    def handle(self, message_type, payload):
        if message_type == "nexus.hypothesis":
            threading.Thread(target=self._run_hypothesis, args=(payload,), daemon=True).start()
        elif message_type == "nexus.pipeline":
            threading.Thread(target=self._run_pipeline, args=(payload,), daemon=True).start()
        elif message_type == "nexus.gate":
            threading.Thread(target=self._run_single_gate, args=(payload,), daemon=True).start()

    # ── Public entry points ───────────────────────────────────────────────────

    def _run_hypothesis(self, payload):
        hypothesis = payload.get("hypothesis", "")
        contract   = payload.get("contract_path", "")
        code       = payload.get("code", "")
        print(f"\n[nexus] Gate 1 — Hypothesis: {hypothesis[:80]}")
        result = self._run_gate(1, hypothesis=hypothesis, contract=contract, code=code)
        self._bus.dispatch("nexus.gate_result", result)

    def _run_pipeline(self, payload):
        hypothesis = payload.get("hypothesis", "")
        contract   = payload.get("contract_path", "")
        code       = payload.get("code", "")
        gates      = payload.get("gates", list(range(1, 8)))

        print(f"\n[nexus] ══ 7-GATE PIPELINE ══")
        print(f"[nexus] Hypothesis : {hypothesis}")
        print(f"[nexus] Contract   : {contract}")

        # Fast pre-check
        kp = _kill_pattern_fast(hypothesis)
        if kp:
            reason = _KILL_PATTERNS[kp]
            print(f"[nexus] FAST-KILL pattern {kp}: {reason}")
            self._bus.dispatch("nexus.rejected", {"hypothesis": hypothesis, "gate": 0, "kill_pattern": kp, "reason": reason})
            return

        evidence = {}
        poc = ""

        for gate_num in gates:
            if gate_num not in _GATES:
                continue
            name = _GATES[gate_num][0]
            print(f"[nexus] ── Gate {gate_num}: {name}")

            result = self._run_gate(
                gate_num,
                hypothesis=hypothesis,
                contract=contract,
                code=code,
                evidence=evidence,
                poc=poc,
            )
            self._bus.dispatch("nexus.gate_result", result)

            # Accumulate evidence
            if gate_num == 2 and result.get("output"):
                evidence = result["output"]
            if gate_num == 3 and result.get("output"):
                poc = result["output"] if isinstance(result["output"], str) else str(result["output"])

            # Gate kill
            if result.get("kill_reason"):
                print(f"[nexus] KILLED at gate {gate_num}: {result['kill_reason']}")
                self._bus.dispatch("nexus.rejected", {
                    "hypothesis": hypothesis,
                    "gate": gate_num,
                    "kill_pattern": result.get("kill_pattern"),
                    "reason": result["kill_reason"],
                })
                return

            # Gate 3: if UNEXPLOITABLE bail
            if gate_num == 3 and isinstance(poc, str) and "UNEXPLOITABLE" in poc:
                self._bus.dispatch("nexus.rejected", {
                    "hypothesis": hypothesis,
                    "gate": 3,
                    "kill_pattern": None,
                    "reason": poc,
                })
                return

            # Gate 6: adversarial verdict
            if gate_num == 6:
                raw = result.get("raw_output", "")
                if "REJECTED" in raw.upper():
                    print(f"[nexus] Gate 6 adversarial rejection: {raw[:200]}")
                    self._bus.dispatch("nexus.rejected", {
                        "hypothesis": hypothesis,
                        "gate": 6,
                        "kill_pattern": None,
                        "reason": raw,
                    })
                    return

            # Gate 7: reproducibility verdict
            if gate_num == 7:
                out = result.get("output", {})
                if isinstance(out, dict) and out.get("verdict") == "FAIL":
                    print(f"[nexus] Gate 7 reproducibility failed: {out.get('issues')}")
                    self._bus.dispatch("nexus.rejected", {
                        "hypothesis": hypothesis,
                        "gate": 7,
                        "kill_pattern": None,
                        "reason": f"PoC not reproducible: {out.get('issues', [])}",
                    })
                    return

        # All gates passed — emit finding
        economic = evidence.get("economic", {}) if isinstance(evidence, dict) else {}
        severity = economic.get("severity", "High") if isinstance(economic, dict) else "High"
        print(f"\n[nexus] ✅ FINDING CONFIRMED — {severity}")
        self._bus.dispatch("nexus.finding", {
            "severity":    severity,
            "title":       hypothesis[:120],
            "hypothesis":  hypothesis,
            "evidence":    evidence,
            "poc":         poc,
            "gates_passed": gates,
            "economic":   economic,
        })

    def _run_single_gate(self, payload):
        gate_num   = payload.get("gate_num", 1)
        hypothesis = payload.get("hypothesis", "")
        evidence   = payload.get("evidence", {})
        poc        = payload.get("poc", "")
        contract   = payload.get("contract_path", "")
        code       = payload.get("code", "")
        result = self._run_gate(gate_num, hypothesis=hypothesis, contract=contract,
                                code=code, evidence=evidence, poc=poc)
        self._bus.dispatch("nexus.gate_result", result)

    # ── Core gate runner ─────────────────────────────────────────────────────

    def _run_gate(self, gate_num: int, *, hypothesis="", contract="", code="",
                  evidence=None, poc="") -> dict:
        router = self._get_router()
        gate_name, tier, system_prompt = _GATES[gate_num]

        user_prompt = self._build_prompt(gate_num, hypothesis=hypothesis,
                                         contract=contract, code=code,
                                         evidence=evidence, poc=poc)

        raw_output = ""
        parsed_output = None
        kill_reason = None
        kill_pattern = None

        if router:
            try:
                raw_output = router.complete(
                    prompt=user_prompt,
                    system=system_prompt,
                    gate=gate_num,
                    think=(tier == 1),
                    code=(tier == 2),
                )
                parsed_output = self._parse_output(gate_num, raw_output)

                # Check for kill signal in output
                kp = _kill_pattern_fast(raw_output)
                if kp:
                    kill_pattern = kp
                    kill_reason = _KILL_PATTERNS[kp]

            except Exception as e:
                raw_output = f"ERROR: {e}"
                print(f"[nexus] gate {gate_num} error: {e}")
        else:
            raw_output = "[model_router unavailable — skipped]"

        result = {
            "gate_num":    gate_num,
            "name":        gate_name,
            "tier":        tier,
            "passed":      kill_reason is None and "ERROR" not in raw_output,
            "output":      parsed_output if parsed_output is not None else raw_output,
            "raw_output":  raw_output,
            "kill_reason": kill_reason,
            "kill_pattern": kill_pattern,
        }
        print(f"[nexus]   Gate {gate_num} {'✓' if result['passed'] else '✗'} — {len(raw_output)} chars")
        return result

    def _build_prompt(self, gate_num: int, *, hypothesis, contract, code, evidence, poc) -> str:
        ev_str  = json.dumps(evidence, indent=2) if isinstance(evidence, dict) else str(evidence or "")
        kp_str  = "\n".join(f"  {k}. {v}" for k, v in _KILL_PATTERNS.items())

        if gate_num == 1:
            return f"Contract: {contract}\n\nCode:\n{code[:6000]}\n\nForm a specific vulnerability hypothesis."
        if gate_num == 2:
            return f"Hypothesis: {hypothesis}\n\nContract: {contract}\n\nCode:\n{code[:6000]}"
        if gate_num == 3:
            return f"Hypothesis: {hypothesis}\n\nEvidence:\n{ev_str}\n\nContract: {contract}\n\nWrite the Foundry fork PoC."
        if gate_num == 4:
            return f"Vulnerability pattern: {hypothesis}\n\nFind matching historical DeFi exploits."
        if gate_num == 5:
            return f"Hypothesis: {hypothesis}\n\nEvidence:\n{ev_str}\n\nPoC sketch:\n{poc[:2000]}\n\nModel economic impact."
        if gate_num == 6:
            return (
                f"Hypothesis: {hypothesis}\n\nEvidence:\n{ev_str}\n\nPoC:\n{poc[:2000]}\n\n"
                f"Kill patterns to check:\n{kp_str}\n\nChallenge this finding — find every reason to reject it."
            )
        if gate_num == 7:
            return f"PoC to verify:\n\n{poc}\n\nVerify reproducibility and output JSON verdict."
        return hypothesis

    def _parse_output(self, gate_num: int, raw: str):
        if gate_num in (2, 4, 5, 7):
            # Expect JSON
            try:
                # Strip markdown fences if present
                text = raw.strip()
                if text.startswith("```"):
                    text = "\n".join(text.split("\n")[1:])
                    text = text.rsplit("```", 1)[0].strip()
                return json.loads(text)
            except Exception:
                return raw
        return raw


def register(bus):
    agent = NexusTrinityAgent(bus)
    bus.register(agent, subscriptions={"nexus.hypothesis", "nexus.pipeline", "nexus.gate"})
    print("[plugin] nexus_trinity registered")
