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

_BEFORE_RE = re.compile(r"BEFORE_STATE\D*(\d+)")
_AFTER_RE = re.compile(r"AFTER_STATE\D*(\d+)")


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
        before_match = _BEFORE_RE.search(output)
        after_match = _AFTER_RE.search(output)
        before = int(before_match.group(1)) if before_match else None
        after = int(after_match.group(1)) if after_match else None

        if before is None or after is None:
            return _result(
                "NOT_CONFIRMED", output=output,
                reason="PoC did not emit BEFORE_STATE/AFTER_STATE markers — can't verify a real delta",
            )

        delta_real = before != after
        claims_confirmed = "VULNERABILITY_CONFIRMED" in output
        forge_passed = res.returncode == 0

        if forge_passed and claims_confirmed and delta_real:
            return _result("CONFIRMED", output=output, before=before, after=after)

        if not forge_passed:
            reason = "forge test failed — the exploit did not execute as claimed"
        elif not claims_confirmed:
            reason = "forge test passed but the PoC never emitted VULNERABILITY_CONFIRMED"
        else:
            reason = f"forge test passed and claimed confirmation, but on-chain state didn't change ({before} -> {after}) — likely false positive"

        return _result("NOT_CONFIRMED", output=output, before=before, after=after, reason=reason)
    finally:
        try:
            verify_path.unlink()
        except OSError:
            pass


def _result(status, output="", before=None, after=None, reason="") -> dict:
    return {
        "status": status,
        "confirmed": status == "CONFIRMED",
        "before_state": before,
        "after_state": after,
        "output": output[-4000:],
        "reason": reason,
    }
