"""U251: Unified Benchmark Logic Transplant Engine (OpenRig + Show GN/AgentCodeGUI + REA).

Transplants the selected high-value mechanisms from the three benchmark repositories
in `.work/library/` into UAOS-RSI's 3-Tool Tiki-Taka Nonstop Parallel Multi-Agent
Orchestrator (`Codex`, `Claude Code`, `Antigravity` + `Ollama` 0-token local calculator):

1. From OpenRig (`https://github.com/mvschwarz/openrig`):
   - `build_three_tool_seat_registry`: 3-tool declarative Seat & Pod registry
     tracking role, live status (`ACTIVE`/`LIMITED`/`ABSENT`), active card,
     checkout path, and non-interruptive autonomy mode.
2. From Show GN / AgentCodeGUI (`https://github.com/UnrealFactory/AgentCodeGUI`):
   - `build_five_chip_telemetry_snapshot`: 5-chip live status bar model
     (`todos_schedule`, `three_tool_seats`, `background_watchers`,
     `changed_files_diff`, `quota_and_reset_timer`) integrated with 3->2->1
     quota failover and >5s foreground wait preemption.
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

from v7_harness.coord.failover_closeout import FOREGROUND_WAIT_LIMIT_S
from v7_harness.library_store import CANONICAL_LIBRARY_PATH_STR

THREE_TOOL_DEFAULT_ROLES: dict[str, dict[str, str]] = {
    "codex": {
        "seat_id": "seat-codex-conductor",
        "role": "Conductor & Final Judge",
        "pod": "orchestration-core",
    },
    "claude": {
        "seat_id": "seat-claude-subconductor",
        "role": "Sub-Conductor & Deep Implementer",
        "pod": "implementation-pod",
    },
    "antigravity": {
        "seat_id": "seat-antigravity-executor",
        "role": "Contracted Executor, Auditor & Primary User Desk",
        "pod": "verification-and-desk-pod",
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


def _compute_failover_plan(
    schedule_phases: list[dict[str, Any]],
    presence_states: dict[str, str],
) -> dict[str, Any]:
    paid_order = ("codex", "claude", "antigravity")
    active_tools = [
        t for t in paid_order if str(presence_states.get(t, "ABSENT")).upper() == "ACTIVE"
    ]
    conductor = active_tools[0] if active_tools else "NONE"
    if len(active_tools) >= 3:
        mode = "THREE_TOOL_NORMAL"
    elif len(active_tools) == 2:
        mode = "TWO_TOOL_CONTINUITY"
    elif len(active_tools) == 1:
        mode = "SOLE_SURVIVOR_AUTONOMOUS"
    else:
        mode = "ALL_PAID_TOOLS_LIMITED"

    reassigned: list[str] = []
    promoted: list[str] = []
    rr = 0
    for phase in schedule_phases:
        pid = str(phase.get("id") or phase.get("phase_id") or "")
        owner = str(phase.get("owner") or phase.get("owner_tool") or "").lower()
        status = str(phase.get("status") or phase.get("state") or "").upper()
        if status in ("DONE", "COMPLETED", "HUMAN"):
            continue
        if len(active_tools) == 1 and status == "REVIEW":
            phase["status"] = "DONE"
            phase["acting_sole_survivor"] = active_tools[0]
            phase["needs_return_review"] = True
            promoted.append(pid)
            continue
        if owner not in active_tools and active_tools:
            new_owner = active_tools[rr % len(active_tools)]
            rr += 1
            phase["owner"] = new_owner
            reassigned.append(pid)

    return {
        "mode": mode,
        "conductor": conductor,
        "active_tools": active_tools,
        "reassigned": reassigned,
        "promoted_sole_survivor": promoted,
    }


def build_three_tool_seat_registry(
    presence_states: dict[str, str],
    schedule_phases: list[dict[str, Any]],
    non_interruptive: bool = True,
) -> dict[str, Any]:
    """OpenRig transplant: build a 3-tool + Ollama Seat Registry with failover routing."""
    replan = _compute_failover_plan(schedule_phases, presence_states)
    seats: list[dict[str, Any]] = []

    for tool in ("codex", "claude", "antigravity", "ollama"):
        meta = THREE_TOOL_DEFAULT_ROLES[tool]
        state = "ACTIVE" if tool == "ollama" else str(presence_states.get(tool, "ABSENT")).upper()
        owned_cards = [
            str(p.get("id") or p.get("phase_id") or "")
            for p in schedule_phases
            if str(p.get("owner") or p.get("owner_tool") or "").lower() == tool
            and str(p.get("status") or p.get("state") or "").upper() not in ("DONE", "COMPLETED")
        ]
        seats.append(
            {
                "tool": tool,
                "seat_id": meta["seat_id"],
                "role": meta["role"],
                "pod": meta["pod"],
                "state": state,
                "active_cards": owned_cards,
                "non_interruptive_mode": bool(non_interruptive),
            }
        )

    return {
        "orchestrator": "UAOS-RSI-3Tool-TikiTaka",
        "mode": replan["mode"],
        "conductor": replan["conductor"],
        "active_paid_tools": replan["active_tools"],
        "reassigned_cards": replan["reassigned"],
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
) -> dict[str, Any]:
    """Show GN (AgentCodeGUI) transplant: 5-chip telemetry bar + >5s wait preemption."""
    reset_map = dict(quota_reset_times or {})
    seat_reg = build_three_tool_seat_registry(presence_states, schedule_phases)

    total_phases = len(schedule_phases)
    done_phases = sum(
        1
        for p in schedule_phases
        if str(p.get("status") or p.get("state") or "").upper() in ("DONE", "COMPLETED")
    )

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
        for p in schedule_phases:
            st = str(p.get("status") or p.get("state") or "").upper()
            if st in ("READY", "PLANNED"):
                claimed_id = str(p.get("id") or p.get("phase_id") or "")
                p["owner"] = acting_tool
                p["status"] = "ACTIVE"
                break
        wait_decision = {
            "action": "PREEMPT_AND_CLAIM" if claimed_id else "AUDIT_COMPLETED",
            "claimed_phase": claimed_id,
            "foreground_wait_s": float(foreground_wait_s),
        }

    total_added = sum(int(f.get("added", 0)) for f in changed_files)
    total_removed = sum(int(f.get("removed", 0)) for f in changed_files)

    chips = {
        "1_todos_schedule": {
            "total": total_phases,
            "done": done_phases,
            "remaining": total_phases - done_phases,
            "all_done": done_phases == total_phases and total_phases > 0,
        },
        "2_three_tool_seats": {
            "mode": seat_reg["mode"],
            "conductor": seat_reg["conductor"],
            "active_paid_tools": seat_reg["active_paid_tools"],
            "seats": seat_reg["seats"],
        },
        "3_background_watchers": {
            "watchers": list(active_watchers),
            "foreground_wait_limit_s": FOREGROUND_WAIT_LIMIT_S,
            "wait_decision": wait_decision,
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
            "auto_resume_on_reset": True,
        },
    }
    return {
        "schema": "uaos.five_chip_telemetry.v1",
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
