"""U248: REA Graceful Process Finalization (finalization_ms) & Finite Typed Reconstruction Verifier."""

from __future__ import annotations

import subprocess
from typing import Any


def terminate_with_finalization(
    proc: subprocess.Popen[Any],
    *,
    finalization_ms: int = 500,
) -> dict[str, Any]:
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
        kill_delivered = False
        try:
            proc.kill()
            kill_delivered = True
            signals.append({"signal": "SIGKILL", "delivered": True})
        except OSError as exc:
            signals.append({"signal": "SIGKILL", "delivered": False, "error": str(exc)})
        exited_code = None
        try:
            exited_code = proc.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            exited_code = proc.poll()
        killed_ok = bool(kill_delivered and (exited_code is not None or proc.poll() is not None))
        return {
            "timed_out": True,
            "exit_code": None,
            "finalization": {
                "signals": signals,
                "exit_code": exited_code,
                "killed": killed_ok,
            },
        }


def verify_reconstruction(
    obligation_ledger: dict[str, Any],
    observed_results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
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
        if passed_cases >= expected_cases and failed_cases == 0 and obs.get("byte_or_behavior_match") is True:
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
