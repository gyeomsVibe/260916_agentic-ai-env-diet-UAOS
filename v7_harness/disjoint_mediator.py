"""U273: Intelligent Zero-Wait Flagman (`disjoint_mediator.py`) for Lag-Free Parallel Execution of Ollama CLI + Haiku 5.5.

Core Philosophy:
- "If Ollama stops and waits while Haiku works, that is a FAILURE. Lag-free parallel execution must run under a
  competent Flagman (유능한 신호수), not a rigid mechanical traffic light."
- How the Competent Zero-Wait Flagman (`ZeroWaitFlagman`) works:
  1. **Dynamic Lane Carve-Out (`flagman_route_lanes`)**: Instead of stopping a worker with a red light when scopes
     overlap, the Flagman dynamically carves out Haiku's paths (`tests/*`, `docs/*`, `*.md`, `*.html`) from Ollama's
     code scope (`v7_harness/*.py`) so BOTH launch at 0ms wait.
  2. **Zero-Wait Scoped Bypass (`flagman_resolve_divergence`)**: In `pilot.py`, whenever `config.allowed_scopes` is
     constrained (e.g., `allow: v7_harness/rsi.py`), the Flagman AUTOMATICALLY ignores any concurrent changes made by
     Haiku outside `allowed_scopes` — WITHOUT requiring any manual lease registration in `.coord/mediator/lanes.json`!
  3. **Live Cross-Feed Test Sync (`flagman_sync_companion_tests_into_staging`)**: Right before Ollama runs `accept_cmd`
     in `staging_dir`, the Flagman copies Haiku's newly updated `tests/*` files from `source_dir` into `staging_dir`
     so Ollama's code slice is immediately verified against Haiku's latest test suite on the first pass.
"""

from __future__ import annotations

import fnmatch
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Sequence

from v7_harness.isolation.manifest import DeterministicManifest, PatchBundle, build_manifest, compute_bundle_id

MEDIATOR_SCHEMA = "uaos-zero-wait-flagman-v2"
DEFAULT_LEASE_TTL_S = 900.0


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


def _is_test_or_doc_scope(scope: str) -> bool:
    s = _norm(scope).lower()
    return (
        s.startswith("tests/")
        or s == "tests"
        or s.startswith("docs/")
        or s == "docs"
        or s.endswith((".md", ".html"))
    )


def flagman_route_lanes(
    ollama_scopes: Sequence[str],
    haiku_scopes: Sequence[str],
) -> dict[str, Any]:
    """Competent Flagman Dynamic Lane Carve-Out (유능한 신호수 실시간 차선 가변 분리):
    Never blocks or waits when Ollama and Haiku scopes overlap. Instead, dynamically carves out
    test/doc scopes to Haiku (`haiku_assigned_scopes`) and code scopes to Ollama (`ollama_assigned_scopes`)
    so both workers depart simultaneously with 0ms wait (`wait_ms=0`).
    """
    raw_olla = [_norm(s) for s in ollama_scopes if _norm(s)]
    raw_haiku = [_norm(s) for s in haiku_scopes if _norm(s)]

    carved_haiku: list[str] = []
    carved_olla: list[str] = []
    rerouted_from_olla_to_haiku: list[str] = []
    rerouted_from_haiku_to_olla: list[str] = []

    for s in raw_haiku:
        if _is_test_or_doc_scope(s):
            if s not in carved_haiku:
                carved_haiku.append(s)
        else:
            if s not in carved_olla:
                carved_olla.append(s)
            rerouted_from_haiku_to_olla.append(s)

    for s in raw_olla:
        if _is_test_or_doc_scope(s):
            if s not in carved_haiku:
                carved_haiku.append(s)
            rerouted_from_olla_to_haiku.append(s)
        elif s == "*":
            # Carve wildcard '*' into code scope so it never collides with Haiku's tests/* or docs/*
            if "v7_harness/*" not in carved_olla:
                carved_olla.append("v7_harness/*")
            rerouted_from_olla_to_haiku.append("tests/*,docs/* (carved from *)")
        else:
            if s not in carved_olla:
                carved_olla.append(s)

    # Guarantee zero overlap after carve-out
    final_olla = [s for s in carved_olla if not any(_scopes_overlap([s], [h]) for h in carved_haiku)]
    overlaps_after = _scopes_overlap(final_olla, carved_haiku)

    return {
        "schema": MEDIATOR_SCHEMA,
        "flagman_action": "ZERO_WAIT_DYNAMIC_BYPASS" if (rerouted_from_olla_to_haiku or rerouted_from_haiku_to_olla) else "ZERO_WAIT_CLEAR_PASS",
        "wait_ms": 0,
        "ollama_Blocked": False,
        "haiku_Blocked": False,
        "ollama_assigned_scopes": final_olla,
        "haiku_assigned_scopes": carved_haiku,
        "rerouted_to_haiku": rerouted_from_olla_to_haiku,
        "rerouted_to_ollama": rerouted_from_haiku_to_olla,
        "disjoint_guaranteed": len(overlaps_after) == 0,
    }


def flagman_sync_companion_tests_into_staging(
    *,
    source_dir: Path,
    staging_dir: Path,
    disjoint_companion_paths: Sequence[str],
    pilot_allowed_scopes: Sequence[str] | None,
) -> list[str]:
    """Competent Flagman Live Cross-Feed Sync (실시간 테스트 핫-싱크):
    When Haiku finishes writing/updating `tests/*` in `source_dir` while Ollama is running in `staging_dir`,
    copies those updated test files into `staging_dir` right before `accept_cmd` runs (as long as they are
    outside Ollama's `pilot_allowed_scopes`) so Ollama's code slice is tested against Haiku's latest tests!
    """
    synced: list[str] = []
    src_root = Path(source_dir).resolve()
    stg_root = Path(staging_dir).resolve()
    for rel in disjoint_companion_paths:
        norm_p = _norm(rel)
        if not norm_p.startswith("tests/"):
            continue
        if _matches_any_scope(norm_p, pilot_allowed_scopes):
            continue
        src_f = src_root / norm_p
        dst_f = stg_root / norm_p
        if src_f.is_file():
            try:
                dst_f.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_f, dst_f)
                synced.append(norm_p)
            except OSError:
                pass
    return synced


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
    auto_carve_on_overlap: bool = False,
    ttl_s: float = DEFAULT_LEASE_TTL_S,
    now: float | None = None,
) -> dict[str, Any]:
    """Register an active worker lane. When `auto_carve_on_overlap=True` (Flagman mode), automatically carves out
    overlapping companion paths so the worker launches immediately with 0ms wait."""
    moment = float(now if now is not None else time.time())
    norm_scopes = [_norm(s) for s in allowed_scopes if _norm(s)]
    if not norm_scopes:
        return {
            "ok": False,
            "signal": "RED_EMPTY_SCOPE",
            "lane_id": lane_id,
            "reason": "Parallel flagman requires explicit non-empty allowed_scopes",
        }

    state = _load_state(source_dir, now=moment)
    active = state["active_lanes"]
    worker_norm = str(worker or "").strip().lower()

    conflicts: list[dict[str, Any]] = []
    carved_scopes = list(norm_scopes)

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
        overlaps = _scopes_overlap(carved_scopes, other_scopes)
        if overlaps:
            if auto_carve_on_overlap:
                routed = (
                    flagman_route_lanes(carved_scopes, other_scopes)
                    if worker_norm in ("ollama", "local")
                    else flagman_route_lanes(other_scopes, carved_scopes)
                )
                carved_scopes = (
                    routed["ollama_assigned_scopes"]
                    if worker_norm in ("ollama", "local")
                    else routed["haiku_assigned_scopes"]
                )
            else:
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
        "allowed_scopes": carved_scopes,
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
        "flagman_action": "ZERO_WAIT_DYNAMIC_BYPASS" if carved_scopes != norm_scopes else "ZERO_WAIT_CLEAR_PASS",
        "wait_ms": 0,
        "lane_id": lane_id,
        "worker": worker_norm,
        "allowed_scopes": carved_scopes,
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
    """Competent Zero-Wait Flagman Scoped Divergence Resolution (`evaluate_scoped_divergence`):
    Whenever `pilot_allowed_scopes` is explicitly constrained (e.g., `allow: v7_harness/rsi.py`) and a companion
    worker (Haiku) edits disjoint files (`tests/*`, `docs/*`) in `source_dir` while Ollama is running:
    - ZERO-WAIT BYPASS (`signal='YELLOW_SCOPED_REBASE'`, `flagman_action='ZERO_WAIT_SCOPED_BYPASS'`):
      Automatically filters out all non-overlapping companion changes and rebases `bundle` onto `current_manifest`
      in <2ms with 0ms wait and NO requirement for manual `.coord/mediator/lanes.json` registration!
    - Only if an external write touched the EXACT SAME file inside `pilot_allowed_scopes` or `bundle.items`
      does it return `RED_CONFLICTING_DIVERGENCE`.
    """
    if base_manifest is None:
        return {
            "signal": "GREEN_NO_DIVERGENCE",
            "flagman_action": "ZERO_WAIT_CLEAR_PASS",
            "wait_ms": 0,
            "conflicting_paths": [],
            "disjoint_companion_paths": [],
            "rebased_bundle": bundle,
        }

    current_manifest = build_manifest(Path(source_dir).resolve(), excludes=list(excludes or []))
    if current_manifest.manifest_hash == base_manifest.manifest_hash:
        return {
            "signal": "GREEN_NO_DIVERGENCE",
            "flagman_action": "ZERO_WAIT_CLEAR_PASS",
            "wait_ms": 0,
            "conflicting_paths": [],
            "disjoint_companion_paths": [],
            "rebased_bundle": bundle,
        }

    before = {entry.path: entry.sha256 for entry in base_manifest.entries}
    after = {entry.path: entry.sha256 for entry in current_manifest.entries}
    all_changed = sorted(path for path in (before.keys() | after.keys()) if before.get(path) != after.get(path))

    norm_pilot_scopes = [_norm(str(s)) for s in (pilot_allowed_scopes or []) if _norm(str(s))]
    if not norm_pilot_scopes or "*" in norm_pilot_scopes:
        return {
            "signal": "RED_CONFLICTING_DIVERGENCE",
            "flagman_action": "UNSCOPED_EXTERNAL_MUTATION",
            "wait_ms": 0,
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
            "flagman_action": "SAME_FILE_COLLISION_DETECTED",
            "wait_ms": 0,
            "conflicting_paths": conflicting,
            "disjoint_companion_paths": disjoint_companion,
            "rebased_bundle": None,
        }

    rebased_bundle: PatchBundle | None = bundle
    if bundle is not None:
        for item in bundle.items:
            if after.get(item.path) != item.base_sha256:
                return {
                    "signal": "RED_CONFLICTING_DIVERGENCE",
                    "flagman_action": "SAME_FILE_COLLISION_DETECTED",
                    "wait_ms": 0,
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
        "flagman_action": "ZERO_WAIT_SCOPED_BYPASS",
        "wait_ms": 0,
        "conflicting_paths": [],
        "disjoint_companion_paths": disjoint_companion,
        "rebased_bundle": rebased_bundle,
        "current_manifest": current_manifest,
    }
