"""U251 / U261 / U267: Unified Benchmark Logic Transplant Engine (OpenRig + Show GN/AgentCodeGUI + REA)
integrated with UAOS-RSI 3-Tool Token/Capacity & Schedule Dashboard (`capacity_planner.py`).

Transplants the selected high-value mechanisms from the three benchmark repositories
in `.work/library/` into UAOS-RSI's 3-Tool Tiki-Taka Nonstop Parallel Multi-Agent
Orchestrator (`Codex`, `Claude Code`, `Antigravity` + `Haiku 5.5` + `Ollama` 0-token local calculator):

1. From OpenRig (`https://github.com/mvschwarz/openrig`):
   - `build_three_tool_seat_registry`: 3-tool (+ Haiku/Ollama) declarative Seat & Pod registry
     tracking role, live status (`ACTIVE`/`LIMITED`/`ABSENT`), active card,
     5h token/card capacity, and non-interruptive autonomy mode, aligned with `U257`
     Codex Plus Astra keypoint protection and `author != judge` quality gate.
2. From Show GN / AgentCodeGUI (`https://github.com/UnrealFactory/AgentCodeGUI`):
   - `build_five_chip_telemetry_snapshot`: 5-chip live status bar model
     (`1_todos_schedule`, `2_three_tool_seats`, `3_background_watchers`,
     `4_changed_files_diff`, `5_quota_and_reset_timer`) integrated with 3->2->1
     quota failover, >5s foreground wait preemption, and `capacity_planner.py`
     read-only (`mutate_schedule=False`) unified snapshots.
3. From REA (`https://github.com/morluto/rea`, v6.8.0):
   - `select_rea_analysis_tier`: 2-Tier Hybrid Analysis Router:
     * Tier 1 (`DEFAULT_ALWAYS_ON`, 0 schema token overhead): 4-tier epistemic
       evidence ledger (`OBSERVED`/`DERIVED`/`INFERRED`/`UNKNOWN`), summary-first
       paginated view (`analysis_view`), and finite oracle differential
       verification (`process_supervisor`).
     * Tier 2 (`ON_DEMAND_REVERSE_ENGINEERING`, loaded only on binary/archive/
       SQLite/external-library targets): activates `rea_bridge.inspect_static_target`
       (`STATIC_ONLY`) and full reverse-engineering capability without wasting
       ~14,000 paid tokens/call during normal source-code tasks.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from v7_harness.coord.next_card import TERMINAL

try:
    from v7_harness.coord.failover_closeout import FOREGROUND_WAIT_LIMIT_S, TOOL_ORDER
except ImportError:
    FOREGROUND_WAIT_LIMIT_S = 5.0
    TOOL_ORDER = ("claude", "antigravity", "codex")

try:
    from v7_harness.library_store import CANONICAL_LIBRARY_PATH_STR
except ImportError:
    CANONICAL_LIBRARY_PATH_STR = (
        r"D:\D_Workspace_NB\-agentic-ai-workspace\260916_agentic-ai-env-diet\.work\library"
    )

AUTHORITY_ORDER = ("codex", "claude", "antigravity")
ROUTINE_FAILOVER_ORDER = TOOL_ORDER  # ("claude", "antigravity", "codex") per U257
TERMINAL_STATES = frozenset(TERMINAL) | {
    "DONE",
    "DONE_SCOPED",
    "DONE_ELSEWHERE",
    "RETIRED",
    "SUPERSEDED",
    "MERGED",
    "COMPLETED",
}

THREE_TOOL_DEFAULT_ROLES: dict[str, dict[str, str]] = {
    "codex": {
        "seat_id": "seat-codex-conductor",
        "role": "Conductor & Final Judge (Plus Astra Keypoint Focus)",
        "pod": "orchestration-core",
    },
    "claude": {
        "seat_id": "seat-claude-subconductor",
        "role": "Sub-Conductor & Deep Implementer",
        "pod": "implementation-pod",
    },
    "antigravity": {
        "seat_id": "seat-antigravity-executor",
        "role": "Google AI Ultra (Pro 대비 5x 사용량) · Gemini 4 Argon",
        "pod": "verification-and-desk-pod",
    },
    "haiku": {
        "seat_id": "seat-haiku-suborchestrator",
        "role": "Low-Cost Multi-Agent Sub-Orchestrator (claude-haiku-5-5)",
        "pod": "sub-orchestrator-pod",
    },
    "ollama": {
        "seat_id": "seat-ollama-calculator",
        "role": "Zero-Paid-Token Local Calculator (qwen2.5-coder:7b)",
        "pod": "local-calculator-pod",
    },
    "flagman": {
        "seat_id": "seat-flagman-autonomous",
        "role": "Independent Autonomic Traffic & 3-Way AST Merge Flagman (0 Paid Tokens)",
        "pod": "autonomic-nervous-system-pod",
    },
}

TIER2_BINARY_EXTENSIONS = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".apk",
        ".dex",
        ".asar",
        ".wasm",
        ".sqlite",
        ".sqlite3",
        ".db",
        ".har",
        ".pcap",
        ".pcapng",
    }
)

ESTIMATED_EAGER_MCP_SCHEMA_TOKENS = 14000


def _phase_id(phase: dict[str, Any]) -> str:
    return str(phase.get("phase_id") or phase.get("id") or "")


def _phase_owner(phase: dict[str, Any]) -> str:
    return str(phase.get("owner_tool") or phase.get("owner") or "").lower()


def _phase_state(phase: dict[str, Any]) -> str:
    return str(phase.get("state") or phase.get("status") or "").upper()


def _set_phase_owner(phase: dict[str, Any], new_owner: str) -> None:
    phase["owner_tool"] = new_owner
    if "owner" in phase or "owner_tool" not in phase:
        phase["owner"] = new_owner


def _set_phase_state(phase: dict[str, Any], new_state: str) -> None:
    phase["state"] = new_state
    if "status" in phase or "state" not in phase:
        phase["status"] = new_state


def _compute_failover_plan(
    schedule_phases: list[dict[str, Any]],
    presence_states: dict[str, str],
) -> dict[str, Any]:
    active_authority = [
        t for t in AUTHORITY_ORDER if str(presence_states.get(t, "ABSENT")).upper() == "ACTIVE"
    ]
    active_routine = [
        t for t in ROUTINE_FAILOVER_ORDER if str(presence_states.get(t, "ABSENT")).upper() == "ACTIVE"
    ]
    non_codex_routine = [t for t in active_routine if t != "codex"] or active_routine
    conductor = active_authority[0] if active_authority else "NONE"
    if len(active_authority) >= 3:
        mode = "THREE_TOOL_NORMAL"
    elif len(active_authority) == 2:
        mode = "TWO_TOOL_CONTINUITY"
    elif len(active_authority) == 1:
        mode = "SOLE_SURVIVOR_AUTONOMOUS"
    else:
        mode = "ALL_PAID_TOOLS_LIMITED"

    reassigned: list[str] = []
    deferred_reviews: list[str] = []
    rr = 0
    for phase in schedule_phases:
        pid = _phase_id(phase)
        owner = _phase_owner(phase)
        status = _phase_state(phase)
        if status in TERMINAL_STATES or status == "HUMAN":
            continue
        # U249 / U257 Supreme Quality Gate: Sole survivor NEVER self-approves REVIEW -> DONE (author != judge).
        if len(active_authority) == 1 and status == "REVIEW":
            phase["acting_sole_survivor"] = active_authority[0]
            phase["needs_return_review"] = True
            phase["failover_mode"] = mode
            deferred_reviews.append(pid)
            continue
        if status in ("READY", "PLANNED") and owner not in active_authority and active_routine:
            is_codex_keypoint = bool(phase.get("codex_exclusive") or phase.get("keypoint"))
            pool = active_authority if is_codex_keypoint else non_codex_routine
            new_owner = pool[rr % len(pool)]
            rr += 1
            _set_phase_owner(phase, new_owner)
            reassigned.append(pid)

    return {
        "mode": mode,
        "conductor": conductor,
        "active_tools": active_authority,
        "reassigned": reassigned,
        "deferred_sole_survivor_reviews": deferred_reviews,
        "promoted_sole_survivor": [],
    }


def build_three_tool_seat_registry(
    presence_states: dict[str, str],
    schedule_phases: list[dict[str, Any]],
    non_interruptive: bool = True,
    *,
    mutate_schedule: bool = True,
    include_haiku: bool = False,
    engines_summary: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """OpenRig transplant: build a 3-tool + Ollama/Haiku Seat Registry with U257-compliant failover routing."""
    working_phases = schedule_phases if mutate_schedule else [dict(p) for p in schedule_phases if isinstance(p, dict)]
    replan = _compute_failover_plan(working_phases, presence_states)
    seats: list[dict[str, Any]] = []
    seat_tools = (
        ("codex", "claude", "antigravity", "haiku", "ollama")
        if include_haiku
        else ("codex", "claude", "antigravity", "ollama")
    )

    for tool in seat_tools:
        meta = THREE_TOOL_DEFAULT_ROLES[tool]
        state = (
            "ACTIVE"
            if tool in ("ollama", "haiku")
            else str(presence_states.get(tool, "ABSENT")).upper()
        )
        owned_cards = [
            _phase_id(p)
            for p in working_phases
            if _phase_owner(p) == tool and _phase_state(p) not in TERMINAL_STATES
        ]
        seat_entry: dict[str, Any] = {
            "tool": tool,
            "seat_id": meta["seat_id"],
            "role": meta["role"],
            "pod": meta["pod"],
            "state": state,
            "active_cards": owned_cards,
            "non_interruptive_mode": bool(non_interruptive),
        }
        if isinstance(engines_summary, dict) and tool in engines_summary:
            eng_info = engines_summary[tool] or {}
            seat_entry["used_5h_effective_tokens"] = int(eng_info.get("used_5h_effective_tokens") or 0)
            seat_entry["usable_remaining_5h_tokens"] = eng_info.get("usable_remaining_5h_tokens")
            seat_entry["usable_cards_capacity"] = eng_info.get("usable_cards_capacity")
            seat_entry["status_tier"] = eng_info.get("status_tier", "UNKNOWN")
        seats.append(seat_entry)

    return {
        "orchestrator": "UAOS-RSI-3Tool-TikiTaka",
        "mode": replan["mode"],
        "conductor": replan["conductor"],
        "active_paid_tools": replan["active_tools"],
        "reassigned_cards": replan["reassigned"],
        "deferred_sole_survivor_reviews": replan["deferred_sole_survivor_reviews"],
        "promoted_sole_survivor": replan["promoted_sole_survivor"],
        "seats": seats,
    }


def build_five_chip_telemetry_snapshot(
    schedule_phases: list[dict[str, Any]],
    presence_states: dict[str, str],
    changed_files: list[dict[str, Any]],
    active_watchers: list[str],
    quota_reset_times: dict[str, str] | None = None,
    foreground_wait_s: float = 0.0,
    is_background_watcher: bool = False,
    acting_tool: str = "antigravity",
    *,
    mutate_schedule: bool = True,
    include_haiku: bool = False,
    engines_summary: dict[str, dict[str, Any]] | None = None,
    wait_transparency: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Show GN (AgentCodeGUI) transplant: 5-chip telemetry bar + >5s wait preemption, unified with capacity_planner."""
    working_phases = schedule_phases if mutate_schedule else [dict(p) for p in schedule_phases if isinstance(p, dict)]
    reset_map = dict(quota_reset_times or {})
    seat_reg = build_three_tool_seat_registry(
        presence_states,
        working_phases,
        mutate_schedule=mutate_schedule,
        include_haiku=include_haiku,
        engines_summary=engines_summary,
    )

    total_phases = len(working_phases)
    done_phases = sum(
        1 for p in working_phases if _phase_state(p) in TERMINAL_STATES
    )
    # U272: auto self-healing cards are the scheduler's own output; counting them as pending work re-raised
    # NO_LIVE_WATCHER_WHILE_WAITING from the cards it had just written.
    remaining_non_auto = sum(
        1 for p in working_phases
        if _phase_state(p) not in TERMINAL_STATES and not str(p.get("phase_id") or "").startswith("RSI-U251-AUTO-")
    )
    active_count = sum(1 for p in working_phases if _phase_state(p) in ("ACTIVE", "IN_PROGRESS"))
    review_count = sum(1 for p in working_phases if _phase_state(p) == "REVIEW")
    ready_count = sum(1 for p in working_phases if _phase_state(p) in ("READY", "PLANNED", "PENDING", "QUEUED"))
    blocked_count = sum(1 for p in working_phases if _phase_state(p) in ("BLOCKED", "WAITING"))

    if is_background_watcher or float(foreground_wait_s) <= FOREGROUND_WAIT_LIMIT_S:
        wait_decision: dict[str, Any] = {
            "action": "CONTINUE_WAIT",
            "claimed_phase": None,
            "foreground_wait_s": float(foreground_wait_s),
        }
    elif not mutate_schedule:
        candidate_id = next(
            (_phase_id(p) for p in working_phases if _phase_state(p) in ("READY", "PLANNED")),
            None,
        )
        wait_decision = {
            "action": "READ_ONLY_WAIT_OBSERVED",
            "claimed_phase": None,
            "next_ready_candidate": candidate_id,
            "foreground_wait_s": float(foreground_wait_s),
        }
    elif done_phases == total_phases and total_phases > 0:
        wait_decision = {
            "action": "NATURAL_SCHEDULE_CLOSEOUT",
            "claimed_phase": None,
            "foreground_wait_s": float(foreground_wait_s),
        }
    else:
        claimed_id = None
        for p in working_phases:
            st = _phase_state(p)
            if st in ("READY", "PLANNED"):
                claimed_id = _phase_id(p)
                _set_phase_owner(p, acting_tool)
                _set_phase_state(p, "ACTIVE")
                break
        wait_decision = {
            "action": "PREEMPT_AND_CLAIM" if claimed_id else "AUDIT_COMPLETED",
            "claimed_phase": claimed_id,
            "foreground_wait_s": float(foreground_wait_s),
        }

    total_added = sum(int(f.get("added", 0)) for f in changed_files)
    total_removed = sum(int(f.get("removed", 0)) for f in changed_files)

    usable_rem_5h: dict[str, Any] = {}
    used_eff_5h: dict[str, int] = {}
    quota_pct: dict[str, float | None] = {}
    if isinstance(engines_summary, dict):
        for t in ("codex", "claude", "antigravity"):
            e_info = engines_summary.get(t) or {}
            usable_rem_5h[t] = e_info.get("usable_remaining_5h_tokens", "UNKNOWN")
            used_eff_5h[t] = int(e_info.get("used_5h_effective_tokens") or 0)
            q_snap = e_info.get("provider_quota_snapshot") or {}
            quota_pct[t] = q_snap.get("used_percent")
            if t not in reset_map and q_snap.get("resets_at"):
                reset_map[t] = str(q_snap["resets_at"])

    chips = {
        "1_todos_schedule": {
            "total": total_phases,
            "done": done_phases,
            "remaining": total_phases - done_phases,
            "remaining_non_auto": remaining_non_auto,
            "active": active_count,
            "review": review_count,
            "ready": ready_count,
            "blocked": blocked_count,
            "all_done": done_phases == total_phases and total_phases > 0,
            "headline": (wait_transparency or {}).get("headline", ""),
        },
        "2_three_tool_seats": {
            "mode": seat_reg["mode"],
            "conductor": seat_reg["conductor"],
            "active_paid_tools": seat_reg["active_paid_tools"],
            "reassigned_cards": seat_reg["reassigned_cards"],
            "deferred_sole_survivor_reviews": seat_reg["deferred_sole_survivor_reviews"],
            "seats": seat_reg["seats"],
        },
        "3_background_watchers": {
            "watchers": list(active_watchers),
            "watcher_count": len(active_watchers),
            "foreground_wait_limit_s": FOREGROUND_WAIT_LIMIT_S,
            "wait_decision": wait_decision,
            "wait_status": (wait_transparency or {}).get("status", "UNKNOWN"),
        },
        "4_changed_files_diff": {
            "file_count": len(changed_files),
            "lines_added": total_added,
            "lines_removed": total_removed,
            "files": list(changed_files),
        },
        "5_quota_and_reset_timer": {
            "presence_states": dict(presence_states),
            "reset_at": reset_map,
            "used_5h_effective_tokens": used_eff_5h,
            "usable_remaining_5h_tokens": usable_rem_5h,
            "provider_used_percent": quota_pct,
            "auto_resume_on_reset": True,
        },
    }
    return {
        "schema": "uaos.five_chip_telemetry.v1",
        "read_only": not mutate_schedule,
        "chips": chips,
    }


def select_rea_analysis_tier(
    target_path_or_desc: str,
    force_reverse_engineering: bool = False,
) -> dict[str, Any]:
    """REA transplant: decide between Tier 1 (Always-On Default) and Tier 2 (On-Demand RE Bridge)."""
    raw = (target_path_or_desc or "").strip()
    lower = raw.lower().replace("\\", "/")
    target_p = Path(raw)
    ext = target_p.suffix.lower()

    is_library_target = (
        "/.work/library/" in lower
        or lower.startswith(".work/library/")
        or "/.antigravity_cockpit" in lower
        or "cockpit tools" in lower
        or "program files" in lower
    )
    is_binary_or_capture = ext in TIER2_BINARY_EXTENSIONS
    if not is_binary_or_capture and not is_library_target and target_p.is_dir():
        try:
            for idx, child in enumerate(target_p.iterdir()):
                if idx >= 40:
                    break
                if child.suffix.lower() in TIER2_BINARY_EXTENSIONS:
                    is_binary_or_capture = True
                    break
        except OSError:
            pass
    activate_tier2 = bool(force_reverse_engineering or is_library_target or is_binary_or_capture)

    tier1_modules = [
        "v7_harness.evidence_ledger (4-tier OBSERVED/DERIVED/INFERRED/UNKNOWN + citation gate)",
        "v7_harness.analysis_view (summary-first retained bundle + paginated field projection)",
        "v7_harness.process_supervisor (SIGTERM->finalization_ms->SIGKILL + verify_reconstruction)",
    ]

    if activate_tier2:
        return {
            "selected_tier": "TIER_2_ON_DEMAND_REVERSE_ENGINEERING",
            "tier1_default_active": True,
            "tier2_on_demand_active": True,
            "tier1_modules": tier1_modules,
            "tier2_modules": [
                "v7_harness.rea_bridge (STATIC_ONLY inspect_static_target + obligation ledger + contract generator)",
                f"{CANONICAL_LIBRARY_PATH_STR}\\rea (full 50+ MCP reverse-engineering suite on-demand)",
            ],
            "paid_schema_tokens_saved_during_normal_turns": 0,
            "reason": (
                "Target requires reverse-engineering or external reference inspection "
                f"({ext or 'library/explicit target'}); full REA Tier-2 bridge activated on-demand."
            ),
        }

    return {
        "selected_tier": "TIER_1_DEFAULT_CORE_ONLY",
        "tier1_default_active": True,
        "tier2_on_demand_active": False,
        "tier1_modules": tier1_modules,
        "tier2_modules": [],
        "paid_schema_tokens_saved_per_call": ESTIMATED_EAGER_MCP_SCHEMA_TOKENS,
        "reason": (
            "Standard source/documentation task: REA Tier-1 epistemic & token-saving core is active "
            "by default while Tier-2 binary decompiler MCP schemas stay dormant (saving ~14,000 tokens/call)."
        ),
    }


U251_OPERATIONAL_TELEMETRY_LEDGER = Path(".coord") / "usage" / "u251_operational_telemetry.jsonl"
PAID_TOOLS = ("codex", "claude", "antigravity")


def _collect_real_live_watchers(desk: Path) -> list[str]:
    """Check actual running background watcher daemons (watch_<tool>.json PID, .coord/watch/*, sentinel loop.pid)."""
    from v7_harness.coord import watch as watch_mod

    watchers: list[str] = []
    desk_path = Path(desk)
    coord_dir = desk_path / ".coord"
    watch_dir = coord_dir / "watch"
    if watch_dir.is_dir():
        for wf in sorted(watch_dir.iterdir()):
            if wf.suffix in (".json", ".pid", ".lock"):
                watchers.append(f"coord watch ({wf.stem})")
    for s_pid in (coord_dir / "sentinel" / "loop.pid", desk_path / ".work" / "sentinel" / "loop.pid"):
        if s_pid.is_file():
            label = "sentinel.loop (0-token daemon)"
            if label not in watchers:
                watchers.append(label)
    for tool in PAID_TOOLS:
        try:
            if watch_mod.watcher_live(desk_path, tool):
                label = f"coord watch --target {tool}"
                if label not in watchers:
                    watchers.append(label)
        except Exception:
            pass
    return watchers


def collect_live_five_chip_telemetry(
    project_root: Path,
    *,
    target_path: str = "v7_harness/cli.py",
    foreground_wait_s: float = 0.0,
    is_background_watcher: bool = False,
    acting_tool: str = "antigravity",
    mutate_schedule: bool = False,
    force_reverse_engineering: bool = False,
) -> dict[str, Any]:
    """U269: Collect live Show GN 5-Chip Telemetry + OpenRig Seat Continuity + REA 2-Tier Routing from project state."""
    import json
    import time
    from datetime import datetime, timezone

    from v7_harness.coord.capacity_planner import (
        _collect_active_watchers,
        _collect_git_diff_chip,
        collect_capacity_snapshot,
        extract_wait_transparency,
    )
    from v7_harness.coord.presence import read_all

    desk = Path(project_root)
    sched_path = desk / ".coord" / "master_schedule.json"
    phases: list[dict[str, Any]] = []
    if sched_path.is_file():
        try:
            raw = json.loads(sched_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("phases"), list):
                phases = [dict(p) for p in raw["phases"] if isinstance(p, dict)]
        except (OSError, ValueError):
            phases = []

    snap_path = desk / ".coord" / "usage" / "capacity_snapshot.json"
    snap: dict[str, Any] = {}
    if snap_path.is_file():
        try:
            loaded = json.loads(snap_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict) and isinstance(loaded.get("engines"), dict):
                snap = loaded
        except (OSError, ValueError):
            snap = {}
    if not snap:
        try:
            home_arg = None if (desk / ".git").exists() else desk
            snap = collect_capacity_snapshot(desk, home=home_arg, persist=False)
        except Exception:
            snap = {}

    engines_summary = snap.get("engines") if isinstance(snap.get("engines"), dict) else {}
    presence_map = read_all(desk)
    presence_states: dict[str, str] = {}
    reset_times: dict[str, str] = {}
    for tool in PAID_TOOLS:
        rec = presence_map.get(tool) if isinstance(presence_map, dict) else {}
        st = str((rec or {}).get("state") or (engines_summary.get(tool) or {}).get("presence_state") or "ABSENT").upper()
        presence_states[tool] = st
        q_snap = (engines_summary.get(tool) or {}).get("provider_quota_snapshot") or {}
        if isinstance(q_snap, dict) and q_snap.get("resets_at"):
            reset_times[tool] = str(q_snap["resets_at"])
        elif isinstance(rec, dict) and isinstance(rec.get("expires_at"), (int, float)):
            reset_times[tool] = datetime.fromtimestamp(float(rec["expires_at"]), timezone.utc).isoformat()
        else:
            reset_times[tool] = "NONE"

    wait_trans = extract_wait_transparency(desk)
    five_chip = build_five_chip_telemetry_snapshot(
        schedule_phases=phases,
        presence_states=presence_states,
        changed_files=_collect_git_diff_chip(desk),
        active_watchers=_collect_real_live_watchers(desk),
        quota_reset_times=reset_times,
        foreground_wait_s=foreground_wait_s,
        is_background_watcher=is_background_watcher,
        acting_tool=acting_tool,
        mutate_schedule=mutate_schedule,
        include_haiku=True,
        engines_summary=engines_summary,
        wait_transparency=wait_trans,
    )
    rea_tier = select_rea_analysis_tier(target_path, force_reverse_engineering=force_reverse_engineering)
    if rea_tier.get("tier2_on_demand_active"):
        from v7_harness.rea_bridge import execute_auto_reverse_engineering_pipeline

        cand_target = Path(target_path)
        if not cand_target.is_absolute():
            cand_target = desk / cand_target
        if cand_target.exists():
            rea_tier["auto_executed_result"] = execute_auto_reverse_engineering_pipeline(
                project_root=desk,
                target_path=cand_target,
            )
    return {
        "schema": "uaos.u251_live_bundle.v1",
        "five_chip_telemetry": five_chip,
        "rea_tier_routing": rea_tier,
    }


def diagnose_u251_operational_anomalies(
    five_chip: dict[str, Any],
    rea_tier: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """U269: Evaluate deterministic self-healing rules across OpenRig, Show GN (5-Chip), and REA operational state."""
    chips = (five_chip or {}).get("chips") or {}
    c1 = chips.get("1_todos_schedule") or {}
    c2 = chips.get("2_three_tool_seats") or {}
    c3 = chips.get("3_background_watchers") or {}

    anomalies: list[dict[str, Any]] = []

    remaining = int(c1.get("remaining_non_auto", c1.get("remaining")) or 0)
    watcher_count = int(c3.get("watcher_count") or 0)
    if remaining > 0 and watcher_count == 0:
        anomalies.append({
            "anomaly_code": "NO_LIVE_WATCHER_WHILE_WAITING",
            "severity": "P1",
            "benchmark_engine": "Show_GN_AgentCodeGUI",
            "title": "[U251-RSI 자가수정] 백그라운드 감시자(Watcher) 누락 자동 재가동 및 훅 복구",
            "observed": f"remaining_phases={remaining}, watcher_count={watcher_count}",
            # U272 feedback loop: the phase count includes the scheduler's own auto cards, so it cannot identify an episode.
            "evidence_key": f"phases_pending={remaining > 0}, watcher_count={watcher_count}",
            "remediation_action": (
                "Re-arm zero-paid-token background watcher (coord watch / sentinel loop) and verify "
                "Stop/PostToolUse hook wake persistence so waiting phases never stall silently."
            ),
            "target_files": ["v7_harness/coord/watch.py", "v7_harness/coord/sentinel.py"],
            "accept_cmd": "python -m unittest tests.test_u251_benchmark_logic_transplant tests.test_u269_u251_rsi_operational_evolution",
        })

    seat_mode = str(c2.get("mode") or "THREE_TOOL_NORMAL")
    if seat_mode in ("TWO_TOOL_CONTINUITY", "SOLE_SURVIVOR_AUTONOMOUS", "ALL_PAID_TOOLS_LIMITED"):
        anomalies.append({
            "anomaly_code": "FAILOVER_DEGRADED_MODE",
            "severity": "P2" if seat_mode == "TWO_TOOL_CONTINUITY" else "P1",
            "benchmark_engine": "OpenRig",
            "title": f"[U251-RSI 자가수정] OpenRig 좌석 우회({seat_mode}) 재배정 및 복귀 인계 검증",
            "observed": f"mode={seat_mode}, active_paid_tools={c2.get('active_paid_tools')}",
            "remediation_action": (
                "Reassign READY/ACTIVE/REVIEW cards owned by LIMITED/ABSENT tools to highest-capacity ACTIVE "
                "paid tool (Google AI Ultra 5x / Claude Code) and maintain codex_return_checklist.md."
            ),
            "target_files": ["v7_harness/benchmark_logic_transplant.py", "v7_harness/coord/capacity_planner.py"],
            "accept_cmd": "python -m unittest tests.test_u251_benchmark_logic_transplant tests.test_u269_u251_rsi_operational_evolution",
        })

    deferred_reviews = c2.get("deferred_sole_survivor_reviews") or []
    if isinstance(deferred_reviews, list) and len(deferred_reviews) > 0:
        anomalies.append({
            "anomaly_code": "SOLE_SURVIVOR_REVIEW_BACKLOG",
            "severity": "P2",
            "benchmark_engine": "OpenRig",
            "title": f"[U251-RSI 자가수정] 단일 생존자 자율 수행 카드({len(deferred_reviews)}건) 교차 사후 감사",
            "observed": f"deferred_sole_survivor_reviews={deferred_reviews}",
            "remediation_action": (
                "Execute mandatory independent peer post-audit on cards completed under SOLE_SURVIVOR_AUTONOMOUS "
                "mode as soon as a peer tool returns ACTIVE."
            ),
            "target_files": ["v7_harness/benchmark_logic_transplant.py", "v7_harness/coord/merge_route.py"],
            "accept_cmd": "python -m unittest tests.test_u251_benchmark_logic_transplant tests.test_u269_u251_rsi_operational_evolution",
        })

    wait_decision = c3.get("wait_decision") or {}
    fg_wait = float(wait_decision.get("foreground_wait_s") or 0.0)
    if wait_decision.get("action") == "PREEMPT_AND_CLAIM" or (
        wait_decision.get("action") == "READ_ONLY_WAIT_OBSERVED" and fg_wait > FOREGROUND_WAIT_LIMIT_S
    ):
        anomalies.append({
            "anomaly_code": "FOREGROUND_WAIT_PREEMPTED",
            "severity": "P2",
            "benchmark_engine": "Show_GN_AgentCodeGUI",
            "title": "[U251-RSI 자가수정] 5초 초과 전면 대기 선점 차단 및 차순위 카드 자동 착수",
            "observed": f"foreground_wait_s={wait_decision.get('foreground_wait_s')}, limit={FOREGROUND_WAIT_LIMIT_S}s",
            "remediation_action": (
                "Preempt foreground wait exceeding 5.0s, delegate peer wait to 0-token background watcher, "
                "and immediately claim next dependency-ready phase."
            ),
            "target_files": ["v7_harness/benchmark_logic_transplant.py", "v7_harness/coord/stop_gate.py"],
            "accept_cmd": "python -m unittest tests.test_u251_benchmark_logic_transplant tests.test_u269_u251_rsi_operational_evolution",
        })

    seats = c2.get("seats") or []
    throttled_tools = [
        str(s.get("tool"))
        for s in seats
        if isinstance(s, dict)
        and s.get("tool") in PAID_TOOLS
        and (
            s.get("status_tier") in ("CRITICAL_OFFLOAD", "LIMITED_PAUSE")
            or (s.get("state") == "ACTIVE" and s.get("usable_remaining_5h_tokens") == 0)
        )
    ]
    if throttled_tools:
        anomalies.append({
            "anomaly_code": "QUOTA_CRITICAL_THROTTLE",
            "severity": "P1",
            "benchmark_engine": "OpenRig_ShowGN_Hybrid",
            "title": f"[U251-RSI 자가수정] 유료 도구 쿼터 임계 도달({','.join(throttled_tools)}) 오프로딩 및 자가 라우팅",
            "observed": f"throttled_tools={throttled_tools}",
            "remediation_action": (
                "Enforce 60%+ Ollama/Haiku local offloading and route paid execution to highest remaining "
                "capacity seat (Antigravity Google AI Ultra 5x · Gemini 4 Argon / active peer)."
            ),
            "target_files": ["v7_harness/coord/capacity_planner.py", "v7_harness/benchmark_logic_transplant.py"],
            "accept_cmd": "python -m unittest tests.test_u256_capacity_planner_and_dashboard tests.test_u269_u251_rsi_operational_evolution",
        })

    return anomalies


# U272: same evidence within one main-session cache lifetime (1 h, global rule) is one episode, not a second observation.
AUTO_CARD_EPISODE_S = 3600.0


def record_u251_operational_telemetry_and_schedule_rsi(
    project_root: Path,
    *,
    live_bundle: dict[str, Any] | None = None,
    target_path: str = "v7_harness/cli.py",
    foreground_wait_s: float = 0.0,
    is_background_watcher: bool = False,
    acting_tool: str = "antigravity",
    auto_schedule: bool = True,
    now: float | None = None,
) -> dict[str, Any]:
    """U269: Record U251 operational telemetry receipt to `.coord/usage/u251_operational_telemetry.jsonl`
    and atomically schedule/update idempotent self-healing RSI evolution cards in `.coord/master_schedule.json`.
    """
    import json
    import os
    import time
    from datetime import datetime, timezone

    from v7_harness import rsi as rsi_mod
    from v7_harness.coord.stream import _exclusive

    desk = Path(project_root)
    ts = float(now if now is not None else time.time())
    iso_ts = datetime.fromtimestamp(ts, timezone.utc).isoformat()

    bundle = live_bundle or collect_live_five_chip_telemetry(
        desk,
        target_path=target_path,
        foreground_wait_s=foreground_wait_s,
        is_background_watcher=is_background_watcher,
        acting_tool=acting_tool,
        mutate_schedule=False,
    )
    five_chip = bundle.get("five_chip_telemetry") or {}
    rea_tier = bundle.get("rea_tier_routing") or {}
    anomalies = diagnose_u251_operational_anomalies(five_chip, rea_tier)

    rsi_proposals: list[dict[str, Any]] = []
    try:
        rsi_policy = rsi_mod.load_policy(desk)
        rsi_analysis = rsi_mod.analyze(rsi_mod.load_rows(desk), rsi_policy)
        prop_list = rsi_mod.propose(rsi_analysis, rsi_policy)
        seen_causes: set[str] = set()
        for p in prop_list:
            if isinstance(p, dict) and p.get("cause") and p.get("recurring"):
                cause = str(p["cause"])
                if cause in seen_causes:
                    continue
                seen_causes.add(cause)
                rsi_proposals.append({
                    "anomaly_code": f"LEDGER_{cause}",
                    "severity": "P2",
                    "benchmark_engine": "UAOS_RSI_Ledger",
                    "title": f"[U251-RSI 자가수정] 원장 반복 실패({cause} {p.get('count', 0)}회) 계약·라우팅 자동 보정",
                    "observed": f"cause={cause}, count={p.get('count')}, worker={p.get('worker')}",
                    "remediation_action": str(p.get("action") or "Apply deterministic RSI remedy"),
                    "target_files": [".coord/rsi/policy.json", "docs/46_standard-process-and-worker-harness.md"],
                    "accept_cmd": "python -m unittest tests.test_u269_u251_rsi_operational_evolution",
                    "remedy_on_file": str(p.get("target") or "") != "review",
                })
    except Exception:
        rsi_proposals = []

    all_findings = anomalies + rsi_proposals

    chips = five_chip.get("chips") or {}
    c1 = chips.get("1_todos_schedule") or {}
    c2 = chips.get("2_three_tool_seats") or {}
    c3 = chips.get("3_background_watchers") or {}
    c4 = chips.get("4_changed_files_diff") or {}

    seats = [s for s in (c2.get("seats") or []) if isinstance(s, dict) and s.get("tool") in PAID_TOOLS]
    active_seats = [s for s in seats if s.get("state") == "ACTIVE"]

    def _seat_rem(s: dict[str, Any]) -> int:
        v = s.get("usable_remaining_5h_tokens")
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0

    if active_seats:
        chosen_owner = str(max(active_seats, key=_seat_rem).get("tool") or acting_tool)
    else:
        chosen_owner = acting_tool if acting_tool in PAID_TOOLS else "antigravity"

    peer_candidates = [
        str(s.get("tool"))
        for s in active_seats
        if str(s.get("tool")) != chosen_owner
    ]
    if not peer_candidates:
        peer_candidates = [t for t in ("claude", "antigravity", "codex") if t != chosen_owner]
    chosen_judge = peer_candidates[0]

    scheduled_cards: list[dict[str, Any]] = []
    quiet_lock = (desk / ".work" / "QUIET_LOCK").is_file()

    if auto_schedule and all_findings and not quiet_lock:
        sched_path = desk / ".coord" / "master_schedule.json"
        sched_path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive(sched_path.with_suffix(".lock")):
            sched_data: dict[str, Any] = {"topic": "5칩계기판·U251-RSI진화", "phases": []}
            if sched_path.is_file():
                try:
                    loaded_s = json.loads(sched_path.read_text(encoding="utf-8"))
                    if isinstance(loaded_s, dict):
                        sched_data = loaded_s
                except (OSError, ValueError):
                    pass
            phases_list = sched_data.get("phases")
            if not isinstance(phases_list, list):
                phases_list = []
                sched_data["phases"] = phases_list

            terminal_states = {"DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED", "SUPERSEDED", "MERGED"}
            for item in all_findings:
                # A cause with a deterministic remedy in rsi.REMEDIES is already routed by `rsi report`; a card with green acceptance has nothing to verify (U272 receipt).
                if item.get("remedy_on_file"):
                    continue
                code = str(item["anomaly_code"])
                card_id = f"RSI-U251-AUTO-{code}"
                existing = next(
                    (
                        p for p in phases_list
                        if isinstance(p, dict)
                        and str(p.get("phase_id") or p.get("id") or "") == card_id
                        and str(p.get("state") or "").upper() not in terminal_states
                    ),
                    None,
                )
                if existing is not None:
                    spec = existing.get("self_healing_spec")
                    if not isinstance(spec, dict):
                        spec = {}
                    prev_evidence = spec.get("last_evidence")
                    prev_ts = spec.get("last_observed_ts")
                    if (
                        prev_evidence == item.get("evidence_key", item.get("observed"))
                        and isinstance(prev_ts, (int, float))
                        and not isinstance(prev_ts, bool)
                        and ts - prev_ts < AUTO_CARD_EPISODE_S
                    ):
                        scheduled_cards.append({
                            "phase_id": card_id,
                            "action": "SAME_EPISODE",
                            "owner": existing.get("owner"),
                            "reviewer": existing.get("reviewer"),
                            "observation_count": int(spec.get("observation_count") or 1),
                        })
                        continue
                    obs_count = int(spec.get("observation_count") or 1) + 1
                    spec.update({
                        "last_evidence": item.get("evidence_key", item.get("observed")),
                        "last_observed_ts": ts,
                        "anomaly_code": code,
                        "severity": item["severity"],
                        "benchmark_engine": item["benchmark_engine"],
                        "remediation_action": item["remediation_action"],
                        "target_files": item["target_files"],
                        "accept_cmd": item["accept_cmd"],
                        "observation_count": obs_count,
                        "last_observed_at": iso_ts,
                        "auto_evolve": True,
                    })
                    existing["self_healing_spec"] = spec
                    if not existing.get("title"):
                        existing["title"] = item["title"]
                    if existing.get("reviewer") == existing.get("owner") or not existing.get("reviewer"):
                        existing["reviewer"] = chosen_judge if existing.get("owner") == chosen_owner else chosen_owner
                    scheduled_cards.append({
                        "phase_id": card_id,
                        "action": "UPDATED_EXISTING",
                        "owner": existing.get("owner"),
                        "reviewer": existing.get("reviewer"),
                        "observation_count": obs_count,
                    })
                else:
                    new_phase = {
                        "phase_id": card_id,
                        "title": item["title"],
                        "state": "READY",
                        "owner": chosen_owner,
                        "reviewer": chosen_judge,
                        "depends_on": [],
                        "self_healing_spec": {
                            "anomaly_code": code,
                            "severity": item["severity"],
                            "benchmark_engine": item["benchmark_engine"],
                            "remediation_action": item["remediation_action"],
                            "target_files": item["target_files"],
                            "accept_cmd": item["accept_cmd"],
                            "observation_count": 1,
                            "first_observed_at": iso_ts,
                            "last_observed_at": iso_ts,
                            "last_evidence": item.get("evidence_key", item.get("observed")),
                            "last_observed_ts": ts,
                            "auto_evolve": True,
                        },
                    }
                    phases_list.append(new_phase)
                    scheduled_cards.append({
                        "phase_id": card_id,
                        "action": "CREATED_READY",
                        "owner": chosen_owner,
                        "reviewer": chosen_judge,
                        "observation_count": 1,
                    })

            active_paid_set = {str(s.get("tool")) for s in active_seats if s.get("tool")}
            reassigned_for_checklist: list[str] = []
            if active_paid_set:
                for ph in phases_list:
                    if not isinstance(ph, dict) or str(ph.get("state") or "").upper() in terminal_states:
                        continue
                    cur_owner = str(ph.get("owner") or ph.get("owner_tool") or "").lower()
                    if cur_owner and cur_owner not in active_paid_set:
                        ph["previous_owner"] = cur_owner
                        ph["owner"] = chosen_owner
                        ph["owner_tool"] = chosen_owner
                        if str(ph.get("reviewer") or "").lower() in ("", chosen_owner):
                            ph["reviewer"] = chosen_judge
                        reassigned_for_checklist.append(f"{ph.get('phase_id') or ph.get('id')} ({cur_owner}->{chosen_owner})")

            deduped_phases: list[dict[str, Any]] = []
            seen_pids: dict[str, int] = {}
            for ph in phases_list:
                if not isinstance(ph, dict):
                    continue
                pid = str(ph.get("phase_id") or ph.get("id") or "")
                if pid and pid in seen_pids:
                    deduped_phases[seen_pids[pid]] = ph
                else:
                    if pid:
                        seen_pids[pid] = len(deduped_phases)
                    deduped_phases.append(ph)
            sched_data["phases"] = deduped_phases
            phases_list = deduped_phases

            tmp_sched = sched_path.with_name(f".master_schedule.{os.getpid()}.{time.time_ns()}.tmp")
            tmp_sched.write_text(json.dumps(sched_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            os.replace(tmp_sched, sched_path)

            if reassigned_for_checklist and "codex" not in active_paid_set:
                chk_path = desk / ".coord" / "codex_return_checklist.md"
                existing_chk = chk_path.read_text(encoding="utf-8") if chk_path.is_file() else "# Codex Return Checklist\n"
                entry_line = f"- [U251-RSI Failover] Reassigned offline seats: {', '.join(reassigned_for_checklist)}\n"
                if entry_line not in existing_chk:
                    chk_path.write_text(existing_chk + entry_line, encoding="utf-8")

            refreshed = collect_live_five_chip_telemetry(
                desk,
                target_path=target_path,
                foreground_wait_s=foreground_wait_s,
                is_background_watcher=is_background_watcher,
                acting_tool=acting_tool,
                mutate_schedule=False,
            )
            five_chip = refreshed.get("five_chip_telemetry") or five_chip
            chips = five_chip.get("chips") or {}
            c1 = chips.get("1_todos_schedule") or c1

    receipt = {
        "schema": "uaos.u251_operational_telemetry.v1",
        "ts": ts,
        "observed_at": iso_ts,
        "chip_summary": {
            "remaining_phases": int(c1.get("remaining") or 0),
            "seat_mode": str(c2.get("mode") or "UNKNOWN"),
            "conductor": str(c2.get("conductor") or "UNKNOWN"),
            "watcher_count": int(c3.get("watcher_count") or 0),
            "wait_action": str((c3.get("wait_decision") or {}).get("action") or "UNKNOWN"),
            "changed_file_count": int(c4.get("file_count") or 0),
            "rea_selected_tier": str(rea_tier.get("selected_tier") or "UNKNOWN"),
        },
        "anomalies_detected": [a["anomaly_code"] for a in anomalies],
        "rsi_ledger_causes": [p["anomaly_code"] for p in rsi_proposals],
        "scheduled_self_healing_cards": scheduled_cards,
    }

    if not quiet_lock:
        ledger_path = desk / U251_OPERATIONAL_TELEMETRY_LEDGER
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive(ledger_path.with_suffix(".lock")):
            with ledger_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")

    return {
        "schema": "uaos.u251_rsi_evolution_report.v1",
        "ok": True,
        "observed_at": iso_ts,
        "five_chip_telemetry": five_chip,
        "rea_tier_routing": rea_tier,
        "anomalies": anomalies,
        "rsi_ledger_proposals": rsi_proposals,
        "scheduled_self_healing_cards": scheduled_cards,
        "ledger_path": str(U251_OPERATIONAL_TELEMETRY_LEDGER.as_posix()),
    }
