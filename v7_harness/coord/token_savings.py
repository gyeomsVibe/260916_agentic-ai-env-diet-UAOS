"""U76-A: paid-token savings from matched controlled pairs only (docs/63). Read-only; never deletes or rewrites rows.

A usage row may carry an optional `comparison` envelope next to the uaos-usage-v2 keys:
    {"comparison_id", "role": "baseline_paid" | "thrift", "input_hash", "acceptance_hash", "task_type",
     "model_family", "rework": <int, default 0>}
A valid pair is one baseline_paid row and one thrift row with the same comparison_id, input hash, acceptance hash,
task type, and model family, both PASS, each checked by an independent verifier who is not the row's actor.
Fewer than WINDOW valid pairs is UNMEASURED. With WINDOW or more, only the latest WINDOW pairs decide; older pairs
stay auditable history with zero decision weight (no half-life, no deletion).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .usage_ledger import UsageRejected, _check_secrets, ledger_file

# The same sample count as U55 (token ratchet) and U56 (THRIFT threshold): 10 valid samples before a claim.
WINDOW = 10
ROLES = ("baseline_paid", "thrift")
MATCH_KEYS = ("input_hash", "acceptance_hash", "task_type")
ENVELOPE_KEYS = ("comparison_id", "role", *MATCH_KEYS, "model_family")
# Reported separately so one improved metric cannot hide a regression in another.
METRICS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "wall_time_s")
EXCLUSIONS = ("malformed", "secret", "duplicate", "incomplete", "cross_model", "unmatched", "failed", "self_verified")


def _number(value: Any) -> float | int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    return value


def _envelope(row: dict[str, Any]) -> dict[str, Any] | None:
    envelope = row.get("comparison")
    if not isinstance(envelope, dict):
        return None
    for key in ENVELOPE_KEYS:
        value = envelope.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
    if envelope["role"] not in ROLES:
        return None
    rework = envelope.get("rework", 0)
    if isinstance(rework, bool) or not isinstance(rework, int) or rework < 0:
        return None
    return envelope


def _read(path: Path) -> tuple[list[dict[str, Any]], dict[str, int], int]:
    """Rows that carry a well-formed envelope, row-level exclusion counts, and rows without any envelope."""
    excluded = dict.fromkeys(EXCLUSIONS, 0)
    rows: list[dict[str, Any]] = []
    without = 0
    if not path.is_file():
        return rows, excluded, without
    for line in path.read_bytes().decode("utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            excluded["malformed"] += 1
            continue
        if not isinstance(row, dict):
            excluded["malformed"] += 1
            continue
        if "comparison" not in row:
            without += 1
            continue
        if _envelope(row) is None:
            excluded["malformed"] += 1
            continue
        try:
            _check_secrets(row)
        except UsageRejected:
            excluded["secret"] += 1
            continue
        rows.append(row)
    return rows, excluded, without


def _pair_problem(members: list[dict[str, Any]]) -> str | None:
    roles = [row["comparison"]["role"] for row in members]
    if any(roles.count(role) > 1 for role in ROLES):
        return "duplicate"  # a second run of one side could cherry-pick the best result
    if sorted(roles) != sorted(ROLES):
        return "incomplete"
    base, thrift = sorted(members, key=lambda row: ROLES.index(row["comparison"]["role"]))
    if base["comparison"]["model_family"] != thrift["comparison"]["model_family"]:
        return "cross_model"
    family = base["comparison"]["model_family"].strip().lower()
    actual_models = []
    for row in (base, thrift):
        actual = row.get("model")
        if not isinstance(actual, str) or not actual.strip():
            return "cross_model"
        normalized = actual.strip().lower()
        if normalized != family and not (
            normalized.startswith(family) and normalized[len(family):len(family) + 1] in {"-", ".", ":", "/"}
        ):
            return "cross_model"
        actual_models.append(normalized)
    if actual_models[0] != actual_models[1]:
        return "cross_model"
    if any(base["comparison"][key] != thrift["comparison"][key] for key in MATCH_KEYS):
        return "unmatched"
    if base.get("outcome") != "PASS" or thrift.get("outcome") != "PASS":
        return "failed"
    for row in (base, thrift):
        verifier = row.get("independent_verifier")
        if not isinstance(verifier, str) or not verifier.strip() or verifier == row.get("actor"):
            return "self_verified"
    return None


def _ts(row: dict[str, Any]) -> float:
    value = _number(row.get("ts"))
    return float(value) if value is not None else 0.0


def _window(pairs: list[tuple[str, dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    regressions: list[str] = []
    pair_regressions: dict[str, list[str]] = {}
    unknown: list[str] = []
    for metric in METRICS:
        sums = {"baseline_paid": 0.0, "thrift": 0.0}
        missing = 0
        regressed_ids = []
        for cid, base, thrift in pairs:
            values = (_number(base.get(metric)), _number(thrift.get(metric)))
            if None in values:
                missing += 1
                continue
            sums["baseline_paid"] += values[0]
            sums["thrift"] += values[1]
            if values[1] > values[0]:
                regressed_ids.append(cid)
        clean = {role: (int(total) if total.is_integer() else round(total, 3)) for role, total in sums.items()}
        saved = None if missing else clean["baseline_paid"] - clean["thrift"]
        if saved is None:
            unknown.append(metric)  # a missing value is UNKNOWN, never zero
        elif saved < 0 or regressed_ids:
            regressions.append(metric)
        if regressed_ids:
            pair_regressions[metric] = regressed_ids
        metrics[metric] = {**clean, "saved": saved, "missing_pairs": missing}
    rework = {role: sum(int(member["comparison"].get("rework", 0)) for pair in pairs for member in pair[1:]
                        if member["comparison"]["role"] == role) for role in ROLES}
    if rework["thrift"] > rework["baseline_paid"]:
        regressions.append("rework")
    rework_ids = [cid for cid, base, thrift in pairs
                  if int(thrift["comparison"].get("rework", 0)) > int(base["comparison"].get("rework", 0))]
    if rework_ids:
        pair_regressions["rework"] = rework_ids
        if "rework" not in regressions:
            regressions.append("rework")
    return {"pairs": len(pairs), "comparison_ids": [cid for cid, _, _ in pairs], "metrics": metrics,
            "rework": rework, "quality": "PASS on both sides of every pair", "regressions": regressions,
            "pair_regressions": pair_regressions, "unknown_metrics": unknown}


def report(project: Path) -> dict[str, Any]:
    path = ledger_file(Path(project))
    rows, excluded, without = _read(path)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(row["comparison"]["comparison_id"], []).append(row)
    valid: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    for cid, members in groups.items():
        problem = _pair_problem(members)
        if problem:
            excluded[problem] += 1
            continue
        base, thrift = sorted(members, key=lambda row: ROLES.index(row["comparison"]["role"]))
        valid.append((cid, base, thrift))
    valid.sort(key=lambda pair: (max(_ts(pair[1]), _ts(pair[2])), pair[0]))
    measured = len(valid) >= WINDOW
    window = _window(valid[-WINDOW:]) if measured else None
    return {
        "source": str(path),
        "status": "MEASURED" if measured else "UNMEASURED",
        "window_size": WINDOW,
        "valid_pairs": len(valid),
        "history_pairs": max(0, len(valid) - WINDOW),
        "rows_without_comparison": without,
        "excluded": excluded,
        "window": window,
        "savings_claim_allowed": bool(window and not window["regressions"] and not window["unknown_metrics"]),
        "note": "Only matched controlled pairs count; UNMEASURED below 10 valid pairs. The ledger is read, never "
                "rewritten; older pairs keep zero decision weight.",
    }
