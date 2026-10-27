from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from v7_harness.adapters.ollama_worker import BLOCK_RE, EDIT_RE

DICTATION_CODE_LINE_LIMIT = 20  # a longer code patch costs the paid conductor more output tokens than a spec for a delegate; policy value, UNMEASURED until an A/B.

DELEGATE_WORKERS = frozenset({"ollama", "local", "cascade", "agy", "lane"})

# Code a shell or runtime executes; a dictated script is dictated code too (U98-D-R P1).
CODE_SUFFIXES = (".py", ".pyw", ".pyi", ".ps1", ".psm1", ".sh", ".bat", ".cmd", ".js", ".ts")

# Outcomes that mean the delegate really failed; APPROVE, PASS or no outcome never unlock apply (U98-D-R P1).
FAILED_OUTCOMES = frozenset({"FAIL", "FAILED", "BLOCKED", "UNUSABLE", "REWORK", "REJECTED"})

def _normalize(path: str) -> str:
    """Normalize the given path."""
    path = path.strip().replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path

def _card(work_id: str) -> str:
    """Get the card from the work_id."""
    return str(work_id or "").split("-")[0]

def dictated_code_lines(text: str) -> int:
    """Count non-test Python lines in a manual dictated by the paid conductor."""
    lines = 0
    for m in BLOCK_RE.finditer(text):
        path = _normalize(m.group("path"))
        body = m.group("body")
        if path.lower().endswith(CODE_SUFFIXES) and not path.startswith("tests/"):
            lines += sum(1 for line in body.splitlines() if line.strip())
    for m in EDIT_RE.finditer(text):
        path = _normalize(m.group("path"))
        replace = m.group("replace")
        if path.lower().endswith(CODE_SUFFIXES) and not path.startswith("tests/"):
            lines += sum(1 for line in replace.splitlines() if line.strip())
    return lines

def _failed_delegate(project: Path, work_id: str, card: str) -> bool:
    """Check if a delegate run with the given work_id failed."""
    if not card or _card(work_id) != card:
        return False
    from v7_harness.coord.hook_context import shared_desk
    path = shared_desk(project) / ".coord" / "usage" / "runs.jsonl"
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("work_id") == work_id and row.get("worker") in DELEGATE_WORKERS and row.get("outcome") in FAILED_OUTCOMES:
                    return True
    except OSError:
        pass
    return False

def delegate_first_errors(text: str, contract: dict[str, Any], project: Path) -> list[str]:
    """Check if the dictated code exceeds the line limit or if apply_after is needed."""
    if contract.get("worker") != "apply":
        return []
    lines = dictated_code_lines(text)
    if lines <= DICTATION_CODE_LINE_LIMIT:
        return []
    after = str(contract.get("apply_after") or "").strip()
    if after and _failed_delegate(project, after, _card(contract.get("work_id"))):
        return []
    return [f"DELEGATE_FIRST: {lines} dictated code lines > {DICTATION_CODE_LINE_LIMIT}; write a spec for worker local (Ollama) or agy first, and apply only with apply_after: <work_id of that failed run>"]


LOCAL_WORKERS = frozenset({"ollama", "local", "cascade"})  # U106: the free local routes; a paid worker takes code only after one of them failed.
PAID_WORKERS = frozenset({"agy", "claude"})


def _failed_local(project: Path, work_id: str, card: str) -> bool:
    """Check if a local run with the given work_id failed."""
    if not card or _card(work_id) != card:
        return False
    from v7_harness.coord.hook_context import shared_desk
    path = shared_desk(project) / ".coord" / "usage" / "runs.jsonl"
    if not path.exists():
        return False
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                if row.get("work_id") == work_id and row.get("worker") in LOCAL_WORKERS and row.get("outcome") in FAILED_OUTCOMES:
                    return True
    except OSError:
        pass
    return False


def local_first_errors(contract: dict[str, Any], project: Path) -> list[str]:
    """Check if code work was attempted locally before routing to a paid worker."""
    if contract.get("worker") not in PAID_WORKERS:
        return []
    raw_allow = contract.get("allow") or []
    if isinstance(raw_allow, str):
        raw_allow = [raw_allow]
    normalized = [_normalize(str(p)) for p in raw_allow]
    code_paths = [p for p in normalized if p.lower().endswith(CODE_SUFFIXES) and not p.startswith("tests/")]
    if not code_paths:
        return []
    after = str(contract.get("paid_after") or "").strip()
    if after and _failed_local(project, after, _card(contract.get("work_id"))):
        return []
    # U106: the commander may pick the paid worker by fit, but never silently: at least three words of reason.
    if len(str(contract.get("paid_reason") or "").split()) >= 3:
        return []
    return [
        "LOCAL_FIRST: code work goes to worker: cascade (Ollama first, escalates to the paid worker on a failed acceptance); a paid worker needs paid_after: <work_id of a failed Ollama/local/cascade run of this card> or paid_reason: <why this card needs the paid worker, at least 3 words>"
    ]


# U271/U272: Disjoint Parallel Architecture & Always-On 3-Tool Quality-Gated Ollama Pre-Pipeline Constants
# Core Philosophy: Maximize 3-tool (Antigravity, Claude Code, Codex) output and save token budgets via parallel
# Ollama pre-digestion & speculative drafting, while preserving Supreme Quality as the non-negotiable foundation.
CRITICAL_OFFLOAD_CODE_LINE_LIMIT = 30  # Expanded from 20 lines when tool 5h utilization >= 70%
NORMAL_READ_MAP_LINE_THRESHOLD = 150   # Always-On: use local_read_map for files > 150 lines in normal mode (<70% 5h usage)
BOOST_READ_MAP_LINE_THRESHOLD = 100    # Lowered to 100 lines when 5h utilization >= 70% (Aggressive Boost)
ALWAYS_ON_PARALLEL_PRE_TASKS = (
    "local_read_map_symbol_index",
    "local_draft_commit_and_pr_body",
    "local_draft_stage1_research_brief",
    "local_draft_test_failure_log_digest",
    "local_draft_doc_summary_skeleton",
)
SUPREME_QUALITY_GATES = (
    "DETERMINISTIC_UNITTEST_GATE",
    "ORIGINAL_SOURCE_HASH_VERIFICATION",
    "INDEPENDENT_NON_AUTHOR_DIFF_AUDIT",
    "TWO_STRIKE_AUTO_ESCALATION_TO_PAID_CORE",
)
HAIKU_PREFLIGHT_TOKEN_CAP = 12000      # Immutable preflight token ceiling for Claude Haiku 5.5 subagent
MAX_CONCURRENT_OLLA = 1                # Serial GPU lock for 8GB VRAM safety
MAX_CONCURRENT_HAIKU = 2               # Bounded parallel cloud subagent streams
CLAUDE_GOLDEN_RATIO = {"ollama_pct": 50.0, "haiku_pct": 30.0, "paid_core_pct": 20.0}
NON_CLAUDE_GOLDEN_RATIO = {"ollama_pct": 60.0, "haiku_pct": 0.0, "paid_core_pct": 40.0}


def _to_norm_list(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, str):
        val = [p.strip() for p in val.split(",") if p.strip()]
    return [_normalize(str(p)) for p in val if str(p).strip()]


def disjoint_parallel_errors(contract: dict[str, Any]) -> list[str]:
    """U271/U272: Enforce mutually exclusive allow sets between Ollama and Haiku 5.5 parallel workers
    to prevent Windows WinError 32 file-write race collisions, and enforce Haiku quarantine on Codex/Antigravity.
    """
    errors: list[str] = []
    caller = str(contract.get("caller") or contract.get("commander") or "").strip().lower()
    worker = str(contract.get("worker") or "").strip().lower()
    model = str(contract.get("model") or "").strip().lower()

    is_haiku_55 = ("haiku" in worker or "haiku-5-5" in model or "haiku-5.5" in model or model == "haiku")
    if is_haiku_55 and caller in ("codex", "antigravity", "agy"):
        errors.append(
            f"HAIKU_QUARANTINED_ON_TOOL: Haiku 5.5 is restricted to Claude Code internal subagent use; "
            f"{caller} must use 0-token Ollama + native subscription engine"
        )

    if "haiku" in worker or (is_haiku_55 and caller):
        try:
            budget = int(contract.get("remote_budget_tokens") or 0)
        except ValueError:
            budget = 0
        if budget > HAIKU_PREFLIGHT_TOKEN_CAP:
            errors.append(
                f"HAIKU_CAP_EXCEEDED: remote_budget_tokens {budget} > {HAIKU_PREFLIGHT_TOKEN_CAP} immutable preflight cap"
            )

    primary_allow = set(_to_norm_list(contract.get("allow")))
    companion_allow = set(
        _to_norm_list(contract.get("parallel_allow"))
        + _to_norm_list(contract.get("companion_allow"))
        + _to_norm_list(contract.get("haiku_allow"))
    )
    ollama_allow = set(_to_norm_list(contract.get("ollama_allow")))
    haiku_allow = set(_to_norm_list(contract.get("haiku_allow")))

    overlap = (primary_allow & companion_allow) | (ollama_allow & haiku_allow)
    if overlap:
        sorted_overlap = ", ".join(sorted(overlap))
        errors.append(
            f"DISJOINT_PARALLEL_OVERLAP: parallel worker allow paths overlap ({sorted_overlap}); "
            "assign code paths to Ollama and tests/docs paths to Haiku 5.5 without overlap"
        )

    return errors


def compute_agy_ollama_boost_plan(utilization_5h_pct: float, file_line_counts: dict[str, int] | None = None) -> dict[str, Any]:
    """U272: Concrete Antigravity Ollama Active Offload Boost specification.
    When 5h utilization >= 70%, expands code slice limit from 20 -> 30 lines and lowers read_map threshold from 250 -> 180 lines.
    """
    boost_active = float(utilization_5h_pct) >= 70.0
    read_threshold = BOOST_READ_MAP_LINE_THRESHOLD if boost_active else NORMAL_READ_MAP_LINE_THRESHOLD
    slice_limit = CRITICAL_OFFLOAD_CODE_LINE_LIMIT if boost_active else DICTATION_CODE_LINE_LIMIT
    files = file_line_counts or {}
    mandatory_map_files = [
        _normalize(path) for path, lines in files.items() if int(lines) > read_threshold
    ]
    estimated_saved_tokens = len(mandatory_map_files) * 4800
    return {
        "engine": "antigravity",
        "boost_active": boost_active,
        "utilization_5h_pct": round(float(utilization_5h_pct), 1),
        "read_map_line_threshold": read_threshold,
        "code_slice_line_limit": slice_limit,
        "mandatory_local_read_map_files": sorted(mandatory_map_files),
        "mandatory_local_draft_tasks": ["commit_msg", "pr_body", "doc_summary", "stage1_brief"],
        "estimated_saved_paid_tokens": estimated_saved_tokens,
        "target_offload_ratio": dict(NON_CLAUDE_GOLDEN_RATIO),
        "paid_argon_reserved_for": [
            "stage0_web_deep_research",
            "complex_multi_file_architecture",
            "independent_counterexample_review_and_merge",
        ],
    }


def compute_claude_532_dispatch_plan(
    ollama_calls_5h: int,
    haiku_calls_5h: int,
    opus_sonnet_calls_5h: int,
    haiku_remaining_5h_tokens: int = 2063363,
) -> dict[str, Any]:
    """U272: Concrete Claude Code 5:3:2 (50% Ollama : 30% Haiku 5.5 : 20% Opus/Sonnet) Golden Ratio optimizer."""
    total = max(1, int(ollama_calls_5h) + int(haiku_calls_5h) + int(opus_sonnet_calls_5h))
    cur_ollama = round((int(ollama_calls_5h) / total) * 100.0, 1)
    cur_haiku = round((int(haiku_calls_5h) / total) * 100.0, 1)
    cur_opus = round((int(opus_sonnet_calls_5h) / total) * 100.0, 1)

    delta_ollama = round(CLAUDE_GOLDEN_RATIO["ollama_pct"] - cur_ollama, 1)
    delta_haiku = round(CLAUDE_GOLDEN_RATIO["haiku_pct"] - cur_haiku, 1)
    delta_opus = round(CLAUDE_GOLDEN_RATIO["paid_core_pct"] - cur_opus, 1)

    next_recommended_tier = (
        "ollama"
        if delta_ollama >= delta_haiku and delta_ollama > 0
        else ("haiku" if delta_haiku > 0 and haiku_remaining_5h_tokens >= HAIKU_PREFLIGHT_TOKEN_CAP else "opus_sonnet")
    )
    return {
        "schema": "uaos-claude-532-dispatch-v1",
        "total_calls_5h": total,
        "current_ratio_pct": {
            "ollama_pct": cur_ollama,
            "haiku_pct": cur_haiku,
            "paid_core_pct": cur_opus,
        },
        "target_golden_ratio_pct": dict(CLAUDE_GOLDEN_RATIO),
        "deficit_delta_pct": {
            "ollama_delta_pct": delta_ollama,
            "haiku_delta_pct": delta_haiku,
            "paid_core_delta_pct": delta_opus,
        },
        "haiku_remaining_5h_tokens": int(haiku_remaining_5h_tokens),
        "haiku_preflight_cap_tokens": HAIKU_PREFLIGHT_TOKEN_CAP,
        "concurrency_caps": {
            "max_concurrent_ollama": MAX_CONCURRENT_OLLA,
            "max_concurrent_haiku": MAX_CONCURRENT_HAIKU,
        },
        "next_recommended_worker_tier": next_recommended_tier,
    }


def partition_disjoint_parallel_lanes(
    paths: list[str],
    caller_tool: str = "claude",
    utilization_5h_pct: float = 0.0,
) -> dict[str, Any]:
    """U271/U272: Deterministically split candidate file paths into mutually exclusive parallel lanes:
    - ollama_lane: 0-token local implementation slices (v7_harness/*.py, scripts)
    - haiku_lane: Claude-only fast test runner & doc sync (tests/*, docs/*) under 12,000 token cap
    - paid_core_lane: High-complexity architecture & final independent review
    """
    caller = caller_tool.strip().lower()
    norm_paths = [_normalize(str(p)) for p in paths if str(p).strip()]
    ollama_lane: list[str] = []
    haiku_lane: list[str] = []
    paid_core_lane: list[str] = []

    is_claude = caller == "claude"
    boost_active = utilization_5h_pct >= 70.0
    slice_limit = CRITICAL_OFFLOAD_CODE_LINE_LIMIT if boost_active else DICTATION_CODE_LINE_LIMIT

    for p in norm_paths:
        if p.startswith("tests/") or p.startswith("docs/") or p.lower().endswith((".md", ".html")):
            if is_claude:
                haiku_lane.append(p)
            else:
                ollama_lane.append(p)
        elif p.lower().endswith(CODE_SUFFIXES):
            ollama_lane.append(p)
        else:
            paid_core_lane.append(p)

    disjoint_ok = set(ollama_lane).isdisjoint(set(haiku_lane))
    return {
        "caller_tool": caller,
        "ollama_boost_active": boost_active,
        "ollama_slice_line_limit": slice_limit,
        "read_map_line_threshold": BOOST_READ_MAP_LINE_THRESHOLD if boost_active else NORMAL_READ_MAP_LINE_THRESHOLD,
        "haiku_preflight_token_cap": HAIKU_PREFLIGHT_TOKEN_CAP if is_claude else 0,
        "ollama_lane": ollama_lane,
        "haiku_lane": haiku_lane,
        "paid_core_lane": paid_core_lane,
        "disjoint_verified": disjoint_ok,
        "target_ratio": dict(CLAUDE_GOLDEN_RATIO if is_claude else NON_CLAUDE_GOLDEN_RATIO),
    }


def compute_always_on_quality_parallel_plan(
    tool: str,
    utilization_5h_pct: float = 0.0,
    file_line_counts: dict[str, int] | None = None,
    consecutive_local_failures: int = 0,
) -> dict[str, Any]:
    """U272: Always-On 3-Tool Quality-Gated Ollama Parallel Pre-Pipeline.
    Increases Ollama CLI utilization even in normal mode (<70% 5h usage) by running 0-token pre-digestion
    (`local_read_map` >= 150 lines, `local_draft` boilerplates, and speculative 20-line code slices) in parallel,
    while strictly enforcing Supreme Quality via 4 immutable gates and immediate escalation after 2 local failures.
    """
    caller = tool.strip().lower()
    boost_active = float(utilization_5h_pct) >= 70.0
    read_threshold = BOOST_READ_MAP_LINE_THRESHOLD if boost_active else NORMAL_READ_MAP_LINE_THRESHOLD
    slice_limit = CRITICAL_OFFLOAD_CODE_LINE_LIMIT if boost_active else DICTATION_CODE_LINE_LIMIT
    files = file_line_counts or {}
    pre_map_files = sorted(_normalize(p) for p, lines in files.items() if int(lines) > read_threshold)
    escalate_to_paid_core = int(consecutive_local_failures) >= 2

    return {
        "schema": "uaos-always-on-quality-parallel-v1",
        "tool": caller,
        "mode": "CRITICAL_BOOST_PARALLEL" if boost_active else "ALWAYS_ON_NORMAL_PARALLEL",
        "boost_active": boost_active,
        "utilization_5h_pct": round(float(utilization_5h_pct), 1),
        "read_map_line_threshold": read_threshold,
        "speculative_code_slice_line_limit": 0 if escalate_to_paid_core else slice_limit,
        "always_on_pre_map_files": pre_map_files,
        "always_on_parallel_pre_tasks": list(ALWAYS_ON_PARALLEL_PRE_TASKS),
        "supreme_quality_gates": list(SUPREME_QUALITY_GATES),
        "quality_compromise_allowed": False,
        "auto_escalated_to_paid_core": escalate_to_paid_core,
        "escalation_reason": (
            "TWO_STRIKE_QUALITY_PROTECTION: >=2 local failures detected; routing directly to paid core engine"
            if escalate_to_paid_core
            else "NONE"
        ),
        "target_golden_ratio": dict(CLAUDE_GOLDEN_RATIO if caller == "claude" else NON_CLAUDE_GOLDEN_RATIO),
    }
