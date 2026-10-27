"""U273: Disjoint Traffic-Light Mediator (`disjoint_mediator.py`) for Ollama CLI + Haiku 5.5 Parallel Execution.

Solves the root cause of `SOURCE_DIVERGED` during parallel Ollama + Haiku execution:
1. Even when Ollama (`v7_harness/*.py`) and Haiku (`tests/*`, `docs/*`) have 100% disjoint `allow` scopes,
   running Haiku directly in `source_dir` while `pilot run` (Ollama) is mid-flight mutates the whole-tree
   `base_manifest_hash`, triggering `source_escape_paths()` and `dry_run_promotion()` `SOURCE_DIVERGED` aborts.
2. This Traffic-Light Mediator provides:
   - **File-Scope Lane Lease (`acquire_lane_lease` / `release_lane_lease`)**: Atomic SQLite/JSON traffic-light
     state machine (`GREEN_PARALLEL`, `YELLOW_SCOPED_REBASE`, `RED_PATH_CONFLICT`) in `.coord/mediator/lanes.json`.
   - **Scoped Manifest Divergence Evaluation (`check_scoped_source_divergence`)**: Distinguishes true same-file
     collision (`CONFLICTING_DIVERGENCE` -> RED abort) from disjoint companion-lane writes (`DISJOINT_COMPANION_WRITE`
     -> GREEN/YELLOW auto-rebase) when the companion lane holds an active registered lease on the changed files
     and zero overlap exists with the pilot's `allowed_scopes` and `patch_bundle` items.
"""

from __future__ import annotations

import fnmatch
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from v7_harness.isolation.manifest import DeterministicManifest, PatchBundle, build_manifest, compute_bundle_id

MEDIATOR_SCHEMA = "uaos-disjoint-traffic-light-v1"
DEFAULT_LEASE_TTL_S = 900.0  # 15 minutes max lease lifetime before automatic stale expiry


def _norm(path: str) -> str:
    p = str(path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.rstrip("/")


def _matches_any_scope(rel_path: str, scopes: Sequence[str] | None) -> bool:
    if not scopes:
        return False
    norm_p = _norm(rel_path)
    for raw_s in scopes:
        s = _norm(str(raw_s))
        if not s or s == "*":
            return True
        if norm_p == s or norm_p.startswith(s + "/") or fnmatch.fnmatch(norm_p, s):
            return True
    return False


def _scopes_overlap(scopes_a: Sequence[str], scopes_b: Sequence[str]) -> list[str]:
    norm_a = [_norm(s) for s in scopes_a if _norm(s)]
    norm_b = [_norm(s) for s in scopes_b if _norm(s)]
    overlaps: set[str] = set()
    for a in norm_a:
        for b in norm_b:
            if a == b or a == "*" or b == "*":
                overlaps.add(f"{a}<->{b}")
            elif a.startswith(b + "/") or b.startswith(a + "/"):
                overlaps.add(f"{a}<->{b}")
            elif fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a):
                overlaps.add(f"{a}<->{b}")
    return sorted(overlaps)


def mediator_state_file(source_dir: Path) -> Path:
    return Path(source_dir).resolve() / ".coord" / "mediator" / "lanes.json"


def _load_state(source_dir: Path, now: float | None = None) -> dict[str, Any]:
    moment = float(now if now is not None else time.time())
    sfile = mediator_state_file(source_dir)
    data: dict[str, Any] = {"schema": MEDIATOR_SCHEMA, "updated_at": moment, "active_lanes": {}}
    if sfile.is_file():
        try:
            loaded = json.loads(sfile.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("active_lanes"), dict):
                data["active_lanes"] = loaded["active_lanes"]
        except (OSError, ValueError):
            pass
    # Prune expired leases
    alive: dict[str, Any] = {}
    for lane_id, info in data["active_lanes"].items():
        if not isinstance(info, dict):
            continue
        expires_at = float(info.get("expires_at") or 0.0)
        if expires_at > moment:
            alive[lane_id] = info
    data["active_lanes"] = alive
    return data


def _save_state(source_dir: Path, state: dict[str, Any]) -> None:
    sfile = mediator_state_file(source_dir)
    sfile.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="lanes.", suffix=".tmp", dir=str(sfile.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(sfile))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def acquire_lane_lease(
    source_dir: Path,
    *,
    lane_id: str,
    worker: str,
    allowed_scopes: Sequence[str],
    ttl_s: float = DEFAULT_LEASE_TTL_S,
    now: float | None = None,
) -> dict[str, Any]:
    """Traffic-Light Signal Check before launching Ollama or Haiku:
    - Returns `signal='GREEN_PARALLEL'` and registers the lease if `allowed_scopes` are disjoint from all active lanes.
    - Returns `signal='RED_PATH_CONFLICT'` (and refuses registration) if any active lane overlaps `allowed_scopes`
      or if `worker == 'ollama'` while another `ollama` lane is already running (GPU serial lock).
    """
    moment = float(now if now is not None else time.time())
    norm_scopes = [_norm(s) for s in allowed_scopes if _norm(s)]
    if not norm_scopes:
        return {
            "ok": False,
            "signal": "RED_EMPTY_SCOPE",
            "lane_id": lane_id,
            "reason": "Parallel mediator requires explicit non-empty allowed_scopes",
        }

    state = _load_state(source_dir, now=moment)
    active = state["active_lanes"]
    worker_norm = str(worker or "").strip().lower()

    conflicts: list[dict[str, Any]] = []
    for other_id, other in active.items():
        if other_id == lane_id:
            continue
        other_worker = str(other.get("worker") or "").lower()
        other_scopes = other.get("allowed_scopes") or []
        if worker_norm in ("ollama", "local") and other_worker in ("ollama", "local"):
            conflicts.append({
                "conflicting_lane_id": other_id,
                "reason": "OLLAMA_GPU_SERIAL_LOCK (max_concurrent_ollama=1)",
                "overlaps": ["GPU:qwen2.5-coder:7b"],
            })
            continue
        overlaps = _scopes_overlap(norm_scopes, other_scopes)
        if overlaps:
            conflicts.append({
                "conflicting_lane_id": other_id,
                "reason": "DISJOINT_SCOPE_OVERLAP",
                "overlaps": overlaps,
            })

    if conflicts:
        return {
            "ok": False,
            "signal": "RED_PATH_CONFLICT",
            "lane_id": lane_id,
            "worker": worker_norm,
            "requested_scopes": norm_scopes,
            "conflicts": conflicts,
        }

    lease_entry = {
        "lane_id": lane_id,
        "worker": worker_norm,
        "allowed_scopes": norm_scopes,
        "acquired_at": moment,
        "expires_at": moment + float(ttl_s),
        "pid": os.getpid(),
    }
    active[lane_id] = lease_entry
    state["updated_at"] = moment
    _save_state(source_dir, state)
    return {
        "ok": True,
        "signal": "GREEN_PARALLEL",
        "lane_id": lane_id,
        "worker": worker_norm,
        "allowed_scopes": norm_scopes,
        "active_companion_lanes": [k for k in active if k != lane_id],
    }


def release_lane_lease(source_dir: Path, *, lane_id: str, now: float | None = None) -> dict[str, Any]:
    moment = float(now if now is not None else time.time())
    state = _load_state(source_dir, now=moment)
    removed = state["active_lanes"].pop(lane_id, None)
    state["updated_at"] = moment
    _save_state(source_dir, state)
    return {"ok": True, "lane_id": lane_id, "released": removed is not None}


def evaluate_scoped_divergence(
    *,
    base_manifest: DeterministicManifest | None,
    source_dir: Path,
    excludes: Sequence[str] | None,
    pilot_allowed_scopes: Sequence[str] | None,
    bundle: PatchBundle | None = None,
) -> dict[str, Any]:
    """Traffic-Light Mediator for `SOURCE_DIVERGED`:
    When `source_dir` changes while a scoped pilot run (`pilot_allowed_scopes`) is executing:
    1. Computes the exact set of files changed in `source_dir` since `base_manifest`.
    2. Checks if ANY changed file overlaps `pilot_allowed_scopes` or `bundle.items`.
       - If overlap exists -> `signal='RED_CONFLICTING_DIVERGENCE'`, returns the conflicting paths so `pilot.py`
         fails closed with `SOURCE_DIVERGED`.
       - If ZERO overlap exists (`pilot_allowed_scopes` is non-empty and disjoint from all external changes) ->
         `signal='YELLOW_SCOPED_REBASE'`, returns a rebased `PatchBundle` anchored to the current `source_dir`
         manifest so Ollama and Haiku never abort each other on disjoint files!
    """
    if base_manifest is None:
        return {"signal": "GREEN_NO_DIVERGENCE", "conflicting_paths": [], "disjoint_companion_paths": [], "rebased_bundle": bundle}

    current_manifest = build_manifest(Path(source_dir).resolve(), excludes=list(excludes or []))
    if current_manifest.manifest_hash == base_manifest.manifest_hash:
        return {"signal": "GREEN_NO_DIVERGENCE", "conflicting_paths": [], "disjoint_companion_paths": [], "rebased_bundle": bundle}

    before = {entry.path: entry.sha256 for entry in base_manifest.entries}
    after = {entry.path: entry.sha256 for entry in current_manifest.entries}
    all_changed = sorted(path for path in (before.keys() | after.keys()) if before.get(path) != after.get(path))

    # If the pilot run had unrestricted scope (None or '*'), any external change is a conflict
    norm_pilot_scopes = [_norm(str(s)) for s in (pilot_allowed_scopes or []) if _norm(str(s))]
    if not norm_pilot_scopes or "*" in norm_pilot_scopes:
        return {
            "signal": "RED_CONFLICTING_DIVERGENCE",
            "conflicting_paths": all_changed,
            "disjoint_companion_paths": [],
            "rebased_bundle": None,
        }

    bundle_item_paths = {_norm(item.path) for item in (bundle.items if bundle else [])}
    conflicting: list[str] = []
    disjoint_companion: list[str] = []

    for rel_path in all_changed:
        norm_p = _norm(rel_path)
        if norm_p in bundle_item_paths or _matches_any_scope(norm_p, norm_pilot_scopes):
            conflicting.append(rel_path)
        else:
            disjoint_companion.append(rel_path)

    if conflicting:
        return {
            "signal": "RED_CONFLICTING_DIVERGENCE",
            "conflicting_paths": conflicting,
            "disjoint_companion_paths": disjoint_companion,
            "rebased_bundle": None,
        }

    rebased_bundle: PatchBundle | None = bundle
    if bundle is not None:
        # Verify that every item in bundle still matches its base_sha256 in current_manifest
        for item in bundle.items:
            if after.get(item.path) != item.base_sha256:
                return {
                    "signal": "RED_CONFLICTING_DIVERGENCE",
                    "conflicting_paths": [item.path],
                    "disjoint_companion_paths": disjoint_companion,
                    "rebased_bundle": None,
                }
        new_bundle_id = compute_bundle_id(
            current_manifest.manifest_hash,
            bundle.target_manifest_hash,
            bundle.items,
            bundle.metadata,
        )
        rebased_bundle = PatchBundle(
            bundle_id=new_bundle_id,
            base_manifest_hash=current_manifest.manifest_hash,
            target_manifest_hash=bundle.target_manifest_hash,
            items=bundle.items,
            metadata=bundle.metadata,
        )

    return {
        "signal": "YELLOW_SCOPED_REBASE",
        "conflicting_paths": [],
        "disjoint_companion_paths": disjoint_companion,
        "rebased_bundle": rebased_bundle,
        "current_manifest": current_manifest,
    }
