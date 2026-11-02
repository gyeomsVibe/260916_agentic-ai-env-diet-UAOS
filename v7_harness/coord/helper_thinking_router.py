"""U297: Official 3-Tool Helper Model Declaration, Reasoning Model Lineup Catalog,
and Master/Sub-Process Schedule Thinking Level (Low/Medium/High) Auto-Selector.

Officially declares and designates the maximum-performance-per-token low-cost Helper Models
(도우미 모델) alongside Ollama CLI (`qwen2.5-coder:7b`) and Core/Flagship Reasoning Models
for Codex, Antigravity, and Claude Code, and automatically optimizes helper model + Thinking Level
selection across `.coord/master_schedule.json` and `.coord/sub_process_schedule.json`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from v7_harness.coord.hook_context import shared_desk

THINKING_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")

PROCESS_LANES: tuple[str, ...] = (
    "IMPL_CODE",
    "VERIFY_AUDIT",
    "ARCH_DESIGN",
    "MERGE_RELEASE",
    "RECOVERY_OPS",
)

SUB_PROCESS_STAGES: tuple[str, ...] = (
    "SP1_RESEARCH_DRAFT",
    "SP2_MIA_DESIGN_AUDIT",
    "SP3_CODE_EXECUTION",
    "SP4_INDEPENDENT_VERIFY",
    "SP5_MERGE_AND_RUNTIME",
)

OFFICIAL_TOOL_MODEL_LINEUP: dict[str, dict[str, Any]] = {
    "codex": {
        "tool": "codex",
        "calculator_worker": "ollama",
        "calculator_model": "qwen2.5-coder:7b",
        "primary_helper_model": "gpt-6-luna",
        "primary_helper_display": "GPT-6 Luna",
        "designated_helper_models": (
            "gpt-6-luna",
            "gpt-5.6-luna",
            "gpt-5.6-terra",
            "gpt-5.6-sol",
            "gpt-6-sol",
        ),
        "helper_model_tiers": {
            "primary_high_efficiency": "gpt-6-luna",
            "lightweight_fast": "gpt-5.6-luna",
            "stabilized_audit_helper": "gpt-5.6-terra",
            "stabilized_code_helper": "gpt-5.6-sol",
            "mid_tier_reasoning_helper": "gpt-6-sol",
        },
        "reasoning_model_lineup": {
            "gpt_6_1_flagship": ("gpt-6.1-sol", "gpt-6.1-terra"),
            "gpt_6_standard": ("gpt-6-astra", "gpt-6-sol", "gpt-6-luna"),
            "gpt_5_6_lightweight_stable": ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"),
        },
        "all_reasoning_models": (
            "gpt-6.1-sol",
            "gpt-6.1-terra",
            "gpt-6-astra",
            "gpt-6-sol",
            "gpt-6-luna",
            "gpt-5.6-sol",
            "gpt-5.6-terra",
            "gpt-5.6-luna",
        ),
        "model_display_names": {
            "gpt-6.1-sol": "GPT-6.1 Sol",
            "gpt-6.1-terra": "GPT-6.1 Terra",
            "gpt-6-astra": "GPT-6 Astra",
            "gpt-6-sol": "GPT-6 Sol",
            "gpt-6-luna": "GPT-6 Luna",
            "gpt-5.6-sol": "GPT-5.6 Sol",
            "gpt-5.6-terra": "GPT-5.6 Terra",
            "gpt-5.6-luna": "GPT-5.6 Luna",
        },
        "thinking_levels": THINKING_LEVELS,
        "thinking_param_name": "reasoning_effort",
        "helper_preflight_cap_tokens": 16000,
        "target_parallel_ratio": {
            "ollama_pct": 50.0,
            "helper_pct": 30.0,
            "reasoning_core_pct": 20.0,
        },
    },
    "antigravity": {
        "tool": "antigravity",
        "calculator_worker": "ollama",
        "calculator_model": "qwen2.5-coder:7b",
        "primary_helper_model": "gemini-3.8-flash",
        "primary_helper_display": "Gemini 3.8 Flash",
        "designated_helper_models": (
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gpt-oss-120b",
        ),
        "helper_model_tiers": {
            "primary_high_efficiency": "gemini-3.8-flash",
            "stabilized_audit_helper": "gemini-3.7-flash",
            "lightweight_fast": "gemini-3.6-flash",
            "open_source_bulk_helper": "gpt-oss-120b",
        },
        "reasoning_model_lineup": {
            "gemini_series": (
                "gemini-4-argon",
                "gemini-3.8-flash",
                "gemini-3.7-flash",
                "gemini-3.6-flash",
                "gemini-3.1-pro",
            ),
            "claude_thinking_series": (
                "claude-sonnet-5-5-thinking",
                "claude-opus-5-5-thinking",
            ),
            "open_source_series": ("gpt-oss-120b",),
        },
        "all_reasoning_models": (
            "gemini-4-argon",
            "gemini-3.8-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.1-pro",
            "claude-sonnet-5-5-thinking",
            "claude-opus-5-5-thinking",
            "gpt-oss-120b",
        ),
        "model_display_names": {
            "gemini-4-argon": "Gemini 4 Argon",
            "gemini-3.8-flash": "Gemini 3.8 Flash",
            "gemini-3.7-flash": "Gemini 3.7 Flash",
            "gemini-3.6-flash": "Gemini 3.6 Flash",
            "gemini-3.1-pro": "Gemini 3.1 Pro",
            "claude-sonnet-5-5-thinking": "Claude Sonnet 5.5 (thinking)",
            "claude-opus-5-5-thinking": "Claude Opus 5.5 (thinking)",
            "gpt-oss-120b": "GPT-OSS-120b",
        },
        "thinking_levels": THINKING_LEVELS,
        "thinking_param_name": "thinking_level",
        "helper_preflight_cap_tokens": 16000,
        "target_parallel_ratio": {
            "ollama_pct": 50.0,
            "helper_pct": 30.0,
            "reasoning_core_pct": 20.0,
        },
    },
    "claude": {
        "tool": "claude",
        "calculator_worker": "ollama",
        "calculator_model": "qwen2.5-coder:7b",
        "primary_helper_model": "claude-haiku-5-5",
        "primary_helper_display": "Claude Haiku 5.5",
        "designated_helper_models": ("claude-haiku-5-5",),
        "helper_model_tiers": {
            "primary_high_efficiency": "claude-haiku-5-5",
            "lightweight_fast": "claude-haiku-5-5",
            "stabilized_audit_helper": "claude-haiku-5-5",
        },
        "reasoning_model_lineup": {
            "claude_series": (
                "claude-opus-5-5",
                "claude-sonnet-5-5",
                "claude-haiku-5-5",
            ),
        },
        "all_reasoning_models": (
            "claude-opus-5-5",
            "claude-sonnet-5-5",
            "claude-haiku-5-5",
        ),
        "model_display_names": {
            "claude-opus-5-5": "Claude Opus 5.5",
            "claude-sonnet-5-5": "Claude Sonnet 5.5",
            "claude-haiku-5-5": "Claude Haiku 5.5",
        },
        "thinking_levels": THINKING_LEVELS,
        "thinking_param_name": "effort",
        "helper_preflight_cap_tokens": 12000,
        "target_parallel_ratio": {
            "ollama_pct": 50.0,
            "helper_pct": 30.0,
            "reasoning_core_pct": 20.0,
        },
    },
}


def normalize_tool_name(tool: str | None) -> str:
    raw = str(tool or "antigravity").strip().lower()
    if raw in ("agy", "antigravity", "gemini"):
        return "antigravity"
    if raw in ("codex", "openai", "gpt"):
        return "codex"
    if raw in ("claude", "claude-code", "anthropic", "haiku"):
        return "claude"
    return "antigravity"


def normalize_thinking_level(level: str | None, default: str = "Medium") -> str:
    raw = str(level or default).strip().capitalize()
    if raw in THINKING_LEVELS:
        return raw
    return default


def get_official_tool_lineup(tool: str | None = None) -> dict[str, Any]:
    """Return the official helper & reasoning model lineup for one tool or all 3 tools."""
    if tool is None:
        return {k: dict(v) for k, v in OFFICIAL_TOOL_MODEL_LINEUP.items()}
    norm = normalize_tool_name(tool)
    return dict(OFFICIAL_TOOL_MODEL_LINEUP[norm])


def infer_lane_from_card_metadata(
    *,
    title: str = "",
    purpose: str = "",
    role: str = "implementer",
    state: str = "READY",
    sub_stage: str = "",
) -> str:
    """Deterministically classify a card or sub-process into one of the 5 process lanes."""
    st_up = str(sub_stage or "").strip().upper()
    if st_up in ("SP1_RESEARCH_DRAFT", "SP2_MIA_DESIGN_AUDIT"):
        return "ARCH_DESIGN"
    if st_up == "SP3_CODE_EXECUTION":
        return "IMPL_CODE"
    if st_up == "SP4_INDEPENDENT_VERIFY":
        return "VERIFY_AUDIT"
    if st_up == "SP5_MERGE_AND_RUNTIME":
        return "MERGE_RELEASE"

    role_low = str(role or "").strip().lower()
    if role_low in ("reviewer", "verifier", "judge", "auditor"):
        return "VERIFY_AUDIT"
    if role_low in ("merger", "release"):
        return "MERGE_RELEASE"
    if role_low in ("recovery", "healer", "sentinel"):
        return "RECOVERY_OPS"
    if str(state or "").strip().upper() == "REVIEW":
        return "VERIFY_AUDIT"

    text = f"{title} {purpose}".lower()
    if any(k in text for k in ("recover", "stall", "deadlock", "reconcile", "복구", "고착", "자가치유", "failover")):
        return "RECOVERY_OPS"
    if any(k in text for k in ("merge", "ship", "release", "runtime-install", "병합", "배포", "재설치")):
        return "MERGE_RELEASE"
    if any(k in text for k in ("audit", "verify", "vaccine", "judge", "review", "감사", "검증", "백신", "판정")):
        return "VERIFY_AUDIT"
    if any(k in text for k in ("mia", "design", "architecture", "plan", "research", "설계", "기획", "리서치", "아키텍처")):
        if not any(k in text for k in ("implement", "구현", "연동", "코드")):
            return "ARCH_DESIGN"
    return "IMPL_CODE"


def select_optimal_helper_and_thinking(
    tool: str,
    *,
    card: str = "",
    role: str = "implementer",
    lane_id: str | None = None,
    purpose: str = "",
    sub_stage: str = "",
    is_keypoint: bool = False,
    utilization_5h_pct: float = 0.0,
    exhaustion_risk: str = "SAFE",
    changed_lines: int = 0,
    multi_file: bool = False,
    prefer_claude_thinking_on_agy: bool = False,
    prefer_open_source_on_agy: bool = False,
) -> dict[str, Any]:
    """Automatically select the optimal Helper Model, Core Reasoning Model, and Thinking Levels
    (`Low` / `Medium` / `High`) for a card session, role, 5-lane process class, and sub-process stage.
    """
    norm_tool = normalize_tool_name(tool)
    catalog = OFFICIAL_TOOL_MODEL_LINEUP[norm_tool]
    resolved_lane = (
        lane_id
        if lane_id in PROCESS_LANES
        else infer_lane_from_card_metadata(
            title=purpose,
            purpose=purpose,
            role=role,
            sub_stage=sub_stage,
        )
    )
    high_pressure = (
        float(utilization_5h_pct or 0.0) >= 70.0
        or str(exhaustion_risk or "SAFE").upper() in ("PRE_HANDOFF_WARNING", "IMMINENT_EXHAUSTION")
    )
    imminent = str(exhaustion_risk or "SAFE").upper() == "IMMINENT_EXHAUSTION"
    st_up = str(sub_stage or "").strip().upper()
    purp_low = str(purpose or "").strip().lower()

    # 1. Select Ollama CLI calculator task
    if st_up == "SP1_RESEARCH_DRAFT":
        ollama_task = "ollama:local_search+local_draft"
    elif st_up == "SP2_MIA_DESIGN_AUDIT" or resolved_lane == "ARCH_DESIGN":
        ollama_task = "ollama:local_read_map+local_draft"
    elif st_up == "SP4_INDEPENDENT_VERIFY" or resolved_lane == "VERIFY_AUDIT":
        ollama_task = "ollama:gate_log_summary+local_read_map"
    elif st_up == "SP5_MERGE_AND_RUNTIME" or resolved_lane == "MERGE_RELEASE":
        ollama_task = "ollama:release_note_draft"
    else:
        slice_lines = 30 if high_pressure else 20
        ollama_task = f"ollama:code_slice_{slice_lines}L_v7_harness"

    # 2. Select Helper Model & Helper Thinking Level + Core Reasoning Model & Core Thinking Level per tool
    if norm_tool == "codex":
        if st_up == "SP1_RESEARCH_DRAFT":
            helper_model = "gpt-5.6-luna"
            helper_thinking = "Low"
            reasoning_model = "gpt-6-sol"
            reasoning_thinking = "Low"
        elif st_up == "SP2_MIA_DESIGN_AUDIT" or resolved_lane == "ARCH_DESIGN":
            helper_model = "gpt-6-sol" if not high_pressure else "gpt-6-luna"
            helper_thinking = "Medium"
            reasoning_model = "gpt-6.1-sol" if is_keypoint else ("gpt-5.6-sol" if imminent else "gpt-6-astra")
            reasoning_thinking = "High"
        elif st_up == "SP4_INDEPENDENT_VERIFY" or resolved_lane == "VERIFY_AUDIT":
            helper_model = "gpt-5.6-terra"
            helper_thinking = "Low"
            reasoning_model = "gpt-6.1-terra" if not imminent else "gpt-6-astra"
            reasoning_thinking = "High"
        elif st_up == "SP5_MERGE_AND_RUNTIME" or resolved_lane == "MERGE_RELEASE":
            helper_model = "gpt-5.6-luna"
            helper_thinking = "Low"
            reasoning_model = "gpt-5.6-sol"
            reasoning_thinking = "Low"
        elif resolved_lane == "RECOVERY_OPS":
            helper_model = "gpt-5.6-terra"
            helper_thinking = "Medium"
            reasoning_model = "gpt-6.1-terra"
            reasoning_thinking = "High"
        else:
            # IMPL_CODE / SP3_CODE_EXECUTION
            if high_pressure:
                helper_model = "gpt-5.6-luna"
                helper_thinking = "Low"
            elif changed_lines > 30 or multi_file:
                helper_model = "gpt-6-luna"
                helper_thinking = "Medium"
            else:
                helper_model = "gpt-6-luna"
                helper_thinking = "Low"
            if is_keypoint:
                reasoning_model = "gpt-6.1-sol"
                reasoning_thinking = "High"
            elif imminent:
                reasoning_model = "gpt-5.6-sol"
                reasoning_thinking = "Medium"
            else:
                reasoning_model = "gpt-6-astra"
                reasoning_thinking = "High" if multi_file else "Medium"

    elif norm_tool == "antigravity":
        use_oss = prefer_open_source_on_agy or "oss" in purp_low or "open_source" in purp_low or "bulk" in purp_low
        use_claude_thinking = prefer_claude_thinking_on_agy or "claude_thinking" in purp_low or "cross_family" in purp_low
        if st_up == "SP1_RESEARCH_DRAFT":
            helper_model = "gpt-oss-120b" if use_oss else "gemini-3.7-flash"
            helper_thinking = "Low"
            reasoning_model = "gemini-3.8-flash"
            reasoning_thinking = "Low"
        elif st_up == "SP2_MIA_DESIGN_AUDIT" or resolved_lane == "ARCH_DESIGN":
            helper_model = "gemini-3.8-flash"
            helper_thinking = "Medium"
            if use_claude_thinking:
                reasoning_model = "claude-opus-5-5-thinking"
            elif is_keypoint:
                reasoning_model = "gemini-4-argon"
            else:
                reasoning_model = "gemini-4-argon" if not imminent else "gemini-3.1-pro"
            reasoning_thinking = "High"
        elif st_up == "SP4_INDEPENDENT_VERIFY" or resolved_lane == "VERIFY_AUDIT":
            helper_model = "gemini-3.7-flash"
            helper_thinking = "Low"
            if use_claude_thinking:
                reasoning_model = "claude-sonnet-5-5-thinking"
            else:
                reasoning_model = "gemini-3.1-pro" if not is_keypoint else "gemini-4-argon"
            reasoning_thinking = "High"
        elif st_up == "SP5_MERGE_AND_RUNTIME" or resolved_lane == "MERGE_RELEASE":
            helper_model = "gemini-3.6-flash"
            helper_thinking = "Low"
            reasoning_model = "gemini-3.8-flash"
            reasoning_thinking = "Low"
        elif resolved_lane == "RECOVERY_OPS":
            helper_model = "gemini-3.7-flash"
            helper_thinking = "Medium"
            reasoning_model = "gemini-4-argon"
            reasoning_thinking = "High"
        else:
            # IMPL_CODE / SP3_CODE_EXECUTION
            if use_oss:
                helper_model = "gpt-oss-120b"
                helper_thinking = "Low"
            elif high_pressure:
                helper_model = "gemini-3.6-flash"
                helper_thinking = "Low"
            else:
                helper_model = "gemini-3.8-flash"
                helper_thinking = "Medium" if (changed_lines > 20 or multi_file) else "Low"
            if use_claude_thinking:
                reasoning_model = "claude-sonnet-5-5-thinking"
            elif imminent:
                reasoning_model = "gemini-3.8-flash"
            else:
                reasoning_model = "gemini-4-argon"
            reasoning_thinking = "High" if (is_keypoint or multi_file) else "Medium"

    else:
        # norm_tool == "claude"
        helper_model = "claude-haiku-5-5"
        if st_up == "SP1_RESEARCH_DRAFT":
            helper_thinking = "Low"
            reasoning_model = "claude-sonnet-5-5"
            reasoning_thinking = "Low"
        elif st_up == "SP2_MIA_DESIGN_AUDIT" or resolved_lane == "ARCH_DESIGN":
            helper_thinking = "Medium"
            reasoning_model = "claude-opus-5-5" if not imminent else "claude-sonnet-5-5"
            reasoning_thinking = "High"
        elif st_up == "SP4_INDEPENDENT_VERIFY" or resolved_lane == "VERIFY_AUDIT":
            helper_thinking = "Low"
            reasoning_model = "claude-opus-5-5" if not imminent else "claude-sonnet-5-5"
            reasoning_thinking = "High"
        elif st_up == "SP5_MERGE_AND_RUNTIME" or resolved_lane == "MERGE_RELEASE":
            helper_thinking = "Low"
            reasoning_model = "claude-sonnet-5-5"
            reasoning_thinking = "Low"
        elif resolved_lane == "RECOVERY_OPS":
            helper_thinking = "Medium"
            reasoning_model = "claude-opus-5-5"
            reasoning_thinking = "High"
        else:
            # IMPL_CODE / SP3_CODE_EXECUTION
            helper_thinking = "Low" if high_pressure else ("Medium" if (changed_lines > 20 or multi_file) else "Low")
            reasoning_model = "claude-opus-5-5" if is_keypoint else "claude-sonnet-5-5"
            reasoning_thinking = "High" if is_keypoint else "Medium"

    param_name = str(catalog["thinking_param_name"])
    native_config: dict[str, Any] = {
        "tool": norm_tool,
        "calculator_cli": f"ollama run {catalog['calculator_model']}",
        "helper_model": helper_model,
        "helper_thinking_param": {param_name: helper_thinking.lower()},
        "reasoning_model": reasoning_model,
        "reasoning_thinking_param": {param_name: reasoning_thinking.lower()},
    }
    if norm_tool == "claude":
        native_config["env"] = {
            "CLAUDE_CODE_SUBAGENT_MODEL": helper_model,
            "CLAUDE_CODE_SUBAGENT_EFFORT": helper_thinking.lower(),
        }
    elif norm_tool == "codex":
        native_config["codex_flags"] = {
            "helper_model": helper_model,
            "helper_reasoning_effort": helper_thinking.lower(),
            "core_model": reasoning_model,
            "core_reasoning_effort": reasoning_thinking.lower(),
        }
    else:
        native_config["gemini_thinking_config"] = {
            "helper_model": helper_model,
            "helper_thinking_level": helper_thinking.upper(),
            "core_model": reasoning_model,
            "core_thinking_level": reasoning_thinking.upper(),
        }

    return {
        "schema": "uaos-helper-thinking-selection-v1",
        "tool": norm_tool,
        "card": str(card or ""),
        "role": str(role or "implementer"),
        "lane_id": resolved_lane,
        "sub_stage": st_up or "CARD_LEVEL",
        "calculator_worker": "ollama",
        "calculator_model": str(catalog["calculator_model"]),
        "ollama_cli_task": ollama_task,
        "designated_helper_model": helper_model,
        "designated_helper_display": catalog["model_display_names"].get(helper_model, helper_model),
        "helper_thinking_level": helper_thinking,
        "helper_preflight_cap_tokens": int(catalog["helper_preflight_cap_tokens"]),
        "designated_reasoning_model": reasoning_model,
        "designated_reasoning_display": catalog["model_display_names"].get(reasoning_model, reasoning_model),
        "reasoning_thinking_level": reasoning_thinking,
        "thinking_level": reasoning_thinking,
        "target_532_ratio": dict(catalog["target_parallel_ratio"]),
        "disjoint_parallel_ready": True,
        "native_config": native_config,
    }


def audit_and_optimize_claude_ollama_haiku_parallel(
    project_root: Path,
    engines: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Full census & optimization of Claude Code's Ollama CLI + Haiku 5.5 disjoint parallel operation logic.

    Reads `.coord/usage/runs.jsonl` and `.coord/usage/helper_runs.jsonl` (if present) to quantify
    observed call/token ratios vs the 50:30:20 (`Ollama : Haiku 5.5 : Opus/Sonnet`) golden ratio,
    checks 12,000-token preflight cap compliance, and emits deterministic auto-promotion rules.
    """
    desk = shared_desk(Path(project_root))
    ledger_path = desk / ".coord" / "usage" / "runs.jsonl"
    helper_path = desk / ".coord" / "usage" / "helper_runs.jsonl"

    total_ledger_runs = 0
    global_worker_counts: dict[str, int] = {}
    claude_caller_counts = {"ollama": 0, "haiku_5_5": 0, "opus_sonnet": 0}
    haiku_total_tokens = 0
    haiku_max_tokens = 0
    haiku_over_12k_runs = 0
    haiku_run_count = 0

    if ledger_path.is_file():
        try:
            for line in ledger_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                total_ledger_runs += 1
                w_raw = str(row.get("worker") or row.get("actor") or row.get("engine") or "unknown").strip().lower()
                m_raw = str(row.get("model") or "").strip().lower()
                caller = str(row.get("caller") or row.get("actor") or "").strip().lower()
                inp = int(row.get("input_tokens") or 0)
                out = int(row.get("output_tokens") or 0)
                tot_tok = inp + out

                if "haiku" in w_raw or "haiku" in m_raw:
                    norm_w = "haiku-5.5"
                    haiku_run_count += 1
                    haiku_total_tokens += tot_tok
                    if tot_tok > haiku_max_tokens:
                        haiku_max_tokens = tot_tok
                    if tot_tok > 12000:
                        haiku_over_12k_runs += 1
                elif w_raw in ("ollama", "local", "cascade") or "qwen" in m_raw or "ollama" in m_raw:
                    norm_w = "ollama"
                elif w_raw in ("claude", "opus", "sonnet"):
                    norm_w = "claude"
                elif w_raw in ("agy", "antigravity"):
                    norm_w = "antigravity"
                else:
                    norm_w = w_raw
                global_worker_counts[norm_w] = global_worker_counts.get(norm_w, 0) + 1

                if caller == "claude" or norm_w in ("claude", "haiku-5.5"):
                    if norm_w == "ollama":
                        claude_caller_counts["ollama"] += 1
                    elif norm_w == "haiku-5.5":
                        claude_caller_counts["haiku_5_5"] += 1
                    elif norm_w == "claude":
                        claude_caller_counts["opus_sonnet"] += 1
        except OSError:
            pass

    helper_telemetry_runs = 0
    if helper_path.is_file():
        try:
            for line in helper_path.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip():
                    helper_telemetry_runs += 1
        except OSError:
            pass

    # If live 5h engines summary is passed, incorporate 5h window metrics too
    w5_ollama = int(((engines or {}).get("ollama") or {}).get("window_5h", {}).get("calls") or 0)
    w5_haiku = int(((engines or {}).get("haiku") or {}).get("window_5h", {}).get("calls") or 0)
    w5_claude = int(((engines or {}).get("claude") or {}).get("window_5h", {}).get("calls") or 0)

    c_tot = max(
        1,
        claude_caller_counts["ollama"]
        + claude_caller_counts["haiku_5_5"]
        + claude_caller_counts["opus_sonnet"],
    )
    obs_ollama_pct = round((claude_caller_counts["ollama"] / c_tot) * 100.0, 1)
    obs_haiku_pct = round((claude_caller_counts["haiku_5_5"] / c_tot) * 100.0, 1)
    obs_core_pct = round((claude_caller_counts["opus_sonnet"] / c_tot) * 100.0, 1)

    target_ratio = {"ollama_pct": 50.0, "haiku_pct": 30.0, "opus_sonnet_pct": 20.0}
    deficit_vs_target = {
        "ollama_delta_pct": round(50.0 - obs_ollama_pct, 1),
        "haiku_delta_pct": round(30.0 - obs_haiku_pct, 1),
        "opus_sonnet_delta_pct": round(20.0 - obs_core_pct, 1),
    }

    if deficit_vs_target["haiku_delta_pct"] >= deficit_vs_target["ollama_delta_pct"] and deficit_vs_target["haiku_delta_pct"] > 0:
        priority_promotion = "PROMOTE_HAIKU_5_5_DISJOINT_SUBAGENT"
    elif deficit_vs_target["ollama_delta_pct"] > 0:
        priority_promotion = "PROMOTE_OLLAMA_CLI_CALCULATOR"
    else:
        priority_promotion = "BALANCED_5_3_2_MAINTAINED"

    return {
        "schema": "uaos-claude-ollama-haiku-census-v1",
        "total_ledger_runs": total_ledger_runs,
        "helper_telemetry_runs": helper_telemetry_runs,
        "global_worker_counts": global_worker_counts,
        "claude_attributed_counts": claude_caller_counts,
        "observed_claude_ratio_pct": {
            "ollama_pct": obs_ollama_pct,
            "haiku_pct": obs_haiku_pct,
            "opus_sonnet_pct": obs_core_pct,
        },
        "window_5h_calls": {
            "ollama": w5_ollama,
            "haiku_5_5": w5_haiku,
            "claude_opus_sonnet": w5_claude,
        },
        "target_golden_ratio_pct": target_ratio,
        "deficit_vs_target_pct": deficit_vs_target,
        "haiku_5_5_telemetry": {
            "designated_helper_model": "claude-haiku-5-5",
            "total_runs": haiku_run_count,
            "total_tokens": haiku_total_tokens,
            "max_single_run_tokens": haiku_max_tokens,
            "preflight_cap_tokens": 12000,
            "over_12k_violations": haiku_over_12k_runs,
            "cap_compliant": haiku_over_12k_runs == 0,
        },
        "parallel_operation_optimization": {
            "priority_action": priority_promotion,
            "max_concurrent_ollama_cli": 1,
            "max_concurrent_haiku_subagents": 2,
            "disjoint_file_lock_invariant": "set(ollama_code_paths).isdisjoint(set(haiku_test_doc_paths))",
            "lane_1_ollama_cli_50pct": {
                "worker": "ollama",
                "model": "qwen2.5-coder:7b",
                "allowed_scope": ["v7_harness/*.py", ".work/cards/*"],
                "operations": ["local_read_map", "local_search", "local_draft", "pilot_local_20_30L_slice"],
                "cost_paid_tokens": 0,
            },
            "lane_2_haiku_5_5_30pct": {
                "worker": "haiku",
                "model": "claude-haiku-5-5",
                "thinking_levels": {"triage_test_runner": "Low", "doc_sync_audit_prep": "Medium", "complex_test_gen": "High"},
                "allowed_scope": ["tests/test_*.py", "docs/*.md"],
                "preflight_cap_tokens": 12000,
                "env_binding": {
                    "CLAUDE_CODE_SUBAGENT_MODEL": "claude-haiku-5-5",
                    "CLAUDE_CODE_SUBAGENT_EFFORT": "low|medium|high",
                },
            },
            "lane_3_opus_sonnet_20pct": {
                "worker": "claude",
                "models": ["claude-opus-5-5", "claude-sonnet-5-5"],
                "thinking_levels": {"routine_supervision": "Medium", "mia_architecture_and_verdict": "High"},
                "allowed_scope": ["architecture_frame", "independent_peer_verdict", "final_integration"],
            },
        },
    }


def optimize_master_and_sub_schedules(
    project_root: Path,
    engines: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Inspect the full `.coord/master_schedule.json` and `.coord/sub_process_schedule.json`
    and automatically bind optimal Helper Models, Reasoning Models, and Thinking Levels (`Low`/`Medium`/`High`)
    to every card session, role, process lane, and sub-process stage (`SP1`~`SP5`).
    """
    desk = shared_desk(Path(project_root))
    master_path = desk / ".coord" / "master_schedule.json"
    sub_path = desk / ".coord" / "sub_process_schedule.json"

    phases: list[dict[str, Any]] = []
    if master_path.is_file():
        try:
            raw_m = json.loads(master_path.read_text(encoding="utf-8"))
            if isinstance(raw_m, dict) and isinstance(raw_m.get("phases"), list):
                phases = [p for p in raw_m["phases"] if isinstance(p, dict)]
        except (OSError, ValueError):
            phases = []

    sub_cards: list[dict[str, Any]] = []
    if sub_path.is_file():
        try:
            raw_s = json.loads(sub_path.read_text(encoding="utf-8"))
            if isinstance(raw_s, dict) and isinstance(raw_s.get("card_sub_schedules"), list):
                sub_cards = [c for c in raw_s["card_sub_schedules"] if isinstance(c, dict)]
        except (OSError, ValueError):
            sub_cards = []

    def _util_of(t: str) -> float:
        val = ((engines or {}).get(t) or {}).get("budget_utilization_5h_pct")
        return float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else 0.0

    def _risk_of(t: str) -> str:
        pred = (((engines or {}).get(t) or {}).get("predictive_exhaustion")) or {}
        return str(pred.get("exhaustion_risk") or "SAFE")

    by_tool_counts: dict[str, int] = {"codex": 0, "antigravity": 0, "claude": 0}
    by_lane_counts: dict[str, int] = {ln: 0 for ln in PROCESS_LANES}
    by_thinking_level_counts: dict[str, int] = {"Low": 0, "Medium": 0, "High": 0}
    by_helper_model_counts: dict[str, int] = {}
    by_reasoning_model_counts: dict[str, int] = {}

    master_phase_optimizations: list[dict[str, Any]] = []
    for idx, p in enumerate(phases):
        pid = str(p.get("phase_id") or p.get("id") or f"PHASE-{idx + 1}").strip()
        state = str(p.get("state") or "READY").strip().upper()
        title = str(p.get("title") or p.get("name") or "")
        note = str(p.get("note") or p.get("action") or "")
        owner = normalize_tool_name(str(p.get("owner_tool") or p.get("owner") or "antigravity"))
        reviewer_raw = str(p.get("reviewer") or p.get("judge") or "")
        reviewer = normalize_tool_name(reviewer_raw) if reviewer_raw else ("claude" if owner != "claude" else "antigravity")
        if reviewer == owner:
            reviewer = "claude" if owner != "claude" else "antigravity"
        is_keypoint = bool(p.get("codex_exclusive") or p.get("keypoint"))

        lane_id = infer_lane_from_card_metadata(
            title=title,
            purpose=note,
            role="implementer",
            state=state,
        )
        exec_sel = select_optimal_helper_and_thinking(
            owner,
            card=pid,
            role="implementer",
            lane_id=lane_id,
            purpose=f"{title} {note}".strip(),
            is_keypoint=is_keypoint,
            utilization_5h_pct=_util_of(owner),
            exhaustion_risk=_risk_of(owner),
        )
        ver_sel = select_optimal_helper_and_thinking(
            reviewer,
            card=pid,
            role="reviewer",
            lane_id="VERIFY_AUDIT",
            purpose=f"Independent audit of {pid}: {title}",
            is_keypoint=is_keypoint,
            utilization_5h_pct=_util_of(reviewer),
            exhaustion_risk=_risk_of(reviewer),
        )

        by_tool_counts[owner] = by_tool_counts.get(owner, 0) + 1
        by_lane_counts[lane_id] = by_lane_counts.get(lane_id, 0) + 1
        by_thinking_level_counts[exec_sel["reasoning_thinking_level"]] = (
            by_thinking_level_counts.get(exec_sel["reasoning_thinking_level"], 0) + 1
        )
        hm = exec_sel["designated_helper_model"]
        rm = exec_sel["designated_reasoning_model"]
        by_helper_model_counts[hm] = by_helper_model_counts.get(hm, 0) + 1
        by_reasoning_model_counts[rm] = by_reasoning_model_counts.get(rm, 0) + 1

        master_phase_optimizations.append({
            "phase_id": pid,
            "state": state,
            "title": title[:160],
            "parallel_session_slot": (idx % 3) + 1,
            "lane_id": lane_id,
            "executor_tool": owner,
            "executor_selection": exec_sel,
            "verifier_tool": reviewer,
            "verifier_selection": ver_sel,
        })

    sub_schedule_optimizations: list[dict[str, Any]] = []
    for c in sub_cards:
        pid = str(c.get("phase_id") or "")
        exec_tool = normalize_tool_name(str(c.get("assigned_executor") or "antigravity"))
        ver_tool = normalize_tool_name(str(c.get("assigned_verifier") or ("claude" if exec_tool != "claude" else "antigravity")))
        stage_selections: list[dict[str, Any]] = []
        for sp in c.get("sub_processes") or []:
            if not isinstance(sp, dict):
                continue
            sub_id = str(sp.get("sub_id") or "")
            st_code = sub_id.split(":", 1)[1] if ":" in sub_id else str(sp.get("stage_name") or "SP3_CODE_EXECUTION")
            stage_tool = ver_tool if st_code == "SP4_INDEPENDENT_VERIFY" else exec_tool
            stage_role = (
                "reviewer"
                if st_code == "SP4_INDEPENDENT_VERIFY"
                else ("merger" if st_code == "SP5_MERGE_AND_RUNTIME" else "implementer")
            )
            sel = select_optimal_helper_and_thinking(
                stage_tool,
                card=pid,
                role=stage_role,
                sub_stage=st_code,
                purpose=str(sp.get("stage_name") or ""),
                utilization_5h_pct=_util_of(stage_tool),
                exhaustion_risk=_risk_of(stage_tool),
            )
            stage_selections.append({
                "sub_id": sub_id,
                "stage_code": st_code,
                "acting_tool": stage_tool,
                "role": stage_role,
                "ollama_cli_task": sel["ollama_cli_task"],
                "designated_helper_model": sel["designated_helper_model"],
                "helper_thinking_level": sel["helper_thinking_level"],
                "designated_reasoning_model": sel["designated_reasoning_model"],
                "reasoning_thinking_level": sel["reasoning_thinking_level"],
            })
        sub_schedule_optimizations.append({
            "phase_id": pid,
            "card_state": str(c.get("card_state") or "READY"),
            "assigned_executor": exec_tool,
            "assigned_verifier": ver_tool,
            "stages": stage_selections,
        })

    claude_audit = audit_and_optimize_claude_ollama_haiku_parallel(desk, engines=engines)

    return {
        "schema": "uaos-3tool-helper-thinking-schedule-optimization-v1",
        "official_3tool_model_lineup": get_official_tool_lineup(),
        "master_schedule_summary": {
            "total_master_phases": len(master_phase_optimizations),
            "by_tool_counts": by_tool_counts,
            "by_lane_counts": by_lane_counts,
            "by_thinking_level_counts": by_thinking_level_counts,
            "by_helper_model_counts": by_helper_model_counts,
            "by_reasoning_model_counts": by_reasoning_model_counts,
        },
        "sub_process_schedule_summary": {
            "total_cards": len(sub_schedule_optimizations),
            "total_sub_stages": sum(len(x["stages"]) for x in sub_schedule_optimizations),
            "cards": sub_schedule_optimizations,
        },
        "claude_ollama_haiku_parallel_audit": claude_audit,
        "master_phase_optimizations": master_phase_optimizations,
    }
