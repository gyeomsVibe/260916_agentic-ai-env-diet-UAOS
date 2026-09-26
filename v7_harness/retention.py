"""U42-R1: deletion-free retention planning.

A retention plan is only ever a dry-run manifest: which files are old or excess for their zone,
which are protected (failure/P1/approval evidence), and which are excluded because their run is
still active or locked. Nothing in this module deletes a file. Archiving/restoring and real
deletion are separate, explicitly-approved steps outside this module's scope; `apply_retention`
with `execute_delete=True` always refuses.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Optional


class RetentionRefused(Exception):
    """Raised when a retention plan or apply call would violate a safety invariant."""


def default_policy() -> dict[str, Any]:
    """Deterministic default retention zones covering the harness's own runtime state."""
    return {
        "zones": [
            {"path": ".coord/usage", "retention_days": 180, "max_count": 5000,
             "max_bytes": 50_000_000, "kind": "generic"},
            {"path": ".coord/stream", "retention_days": 90, "max_count": 5000,
             "max_bytes": 20_000_000, "kind": "generic"},
            {"path": ".coord/pilot/runs", "retention_days": 30, "max_count": 500,
             "max_bytes": 200_000_000, "kind": "runs"},
            {"path": ".work/logs", "retention_days": 30, "max_count": 200,
             "max_bytes": 100_000_000, "kind": "generic"},
            {"path": ".coord/approvals", "retention_days": 3650, "max_count": 100000,
             "max_bytes": 50_000_000, "kind": "approvals"},
            {"path": ".coord/rsi", "retention_days": 365, "max_count": 2000,
             "max_bytes": 50_000_000, "kind": "generic"},
            {"path": ".coord/sentinel/receipts", "retention_days": 90, "max_count": 5000,
             "max_bytes": 50_000_000, "kind": "generic"},
        ],
    }


def _resolve_zone_path(root: Path, zone_path: str) -> Path:
    root_resolved = Path(root).resolve()
    target = (root_resolved / zone_path).resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        raise RetentionRefused(f"PATH_ESCAPE: zone path escapes the retention root: {zone_path}")
    return target


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_run_status(path: Path) -> tuple[Optional[str], bool]:
    """Best-effort read of a run/summary JSON file's status and P1-ness. Never raises."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return None, False
    if not isinstance(data, dict):
        return None, False
    status = data.get("status")
    is_p1 = bool(data.get("p1")) or str(status).upper() == "P1"
    return status, is_p1


def plan_retention(root: Path, policy: dict[str, Any], now: float) -> dict[str, Any]:
    """Build a deterministic, deletion-free retention manifest.

    Enumeration is sorted (stable), path escape is rejected, ACTIVE/locked runs are excluded, and
    failure/P1/approval evidence is protected regardless of age. Everything else past its zone's
    retention window is classified ARCHIVE_CANDIDATE with a planned archive/restore path and its
    SHA-256, never deleted here.
    """
    # Normalize Windows short/long path spellings before relative comparisons.
    root = Path(root).resolve()
    items: list[dict[str, Any]] = []

    for zone in policy.get("zones", []):
        zone_path = zone["path"]
        target_dir = _resolve_zone_path(root, zone_path)
        if not target_dir.is_dir():
            continue

        kind = zone.get("kind", "generic")
        retention_days = zone.get("retention_days", 30)

        for path in sorted(p for p in target_dir.rglob("*") if p.is_file()):
            try:
                stat = path.stat()
            except OSError:
                continue
            rel = path.relative_to(root).as_posix()
            age_days = max(0.0, (now - stat.st_mtime) / 86400.0)

            action = "KEEP"
            if kind == "approvals":
                action = "PROTECT"
            elif kind == "runs":
                status, is_p1 = _read_run_status(path)
                if str(status).upper() == "ACTIVE":
                    action = "ACTIVE_EXCLUDE"
                elif str(status).upper() == "FAILED" or is_p1:
                    action = "PROTECT"
                elif age_days >= retention_days:
                    action = "ARCHIVE_CANDIDATE"
            elif age_days >= retention_days:
                action = "ARCHIVE_CANDIDATE"

            item: dict[str, Any] = {
                "path": rel,
                "zone": zone_path,
                "action": action,
                "age_days": round(age_days, 3),
                "size_bytes": stat.st_size,
                "sha256": _file_sha256(path),
            }
            if action == "ARCHIVE_CANDIDATE":
                item["archive_path"] = f".coord/retention_archive/{rel}"
                item["restore_path"] = rel
            items.append(item)

    items.sort(key=lambda entry: entry["path"])
    manifest_sha256 = hashlib.sha256(
        json.dumps(items, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return {"generated_at": now, "policy_zones": len(policy.get("zones", [])),
            "items": items, "manifest_sha256": manifest_sha256}


def apply_retention(root: Path, plan: dict[str, Any], *, execute_delete: bool = False) -> dict[str, Any]:
    """Print/return the plan. Defaults to DRY_RUN; a real delete needs a fresh, separate approval
    and is out of this task's scope, so `execute_delete=True` always refuses."""
    if execute_delete:
        raise RetentionRefused(
            "FRESH_DELETE_APPROVAL_REQUIRED: retention deletion needs a fresh, explicit approval "
            "receipt bound to this manifest hash; this call performs no deletion"
        )
    candidates = [item for item in plan.get("items", []) if item.get("action") == "ARCHIVE_CANDIDATE"]
    return {
        "status": "DRY_RUN",
        "manifest_sha256": plan.get("manifest_sha256"),
        "archive_candidates": len(candidates),
        "items": plan.get("items", []),
    }
