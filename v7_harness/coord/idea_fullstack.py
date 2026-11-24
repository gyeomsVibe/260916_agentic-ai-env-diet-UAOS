"""U390: Full-stack Raw-Idea -> 3-Tool Interlocking Gears -> Reality engine.

Turns vague abstract user ideas into codebase-grounded specifications, disjoint
cycle-free 3-tool execution DAGs with independent non-author verification gates,
VRAM-tiered Ollama + helper allocation schedules, and zero-token health audits.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import time
from typing import Any, Callable, Iterable, Sequence

from v7_harness.adapters import ollama_vram_guard
from v7_harness.coord import mia_triage

CONCRETIZE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "goal": {"type": "string"},
        "problem_statement": {"type": "string"},
        "measurable_success_signals": {"type": "array", "items": {"type": "string"}},
        "non_goals": {"type": "array", "items": {"type": "string"}},
        "risks_and_rollback": {"type": "array", "items": {"type": "string"}},
        "candidate_domains": {"type": "array", "items": {"type": "string"}},
        "ambiguities": {"type": "array", "items": {"type": "string"}},
        "clarification_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "goal",
        "problem_statement",
        "measurable_success_signals",
        "non_goals",
        "risks_and_rollback",
        "candidate_domains",
        "ambiguities",
        "clarification_questions",
    ],
}

KEYPOINT_KEYWORDS = (
    "security",
    "authority",
    "global_rule",
    "global rule",
    "protocol",
    "release",
    "권한",
    "보안",
    "전역규칙",
    "전역",
    "프로토콜",
    "릴리스",
    "calculator_gate",
    "global_install",
)

_SAFETY_HUMAN_KEYWORDS = (
    "원격 푸시",
    "git push",
    "배포",
    "deploy",
    "결제",
    "지출",
    "계정",
    "자격 증명",
    "credential",
    "영구 삭제",
)

BRAIN_TOOLS: tuple[str, ...] = ("codex", "claude")
LABOR_TOOL: str = "antigravity"
DAILY_PACE_TARGET_PCT: float = round(100.0 / 7.0, 2)
BRAIN_PACKET_MAX_BYTES: int = 12_000
BRAIN_CONSERVATION_PACKET_MAX_BYTES: int = 8_192

BRAIN_LABOR_7D_POLICY: dict[str, Any] = {
    "schema": "uaos-brain-labor-7d-v1",
    "labor_tool": LABOR_TOOL,
    "labor_preferred_pool": "pool_b_gemini",
    "brain_tools": list(BRAIN_TOOLS),
    "daily_pace_target_pct": DAILY_PACE_TARGET_PCT,
    "brain_packet_max_bytes": BRAIN_PACKET_MAX_BYTES,
    "brain_conservation_packet_max_bytes": BRAIN_CONSERVATION_PACKET_MAX_BYTES,
    "invariants": {
        "author_ne_judge": True,
        "no_pct_to_token_conversion": True,
        "pool_a_blocked_when_depleted": True,
        "paid_savings_status": "UNMEASURED",
    },
}

DEFAULT_PLAN_TIER_WEIGHTS: dict[str, float] = {
    "antigravity": 5.0,
    "codex": 1.0,
    "claude": 1.0,
}

MIN_PASS_PROB_BY_COMPLEXITY: dict[str, float] = {
    "mechanical": 0.70,
    "standard_code": 0.78,
    "complex_multi_file": 0.85,
    "ultra_architecture": 0.88,
}

LATEST_BENCHMARK_CATALOG_202611: dict[str, Any] = {
    "schema": "uaos-model-benchmark-catalog-v1",
    "as_of": "2026-11-24",
    "live_paid_benchmarking_allowed": False,
    "sync_method": "external_verified_benchmarks_and_local_cache_zero_paid_tokens",
    "sources": [
        "docs/20261123-AI모델 최신동향-자료/0~11",
        "~/.codex/models_cache.json",
        "arXiv:2504.13359 (Cost-of-Pass)",
        "arXiv:2510.07505 (PEAR)",
        "arXiv:2609.32917 (Planner-as-Router)",
    ],
    "models": [
        {
            "tool": "antigravity",
            "model_id": "gemini-4-orchestrator-neon",
            "display": "Orchestrator (Neon)",
            "tier": "orchestrator_hybrid",
            "aa_index": 61.0,
            "swebench_or_tbench_pct": 85.0,
            "input_usd_per_1m": 1.9,
            "output_usd_per_1m": 9.4,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High", "XHigh"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.96,
                "standard_code": 0.94,
                "complex_multi_file": 0.90,
                "ultra_architecture": 0.88,
            },
        },
        {
            "tool": "antigravity",
            "model_id": "gemini-4-orchestrator-carbon",
            "display": "Orchestrator (Carbon)",
            "tier": "orchestrator_hybrid",
            "aa_index": 60.0,
            "swebench_or_tbench_pct": 84.0,
            "input_usd_per_1m": 2.4,
            "output_usd_per_1m": 12.0,
            "reasoning_token_multiplier": 1.35,
            "thinking_levels": ["Low", "Medium", "High"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.95,
                "standard_code": 0.93,
                "complex_multi_file": 0.89,
                "ultra_architecture": 0.90,
            },
        },
        {
            "tool": "antigravity",
            "model_id": "gemini-4-neon",
            "display": "Gemini 4 Neon",
            "tier": "one_shot_core",
            "aa_index": 61.0,
            "swebench_or_tbench_pct": 85.0,
            "input_usd_per_1m": 3.0,
            "output_usd_per_1m": 15.0,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Medium", "High", "XHigh"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.97,
                "standard_code": 0.95,
                "complex_multi_file": 0.91,
                "ultra_architecture": 0.90,
            },
        },
        {
            "tool": "antigravity",
            "model_id": "gemini-4-hydrogen",
            "display": "Gemini 4 Hydrogen",
            "tier": "fast_workhorse",
            "aa_index": 54.0,
            "swebench_or_tbench_pct": 72.0,
            "input_usd_per_1m": 1.5,
            "output_usd_per_1m": 7.5,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High", "XHigh"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.95,
                "standard_code": 0.86,
                "complex_multi_file": 0.52,
                "ultra_architecture": 0.40,
            },
        },
        {
            "tool": "antigravity",
            "model_id": "gemini-4-carbon",
            "display": "Gemini 4 Carbon",
            "tier": "flagship_strike",
            "aa_index": 60.0,
            "swebench_or_tbench_pct": 83.0,
            "input_usd_per_1m": 2.0,
            "output_usd_per_1m": 10.0,
            "promo_expires_at": "2026-11-30",
            "post_promo_input_usd_per_1m": 4.0,
            "post_promo_output_usd_per_1m": 20.0,
            "reasoning_token_multiplier": 2.1,
            "thinking_levels": ["Medium", "High"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.95,
                "standard_code": 0.93,
                "complex_multi_file": 0.90,
                "ultra_architecture": 0.92,
            },
        },
        {
            "tool": "antigravity",
            "model_id": "gemini-4-argon",
            "display": "Gemini 4 Argon",
            "tier": "one_shot_core",
            "aa_index": 50.4,
            "swebench_or_tbench_pct": 74.0,
            "input_usd_per_1m": 2.0,
            "output_usd_per_1m": 10.0,
            "promo_expires_at": "2026-11-30",
            "post_promo_input_usd_per_1m": 4.0,
            "post_promo_output_usd_per_1m": 20.0,
            "reasoning_token_multiplier": 1.1,
            "thinking_levels": ["Medium", "High"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.90,
                "standard_code": 0.84,
                "complex_multi_file": 0.80,
                "ultra_architecture": 0.72,
            },
        },
        {
            "tool": "antigravity",
            "model_id": "gemini-3.8-flash",
            "display": "Gemini 3.8 Flash",
            "tier": "deprecated",
            "aa_index": 31.0,
            "swebench_or_tbench_pct": 42.0,
            "input_usd_per_1m": 0.75,
            "output_usd_per_1m": 3.75,
            "reasoning_token_multiplier": 1.5,
            "thinking_levels": ["Low", "High"],
            "forbidden_efforts": [],
            "status": "deprecated",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.72,
                "standard_code": 0.50,
                "complex_multi_file": 0.30,
                "ultra_architecture": 0.15,
            },
        },
        {
            "tool": "codex",
            "model_id": "gpt-6.2-sol",
            "display": "GPT-6.2 Sol",
            "tier": "one_shot_core",
            "aa_index": 58.0,
            "swebench_or_tbench_pct": 82.0,
            "input_usd_per_1m": 1.0,
            "output_usd_per_1m": 5.0,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High", "XHigh", "Max"],
            "forbidden_efforts": ["ultra"],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.95,
                "standard_code": 0.93,
                "complex_multi_file": 0.88,
                "ultra_architecture": 0.84,
            },
        },
        {
            "tool": "codex",
            "model_id": "gpt-6.2-astra",
            "display": "GPT-6.2 Astra",
            "tier": "flagship_strike",
            "aa_index": 62.0,
            "swebench_or_tbench_pct": 86.0,
            "input_usd_per_1m": 4.0,
            "output_usd_per_1m": 20.0,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High", "XHigh", "Max"],
            "forbidden_efforts": ["ultra"],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.97,
                "standard_code": 0.96,
                "complex_multi_file": 0.94,
                "ultra_architecture": 0.93,
            },
        },
        {
            "tool": "codex",
            "model_id": "gpt-6.1-sol",
            "display": "GPT-6.1 Sol",
            "tier": "one_shot_core",
            "aa_index": 54.0,
            "swebench_or_tbench_pct": 78.0,
            "input_usd_per_1m": 1.25,
            "output_usd_per_1m": 6.25,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High", "XHigh", "Max"],
            "forbidden_efforts": ["ultra"],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.92,
                "standard_code": 0.89,
                "complex_multi_file": 0.85,
                "ultra_architecture": 0.80,
            },
        },
        {
            "tool": "codex",
            "model_id": "gpt-6-luna",
            "display": "GPT-6 Luna",
            "tier": "bounded_helper",
            "aa_index": 44.0,
            "swebench_or_tbench_pct": 58.0,
            "input_usd_per_1m": 0.10,
            "output_usd_per_1m": 0.50,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High"],
            "forbidden_efforts": ["ultra"],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.88,
                "standard_code": 0.62,
                "complex_multi_file": 0.38,
                "ultra_architecture": 0.20,
            },
        },
        {
            "tool": "claude",
            "model_id": "claude-opus-5-5",
            "display": "Claude Opus 5.5",
            "tier": "flagship_strike",
            "aa_index": 59.0,
            "swebench_or_tbench_pct": 65.8,
            "input_usd_per_1m": 4.0,
            "output_usd_per_1m": 20.0,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High", "Max"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.96,
                "standard_code": 0.94,
                "complex_multi_file": 0.92,
                "ultra_architecture": 0.91,
            },
        },
        {
            "tool": "claude",
            "model_id": "claude-haiku-5-5",
            "display": "Claude Haiku 5.5",
            "tier": "bounded_helper",
            "aa_index": 46.0,
            "swebench_or_tbench_pct": 52.0,
            "input_usd_per_1m": 0.10,
            "output_usd_per_1m": 0.50,
            "reasoning_token_multiplier": 1.0,
            "thinking_levels": ["Low", "Medium", "High"],
            "forbidden_efforts": [],
            "status": "active",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.89,
                "standard_code": 0.65,
                "complex_multi_file": 0.40,
                "ultra_architecture": 0.22,
            },
        },
        {
            "tool": "claude",
            "model_id": "claude-sonnet-5-5",
            "display": "Claude Sonnet 5.5",
            "tier": "deprecated",
            "aa_index": 54.0,
            "swebench_or_tbench_pct": 62.0,
            "input_usd_per_1m": 2.0,
            "output_usd_per_1m": 10.0,
            "reasoning_token_multiplier": 1.9,
            "thinking_levels": ["Low", "Medium", "High"],
            "forbidden_efforts": [],
            "status": "excluded_cot_bloat",
            "est_pass_prob_by_complexity": {
                "mechanical": 0.92,
                "standard_code": 0.86,
                "complex_multi_file": 0.80,
                "ultra_architecture": 0.72,
            },
        },
    ],
}

_DOMAIN_PATH_HINTS: dict[str, tuple[str, ...]] = {
    "ollama": (
        "v7_harness/adapters/ollama_vram_guard.py",
        "v7_harness/adapters/ollama_worker.py",
        "v7_harness/olla.py",
    ),
    "올라마": (
        "v7_harness/adapters/ollama_vram_guard.py",
        "v7_harness/adapters/ollama_worker.py",
        "v7_harness/olla.py",
    ),
    "사서함": ("v7_harness/coord/mailbox.py", "v7_harness/coord/sentinel.py", "v7_harness/coord/deliver.py"),
    "mailbox": ("v7_harness/coord/mailbox.py", "v7_harness/coord/sentinel.py", "v7_harness/coord/deliver.py"),
    "우편함": ("v7_harness/coord/mailbox.py", "v7_harness/coord/sentinel.py", "v7_harness/coord/deliver.py"),
    "권한": ("v7_harness/coord/presence.py", "v7_harness/coord/participation.py"),
    "출석": ("v7_harness/coord/presence.py", "v7_harness/coord/participation.py"),
    "presence": ("v7_harness/coord/presence.py", "v7_harness/coord/participation.py"),
    "아이디어": ("v7_harness/coord/idea_fullstack.py", "v7_harness/coord/desk_router.py", "v7_harness/coord/mia_triage.py"),
    "구체화": ("v7_harness/coord/idea_fullstack.py", "v7_harness/coord/desk_router.py", "v7_harness/coord/mia_triage.py"),
    "톱니바퀴": ("v7_harness/coord/idea_fullstack.py", "v7_harness/coord/desk_router.py", "v7_harness/coord/sentinel.py"),
    "현실화": ("v7_harness/coord/idea_fullstack.py", "v7_harness/coord/desk_router.py"),
    "자동화": ("v7_harness/coord/idea_fullstack.py", "v7_harness/coord/sentinel.py", "v7_harness/coord/desk_router.py"),
    "스케줄": ("v7_harness/coord/schedule_reconcile.py", "v7_harness/coord/schedule_planner.py"),
    "schedule": ("v7_harness/coord/schedule_reconcile.py", "v7_harness/coord/schedule_planner.py"),
    "세션": ("v7_harness/coord/card_sessions.py", "v7_harness/coord/windows.py"),
    "창": ("v7_harness/coord/windows.py", "v7_harness/coord/user_window.py"),
    "토큰": ("v7_harness/coord/usage_budget.py", "v7_harness/adapters/ollama_vram_guard.py"),
    "예산": ("v7_harness/coord/usage_budget.py", "v7_harness/coord/helper_thinking_router.py"),
    "도우미": ("v7_harness/coord/helper_thinking_router.py", "v7_harness/coord/idea_fullstack.py"),
    "풀스택": ("v7_harness/coord/idea_fullstack.py", "v7_harness/coord/desk_router.py", "v7_harness/coord/presence.py"),
}

_SOURCE_EXTS = frozenset({".py", ".ts", ".js", ".md"})
_SKIP_DIRS = frozenset({".git", ".work", ".pytest_cache", "__pycache__", "node_modules", ".coord"})
_NEGATIVE_LINE_RE = re.compile(r"하지\s*(?:말|마)|금지|않는다|제외|do not|don't|never|out of scope", re.I)


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").lstrip("./")


def scan_repo_surface(project: Path, *, max_files: int = 400) -> dict[str, Any]:
    """Build a deterministic 0-token index of repository source paths and domain hints."""
    root = Path(project)
    files: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in _SKIP_DIRS and not d.startswith("."))
        for fname in sorted(filenames):
            if Path(fname).suffix.lower() not in _SOURCE_EXTS:
                continue
            rel = _norm(str(Path(dirpath, fname).relative_to(root)))
            files.append(rel)
            if len(files) >= max_files:
                break
        if len(files) >= max_files:
            break

    graph_nodes = 0
    graph_path = root / ".coord" / "code_graph.json"
    if graph_path.is_file():
        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            if isinstance(graph, dict):
                nodes = graph.get("nodes") or graph.get("files") or []
                graph_nodes = len(nodes) if isinstance(nodes, (list, dict)) else 0
        except (OSError, ValueError):
            graph_nodes = 0

    domains: dict[str, list[str]] = {}
    for rel in files:
        parts = Path(rel).parts
        key = "/".join(parts[:2]) if len(parts) >= 2 else parts[0]
        domains.setdefault(key, []).append(rel)

    return {
        "files": files,
        "file_set": set(files),
        "domains": domains,
        "graph_nodes": graph_nodes,
    }


def _ground_files(text: str, repo_index: dict[str, Any]) -> tuple[list[str], list[str]]:
    from v7_harness.coord.desk_router import extract_files

    file_set: set[str] = set(repo_index.get("file_set") or ())
    all_files: list[str] = list(repo_index.get("files") or ())
    lowered = text.lower()

    explicit = [_norm(f) for f in sorted(extract_files(text)) if not file_set or _norm(f) in file_set]
    grounded: list[str] = list(explicit)
    domains: list[str] = []

    for keyword, candidates in _DOMAIN_PATH_HINTS.items():
        if keyword in lowered:
            domains.append(keyword)
            for cand in candidates:
                if (not file_set or cand in file_set) and cand not in grounded:
                    grounded.append(cand)

    if not grounded:
        tokens = [t for t in re.findall(r"[a-z_]{3,}", lowered)]
        for rel in all_files:
            stem = Path(rel).stem.lower()
            if any(tok in stem for tok in tokens) and rel not in grounded:
                grounded.append(rel)
            if len(grounded) >= 6:
                break

    if not grounded and all_files:
        for fallback in (
            "v7_harness/coord/idea_fullstack.py",
            "v7_harness/coord/desk_router.py",
            "v7_harness/coord/presence.py",
        ):
            if fallback in file_set:
                grounded.append(fallback)
        if not grounded:
            grounded.extend(p for p in all_files if not p.startswith("tests/"))[:3]

    return grounded[:12], sorted(set(domains))


def _valid_schema_draft(draft: Any) -> bool:
    if not isinstance(draft, dict):
        return False
    if not isinstance(draft.get("goal"), str) or not draft["goal"].strip():
        return False
    if not isinstance(draft.get("problem_statement"), str) or not draft["problem_statement"].strip():
        return False
    for list_key in (
        "measurable_success_signals",
        "non_goals",
        "risks_and_rollback",
        "candidate_domains",
        "ambiguities",
        "clarification_questions",
    ):
        val = draft.get(list_key)
        if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
            return False
    return bool(draft["measurable_success_signals"])


def _has_measurable_gate(signals: Sequence[str]) -> bool:
    return any(re.search(r"exit\s*0|pytest|unittest|pass|통과|\d+|%", s, re.I) for s in signals)


def concretize_raw_idea(
    project: Path,
    raw_idea: str,
    *,
    drafter: Callable[[str, dict[str, Any]], str] | None = None,
    repo_index: dict[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Transform a raw abstract user idea into a repo-grounded, gate-equipped spec."""
    from v7_harness.coord.desk_router import extract_resources

    root = Path(project)
    text = str(raw_idea or "").strip()
    raw_bytes = text.encode("utf-8")
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    index = repo_index if repo_index is not None else scan_repo_surface(root)

    grounded_files, matched_domains = _ground_files(text, index)
    shared_resources = sorted(extract_resources(text))
    lines = [ln.strip() for ln in re.split(r"(?<=[.!?。])\s+|\n+", text) if ln.strip()]
    goal = (lines[0] if lines else text)[:240] or "Clarify and implement user directive safely"
    non_goals = [ln[:200] for ln in lines if _NEGATIVE_LINE_RE.search(ln)]
    if not non_goals:
        non_goals = ["Do not modify unrelated modules or perform unapproved human-only actions"]
    signals = [ln[:200] for ln in lines if re.search(r"exit\s*0|pytest|test|통과|검증|\d+", ln, re.I)]
    if not _has_measurable_gate(signals):
        signals.append("python -B -m pytest -q passes with exit 0 and zero regressions")

    ambiguities: list[str] = []
    clarification_questions: list[str] = []
    if not grounded_files:
        ambiguities.append("No repository module matched the idea surface")
    lowered = text.lower()
    if any(kw in lowered for kw in _SAFETY_HUMAN_KEYWORDS):
        ambiguities.append("Touches human-only safety boundary")
        clarification_questions.append("Safety 사람 전용 경계(원격 푸시/배포/결제/계정/삭제) 승인 여부를 확인하세요.")

    risks_and_rollback = [
        "Backup modified files under .work/backup_<date>/ and isolate work in a dedicated git worktree",
        "Revert or discard isolated worktree branch if fixed acceptance or regression suite fails",
    ]

    source = "deterministic"
    problem_statement = f"Raw directive ({len(text)} chars) lacked explicit file/gate contract; grounded to repo surface."
    if drafter is not None:
        prompt = (
            "Convert this raw user directive into strict JSON matching CONCRETIZE_SCHEMA. "
            f"Candidate repo files: {', '.join(grounded_files[:8])}.\nDirective:\n{text}"
        )
        try:
            raw_reply = drafter(prompt, CONCRETIZE_SCHEMA)
            draft = json.loads(raw_reply)
            if _valid_schema_draft(draft):
                goal = draft["goal"].strip()[:240]
                problem_statement = draft["problem_statement"].strip()[:300]
                if _has_measurable_gate(draft["measurable_success_signals"]):
                    signals = [s.strip()[:200] for s in draft["measurable_success_signals"] if s.strip()]
                non_goals = [s.strip()[:200] for s in draft["non_goals"] if s.strip()] or non_goals
                risks_and_rollback = [s.strip()[:200] for s in draft["risks_and_rollback"] if s.strip()] or risks_and_rollback
                matched_domains = sorted(set(matched_domains) | {s.strip() for s in draft["candidate_domains"] if s.strip()})
                if draft["clarification_questions"]:
                    clarification_questions = [q.strip()[:200] for q in draft["clarification_questions"] if q.strip()]
                source = "ollama"
            else:
                source = "deterministic_fallback"
        except Exception:
            source = "deterministic_fallback"

    mia = mia_triage.classify_mia_tier(text, file_count=len(grounded_files) or None, paths=grounded_files)
    confidence = 0.85 if grounded_files and _has_measurable_gate(signals) else 0.55
    if ambiguities:
        confidence = max(0.35, confidence - 0.15 * len(ambiguities))

    return {
        "schema": "uaos-concretized-idea-v1",
        "created_at": time.time() if now is None else float(now),
        "raw_sha256": raw_sha,
        "goal": goal,
        "problem_statement": problem_statement,
        "measurable_success_signals": signals,
        "non_goals": non_goals,
        "grounded_files": grounded_files,
        "candidate_domains": matched_domains,
        "shared_resources": shared_resources,
        "risks_and_rollback": risks_and_rollback,
        "ambiguities": ambiguities,
        "clarification_questions": clarification_questions,
        "mia_tier": mia,
        "confidence": round(confidence, 3),
        "source": source,
    }


def _num_or_none(val: Any) -> float | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return None


def parse_iso_timestamp(iso_ts: Any) -> float | None:
    """Parse an ISO-8601 timestamp safely into UTC epoch seconds."""
    if not isinstance(iso_ts, str) or not iso_ts.strip():
        return None
    raw = iso_ts.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.timestamp()


def _days_until_iso(iso_ts: Any, now: float) -> float:
    ts = parse_iso_timestamp(iso_ts)
    if ts is None:
        return 7.0
    days = (ts - float(now)) / 86400.0
    return max(1.0, min(7.0, days))


def _tool_available(tool: str, tool_states: dict[str, str], quota_snapshot: dict[str, Any] | None) -> bool:
    if str(tool_states.get(tool) or "UNKNOWN").upper() != "ACTIVE":
        return False
    if quota_snapshot and isinstance(quota_snapshot.get(tool), dict):
        q = quota_snapshot[tool]
        if q.get("paused") is True:
            return False
        if tool == "antigravity" and (
            "pool_b_gemini_7d_remaining_pct" in q or "pool_b_gemini_5h_remaining_pct" in q
        ):
            rem7 = _num_or_none(q.get("pool_b_gemini_7d_remaining_pct"))
            rem5 = _num_or_none(q.get("pool_b_gemini_5h_remaining_pct"))
        else:
            rem7 = _num_or_none(q.get("7d_remaining_pct"))
            rem5 = _num_or_none(q.get("5h_remaining_pct"))
        if rem7 is not None and rem7 <= 2.0:
            return False
        if rem5 is not None and rem5 <= 5.0:
            return False
    return True


def evaluate_tool_pacing(
    tool: str,
    *,
    state: str,
    quota: dict[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Compute dimensionless 5h/7d pacing tier without ever converting % to tokens."""
    moment = time.time() if now is None else float(now)
    norm_tool = str(tool or "").strip().lower()
    norm_state = str(state or "UNKNOWN").strip().upper()
    q = quota if isinstance(quota, dict) else {}
    is_active = norm_state == "ACTIVE"
    paused = q.get("paused") is True

    if norm_tool == LABOR_TOOL:
        rem5 = _num_or_none(q.get("pool_b_gemini_5h_remaining_pct"))
        if rem5 is None:
            rem5 = _num_or_none(q.get("5h_remaining_pct"))
        rem7 = _num_or_none(q.get("pool_b_gemini_7d_remaining_pct"))
        if rem7 is None:
            rem7 = _num_or_none(q.get("7d_remaining_pct"))
        if rem5 is None:
            rem5 = 100.0 if is_active else 0.0
        if rem7 is None:
            rem7 = 100.0 if is_active else 0.0

        pool_a_7d = _num_or_none(q.get("pool_a_3p_7d_remaining_pct"))
        pool_a_blocked = pool_a_7d is not None and pool_a_7d <= 2.0
        remaining_days = _days_until_iso(q.get("pool_b_resets_at") or q.get("7d_resets_at"), moment)
        daily_allowance_pct = round(rem7 / remaining_days, 2)

        if not is_active or paused or rem7 <= 2.0 or rem5 <= 5.0:
            tier = "PAUSED_PROTECT"
        elif rem5 < 20.0 or rem7 < 15.0:
            tier = "LABOR_CONSERVE"
        else:
            tier = "LABOR_READY"

        return {
            "tool": norm_tool,
            "role": "LABOR",
            "state": norm_state,
            "tier": tier,
            "selected_pool": "pool_b_gemini" if tier != "PAUSED_PROTECT" else "NONE",
            "pool_a_blocked": pool_a_blocked,
            "5h_remaining_pct": rem5,
            "7d_remaining_pct": rem7,
            "remaining_days": round(remaining_days, 2),
            "daily_allowance_pct": daily_allowance_pct,
            "max_packet_bytes": BRAIN_PACKET_MAX_BYTES,
        }

    rem5 = _num_or_none(q.get("5h_remaining_pct"))
    rem7 = _num_or_none(q.get("7d_remaining_pct"))
    if rem5 is None:
        rem5 = 100.0 if is_active else 0.0
    if rem7 is None:
        rem7 = 100.0 if is_active else 0.0

    remaining_days = _days_until_iso(q.get("7d_resets_at"), moment)
    daily_allowance_pct = round(rem7 / remaining_days, 2)

    if not is_active or paused or rem7 <= 2.0 or rem5 <= 5.0:
        tier = "PAUSED_PROTECT"
    elif rem5 < 25.0 or rem7 < 15.0 or daily_allowance_pct < 8.0:
        tier = "KEYPOINT_VERDICT_ONLY"
    else:
        tier = "FULL_BRAIN"

    max_bytes = BRAIN_CONSERVATION_PACKET_MAX_BYTES if tier == "KEYPOINT_VERDICT_ONLY" else BRAIN_PACKET_MAX_BYTES
    return {
        "tool": norm_tool,
        "role": "BRAIN",
        "state": norm_state,
        "tier": tier,
        "5h_remaining_pct": rem5,
        "7d_remaining_pct": rem7,
        "remaining_days": round(remaining_days, 2),
        "daily_allowance_pct": daily_allowance_pct,
        "max_packet_bytes": max_bytes,
    }


def _encoded_packet_bytes(pkt: dict[str, Any]) -> int:
    return len(json.dumps(pkt, ensure_ascii=False, sort_keys=True).encode("utf-8"))


def build_compact_brain_packet(
    *,
    card_id: str,
    author: str,
    judge: str,
    patch_sha256: str,
    changed_files: Sequence[str],
    test_command: str,
    test_exit_code: int,
    test_summary: str,
    diff_stat: str = "",
    notes: str = "",
    max_bytes: int = BRAIN_PACKET_MAX_BYTES,
) -> dict[str, Any]:
    """Build a compact non-author review packet gated by local pre-tests and byte caps."""
    norm_author = str(author or "").strip().lower()
    norm_judge = str(judge or "").strip().lower()
    if norm_author == norm_judge:
        raise ValueError("SELF_JUDGE_FORBIDDEN: author cannot judge own compact packet")

    limit = max(512, int(max_bytes))
    code = int(test_exit_code)
    pre_passed = code == 0
    pkt: dict[str, Any] = {
        "schema": "uaos-compact-brain-packet-v1",
        "card_id": str(card_id),
        "author": norm_author,
        "judge": norm_judge,
        "patch_sha256": str(patch_sha256),
        "changed_files": [_norm(p) for p in changed_files],
        "test_command": str(test_command),
        "test_exit_code": code,
        "test_summary": str(test_summary),
        "diff_stat": str(diff_stat),
        "notes": str(notes),
        "pre_gate_passed": pre_passed,
        "ready_for_brain_review": pre_passed,
        "block_reason": None if pre_passed else "LOCAL_PREGATE_FAILED",
        "max_bytes": limit,
        "truncated": False,
        "packet_bytes": limit,
        "within_budget": True,
    }

    if _encoded_packet_bytes(pkt) > limit:
        pkt["truncated"] = True
        marker = "...[TRUNCATED]"
        for field in ("notes", "diff_stat", "test_summary"):
            if _encoded_packet_bytes(pkt) <= limit:
                break
            orig = str(pkt[field])
            if not orig:
                continue
            pkt[field] = marker if field != "notes" else ""
            if _encoded_packet_bytes(pkt) > limit:
                pkt[field] = ""
                continue
            lo, hi = 0, len(orig)
            best = marker if field != "notes" else ""
            while lo <= hi:
                mid = (lo + hi) // 2
                cand = (orig[:mid] + marker) if mid > 0 or field != "notes" else ""
                pkt[field] = cand
                if _encoded_packet_bytes(pkt) <= limit:
                    best = cand
                    lo = mid + 1
                else:
                    hi = mid - 1
            pkt[field] = best

    final_bytes = _encoded_packet_bytes(pkt)
    pkt["packet_bytes"] = final_bytes
    pkt["within_budget"] = final_bytes <= limit
    return pkt


def load_synced_benchmark_catalog(
    project: Path | None = None,
    *,
    codex_cache_models: Sequence[str] | None = None,
    reference_date: str = "2026-11-24",
) -> dict[str, Any]:
    """Load external benchmark catalog with date-aware pricing and zero paid model trials."""
    catalog = copy.deepcopy(LATEST_BENCHMARK_CATALOG_202611)
    by_key: dict[tuple[str, str], dict[str, Any]] = {
        (str(m.get("tool")), str(m.get("model_id"))): m for m in catalog["models"]
    }

    if project is not None:
        sync_file = Path(project) / ".coord" / "model_benchmarks_latest.json"
        if sync_file.is_file():
            try:
                ext = json.loads(sync_file.read_text(encoding="utf-8"))
                ext_models = ext.get("models") if isinstance(ext, dict) else None
                if isinstance(ext_models, list):
                    for item in ext_models:
                        if not isinstance(item, dict) or not item.get("tool") or not item.get("model_id"):
                            continue
                        key = (str(item["tool"]), str(item["model_id"]))
                        if key in by_key:
                            by_key[key].update(item)
                        else:
                            merged = dict(item)
                            merged.setdefault("status", "active")
                            by_key[key] = merged
                            catalog["models"].append(merged)
                    if isinstance(ext.get("as_of"), str):
                        catalog["as_of"] = ext["as_of"]
            except (OSError, ValueError):
                pass

    ref = str(reference_date or "2026-11-24")[:10]
    cache_set = {str(m).strip() for m in codex_cache_models} if codex_cache_models is not None else None
    for entry in catalog["models"]:
        promo_exp = str(entry.get("promo_expires_at") or "").strip()[:10]
        if promo_exp and ref > promo_exp:
            if "post_promo_input_usd_per_1m" in entry:
                entry["input_usd_per_1m"] = entry["post_promo_input_usd_per_1m"]
            if "post_promo_output_usd_per_1m" in entry:
                entry["output_usd_per_1m"] = entry["post_promo_output_usd_per_1m"]
            entry["promo_active"] = False
        else:
            entry["promo_active"] = bool(promo_exp)

        if cache_set is not None and entry.get("tool") == "codex" and entry.get("status") == "active":
            mid = str(entry.get("model_id") or "")
            if mid not in cache_set and mid in ("gpt-6.2-sol", "gpt-6.2-astra"):
                entry["status"] = "unavailable_in_local_cache"

    catalog["live_paid_benchmarking_allowed"] = False
    catalog["effective_reference_date"] = ref
    return catalog


def _default_pass_prob(aa_index: float, complexity: str) -> float:
    base = min(0.97, max(0.35, (float(aa_index) - 18.0) / 52.0))
    penalty = {"mechanical": 0.0, "standard_code": 0.02, "complex_multi_file": 0.04, "ultra_architecture": 0.06}
    return max(0.15, min(0.97, base - penalty.get(complexity, 0.03)))


def select_model_by_perf_per_token(
    tool: str,
    *,
    complexity: str = "standard_code",
    is_keypoint: bool = False,
    high_quota_pressure: bool = False,
    catalog: dict[str, Any] | None = None,
    reference_date: str = "2026-11-24",
) -> dict[str, Any]:
    """Select the highest Performance-per-Token (inverse Cost-of-Pass) active model."""
    norm_tool = str(tool or "antigravity").strip().lower()
    comp = complexity if complexity in MIN_PASS_PROB_BY_COMPLEXITY else "standard_code"
    cat = catalog if catalog is not None else load_synced_benchmark_catalog(reference_date=reference_date)
    min_pass = MIN_PASS_PROB_BY_COMPLEXITY[comp]

    candidates = [
        m
        for m in (cat.get("models") or ())
        if isinstance(m, dict) and str(m.get("tool")).lower() == norm_tool and m.get("status") == "active"
    ]
    if not candidates:
        return {
            "tool": norm_tool,
            "model_id": None,
            "display": None,
            "effort": "medium",
            "complexity": comp,
            "live_paid_benchmarking_used": False,
        }

    if is_keypoint and not high_quota_pressure:
        flagships = [m for m in candidates if m.get("tier") == "flagship_strike"]
        if norm_tool == "codex" and flagships:
            candidates = flagships

    qualified = []
    for m in candidates:
        aa = float(m.get("aa_index") or 50.0)
        pmap = m.get("est_pass_prob_by_complexity") or {}
        p_pass = float(pmap.get(comp) if comp in pmap else _default_pass_prob(aa, comp))
        if p_pass >= min_pass:
            qualified.append((m, p_pass))
    if not qualified:
        best_fallback = max(
            candidates,
            key=lambda m: float((m.get("est_pass_prob_by_complexity") or {}).get(comp, _default_pass_prob(float(m.get("aa_index") or 50.0), comp))),
        )
        qualified = [
            (
                best_fallback,
                float((best_fallback.get("est_pass_prob_by_complexity") or {}).get(comp, _default_pass_prob(float(best_fallback.get("aa_index") or 50.0), comp))),
            )
        ]

    scored: list[tuple[float, dict[str, Any], float, float]] = []
    for m, p_pass in qualified:
        inp = float(m.get("input_usd_per_1m") or 2.0)
        out = float(m.get("output_usd_per_1m") or 10.0)
        mult = float(m.get("reasoning_token_multiplier") or 1.0)
        weighted_cost = max(0.05, (0.3 * inp + 0.7 * out) * mult)
        retry_inflation = 1.0 + 2.8 * (1.0 - p_pass) if p_pass < 0.75 else 1.0
        cost_of_pass = (weighted_cost * retry_inflation) / max(0.05, p_pass)
        perf_index = 100.0 / max(0.01, cost_of_pass)
        aa = float(m.get("aa_index") or 50.0)
        aa_bonus = max(0.0, aa - 55.0) * 0.04
        score = perf_index * (1.0 + aa_bonus)
        if m.get("tier") == "orchestrator_hybrid" and comp in ("standard_code", "complex_multi_file"):
            score *= 1.05
        scored.append((score, m, p_pass, cost_of_pass))

    scored.sort(key=lambda row: (-row[0], row[3], str(row[1].get("model_id"))))
    top_score, winner, top_pass, top_cop = scored[0]

    forbidden = {str(e).lower() for e in (winner.get("forbidden_efforts") or ())}
    allowed_levels = [str(lv).lower() for lv in (winner.get("thinking_levels") or ("Medium", "High")) if str(lv).lower() not in forbidden]
    if high_quota_pressure:
        desired = "medium"
    elif is_keypoint or comp in ("complex_multi_file", "ultra_architecture"):
        desired = "high" if "high" in allowed_levels else (allowed_levels[-1] if allowed_levels else "medium")
    else:
        desired = "medium" if "medium" in allowed_levels else (allowed_levels[0] if allowed_levels else "low")
    effort = desired if desired in allowed_levels or not allowed_levels else allowed_levels[0]
    if effort in forbidden:
        effort = "high"

    return {
        "tool": norm_tool,
        "model_id": winner.get("model_id"),
        "display": winner.get("display"),
        "tier": winner.get("tier"),
        "effort": effort,
        "complexity": comp,
        "aa_index": winner.get("aa_index"),
        "est_pass_prob": round(top_pass, 3),
        "cost_of_pass": round(top_cop, 3),
        "perf_per_token_score": round(top_score, 3),
        "input_usd_per_1m": winner.get("input_usd_per_1m"),
        "output_usd_per_1m": winner.get("output_usd_per_1m"),
        "promo_active": winner.get("promo_active", False),
        "forbidden_efforts": sorted(forbidden),
        "live_paid_benchmarking_used": False,
    }


def plan_brain_labor_7d_schedule(
    *,
    tool_states: dict[str, str],
    quota_snapshot: dict[str, Any] | None = None,
    is_keypoint: bool = False,
    plan_weights: dict[str, float] | None = None,
    benchmark_catalog: dict[str, Any] | None = None,
    reference_date: str = "2026-11-24",
    now: float | None = None,
) -> dict[str, Any]:
    """Dynamically allocate Labor vs Brain roles across 3 tools by live 5h/7d quota & recency."""
    moment = time.time() if now is None else float(now)
    qsnap = quota_snapshot if isinstance(quota_snapshot, dict) else {}
    pacing = {
        t: evaluate_tool_pacing(
            t,
            state=str(tool_states.get(t) or "UNKNOWN"),
            quota=qsnap.get(t) if isinstance(qsnap.get(t), dict) else None,
            now=moment,
        )
        for t in ("antigravity", "codex", "claude")
    }

    weights = dict(DEFAULT_PLAN_TIER_WEIGHTS)
    if plan_weights:
        for k, v in plan_weights.items():
            weights[str(k).lower()] = float(v)

    headroom = {
        t: (0.0 if pacing[t]["tier"] == "PAUSED_PROTECT" else round(pacing[t]["daily_allowance_pct"] * weights.get(t, 1.0), 3))
        for t in ("antigravity", "codex", "claude")
    }

    active_brains = [b for b in BRAIN_TOOLS if pacing[b]["tier"] != "PAUSED_PROTECT"]
    full_brains = [b for b in active_brains if pacing[b]["tier"] == "FULL_BRAIN"]
    agy_tier = pacing["antigravity"]["tier"]
    agy_ready = agy_tier in ("LABOR_READY", "LABOR_CONSERVE")

    max_full_brain_headroom = max((headroom[b] for b in full_brains), default=0.0)
    invert_to_brain = bool(full_brains) and (
        not agy_ready
        or agy_tier == "LABOR_CONSERVE"
        or (pacing["antigravity"]["7d_remaining_pct"] < 25.0 and max_full_brain_headroom > headroom["antigravity"])
    )

    position_shifted = False
    shift_reason: str | None = None
    if invert_to_brain:
        labor_owner = max(
            full_brains,
            key=lambda b: (pacing[b]["daily_allowance_pct"], headroom[b], b == "claude"),
        )
        labor_pool = "dynamic_peer_labor"
        position_shifted = True
        shift_reason = f"DYNAMIC_SHIFT:antigravity({agy_tier})->{labor_owner}(FULL_BRAIN)"
    elif agy_ready:
        labor_owner = "antigravity"
        labor_pool = "pool_b_gemini"
    elif active_brains:
        labor_owner = max(
            active_brains,
            key=lambda b: (pacing[b]["tier"] == "FULL_BRAIN", pacing[b]["daily_allowance_pct"], b == "claude"),
        )
        labor_pool = "brain_fallback"
        position_shifted = True
        shift_reason = f"AGY_UNAVAILABLE->{labor_owner}"
    else:
        labor_owner = "antigravity"
        labor_pool = "brain_fallback"

    acting_brain_mode = not active_brains
    deferred_until_brain_return = acting_brain_mode

    spec_pool = [t for t in ("codex", "claude", "antigravity") if pacing[t]["tier"] != "PAUSED_PROTECT" and (t != labor_owner or len(active_brains) <= 1)]
    if is_keypoint and "codex" in active_brains:
        spec_brain = "codex"
    elif active_brains and not position_shifted:
        spec_brain = max(
            active_brains,
            key=lambda b: (pacing[b]["tier"] == "FULL_BRAIN", pacing[b]["daily_allowance_pct"], b == "codex"),
        )
    elif spec_pool:
        spec_brain = max(
            spec_pool,
            key=lambda t: (pacing[t]["tier"] == "FULL_BRAIN", t == "codex", pacing[t]["daily_allowance_pct"]),
        )
    else:
        spec_brain = "antigravity"

    active_all_non_author = [t for t in ("codex", "claude", "antigravity") if pacing[t]["tier"] != "PAUSED_PROTECT" and t != labor_owner]
    judge_brains_non_author = [b for b in active_brains if b != labor_owner]
    if is_keypoint and "codex" in judge_brains_non_author:
        judge_brain = "codex"
    elif judge_brains_non_author:
        judge_brain = max(
            judge_brains_non_author,
            key=lambda b: (pacing[b]["tier"] == "FULL_BRAIN", pacing[b]["daily_allowance_pct"], b == "claude"),
        )
    elif position_shifted and active_all_non_author:
        judge_brain = max(
            active_all_non_author,
            key=lambda t: (pacing[t]["daily_allowance_pct"], t == "codex"),
        )
    else:
        judge_brain = "codex" if labor_owner != "codex" else "claude"
        deferred_until_brain_return = True

    if position_shifted and agy_ready and labor_owner != "antigravity":
        merge_owner = "antigravity"
    elif agy_ready:
        merge_owner = "antigravity"
    elif "codex" in active_brains:
        merge_owner = "codex"
    elif "claude" in active_brains:
        merge_owner = "claude"
    else:
        merge_owner = "antigravity"

    brain_packet_max_bytes = pacing.get(judge_brain, {}).get("max_packet_bytes", BRAIN_PACKET_MAX_BYTES)
    if position_shifted and agy_ready:
        continuity_mode = "DYNAMIC_POSITION_INVERTED"
    elif agy_ready and len(active_brains) == 2:
        continuity_mode = "DUAL_BRAIN_AGY_LABOR"
    elif agy_ready and len(active_brains) == 1:
        continuity_mode = "SINGLE_BRAIN_CONSERVATION_AGY_LABOR"
    elif agy_ready and not active_brains:
        continuity_mode = "ACTING_LABOR_DEFERRED_REVIEW"
    else:
        continuity_mode = "BRAIN_FALLBACK_NO_AGY"

    cat = benchmark_catalog if benchmark_catalog is not None else load_synced_benchmark_catalog(reference_date=reference_date)
    selected_models = {
        "spec_brain": select_model_by_perf_per_token(
            spec_brain,
            complexity="ultra_architecture" if is_keypoint else "standard_code",
            is_keypoint=is_keypoint,
            high_quota_pressure=pacing.get(spec_brain, {}).get("tier") == "KEYPOINT_VERDICT_ONLY",
            catalog=cat,
            reference_date=reference_date,
        ),
        "labor_owner": select_model_by_perf_per_token(
            labor_owner,
            complexity="complex_multi_file",
            is_keypoint=is_keypoint,
            high_quota_pressure=pacing.get(labor_owner, {}).get("tier") in ("KEYPOINT_VERDICT_ONLY", "LABOR_CONSERVE"),
            catalog=cat,
            reference_date=reference_date,
        ),
        "judge_brain": select_model_by_perf_per_token(
            judge_brain,
            complexity="complex_multi_file" if is_keypoint else "standard_code",
            is_keypoint=is_keypoint,
            high_quota_pressure=pacing.get(judge_brain, {}).get("tier") == "KEYPOINT_VERDICT_ONLY",
            catalog=cat,
            reference_date=reference_date,
        ),
    }

    return {
        "schema": "uaos-brain-labor-7d-schedule-v1",
        "policy_version": "v2-dynamic",
        "is_keypoint": bool(is_keypoint),
        "continuity_mode": continuity_mode,
        "position_shifted": position_shifted,
        "shift_reason": shift_reason,
        "labor_owner": labor_owner,
        "labor_pool": labor_pool,
        "spec_brain": spec_brain,
        "judge_brain": judge_brain,
        "merge_owner": merge_owner,
        "acting_brain_mode": acting_brain_mode,
        "requires_brain_return_review": acting_brain_mode,
        "deferred_until_brain_return": deferred_until_brain_return,
        "brain_packet_max_bytes": brain_packet_max_bytes,
        "pool_a_blocked": bool(pacing["antigravity"]["pool_a_blocked"]),
        "weighted_headroom": headroom,
        "pacing": pacing,
        "selected_models": selected_models,
        "daily_pace_target_pct": DAILY_PACE_TARGET_PCT,
        "paid_savings_status": "UNMEASURED",
    }


plan_dynamic_3tool_positions = plan_brain_labor_7d_schedule


def _pick_judge(
    author: str,
    *,
    is_keypoint: bool,
    active_tools: Sequence[str],
) -> str:
    if is_keypoint and "codex" in active_tools and author != "codex":
        return "codex"
    for cand in ("codex", "antigravity", "claude"):
        if cand in active_tools and cand != author:
            return cand
    for fallback in ("codex", "antigravity", "claude"):
        if fallback != author:
            return fallback
    return "codex"


def _has_cycle(units: Sequence[dict[str, Any]]) -> bool:
    deps_map = {u["unit_id"]: list(u.get("depends_on") or ()) for u in units}
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str) -> bool:
        if node in visited:
            return False
        if node in visiting:
            return True
        visiting.add(node)
        for nxt in deps_map.get(node, ()):
            if nxt in deps_map and dfs(nxt):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(dfs(uid) for uid in deps_map)


def build_gear_dag(
    spec: dict[str, Any],
    *,
    tool_states: dict[str, str],
    quota_snapshot: dict[str, Any] | None = None,
    existing_locked_files: Iterable[str] = (),
    max_slice_files: int = 3,
    routing_mode: str = "brain_labor",
    now: float | None = None,
) -> dict[str, Any]:
    """Decompose a grounded spec into interlocking, disjoint, non-self-judged 3-tool gears."""
    locked = {_norm(p) for p in existing_locked_files}
    raw_files = [_norm(p) for p in (spec.get("grounded_files") or ())]
    available_files = [p for p in raw_files if p not in locked]
    blocked_by_lock = [p for p in raw_files if p in locked]

    active_tools = [t for t in ("codex", "antigravity", "claude") if _tool_available(t, tool_states, quota_snapshot)]
    spec_text = " ".join(
        [str(spec.get("goal", "")), str(spec.get("problem_statement", "")), *available_files]
    ).lower()
    is_keypoint = any(kw in spec_text for kw in KEYPOINT_KEYWORDS)

    bl_schedule = (
        plan_brain_labor_7d_schedule(
            tool_states=tool_states,
            quota_snapshot=quota_snapshot,
            is_keypoint=is_keypoint,
            now=now,
        )
        if routing_mode == "brain_labor"
        else None
    )

    if bl_schedule is not None:
        spec_owner = bl_schedule["spec_brain"]
        spec_judge = _pick_judge(spec_owner, is_keypoint=is_keypoint, active_tools=active_tools)
        spec_unit: dict[str, Any] = {
            "unit_id": "STAGE_SPEC",
            "stage": "SPEC_AND_CONTRACT",
            "capability": "READ_ONLY",
            "owner": spec_owner,
            "judge": spec_judge,
            "role_tier": "BRAIN",
            "allow_files": [],
            "depends_on": [],
            "work_mode": "paid_core_and_ollama_draft",
        }
    else:
        spec_owner = "codex" if "codex" in active_tools else (active_tools[0] if active_tools else "antigravity")
        spec_judge = _pick_judge(spec_owner, is_keypoint=is_keypoint, active_tools=active_tools)
        spec_unit = {
            "unit_id": "STAGE_SPEC",
            "stage": "SPEC_AND_CONTRACT",
            "capability": "READ_ONLY",
            "owner": spec_owner,
            "judge": spec_judge,
            "allow_files": [],
            "depends_on": [],
            "work_mode": "paid_core_and_ollama_draft",
        }

    units: list[dict[str, Any]] = [spec_unit]

    slice_size = max(1, int(max_slice_files))
    chunks = [available_files[i : i + slice_size] for i in range(0, len(available_files), slice_size)] or [[]]
    impl_pool = [t for t in ("antigravity", "codex", "claude") if t in active_tools] or ["antigravity"]

    impl_ids: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        uid = f"STAGE_IMPL_{idx}"
        impl_ids.append(uid)
        if bl_schedule is not None:
            owner = bl_schedule["labor_owner"]
            judge = bl_schedule["judge_brain"]
            units.append(
                {
                    "unit_id": uid,
                    "stage": "IMPLEMENTATION_SLICE",
                    "capability": "SCOPED_WRITE",
                    "owner": owner,
                    "judge": judge,
                    "role_tier": "LABOR",
                    "labor_pool": bl_schedule["labor_pool"],
                    "brain_packet_max_bytes": bl_schedule["brain_packet_max_bytes"],
                    "deferred_until_brain_return": bl_schedule["deferred_until_brain_return"],
                    "allow_files": list(chunk),
                    "depends_on": ["STAGE_SPEC"],
                    "work_mode": "ollama_first_then_agy_pool_b_labor",
                }
            )
        else:
            owner = impl_pool[(idx - 1) % len(impl_pool)]
            judge = _pick_judge(owner, is_keypoint=is_keypoint, active_tools=active_tools)
            units.append(
                {
                    "unit_id": uid,
                    "stage": "IMPLEMENTATION_SLICE",
                    "capability": "SCOPED_WRITE",
                    "owner": owner,
                    "judge": judge,
                    "allow_files": list(chunk),
                    "depends_on": ["STAGE_SPEC"],
                    "work_mode": "ollama_first_then_apply",
                }
            )

    if bl_schedule is not None:
        verify_owner = bl_schedule["judge_brain"]
        verify_judge = _pick_judge(verify_owner, is_keypoint=is_keypoint, active_tools=active_tools)
        units.append(
            {
                "unit_id": "STAGE_VERIFY",
                "stage": "VACCINE_AND_REGRESSION",
                "capability": "READ_ONLY",
                "owner": verify_owner,
                "judge": verify_judge,
                "role_tier": "BRAIN_JUDGE",
                "compact_packet_max_bytes": bl_schedule["brain_packet_max_bytes"],
                "deferred_until_brain_return": bl_schedule["deferred_until_brain_return"],
                "allow_files": [],
                "depends_on": list(impl_ids),
                "work_mode": "deterministic_pytest_gate",
            }
        )
        merge_owner = bl_schedule["merge_owner"]
        merge_judge = _pick_judge(merge_owner, is_keypoint=True, active_tools=active_tools)
        units.append(
            {
                "unit_id": "STAGE_MERGE",
                "stage": "AUTONOMOUS_MERGE",
                "capability": "MERGE_ONLY",
                "owner": merge_owner,
                "judge": merge_judge,
                "role_tier": "LABOR_MERGE",
                "allow_files": [],
                "depends_on": ["STAGE_VERIFY"],
                "work_mode": "cross_tool_release_gate",
            }
        )
    else:
        verify_owner = _pick_judge(impl_pool[0], is_keypoint=is_keypoint, active_tools=active_tools)
        verify_judge = _pick_judge(verify_owner, is_keypoint=is_keypoint, active_tools=active_tools)
        units.append(
            {
                "unit_id": "STAGE_VERIFY",
                "stage": "VACCINE_AND_REGRESSION",
                "capability": "READ_ONLY",
                "owner": verify_owner,
                "judge": verify_judge,
                "allow_files": [],
                "depends_on": list(impl_ids),
                "work_mode": "deterministic_pytest_gate",
            }
        )

        merge_owner = "antigravity" if "antigravity" in active_tools else ("codex" if "codex" in active_tools else verify_judge)
        merge_judge = _pick_judge(merge_owner, is_keypoint=True, active_tools=active_tools)
        units.append(
            {
                "unit_id": "STAGE_MERGE",
                "stage": "AUTONOMOUS_MERGE",
                "capability": "MERGE_ONLY",
                "owner": merge_owner,
                "judge": merge_judge,
                "allow_files": [],
                "depends_on": ["STAGE_VERIFY"],
                "work_mode": "cross_tool_release_gate",
            }
        )

    out: dict[str, Any] = {
        "schema": "uaos-gear-dag-v1",
        "goal": spec.get("goal", ""),
        "mia_tier": (spec.get("mia_tier") or {}).get("tier", "MIA-Standard"),
        "is_keypoint": is_keypoint,
        "routing_mode": routing_mode,
        "active_tools": active_tools,
        "excluded_locked_files": blocked_by_lock,
        "cycle_free": not _has_cycle(units),
        "units": units,
    }
    if bl_schedule is not None:
        out["brain_labor_schedule"] = bl_schedule
    return out


def plan_ollama_helper_allocation(
    gear_plan: dict[str, Any],
    *,
    vram_gb: float = 6.0,
    installed_models: Sequence[str] = (),
    tool_states: dict[str, str] | None = None,
    quota_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Allocate 50% cellular Ollama / 30% Perf-per-Token Helper / 20% Paid Core."""
    safe_installed = [m for m in installed_models if ollama_vram_guard.is_safe_ollama_model_tag(m)]
    quarantined_tags = [m for m in installed_models if not ollama_vram_guard.is_safe_ollama_model_tag(m)]
    installed = set(safe_installed)
    states = dict(tool_states or {})

    def pick_model(preferred: Sequence[str], default: str) -> str:
        if not installed_models:
            return default
        if not installed:
            return default
        for name in preferred:
            if name in installed:
                return name
        return default

    embed_model = pick_model(("qwen3-embedding:0.6b",), "qwen3-embedding:0.6b")
    draft_model = pick_model(("qwen2.5-coder:3b", "qwen3.5:4b", "qwen2.5-coder:7b"), "qwen2.5-coder:3b")
    code_model = pick_model(("qwen2.5-coder:7b", "qwen3.5:4b"), "qwen2.5-coder:7b")

    safe_ctx = 8192 if float(vram_gb) <= 6.5 else 16384
    draft_cellular = ollama_vram_guard.build_cellular_ollama_options(draft_model, prompt_tokens=1500, vram_gb=vram_gb)
    code_cellular = ollama_vram_guard.build_cellular_ollama_options(code_model, prompt_tokens=1500, vram_gb=vram_gb)

    helpers = {
        "antigravity": {
            "model": "gemini-4-hydrogen",
            "complex_override": "gemini-4-orchestrator-neon",
            "cap_tokens": 12000,
            "available": _tool_available("antigravity", states, quota_snapshot),
        },
        "codex": {
            "model": "gpt-6-luna",
            "complex_override": "gpt-6.2-sol",
            "cap_tokens": 12000,
            "available": _tool_available("codex", states, quota_snapshot),
        },
        "claude": {
            "model": "claude-haiku-5-5",
            "complex_override": "claude-opus-5-5",
            "cap_tokens": 12000,
            "available": _tool_available("claude", states, quota_snapshot),
        },
    }
    active_helpers = [t for t, cfg in helpers.items() if cfg["available"]]

    assignments: list[dict[str, Any]] = []
    for unit in gear_plan.get("units") or ():
        stage = unit.get("stage")
        owner = str(unit.get("owner") or "antigravity")
        if stage == "SPEC_AND_CONTRACT":
            assignments.append(
                {
                    "unit_id": unit["unit_id"],
                    "deterministic_first": ["scan_repo_surface", "mia_triage"],
                    "ollama_model": draft_model,
                    "ollama_num_ctx": min(8192, safe_ctx, int(draft_cellular["options"]["num_ctx"])),
                    "ollama_cellular_options": draft_cellular,
                    "keep_alive": ollama_vram_guard.normalize_keep_alive("10m"),
                    "helper_tool": active_helpers[0] if active_helpers else owner,
                    "helper_model": helpers.get(active_helpers[0] if active_helpers else owner, {}).get("model"),
                }
            )
        elif stage == "IMPLEMENTATION_SLICE":
            helper_choice = owner if helpers.get(owner, {}).get("available") else (active_helpers[0] if active_helpers else owner)
            assignments.append(
                {
                    "unit_id": unit["unit_id"],
                    "deterministic_first": ["pilot manual lint", "input sha256 pin"],
                    "ollama_model": code_model,
                    "ollama_num_ctx": int(code_cellular["options"]["num_ctx"]),
                    "ollama_cellular_options": code_cellular,
                    "max_prompt_tokens": 10000,
                    "serial_gpu_lock": True,
                    "keep_alive": ollama_vram_guard.normalize_keep_alive("10m"),
                    "helper_tool": helper_choice,
                    "helper_model": helpers[helper_choice]["model"],
                    "complex_one_shot_model": helpers[helper_choice]["complex_override"],
                }
            )
        else:
            assignments.append(
                {
                    "unit_id": unit["unit_id"],
                    "deterministic_first": ["pytest fixed acceptance", "sha256 parity check"],
                    "ollama_model": embed_model if stage == "VACCINE_AND_REGRESSION" else None,
                    "helper_tool": active_helpers[0] if active_helpers else owner,
                    "helper_model": helpers.get(active_helpers[0] if active_helpers else owner, {}).get("model"),
                    "paid_core_role": "independent_non_author_judge",
                }
            )

    return {
        "schema": "uaos-resource-allocation-v1",
        "target_parallel_ratio": {"ollama_pct": 50.0, "helper_pct": 30.0, "paid_core_pct": 20.0},
        "vram_gb": float(vram_gb),
        "serial_gpu_lease": True,
        "ollama_tiers": {"embed": embed_model, "draft_json": draft_model, "code_slice": code_model},
        "quarantined_ollama_tags": quarantined_tags,
        "helper_pool": helpers,
        "active_helpers": active_helpers,
        "assignments": assignments,
        "paid_savings_status": "UNMEASURED",
    }


def diagnose_fullstack_health(project: Path, *, now: float | None = None) -> dict[str, Any]:
    """Read-only 0-token auditor detecting the 6 live UAOS-RSI operational blockers."""
    root = Path(project)
    moment = time.time() if now is None else float(now)
    blockers: list[dict[str, Any]] = []
    remedies: list[str] = []

    from v7_harness.coord import presence as presence_mod

    mismatches = presence_mod.audit_desk_split_brain(root)
    states = presence_mod.read_all(root, now=moment)
    unknown_tools = [t for t, info in states.items() if info.get("state") == "UNKNOWN"]
    if mismatches or unknown_tools:
        blockers.append(
            {
                "code": "PRESENCE_SPLIT_BRAIN",
                "mismatches": mismatches,
                "unknown_tools": unknown_tools,
            }
        )
        remedies.append("Sync unified_desks.json with user_desk_<tool>.json and honor execution_paused_until leases.")

    inbox = root / ".coord" / "mailbox" / "inbox"
    pending_count = 0
    wake_count = 0
    if inbox.is_dir():
        for entry in inbox.iterdir():
            if entry.suffix == ".json":
                pending_count += 1
                if entry.name.startswith("wake_"):
                    wake_count += 1
    if pending_count >= 500 or wake_count >= 10:
        blockers.append(
            {
                "code": "MAILBOX_BLOAT_AND_WAKE_STORM",
                "pending_inbox": pending_count,
                "wake_files": wake_count,
            }
        )
        remedies.append("Run deletion-free mailbox.compact_inbox() and deduplicate canonical sentinel wakes.")

    runs_path = root / ".coord" / "usage" / "runs.jsonl"
    ollama_errors = 0
    oversized_ollama = 0
    qwen35_failures = 0
    if runs_path.is_file():
        tail = runs_path.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]
        for line in tail:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("worker") not in ("ollama", "local"):
                continue
            if row.get("error_class") == "PROVIDER_ERROR" or row.get("outcome") in ("BLOCKED", "FAILED"):
                ollama_errors += 1
            if str(row.get("model") or "").startswith("qwen3.5") and row.get("outcome") in ("BLOCKED", "FAILED"):
                qwen35_failures += 1
            if int(row.get("input_tokens") or 0) > int(ollama_vram_guard.DEFAULT_NUM_CTX * 0.78):
                oversized_ollama += 1
    if ollama_errors > 0 or oversized_ollama > 0 or qwen35_failures > 0:
        blockers.append(
            {
                "code": "OLLAMA_PROVIDER_ERROR_RISK",
                "recent_errors": ollama_errors,
                "oversized_prompts": oversized_ollama,
                "qwen35_thinking_failures": qwen35_failures,
            }
        )
        remedies.append(
            "Enforce ollama_vram_guard cellular options (7b num_ctx<=4096, qwen3.5 think=False/temp=0)."
        )

    sched_path = root / ".coord" / "master_schedule.json"
    null_phases = 0
    total_phases = 0
    if sched_path.is_file():
        try:
            sched = json.loads(sched_path.read_text(encoding="utf-8"))
            phases = sched.get("phases") or []
            total_phases = len(phases)
            null_phases = sum(1 for p in phases if isinstance(p, dict) and p.get("status") is None)
        except (OSError, ValueError):
            pass
    if total_phases > 0 and null_phases > total_phases // 2:
        blockers.append(
            {
                "code": "SCHEDULE_ZOMBIE_LAG",
                "null_status_phases": null_phases,
                "total_phases": total_phases,
            }
        )
        remedies.append("Reconcile unstatused historical phases in master_schedule.json via schedule_reconcile.")

    work_dir = root / ".work"
    wt_count = sum(1 for p in work_dir.glob("wt_*") if p.is_dir()) if work_dir.is_dir() else 0
    if wt_count >= 5:
        blockers.append({"code": "STRANDED_WORKTREES", "worktree_count": wt_count})
        remedies.append("Close and merge verified Wave 1 worktrees cleanly before opening redundant branches.")

    ud_path = root / ".coord" / "presence" / "unified_desks.json"
    constrained: list[str] = []
    if ud_path.is_file():
        try:
            raw_ud = json.loads(ud_path.read_text(encoding="utf-8"))
            desks = raw_ud.get("desks") if isinstance(raw_ud, dict) else None
            if not isinstance(desks, dict):
                desks = {}
            for tool, info in desks.items():
                if not isinstance(info, dict):
                    continue
                q = info.get("quota")
                q = q if isinstance(q, dict) else {}
                rem7 = q.get("7d_remaining_pct")
                if info.get("execution_paused_until") or (isinstance(rem7, (int, float)) and not isinstance(rem7, bool) and rem7 <= 5.0):
                    constrained.append(tool)
        except (OSError, ValueError):
            pass
    if constrained:
        blockers.append({"code": "CLAUDE_OR_CODEX_QUOTA_CONSTRAINT", "tools": sorted(constrained)})
        remedies.append("Bypass paused/low-quota pools automatically and route helpers to active pools.")

    return {
        "ok": not blockers,
        "blockers": blockers,
        "remedies": remedies,
        "summary": {
            "blocker_count": len(blockers),
            "pending_inbox": pending_count,
            "wake_files": wake_count,
            "worktree_count": wt_count,
            "null_phases": null_phases,
        },
    }


def build_urgent_card_handshake(
    *,
    card_id: str,
    session_id: str,
    director_session: str,
    codex_session: str,
    disjoint_files: Sequence[str],
    user_approved: bool,
) -> dict[str, Any]:
    """Validate and emit non-hijacking urgent independent card handover metadata."""
    sid = str(session_id or "").strip()
    d_sid = str(director_session or "").strip()
    c_sid = str(codex_session or "").strip()
    if not user_approved:
        raise ValueError("USER_APPROVAL_REQUIRED: urgent card independence requires explicit user approval")
    if not sid or not d_sid or sid == d_sid:
        raise ValueError("DIRECTOR_HIJACK_FORBIDDEN: independent card session must differ from primary director")
    clean_files = [_norm(p) for p in disjoint_files if str(p).strip()]
    if not clean_files:
        raise ValueError("EMPTY_SCOPE: disjoint_files must not be empty")
    return {
        "schema": "uaos-urgent-card-handshake-v1",
        "card_id": card_id,
        "priority": "URGENT_P0",
        "independent_session_id": sid,
        "preserved_director_session": d_sid,
        "codex_director_session": c_sid,
        "disjoint_files": clean_files,
        "judge": "codex",
    }
