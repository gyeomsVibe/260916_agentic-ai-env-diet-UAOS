"""U248: REA Graceful Process Finalization (finalization_ms) & Finite Typed Reconstruction Verifier.

1. `terminate_with_finalization`: When a captured/supervised worker times out,
   sends SIGTERM (`terminate()`) first, observes for `finalization_ms` so the
   process can flush its final receipt, and sends SIGKILL (`kill()`) once only
   if it has not exited by the end of the interval.
2. `verify_reconstruction`: Evaluates a finite typed obligation ledger against
   observed test/oracle results (e.g. DX-Ball 3,205 cases), passing only when
   all declared comparable claims pass without claiming global equivalence.
"""

from __future__ import annotations

import subprocess
from typing import Any


def terminate_with_finalization(
    proc: subprocess.Popen[Any],
    *,
    finalization_ms: int = 500,
) -> dict[str, Any]:
    """Gracefully stop a timed-out process with a bounded finalization window."""
    signals: list[dict[str, Any]] = []
    if proc.poll() is not None:
        return {
            "timed_out": False,
            "exit_code": proc.returncode,
            "finalization": {"signals": signals, "exit_code": proc.returncode, "killed": False},
        }

    try:
        proc.terminate()
        signals.append({"signal": "SIGTERM", "delivered": True})
    except OSError as exc:
        signals.append({"signal": "SIGTERM", "delivered": False, "error": str(exc)})

    wait_sec = max(0.01, float(finalization_ms) / 1000.0)
    try:
        finalizer_code = proc.wait(timeout=wait_sec)
        return {
            "timed_out": True,
            "exit_code": None,
            "finalization": {
                "signals": signals,
                "exit_code": finalizer_code,
                "killed": False,
            },
        }
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
            signals.append({"signal": "SIGKILL", "delivered": True})
        except OSError as exc:
            signals.append({"signal": "SIGKILL", "delivered": False, "error": str(exc)})
        try:
            proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            pass
        return {
            "timed_out": True,
            "exit_code": None,
            "finalization": {
                "signals": signals,
                "exit_code": None,
                "killed": True,
            },
        }


def verify_reconstruction(
    obligation_ledger: dict[str, Any],
    observed_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Verify finite typed reconstruction obligations against oracle outcomes."""
    obligations = obligation_ledger.get("obligations") or []
    if not obligations:
        return {"verdict": "FAILED", "reason": "EMPTY_OBLIGATION_LEDGER", "verified": [], "failed": []}

    verified: list[str] = []
    failed: list[dict[str, Any]] = []
    for obl in obligations:
        oid = str(obl.get("obligation_id"))
        expected_cases = int(obl.get("oracle_cases", 1))
        obs = observed_results.get(oid)
        if not isinstance(obs, dict):
            failed.append({"obligation_id": oid, "reason": "MISSING_OBSERVATION"})
            continue
        passed_cases = int(obs.get("passed_cases", 0))
        failed_cases = int(obs.get("failed_cases", 0))
        if passed_cases >= expected_cases and failed_cases == 0 and obs.get("byte_or_behavior_match", True):
            verified.append(oid)
        else:
            failed.append({
                "obligation_id": oid,
                "reason": "ORACLE_MISMATCH",
                "expected_cases": expected_cases,
                "passed_cases": passed_cases,
                "failed_cases": failed_cases,
            })

    verdict = "PASS" if not failed else "FAILED"
    return {
        "verdict": verdict,
        "target_id": obligation_ledger.get("target_id"),
        "verified_count": len(verified),
        "total_obligations": len(obligations),
        "verified": verified,
        "failed": failed,
        "global_equivalence_claimed": False,
        "scope_note": "Pass covers only declared comparable obligations, not global binary equivalence.",
    }
