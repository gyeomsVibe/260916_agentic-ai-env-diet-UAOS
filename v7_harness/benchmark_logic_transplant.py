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
        mutate_schedule=True,
        include_haiku=include_haiku,
        engines_summary=engines_summary,
    )

    total_phases = len(working_phases)
    done_phases = sum(
        1 for p in working_phases if _phase_state(p) in TERMINAL_STATES
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
    ext = Path(raw).suffix.lower()

    is_library_target = "/.work/library/" in lower or lower.startswith(".work/library/")
    is_binary_or_capture = ext in TIER2_BINARY_EXTENSIONS
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
