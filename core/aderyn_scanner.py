# core/aderyn_scanner.py
"""
Static analysis via Aderyn (Cyfrin's Rust-based Solidity analyzer) for
Nexus Trinity's Gate 2 (Evidence Gathering).

This adds a second, independent, zero-LLM signal alongside Gate 2's
LLM-read evidence: real findings from an actual external static-analysis
tool, not an LLM's pattern-matched guess at what might be wrong.

`--skip-update-check` is REQUIRED, not optional — confirmed by direct
testing, not documentation. aderyn 0.1.9 installed via cargo (rather than
its own installer script) panics in a separate self-update-check step
that runs immediately after the report is already written correctly to
disk; without this flag the tool crashes on every single invocation in a
cargo-installed environment. `--stdout` mode is separately broken in this
version (panics while printing instance locations) — writing to a real
file and reading it back, as this module does, is the path that actually
works.
"""
import re
import subprocess
import tempfile
from pathlib import Path

_ISSUE_RE = re.compile(r"^## ([A-Z]{1,3})-(\d+): (.+)$", re.MULTILINE)


def scan(code: str, timeout: int = 60) -> dict:
    """
    Writes `code` to a temporary directory as a single .sol file and runs
    aderyn against it.

    Returns:
      status: "OK" | "UNAVAILABLE" | "ERROR"
      issues: list[{"id": "H-1", "title": "..."}]
      report: str (full markdown report, tail-truncated)
      reason: str (set for UNAVAILABLE/ERROR)
    """
    with tempfile.TemporaryDirectory(prefix="aderyn_scan_") as tmpdir:
        src_path = Path(tmpdir) / "Target.sol"
        report_path = Path(tmpdir) / "report.md"

        try:
            src_path.write_text(code, encoding="utf-8")
        except OSError as e:
            return _result("ERROR", reason=f"could not write source file: {e}")

        try:
            subprocess.run(
                ["aderyn", tmpdir, "-o", str(report_path), "--skip-update-check", "--skip-cloc"],
                capture_output=True, text=True, timeout=timeout,
            )
        except FileNotFoundError:
            return _result("UNAVAILABLE", reason="aderyn binary not found on PATH")
        except subprocess.TimeoutExpired:
            return _result("ERROR", reason=f"aderyn exceeded {timeout}s timeout")

        if not report_path.exists():
            return _result("ERROR", reason="aderyn did not produce a report (likely a compile error in the code)")

        report = report_path.read_text(encoding="utf-8")
        issues = [
            {"id": f"{m.group(1)}-{m.group(2)}", "title": m.group(3)}
            for m in _ISSUE_RE.finditer(report)
        ]
        return _result("OK", issues=issues, report=report)


def _result(status, issues=None, report="", reason="") -> dict:
    return {
        "status": status,
        "issues": issues or [],
        "report": report[-6000:],
        "reason": reason,
    }
