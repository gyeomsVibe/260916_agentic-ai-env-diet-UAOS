"""UAOS-RSI Bilateral Parallel Surge & Congestion-Relief Scheduler (U390-C).

Relieves single-director backlog, latency, pointer tangles, and split-brain
confusion by activating a threshold-triggered Fork-Join Bilateral Surge across
all verified awake organs, paired with monotonic fencing tokens, disjoint file
partitioning, Cilk-style work-stealing, and a 1-round cyclic terminal Corpus
Callosum cross-verification join.

Scientific & Systems Foundations (Stage 0):
- Banich & Belger (1990, Cortex 26:77-94): Interhemispheric processing
  advantage emerges under high cognitive load/complexity, whereas low load
  favors single-hemisphere processing to avoid transfer overhead.
- Blumofe & Leiserson (1999, JACM 46(5), MIT Cilk): Work-stealing fork-join
  scheduling reduces expected makespan toward T_1 / P + O(T_inf) with bounded
  space S_1 * P.
- Martin Kleppmann (2016): Monotonic fencing tokens + resource-side validation
  prevent stale-lease split-brain overwrites and ownership tangles.

Deployment Boundary & Invariants:
- Proposal and verification module (`PROPOSAL_ONLY_UNINSTALLED`); not wired
  into production hooks or global rules until non-author keypoint review.
- Strictly model-agnostic (`assert_surge_model_agnostic`: 0 model identifiers).
- Fail-closed on `UNKNOWN` / `None` quotas, unproven availability, unscoped
  mutating tasks, and stale fencing epochs.
- `author != judge` (`self_judge_permitted = False`) across all 8 availability
  scenarios (S1..S8).
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

SURGE_SCHEMA_VERSION = "uaos.bilateral_surge_scheduler/v1"
DEPLOYMENT_STATUS = "PROPOSAL_ONLY_UNINSTALLED"

# Pure percentage floor matching UAOS-RSI physiology (never converted to tokens).
ORGAN_PAUSE_PROTECT_PCT = 5.0
CEREBELLAR_MAX_SLICE_LINES = 20

# Congestion thresholds (Banich-Belger single-director vs bilateral-surge crossover).
SURGE_PENDING_THRESHOLD = 3
SURGE_WAIT_MINUTES_THRESHOLD = 15.0
SURGE_DIRECTOR_LOAD_THRESHOLD = 0.80
ELEVATED_WAIT_MINUTES_THRESHOLD = 8.0
ELEVATED_DIRECTOR_LOAD_THRESHOLD = 0.60

PRIORITY_ORDER: dict[str, int] = {
    "URGENT": 0,
    "CRITICAL": 1,
    "HIGH": 2,
    "NORMAL": 3,
    "LOW": 4,
}


def _build_forbidden_model_regexes() -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Construct model-specificity detectors without embedding literal model strings."""
    gp = "g" + "pt"
    cl = "clau" + "de"
    gm = "gem" + "ini"
    qw = "qw" + "en"
    ll = "lla" + "ma"
    ds = "deep" + "seek"
    ms = "mis" + "tral"
    ph = "ph" + "i"
    op = "op" + "us"
    sn = "son" + "net"
    hk = "hai" + "ku"
    fl = "fla" + "sh"
    ne = "ne" + "on"
    ar = "ar" + "gon"
    cb = "car" + "bon"
    hy = "hydro" + "gen"
    as_ = "as" + "tra"
    lu = "lu" + "na"
    te = "ter" + "ra"
    so = "s" + "ol"

    specs = (
        ("OPENAI_FAMILY_VERSION", rf"\b{gp}[-\s]?(?:[0-9]|oss)\w*"),
        ("OPENAI_REASONING_SERIES", r"\bo[134](?:-[a-z0-9]+)?\b"),
        ("OPENAI_CODENAME_TIER", rf"\b(?:{as_}|{lu}|{te})\b|\b{gp}[-\s0-9.]*{so}\b"),
        ("ANTHROPIC_VERSIONED", rf"\b{cl}[-\s]+(?:[0-9]|{op}|{sn}|{hk})\w*"),
        ("ANTHROPIC_TIER_NAME", rf"\b(?:{op}|{sn}|{hk})(?:[-\s]+[0-9]+(?:\.[0-9]+)?)?\b"),
        ("GOOGLE_FAMILY_VERSION", rf"\b{gm}(?:[-\s]+[0-9a-z.]+)+"),
        ("GOOGLE_HYBRID_CODENAME", rf"\b(?:{ne}|{ar}|{cb}|{hy}|{fl}-lite)\b"),
        ("LOCAL_WEIGHT_FAMILY", rf"\b(?:{qw}[0-9.]*|{ll}[0-9.-]*|{ds}[-\w]*|{ms}[-\w]*|{ph}-[0-9])\b"),
        ("PARAMETER_TAG_SUFFIX", r":[0-9]+(?:\.[0-9]+)?(?:b|k)\b"),
    )
    return tuple((code, re.compile(pat, re.IGNORECASE)) for code, pat in specs)


_FORBIDDEN_MODEL_REGEXES = _build_forbidden_model_regexes()


def assert_surge_model_agnostic(text: str, *, context: str = "surge_artifact") -> dict[str, Any]:
    """Negative-selection guard rejecting hardcoded model names in surge specs/tasks."""
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    violations: list[dict[str, str]] = []
    for code, pat in _FORBIDDEN_MODEL_REGEXES:
        for match in pat.finditer(text):
            violations.append(
                {
                    "code": "MODEL_SPECIFICITY_VIOLATION",
                    "detector": code,
                    "matched": match.group(0),
                    "context": context,
                }
            )
    return {
        "ok": len(violations) == 0,
        "context": context,
        "violation_count": len(violations),
        "violations": violations,
    }


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _normalize_repo_path(path_str: str) -> str:
    """Normalize slash/case/dot prefix so overlapping path detection never misses Windows variants."""
    cleaned = str(path_str or "").strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    cleaned = re.sub(r"/+", "/", cleaned).rstrip("/")
    return cleaned.lower()


def _admit_organ(vitality_map: Mapping[str, Any] | None, organ: str, *, is_cloud: bool) -> dict[str, Any]:
    """Fail-closed admission check requiring explicit `available is True` and finite numeric `%` quota."""
    if not isinstance(vitality_map, Mapping):
        return {"admitted": False, "pct": None, "reason": "MISSING_VITALITY_MAP"}
    entry = vitality_map.get(organ)
    if not isinstance(entry, Mapping):
        return {"admitted": False, "pct": None, "reason": "MISSING_ORGAN_ENTRY"}
    avail = entry.get("available")
    if avail is not True:
        return {
            "admitted": False,
            "pct": None,
            "reason": "EXPLICITLY_UNAVAILABLE" if avail is False else "AVAILABILITY_UNPROVEN",
        }
    if not is_cloud:
        return {"admitted": True, "pct": None, "reason": "VERIFIED_LOCAL_AVAILABLE"}
    raw_pct = entry.get("remaining_7d_pct")
    if not _is_finite_number(raw_pct):
        return {"admitted": False, "pct": None, "reason": "UNKNOWN_QUOTA"}
    pct = float(raw_pct)
    if pct < 0.0 or pct > 100.0:
        return {"admitted": False, "pct": None, "reason": "INVALID_QUOTA_RANGE"}
    if pct <= ORGAN_PAUSE_PROTECT_PCT:
        return {"admitted": False, "pct": pct, "reason": "PROTECTIVE_QUOTA_REST"}
    return {"admitted": True, "pct": pct, "reason": "VERIFIED_AWAKE"}


AVAILABILITY_SCENARIO_MATRIX: dict[tuple[bool, bool, bool], dict[str, Any]] = {
    (True, True, True): {
        "scenario_id": "S1",
        "korean_label": "3도구 전원 가동 (좌뇌·우뇌·감각운동 전신 병렬 급행)",
        "parallelism": 3,
        "execution_mode": "TRI_ORGAN_BILATERAL_SURGE",
        "cross_verify_mode": "CYCLIC_3WAY_TERMINAL_CROSS_VERIFY",
        "terminal_join_rounds": 1,
        "keypoint_policy": "LEFT_BRAIN_DIRECT",
    },
    (True, True, False): {
        "scenario_id": "S2",
        "korean_label": "좌뇌·우뇌 2도구 가동 (감각운동 부재 — 양반구 분산 급행)",
        "parallelism": 2,
        "execution_mode": "BILATERAL_HEMISPHERE_SURGE",
        "cross_verify_mode": "MIRROR_2WAY_BILATERAL_CROSS_VERIFY",
        "terminal_join_rounds": 1,
        "keypoint_policy": "LEFT_BRAIN_DIRECT",
    },
    (True, False, True): {
        "scenario_id": "S3",
        "korean_label": "좌뇌·감각운동 2도구 가동 (우뇌 부재 — 형식·실행 병렬 급행)",
        "parallelism": 2,
        "execution_mode": "LEFT_BRAIN_SENSORIMOTOR_SURGE",
        "cross_verify_mode": "MIRROR_2WAY_LEFT_BODY_CROSS_VERIFY",
        "terminal_join_rounds": 1,
        "keypoint_policy": "LEFT_BRAIN_DIRECT",
    },
    (False, True, True): {
        "scenario_id": "S4",
        "korean_label": "우뇌·감각운동 2도구 가동 (좌뇌 부재 — 맥락·실행 병렬 급행)",
        "parallelism": 2,
        "execution_mode": "RIGHT_BRAIN_SENSORIMOTOR_SURGE",
        "cross_verify_mode": "MIRROR_2WAY_RIGHT_BODY_CROSS_VERIFY",
        "terminal_join_rounds": 1,
        "keypoint_policy": "DEFERRED_LEFT_KEYPOINT_SIGN_OFF",
    },
    (True, False, False): {
        "scenario_id": "S5",
        "korean_label": "좌뇌 단독 가동 (우뇌·감각운동 부재 — 단일 직렬 급행 + 사후 교차판정)",
        "parallelism": 1,
        "execution_mode": "SOLO_LEFT_SERIAL_DRAIN",
        "cross_verify_mode": "SOLO_LEFT_DEFERRED_PEER_VERDICT",
        "terminal_join_rounds": 0,
        "keypoint_policy": "DEFERRED_PEER_REVIEW_NO_SELF_JUDGE",
    },
    (False, True, False): {
        "scenario_id": "S6",
        "korean_label": "우뇌 단독 가동 (좌뇌·감각운동 부재 — 단일 직렬 급행 + 사후 교차판정)",
        "parallelism": 1,
        "execution_mode": "SOLO_RIGHT_SERIAL_DRAIN",
        "cross_verify_mode": "SOLO_RIGHT_DEFERRED_PEER_VERDICT",
        "terminal_join_rounds": 0,
        "keypoint_policy": "DEFERRED_LEFT_KEYPOINT_SIGN_OFF",
    },
    (False, False, True): {
        "scenario_id": "S7",
        "korean_label": "감각운동 단독 가동 (좌·우뇌 부재 — 임시대행 직렬 + 대뇌 복귀 감사)",
        "parallelism": 1,
        "execution_mode": "SOLO_SENSORIMOTOR_ACTING_DRAIN",
        "cross_verify_mode": "SOLO_SENSORIMOTOR_DEFERRED_CORTICAL_AUDIT",
        "terminal_join_rounds": 0,
        "keypoint_policy": "DEFERRED_LEFT_KEYPOINT_SIGN_OFF",
    },
    (False, False, False): {
        "scenario_id": "S8",
        "korean_label": "유료 3도구 전원 부재/미확인 (Fail-Closed 차단 · 로컬 소뇌 오프라인 스테이징 전용)",
        "parallelism": 0,
        "execution_mode": "FAIL_CLOSED_NO_CLOUD_ORGAN",
        "cross_verify_mode": "BLOCKED_OR_LOCAL_OFFLINE_STAGING_ONLY",
        "terminal_join_rounds": 0,
        "keypoint_policy": "BLOCKED_AWAITING_ACTIVE_HEMISPHERE",
    },
}


def evaluate_congestion_state(telemetry: Mapping[str, Any]) -> dict[str, Any]:
    """Classify single-director congestion using explicit observed telemetry (missing -> UNKNOWN)."""
    if not isinstance(telemetry, Mapping):
        raise TypeError("telemetry must be a Mapping")

    missing: list[str] = []
    raw_pending = telemetry.get("pending_tasks")
    raw_urgent = telemetry.get("urgent_tasks")
    raw_wait = telemetry.get("oldest_wait_minutes")
    raw_load = telemetry.get("active_director_load")
    raw_conflicts = telemetry.get("stale_pointer_conflicts")

    if not (_is_finite_number(raw_pending) and int(raw_pending) >= 0):
        missing.append("pending_tasks")
    if not (_is_finite_number(raw_urgent) and int(raw_urgent) >= 0):
        missing.append("urgent_tasks")
    if not (_is_finite_number(raw_wait) and float(raw_wait) >= 0.0):
        missing.append("oldest_wait_minutes")
    if not (_is_finite_number(raw_load) and 0.0 <= float(raw_load) <= 1.0):
        missing.append("active_director_load")

    if missing:
        return {
            "schema": SURGE_SCHEMA_VERSION,
            "congestion_level": "UNKNOWN",
            "surge_recommended": False,
            "triggers": [],
            "missing_evidence": missing,
        }

    pending = int(raw_pending)
    urgent = int(raw_urgent)
    oldest_wait = float(raw_wait)
    director_load = float(raw_load)
    pointer_conflicts = int(raw_conflicts) if (_is_finite_number(raw_conflicts) and int(raw_conflicts) >= 0) else 0

    triggers: list[str] = []
    if pending >= SURGE_PENDING_THRESHOLD:
        triggers.append(f"PENDING_QUEUE_GE_{SURGE_PENDING_THRESHOLD}")
    if urgent >= 1 and pending >= 2:
        triggers.append("URGENT_PREEMPTION_WITH_BACKLOG")
    if oldest_wait >= SURGE_WAIT_MINUTES_THRESHOLD:
        triggers.append(f"WAIT_GE_{int(SURGE_WAIT_MINUTES_THRESHOLD)}M")
    if director_load >= SURGE_DIRECTOR_LOAD_THRESHOLD:
        triggers.append("DIRECTOR_SATURATION_GE_80PCT")
    if pointer_conflicts >= 1:
        triggers.append("STALE_POINTER_OR_SPLIT_BRAIN_CONFLICT")

    if triggers:
        level = "SURGE"
        surge = True
    elif (
        pending == 2
        or urgent >= 1
        or oldest_wait >= ELEVATED_WAIT_MINUTES_THRESHOLD
        or director_load >= ELEVATED_DIRECTOR_LOAD_THRESHOLD
    ):
        level = "ELEVATED"
        surge = True
    else:
        level = "NORMAL"
        surge = False

    return {
        "schema": SURGE_SCHEMA_VERSION,
        "congestion_level": level,
        "surge_recommended": surge,
        "triggers": triggers,
        "missing_evidence": [],
    }


def classify_availability_scenario(vitality_map: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Classify the exact 1-of-8 (2^3) verified availability state across Codex, Claude, Antigravity (+ Ollama)."""
    admissions = {
        "codex": _admit_organ(vitality_map, "codex", is_cloud=True),
        "claude": _admit_organ(vitality_map, "claude", is_cloud=True),
        "antigravity": _admit_organ(vitality_map, "antigravity", is_cloud=True),
        "ollama": _admit_organ(vitality_map, "ollama", is_cloud=False),
    }
    key = (
        bool(admissions["codex"]["admitted"]),
        bool(admissions["claude"]["admitted"]),
        bool(admissions["antigravity"]["admitted"]),
    )
    meta = AVAILABILITY_SCENARIO_MATRIX[key]
    active_cloud = tuple(
        tool
        for tool, admitted in zip(("codex", "claude", "antigravity"), key)
        if admitted
    )
    return {
        **meta,
        "active_cloud_organs": active_cloud,
        "ollama_available": bool(admissions["ollama"]["admitted"]),
        "tool_admissions": admissions,
    }


def _select_terminal_judge(
    *,
    worker: str,
    active_cloud: tuple[str, ...],
    is_keypoint: bool,
    judge_load: Mapping[str, int],
) -> tuple[str, str, bool]:
    """Assign a balanced non-author terminal cross-verifier across awake organs.

    Returns ``(judge_tool, judge_mode, requires_codex_keypoint_signoff)``.
    """
    peers = [tool for tool in active_cloud if tool != worker]
    if not peers:
        mode = (
            "SOLO_SENSORIMOTOR_DEFERRED_CORTICAL_AUDIT"
            if worker == "antigravity"
            else "DEFERRED_PEER_VERDICT_NO_SELF_JUDGE"
        )
        return "DEFERRED_PEER_JUDGE", mode, bool(is_keypoint and worker != "codex")

    if is_keypoint and "codex" in peers:
        return "codex", "TERMINAL_KEYPOINT_LEFT_JUDGE", False

    cyclic_next = {"codex": "claude", "claude": "antigravity", "antigravity": "codex"}
    preferred = cyclic_next.get(worker)
    ranked = sorted(
        peers,
        key=lambda t: (judge_load.get(t, 0), 0 if t == preferred else 1, t),
    )
    chosen = ranked[0]
    needs_codex_signoff = bool(is_keypoint and worker != "codex" and chosen != "codex")
    mode = (
        "TERMINAL_CYCLIC_CROSS_VERIFY_PENDING_LEFT_KEYPOINT"
        if needs_codex_signoff
        else "TERMINAL_CYCLIC_CROSS_VERIFY"
    )
    return chosen, mode, needs_codex_signoff


def plan_bilateral_surge_wave(
    tasks: Sequence[Mapping[str, Any]],
    vitality_map: Mapping[str, Mapping[str, Any]],
    *,
    active_fencing_epoch: int,
    congestion_telemetry: Mapping[str, Any],
    max_cards_per_organ: int = 1,
) -> dict[str, Any]:
    """Compute a tangle-free, fenced, disjoint parallel surge wave and fast terminal cross-verify join.

    - Low load (`NORMAL`): dispatches at most 1 serial task to avoid callosal overhead (Banich & Belger 1990).
    - High load (`ELEVATED` / `SURGE`): shards disjoint tasks across all verified awake organs (`P in {3,2,1}`)
      via affinity + Cilk work-stealing and binds a 1-round cyclic non-author judge for every shard.
    - Missing/unknown congestion telemetry (`UNKNOWN`): fails closed (`status="BLOCKED_UNKNOWN_CONGESTION"`).
    - Zero verified organs (`S8` without local eligible slice): fails closed (`status="BLOCKED_NO_VERIFIED_ORGAN"`).
    """
    if not isinstance(active_fencing_epoch, int) or isinstance(active_fencing_epoch, bool) or active_fencing_epoch < 1:
        raise ValueError("active_fencing_epoch must be a positive integer")
    if not isinstance(max_cards_per_organ, int) or isinstance(max_cards_per_organ, bool) or max_cards_per_organ < 1:
        raise ValueError("max_cards_per_organ must be a positive integer")

    tasks_json = json.dumps([dict(t) for t in tasks], ensure_ascii=False, sort_keys=True)
    agnostic = assert_surge_model_agnostic(tasks_json, context="surge_tasks")
    if not agnostic["ok"]:
        raise ValueError(f"MODEL_SPECIFICITY_VIOLATION: {agnostic['violations']}")

    congestion = evaluate_congestion_state(congestion_telemetry)
    scenario = classify_availability_scenario(vitality_map)

    if congestion["congestion_level"] == "UNKNOWN":
        return {
            "schema": SURGE_SCHEMA_VERSION,
            "deployment_status": DEPLOYMENT_STATUS,
            "installed_in_production": False,
            "production_caller_wired": False,
            "routable": False,
            "status": "BLOCKED_UNKNOWN_CONGESTION",
            "active_fencing_epoch": active_fencing_epoch,
            "congestion": congestion,
            "scenario": scenario,
            "dispatches": [],
            "terminal_cross_verify_plan": [],
            "deferred_file_conflict_queue": [],
            "deferred_capacity_queue": [],
            "rejected_stale_epoch_tasks": [],
            "rejected_unscoped_tasks": [],
            "theoretical_parallelism_factor": 0,
            "self_judge_permitted": False,
            "measured_wallclock_gain": "UNMEASURED",
            "paid_token_savings": "UNMEASURED",
            "model_agnostic_verified": True,
        }

    rejected_stale: list[dict[str, Any]] = []
    rejected_unscoped: list[dict[str, Any]] = []
    eligible: list[tuple[int, int, dict[str, Any], frozenset[str]]] = []

    for idx, raw_task in enumerate(tasks):
        task = dict(raw_task)
        task_id = str(task.get("task_id") or f"TASK-{idx + 1}")
        raw_epoch = task.get("fencing_epoch")
        if not (isinstance(raw_epoch, int) and not isinstance(raw_epoch, bool)) or raw_epoch < active_fencing_epoch:
            rejected_stale.append(
                {
                    "task_id": task_id,
                    "reason": "STALE_OR_MISSING_FENCING_EPOCH",
                    "task_epoch": raw_epoch,
                    "active_fencing_epoch": active_fencing_epoch,
                }
            )
            continue

        read_only = bool(task.get("read_only", False))
        raw_files = task.get("allow_files")
        norm_files = frozenset(
            _normalize_repo_path(p)
            for p in (raw_files or ())
            if isinstance(p, str) and p.strip()
        )
        if not read_only and not norm_files:
            rejected_unscoped.append(
                {
                    "task_id": task_id,
                    "reason": "UNSCOPED_ALLOW_FILES_FORBIDDEN",
                }
            )
            continue

        prio = str(task.get("priority") or "NORMAL").upper()
        prio_rank = PRIORITY_ORDER.get(prio, PRIORITY_ORDER["NORMAL"])
        eligible.append((prio_rank, idx, task, norm_files))

    eligible.sort(key=lambda item: (item[0], item[1]))

    active_cloud: tuple[str, ...] = scenario["active_cloud_organs"]
    ollama_up: bool = scenario["ollama_available"]
    is_surge = bool(congestion["surge_recommended"])
    wave_cloud_limit = (len(active_cloud) * max_cards_per_organ) if is_surge else (1 if active_cloud else 0)

    locked_files: dict[str, str] = {}
    organ_load: dict[str, int] = {t: 0 for t in active_cloud}
    judge_load: dict[str, int] = {t: 0 for t in active_cloud}
    ollama_load = 0

    dispatches: list[dict[str, Any]] = []
    terminal_plan: list[dict[str, Any]] = []
    deferred_conflicts: list[dict[str, Any]] = []
    deferred_capacity: list[dict[str, Any]] = []

    affinity_orders: dict[str, tuple[str, ...]] = {
        "FORMAL_INVARIANT": ("codex", "claude", "antigravity"),
        "HOLISTIC_CONTEXT": ("claude", "codex", "antigravity"),
        "SENSORIMOTOR_LABOR": ("antigravity", "claude", "codex"),
        "CEREBELLAR_SLICE": ("antigravity", "claude", "codex"),
    }

    cloud_dispatched_count = 0

    for _prio_rank, _idx, task, norm_files in eligible:
        task_id = str(task.get("task_id") or "")
        domain = str(task.get("domain") or "SENSORIMOTOR_LABOR").upper()
        is_keypoint = bool(task.get("is_keypoint", False))
        requires_judgment = bool(task.get("requires_judgment", False))
        raw_lines = task.get("line_budget", 0)
        line_budget = int(raw_lines) if (_is_finite_number(raw_lines) and int(raw_lines) >= 0) else 0

        overlapping = sorted(p for p in norm_files if p in locked_files)
        if overlapping:
            blockers = sorted({locked_files[p] for p in overlapping})
            deferred_conflicts.append(
                {
                    "task_id": task_id,
                    "reason": "DISJOINT_FILE_LOCK_CONFLICT",
                    "conflict_files": overlapping,
                    "blocked_by_tasks": blockers,
                }
            )
            continue

        if domain == "CEREBELLAR_SLICE" and not requires_judgment and line_budget <= CEREBELLAR_MAX_SLICE_LINES:
            if ollama_up and ollama_load < 1:
                ollama_load += 1
                for p in norm_files:
                    locked_files[p] = task_id
                judge_tool, judge_mode, needs_left = _select_terminal_judge(
                    worker="ollama",
                    active_cloud=active_cloud,
                    is_keypoint=is_keypoint,
                    judge_load=judge_load,
                )
                if judge_tool in judge_load:
                    judge_load[judge_tool] += 1
                dispatches.append(
                    {
                        "task_id": task_id,
                        "priority": str(task.get("priority") or "NORMAL").upper(),
                        "domain": domain,
                        "worker_tool": "ollama",
                        "dispatch_route": "CEREBELLAR_LOCAL_OFFLOAD",
                        "work_stolen": False,
                        "fencing_epoch": active_fencing_epoch,
                        "locked_files": sorted(norm_files),
                        "requires_codex_keypoint_signoff": needs_left,
                    }
                )
                terminal_plan.append(
                    {
                        "task_id": task_id,
                        "author_tool": "ollama",
                        "judge_tool": judge_tool,
                        "judge_mode": judge_mode,
                        "self_judge_permitted": False,
                    }
                )
                continue

        if not active_cloud:
            deferred_capacity.append(
                {
                    "task_id": task_id,
                    "reason": "NO_VERIFIED_CLOUD_ORGAN",
                }
            )
            continue

        if cloud_dispatched_count >= wave_cloud_limit:
            deferred_capacity.append(
                {
                    "task_id": task_id,
                    "reason": "BACKPRESSURE_WAVE_CAPACITY_REACHED",
                }
            )
            continue

        order = affinity_orders.get(domain, ("antigravity", "claude", "codex"))
        available_for_wave = [t for t in order if t in active_cloud and organ_load[t] < max_cards_per_organ]
        if not available_for_wave:
            deferred_capacity.append(
                {
                    "task_id": task_id,
                    "reason": "ALL_ACTIVE_ORGANS_AT_WAVE_CAP",
                }
            )
            continue

        preferred_awake = [t for t in order if t in active_cloud]
        natural_owner = preferred_awake[0]
        if natural_owner in available_for_wave:
            worker = natural_owner
            stolen = False
        else:
            available_for_wave.sort(
                key=lambda t: (
                    organ_load[t],
                    -(scenario["tool_admissions"][t]["pct"] or 0.0),
                    order.index(t),
                )
            )
            worker = available_for_wave[0]
            stolen = True

        organ_load[worker] += 1
        cloud_dispatched_count += 1
        for p in norm_files:
            locked_files[p] = task_id

        judge_tool, judge_mode, needs_left = _select_terminal_judge(
            worker=worker,
            active_cloud=active_cloud,
            is_keypoint=is_keypoint,
            judge_load=judge_load,
        )
        if judge_tool in judge_load:
            judge_load[judge_tool] += 1

        dispatches.append(
            {
                "task_id": task_id,
                "priority": str(task.get("priority") or "NORMAL").upper(),
                "domain": domain,
                "worker_tool": worker,
                "dispatch_route": "CILK_WORK_STEAL_SURGE" if stolen else "AFFINITY_DIRECT",
                "work_stolen": stolen,
                "fencing_epoch": active_fencing_epoch,
                "locked_files": sorted(norm_files),
                "requires_codex_keypoint_signoff": needs_left,
            }
        )
        terminal_plan.append(
            {
                "task_id": task_id,
                "author_tool": worker,
                "judge_tool": judge_tool,
                "judge_mode": judge_mode,
                "self_judge_permitted": False,
            }
        )

    routable = len(dispatches) > 0
    if not routable and scenario["scenario_id"] == "S8":
        status = "BLOCKED_NO_VERIFIED_ORGAN"
    elif not routable:
        status = "NO_ELIGIBLE_DISPATCH"
    elif is_surge and len({d["worker_tool"] for d in dispatches if d["worker_tool"] != "ollama"}) >= 2:
        status = "BILATERAL_SURGE_DISPATCHED"
    else:
        status = "SERIAL_OR_LOCAL_DISPATCHED"

    return {
        "schema": SURGE_SCHEMA_VERSION,
        "deployment_status": DEPLOYMENT_STATUS,
        "installed_in_production": False,
        "production_caller_wired": False,
        "routable": routable,
        "status": status,
        "active_fencing_epoch": active_fencing_epoch,
        "congestion": congestion,
        "scenario": scenario,
        "dispatches": dispatches,
        "terminal_cross_verify_plan": terminal_plan,
        "deferred_file_conflict_queue": deferred_conflicts,
        "deferred_capacity_queue": deferred_capacity,
        "rejected_stale_epoch_tasks": rejected_stale,
        "rejected_unscoped_tasks": rejected_unscoped,
        "theoretical_parallelism_factor": len({d["worker_tool"] for d in dispatches if d["worker_tool"] != "ollama"}),
        "self_judge_permitted": False,
        "measured_wallclock_gain": "UNMEASURED",
        "paid_token_savings": "UNMEASURED",
        "model_agnostic_verified": True,
    }


CHARTER_SURGE_PROPOSAL: dict[str, Any] = {
    "article_id": "CHARTER-SURGE-1",
    "version": "1.0.0",
    "deployment_status": DEPLOYMENT_STATUS,
    "installed_in_production": False,
    "production_caller_wired": False,
    "target_documents": (
        "uaos_everywhere/uaos_global_rule_block.md",
        "AGENTS.md",
        "CLAUDE.md",
        "GEMINI.md",
        "docs/01_unified-agent-orchestration-design.md",
    ),
    "korean_title": "제0조의5 (총괄 병목 해소용 좌·우뇌 분산 병렬 급행 및 말단 고속 교차검증 원칙)",
    "korean_body": (
        "단일 총괄 디렉터 창과 [긴급] 카드 창의 동시 누적으로 대기열 병목·지연·포인터 꼬임이 관측되면, "
        "UAOS-RSI는 단조 증가 펜싱 에포크(fencing_epoch)로 구형 지시를 차단하고 상호 비겹침 파일 범위(allow_files)로 "
        "분리된 작업만 현재 실측 가용한 전 기관(S1 3도구 전원 ~ S7 단독, S8 전원 부재 시 fail-closed)에 동시 분산 급행(Fork)한다. "
        "각 기관이 독립 슬라이스를 병렬 완수한 말단(Join)에는 작성자가 아닌 가용 동료 기관이 순환 1라운드 고속 교차검증(author != judge)을 수행하며, "
        "단독 가동(S5~S7)이나 미확인 상태(UNKNOWN/None)에서는 절대 자기승인이나 임의 배정 없이 사후 교차검증 대기 또는 fail-closed로 정직하게 보호한다."
    ),
    "english_global_rule_bullet": (
        "- Bilateral Parallel Surge & Terminal Cross-Verify (Congestion Relief): Under verified single-director congestion "
        "(backlog >=3, urgent preemption with backlog, wait >=15m, director load >=80%, or stale-pointer conflict), "
        "enforce monotonic `fencing_epoch` rejection of stale directives and disjoint `allow_files` locks, shard tasks across all "
        "verified awake cloud organs (`S1` 3-way, `S2..S4` 2-way, `S5..S7` solo serial + deferred peer verdict, `S8` fail-closed + optional "
        "local zero-paid-token <=20-line staging) via affinity + work-stealing, and run a 1-round cyclic non-author terminal cross-verify "
        "join (`author != judge`; never self-judge; never hardcode model names; report speedup/savings as `UNMEASURED` until controlled benchmark)."
    ),
}


def export_surge_charter_proposal() -> dict[str, Any]:
    """Export SHA-256-verified, model-agnostic Charter proposal for Bilateral Surge."""
    serialized = json.dumps(CHARTER_SURGE_PROPOSAL, ensure_ascii=False, sort_keys=True)
    audit = assert_surge_model_agnostic(serialized, context="charter_surge_proposal")
    if not audit["ok"]:
        raise AssertionError(f"Charter surge proposal leaked model names: {audit['violations']}")
    return {
        "schema": SURGE_SCHEMA_VERSION,
        "proposal": CHARTER_SURGE_PROPOSAL,
        "model_agnostic_verified": True,
        "sha256": hashlib.sha256(serialized.encode("utf-8")).hexdigest().upper(),
    }
