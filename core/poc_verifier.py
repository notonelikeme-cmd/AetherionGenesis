# core/poc_verifier.py
"""
Deterministic PoC verification for Nexus Trinity's Gate 3 (Simulation/PoC).

An LLM's own narration that "the exploit worked" is not evidence — it can
hallucinate, misreport a failing run as a pass, or write a PoC that never
actually asserts anything meaningful (assertTrue(true) is exactly the kill
pattern this pipeline already screens for in plugins/nexus_trinity_plugin.py).
This module closes that gap: it actually runs the PoC via `forge test`
against a real fork and only calls a finding confirmed if three independent
signals agree — forge's own exit code, an explicit confirmation marker in
the PoC's own output, and a real non-zero on-chain state delta. Zero LLM
involvement in this step.

Convention the PoC must follow (see the Gate 3 system prompt in
nexus_trinity_plugin.py, which instructs the LLM to emit these):
  console.log("BEFORE_STATE", <uint state before the attack>);
  ... execute the attack ...
  console.log("AFTER_STATE", <uint state after the attack>);
  console.log("VULNERABILITY_CONFIRMED");   // only if the attack worked
"""
import os
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFY_DIR = Path(os.getenv("POC_VERIFY_DIR", str(ROOT / "verify")))

# A real transaction can't spend more gas than fits in a block. If a
# "confirmed" run claims more than this, the fork state itself is bogus
# (e.g. a corrupted storage slot forcing an expensive retry loop) rather
# than a real exploit — mainnet's gas limit is well above 30M as of 2026,
# so this is a deliberately conservative ceiling, not a precise one.
_MAX_SANE_GAS = 30_000_000

_BEFORE_RE = re.compile(r"BEFORE_STATE\D*(\d+)")
_AFTER_RE = re.compile(r"AFTER_STATE\D*(\d+)")
# Real forge 1.7.1 output, confirmed by direct observation (not assumed):
#   [PASS] test_exploit() (gas: 48032)
#   [FAIL: exploit failed: 0 <= 0] test_exploit() (gas: 17456)
#   [FAIL: simulated attack revert] test_exploit() (gas: 3914)
# forge does not distinguish a plain assertion failure from a revert in
# this tag — both come through as [FAIL: <reason>] — so the reason text
# itself, not a coarse revert/assert split, is what's actually specific.
_PASS_GAS_RE = re.compile(r"\[PASS\]\s+\S+\(\)\s+\(gas:\s*(\d+)\)")
_FAIL_RE = re.compile(r"\[FAIL:\s*([^\]]*)\]")
_COMPILE_FAIL_RE = re.compile(r"Compiler run failed|Compilation failed")


def verify_evm_poc(finding_id: str, poc_code: str, timeout: int = 180) -> dict:
    """
    Writes `poc_code` to a real Foundry test file under VERIFY_DIR and runs
    `forge test` against it from the repo root (so foundry.toml/lib/forge-std
    resolve regardless of the caller's cwd).

    Returns:
      status: "CONFIRMED" | "NOT_CONFIRMED" | "UNAVAILABLE" | "ERROR"
      confirmed: bool
      before_state / after_state: int | None
      output: str (forge's combined stdout+stderr, tail-truncated)
      reason: str  (why NOT_CONFIRMED/UNAVAILABLE/ERROR)
    """
    safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", finding_id)[:60] or "poc"
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    verify_path = VERIFY_DIR / f"Verify_{safe_id}_{int(time.time())}.t.sol"

    try:
        verify_path.write_text(poc_code, encoding="utf-8")
    except OSError as e:
        return _result("ERROR", reason=f"could not write PoC file: {e}")

    try:
        try:
            res = subprocess.run(
                ["forge", "test", "--match-path", str(verify_path), "-vvvv"],
                capture_output=True, text=True, timeout=timeout,
                cwd=str(ROOT), env=os.environ.copy(),
            )
        except FileNotFoundError:
            return _result("UNAVAILABLE", reason="forge binary not found on PATH")
        except subprocess.TimeoutExpired:
            return _result("ERROR", reason=f"forge test exceeded {timeout}s timeout")

        output = res.stdout + res.stderr

        if _COMPILE_FAIL_RE.search(output):
            return _result(
                "NOT_CONFIRMED", output=output, failure_class="COMPILE_ERROR",
                reason="the PoC did not compile — see output for the solc error",
            )

        before_match = _BEFORE_RE.search(output)
        after_match = _AFTER_RE.search(output)
        before = int(before_match.group(1)) if before_match else None
        after = int(after_match.group(1)) if after_match else None

        if before is None or after is None:
            fail_match = _FAIL_RE.search(output)
            reason = "PoC did not emit BEFORE_STATE/AFTER_STATE markers — can't verify a real delta"
            if fail_match:
                reason += f" (forge also reported: {fail_match.group(1).strip()})"
            return _result("NOT_CONFIRMED", output=output, failure_class="MARKERS_MISSING", reason=reason)

        delta_real = before != after
        claims_confirmed = "VULNERABILITY_CONFIRMED" in output
        forge_passed = res.returncode == 0
        gas_match = _PASS_GAS_RE.search(output)
        gas_used = int(gas_match.group(1)) if gas_match else None

        if forge_passed and claims_confirmed and delta_real:
            if gas_used is not None and gas_used > _MAX_SANE_GAS:
                return _result(
                    "NOT_CONFIRMED", output=output, before=before, after=after, gas_used=gas_used,
                    failure_class="GAS_ANOMALY",
                    reason=f"forge test passed and claimed confirmation, but used {gas_used} gas — more than fits in a real block, so the fork state isn't trustworthy",
                )
            return _result("CONFIRMED", output=output, before=before, after=after, gas_used=gas_used)

        fail_match = _FAIL_RE.search(output)
        forge_reason = fail_match.group(1).strip() if fail_match else None

        if not forge_passed:
            failure_class = "ASSERTION_FAILED"
            reason = "forge test failed — the exploit did not execute as claimed"
            if forge_reason:
                reason += f": {forge_reason}"
        elif not claims_confirmed:
            failure_class = "NOT_CLAIMED"
            reason = "forge test passed but the PoC never emitted VULNERABILITY_CONFIRMED"
        else:
            failure_class = "NO_STATE_DELTA"
            reason = f"forge test passed and claimed confirmation, but on-chain state didn't change ({before} -> {after}) — likely false positive"

        return _result("NOT_CONFIRMED", output=output, before=before, after=after,
                        gas_used=gas_used, failure_class=failure_class, reason=reason)
    finally:
        try:
            verify_path.unlink()
        except OSError:
            pass


def _result(status, output="", before=None, after=None, gas_used=None, failure_class=None, reason="") -> dict:
    return {
        "status": status,
        "confirmed": status == "CONFIRMED",
        "before_state": before,
        "after_state": after,
        "gas_used": gas_used,
        "failure_class": failure_class,
        "output": output[-4000:],
        "reason": reason,
    }
