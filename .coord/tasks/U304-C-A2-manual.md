```contract
work_id: U304-C-A2
worker: apply
goal: Land the U304-C schedule planner with the measured-budget gate (Item 7), live driver, CLI and tests
inputs:
- v7_harness/cli.py sha256=c641257ec251a5a56e81ef9717b82861828b90f1932d21d9683b8dc3516b075f
allow:
- v7_harness/coord/schedule_planner.py
- v7_harness/cli.py
- tests/test_u304c_schedule_planner.py
- .coord/tasks/U304-C-schedule-planner.md
- .coord/results/U304-C.md
acceptance: python -m pytest tests/test_u304c_schedule_planner.py -q
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
apply_after: U304-C-L2
```

## Instructions for the worker

Apply the blocks exactly (U304-C bundle superseding U304-C-A1; apply_after U304-C-L2, the failed Ollama delegation of the live driver). In schedule_planner.py, classify() is the Ollama U304-C-L1 PASS output and paced_allowance() the Ollama U304-C-L3 PASS output.

===FILE: v7_harness/coord/schedule_planner.py===
"""U304-C: schedule-time model, effort and helper assignment, plus the live driver of the detailed schedule.

When a master phase or a detailed (sub) step is written, its process is estimated from the step text and the
measured ledger (`.coord/usage/runs.jsonl`): importance, design and implementation difficulty, expected size,
risk and lane. The estimate picks the main model (flagship only where importance AND difficulty are high), the
reasoning effort, the tool's one helper model and the helper effort. Every threshold carries its reason in
`THRESHOLDS`; design and citations: `.coord/tasks/U304-C-schedule-planner.md`.

The helper lineup and lane rules belong to `helper_thinking_router` (U304-B); this module only calls it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import statistics
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from v7_harness.coord.helper_thinking_router import (
    SUB_PROCESS_STAGES,
    get_official_tool_lineup,
    infer_lane_from_card_metadata,
    normalize_tool_name,
    select_optimal_helper_and_thinking,
)
from v7_harness.coord.hook_context import shared_desk

ASSIGNMENT_SCHEMA = "uaos-schedule-assignment-v1"
DRIVER_SCHEMA = "uaos-sub-schedule-driver-v1"

# Flagship vs cheaper main per tool (윤겸스 2026-11-04 item 4: Claude Opus 5.5, Antigravity Gemini 4 Argon,
# Codex GPT-6 Astra as the flagship examples). The standard main is the next model of the same family that the
# router already uses as a main (not as a helper), so a demotion never lands on the helper itself.
MAIN_MODEL_TIERS: dict[str, dict[str, str]] = {
    "codex": {"flagship": "gpt-6-astra", "standard": "gpt-6-sol"},
    "claude": {"flagship": "claude-opus-5-5", "standard": "claude-sonnet-5-5"},
    "antigravity": {"flagship": "gemini-4-argon", "standard": "gemini-3.1-pro"},
}

THRESHOLDS: dict[str, dict[str, Any]] = {
    "flagship": {
        "rule": "importance >= 2 and complexity >= 2",
        "why": "RouteLLM routes to the strong model only where the weak one is expected to fail; with no preference "
               "data the proxy is both axes at level 2 of 3. One high axis alone gets High effort on the cheaper main.",
    },
    "standard_high": {
        "rule": "importance >= 2 or complexity >= 2",
        "why": "Anthropic/OpenAI docs: high effort is for complex reasoning or quality-first work; one high axis "
               "qualifies, the model tier does not change.",
    },
    "mechanical": {
        "rule": "complexity == 0 and importance <= 1",
        "why": "Anthropic docs: low effort is for simple, high-volume work; an unimportant step with no design or "
               "size burden is that class.",
    },
    "stage_importance_offset": {
        "SP1_RESEARCH_DRAFT": -1,
        "SP5_MERGE_AND_RUNTIME": -1,
        "why": "research drafts and merges are cheap to redo and are re-checked by SP2 design audit and SP4 verdict.",
    },
    "multi_file_min": {
        "value": 4,
        "why": "a card of one module + its test + one CLI hook is 3 files and is one change; from 4 files the change "
               "spans modules (router `multi_file`).",
    },
    "size_bands": {
        "rule": "q25/q50/q75 of measured ledger tokens (input+output+cache_creation)",
        "why": "difficulty by size = which quartile of past measured work the step falls in; calibrated on own "
               "traffic as RouteLLM calibrates its threshold.",
        "fallback": (8000, 30000, 90000),
        "fallback_why": "used only with fewer than 4 measured rows: 8k = one U198 ~20-line slice prompt, "
                        "30k = a one-module card, 90k = the 3x yardstick region of a multi-module card.",
    },
    "helper_effort": {
        "rule": "Low if MECHANICAL or expected_tokens <= q25, else Medium; never High",
        "why": "a step inside the smallest measured quartile is one helper slice; High reasoning is the main "
               "model's job, a High helper would cost a main-model price at helper quality.",
    },
    "lane_prior_tokens": {
        "ARCH_DESIGN": 40000, "IMPL_CODE": 30000, "VERIFY_AUDIT": 15000, "RECOVERY_OPS": 20000, "MERGE_RELEASE": 5000,
        "why": "only with an empty ledger: each lane lands in the size band its stage typically has (merge small, "
               "design/impl one-module card); replaced by measured medians as soon as one row exists.",
    },
    "budget_freshness_s": {
        "value": 900,
        "why": "a schedule is written from the measured budget (윤겸스 2026-11-04 U304 item 7); a 5h window spent at "
               "full pace moves ~5% in 15 min, more than one median step, so an older snapshot can grant a flagship "
               "the window no longer holds. Older or missing -> fail closed, nothing written.",
    },
    "flagship_pace_share": {
        "antigravity": 0.5, "codex": 0.1, "claude": 0.1,
        "why": "share of a tool's paced headroom that flagship steps may take. Google AI Ultra gives ~5x the top-model "
               "usage of the $20 plans (윤겸스 2026-11-04), so Gemini 4 Argon High gets 5x the share and is the main "
               "heavy route; Opus 5.5 / GPT-6 Astra stay scarce: a tenth of the window, keypoints only.",
    },
    "budget_window_h": {
        "value": 5,
        "why": "paced headroom = min(5h remaining, weekly remaining / 5h windows left before the weekly reset), so "
               "the weekly pool lasts until its reset instead of being spent in the first windows.",
    },
}

BUDGET_KEYS: tuple[str, ...] = (
    "remaining_5h_tokens", "remaining_week_tokens", "reset_5h_at", "reset_week_at", "measured_at", "plan",
)


class BudgetUnavailable(ValueError):
    """No usable measured budget: schedule writing fails closed (U304 item 7)."""

KEYPOINT_WORDS: tuple[str, ...] = (
    "security", "authority", "evaluator", "gate", "schema", "canonical", "permission", "credential", "concurrency",
    "atomic", "keypoint", "권한", "보안", "평가기", "게이트", "정본", "동시성", "원자",
)
EMPHASIS_WORDS: tuple[str, ...] = ("top-emphasis", "emphasized", "p1", "강조", "핵심", "codex_exclusive")
DESIGN_WORDS: tuple[str, ...] = (
    "architecture", "design", "concurrency", "atomic", "algorithm", "estimator", "router", "routing", "scheduler",
    "protocol", "state machine", "dag", "설계", "아키텍처", "동시성", "알고리즘", "추론", "스케줄", "로직",
)
RISK_WORDS: tuple[str, ...] = (
    "delete", "migration", "runtime", "reinstall", "deploy", "force", "삭제", "재설치", "배포", "이전",
)

_CARD_RE = re.compile(r"^(U\d+)", re.IGNORECASE)
_STEP_STATES = ("PLANNED", "READY", "ACTIVE", "REVIEW", "DONE", "BLOCKED")


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def card_family(work_id: str) -> str:
    """`U304-C`, `U304-L1`, `u304c` -> `U304` (the card family a ledger row belongs to)."""
    m = _CARD_RE.match(str(work_id or "").strip())
    return m.group(1).upper() if m else ""


def _hits(text: str, words: tuple[str, ...]) -> int:
    low = text.lower()
    return sum(1 for w in words if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low))


def _row_tokens(row: dict[str, Any]) -> int:
    total = 0
    for key in ("input_tokens", "output_tokens", "cache_creation_input_tokens"):
        val = row.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            total += int(val)
    return total


def load_history(desk: Path, master_phases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Measured ledger stats: band edges, per-lane and per-family medians of tokens and wall time."""
    lanes_by_family: dict[str, str] = {}
    for p in master_phases or []:
        fam = card_family(str(p.get("phase_id") or ""))
        if fam and fam not in lanes_by_family:
            lane = str(p.get("lane") or "") or infer_lane_from_card_metadata(
                title=str(p.get("title") or ""), purpose=str(p.get("note") or ""), state=str(p.get("state") or "")
            )
            lanes_by_family[fam] = lane
    rows: list[dict[str, Any]] = []
    path = Path(desk) / ".coord" / "usage" / "runs.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        tokens = _row_tokens(row)
        if tokens <= 0:
            continue
        fam = card_family(str(row.get("work_id") or ""))
        wall = row.get("wall_time_s")
        rows.append({
            "family": fam,
            "lane": lanes_by_family.get(fam, ""),
            "tokens": tokens,
            "wall_s": float(wall) if isinstance(wall, (int, float)) and not isinstance(wall, bool) else None,
        })
    return summarize_history(rows)


def summarize_history(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tokens = sorted(r["tokens"] for r in rows)
    if len(tokens) >= 4:
        q = statistics.quantiles(tokens, n=4)
        edges = (int(q[0]), int(q[1]), int(q[2]))
        edge_source = "measured"
    else:
        edges = tuple(THRESHOLDS["size_bands"]["fallback"])
        edge_source = "fallback"

    def _group(key: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for name in sorted({r[key] for r in rows if r[key]}):
            sel = [r for r in rows if r[key] == name]
            walls = [r["wall_s"] for r in sel if r["wall_s"] is not None]
            out[name] = {
                "n": len(sel),
                "median_tokens": int(statistics.median(r["tokens"] for r in sel)),
                "median_wall_s": round(statistics.median(walls), 1) if walls else None,
            }
        return out

    return {"rows": len(rows), "band_edges": edges, "band_source": edge_source,
            "by_lane": _group("lane"), "by_family": _group("family")}


def _size_band(tokens: int, edges: tuple[int, int, int]) -> int:
    return sum(1 for e in edges if tokens > e)


def estimate_step(
    *,
    text: str,
    stage: str = "",
    lane: str = "",
    card_id: str = "",
    files: int = 0,
    keypoint: bool = False,
    history: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Deterministic process estimate of one step; every component is returned with its source."""
    history = history or summarize_history([])
    stage = str(stage or "").upper()
    lane = lane or infer_lane_from_card_metadata(title=text, purpose=text, sub_stage=stage)
    kp_hits = _hits(text, KEYPOINT_WORDS)
    emph = keypoint or _hits(text, EMPHASIS_WORDS) > 0
    importance = 1 + (1 if kp_hits else 0) + (1 if emph else 0)
    importance += int(THRESHOLDS["stage_importance_offset"].get(stage, 0))
    importance = max(0, min(3, importance))

    design = min(3, _hits(text, DESIGN_WORDS) + (1 if lane == "ARCH_DESIGN" else 0))

    fam = card_family(card_id)
    if fam and fam in history["by_family"]:
        expected = history["by_family"][fam]["median_tokens"]
        size_source = f"ledger:family:{fam}:n={history['by_family'][fam]['n']}"
    elif lane in history["by_lane"]:
        expected = history["by_lane"][lane]["median_tokens"]
        size_source = f"ledger:lane:{lane}:n={history['by_lane'][lane]['n']}"
    else:
        expected = int(THRESHOLDS["lane_prior_tokens"].get(lane, 30000))
        size_source = f"prior:{lane}"
    multi_file = files >= int(THRESHOLDS["multi_file_min"]["value"])
    impl = min(3, _size_band(expected, history["band_edges"]) + (1 if multi_file else 0))
    risk = _hits(text, RISK_WORDS)

    if stage == "SP1_RESEARCH_DRAFT":
        complexity = min(1, design)
    elif stage == "SP2_MIA_DESIGN_AUDIT":
        complexity = design
    elif stage == "SP3_CODE_EXECUTION":
        complexity = impl
    elif stage == "SP4_INDEPENDENT_VERIFY":
        complexity = max(design, impl)
    elif stage == "SP5_MERGE_AND_RUNTIME":
        complexity = 1 if risk else 0
    else:
        complexity = max(design, impl)

    return {
        "lane": lane,
        "stage": stage or "CARD_LEVEL",
        "importance": importance,
        "design_difficulty": design,
        "impl_difficulty": impl,
        "complexity": complexity,
        "expected_tokens": int(expected),
        "size_source": size_source,
        "band_edges": list(history["band_edges"]),
        "band_source": history["band_source"],
        "files": int(files),
        "multi_file": multi_file,
        "risk_hits": risk,
        "keypoint_hits": kp_hits,
        "emphasis": bool(emph),
        "declared_keypoint": bool(keypoint),
    }


def classify(estimate: dict[str, Any], *, exhaustion_risk: str = "SAFE") -> dict[str, Any]:
    imp = int(estimate["importance"])
    cx = int(estimate["complexity"])
    if imp >= 2 and cx >= 2:
        tier = "FLAGSHIP"
        effort = "High"
        rule_key = "flagship"
    elif imp >= 2 or cx >= 2:
        tier = "STANDARD_HIGH"
        effort = "High"
        rule_key = "standard_high"
    elif cx == 0 and imp <= 1:
        tier = "MECHANICAL"
        effort = "Low"
        rule_key = "mechanical"
    else:
        tier = "STANDARD_MEDIUM"
        effort = "Medium"
        rule_key = "standard_medium"

    if tier == "FLAGSHIP" and str(exhaustion_risk or "").upper() == "IMMINENT_EXHAUSTION":
        tier = "STANDARD_HIGH"
        demoted = True
    else:
        demoted = False

    reason = THRESHOLDS.get(rule_key, {}).get("rule", "otherwise: one axis at 1, none at 2 -> balanced medium effort")
    return {
        "tier": tier,
        "effort": effort,
        "rule": reason,
        "demoted_for_exhaustion": demoted,
        "score": round((imp / 3) * (cx / 3), 3)
    }


def _ts(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def validate_budget(budget: Any, *, now: float | None = None) -> dict[str, dict[str, Any]]:
    """Measured budget snapshot per tool, or BudgetUnavailable (missing, partial, unparseable or stale)."""
    now = time.time() if now is None else now
    if not isinstance(budget, dict) or not budget:
        raise BudgetUnavailable("no measured budget snapshot; schedule writing fails closed")
    limit = int(THRESHOLDS["budget_freshness_s"]["value"])
    out: dict[str, dict[str, Any]] = {}
    for tool in MAIN_MODEL_TIERS:
        entry = budget.get(tool)
        missing = [k for k in BUDGET_KEYS if not isinstance(entry, dict) or entry.get(k) is None]
        if missing:
            raise BudgetUnavailable(f"budget for {tool} lacks {missing}")
        measured, r5, rw = (_ts(entry[k]) for k in ("measured_at", "reset_5h_at", "reset_week_at"))
        if measured is None or r5 is None or rw is None:
            raise BudgetUnavailable(f"budget for {tool} has an unparseable timestamp")
        if now - measured > limit:
            raise BudgetUnavailable(f"budget for {tool} is {int(now - measured)}s old (limit {limit}s)")
        if rw <= now:
            raise BudgetUnavailable(f"budget for {tool}: weekly reset passed since it was measured")
        out[tool] = {**entry, "_measured": measured, "_reset_5h": r5, "_reset_week": rw}
    return out


def paced_allowance(budget: dict[str, dict[str, Any]], *, now: float | None = None) -> dict[str, dict[str, Any]]:
    """Flagship tokens each tool may still grant: paced headroom x flagship share (THRESHOLDS)."""
    now = time.time() if now is None else now
    window_s = float(THRESHOLDS["budget_window_h"]["value"]) * 3600
    out: dict[str, dict[str, Any]] = {}
    for tool, entry in budget.items():
        windows_left = max(1.0, (entry["_reset_week"] - now) / window_s)
        weekly_paced = max(0, int(entry["remaining_week_tokens"])) / windows_left
        # A passed 5h reset means the window refilled after the measurement; only the weekly pace binds then.
        five_h = None if entry["_reset_5h"] <= now else max(0, int(entry["remaining_5h_tokens"]))
        paced = int(weekly_paced if five_h is None else min(five_h, weekly_paced))
        share = float(THRESHOLDS["flagship_pace_share"][tool])
        out[tool] = {"paced_tokens": paced, "share": share, "flagship_tokens_left": int(paced * share), "plan": entry["plan"], "measured_at": entry["measured_at"]}
    return out


def assign_step(
    tool: str,
    estimate: dict[str, Any],
    *,
    card_id: str = "",
    role: str = "implementer",
    exhaustion_risk: str = "SAFE",
    utilization_5h_pct: float = 0.0,
    allowance: dict[str, dict[str, Any]] | None = None,
    no_reroute: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Main model, effort, helper and helper effort for one estimated step, with its rationale.

    With `allowance` (paced_allowance) a FLAGSHIP step is budget-routed: Antigravity steps take Gemini 4 Argon
    High while its paced share lasts; Codex/Claude flagships only for declared keypoints within their own share;
    any other heavy step goes to Antigravity Argon High when it fits and `antigravity` is not in `no_reroute`
    (the step's judge), else stays on its tool at STANDARD_HIGH. Each grant spends its expected tokens.
    """
    norm = normalize_tool_name(tool)
    origin = norm
    cls = classify(estimate, exhaustion_risk=exhaustion_risk)
    budget_note = ""
    if cls["tier"] == "FLAGSHIP" and allowance is not None:
        need = int(estimate["expected_tokens"])

        def _fits(t: str) -> bool:
            return t in allowance and int(allowance[t]["flagship_tokens_left"]) >= need

        if (norm == "antigravity" or estimate.get("declared_keypoint")) and _fits(norm):
            grant = norm
        elif norm != "antigravity" and "antigravity" not in no_reroute and _fits("antigravity"):
            grant = "antigravity"
        else:
            grant = None
        if grant is None:
            cls = {**cls, "tier": "STANDARD_HIGH"}
            budget_note = "; flagship withheld (no paced budget share fits)"
        else:
            allowance[grant]["flagship_tokens_left"] = int(allowance[grant]["flagship_tokens_left"]) - need
            norm = grant
            budget_note = (f"; flagship from {grant} paced share ({allowance[grant]['flagship_tokens_left']} tok left)"
                           + (f", rerouted from {origin}" if grant != origin else ""))
    lineup = get_official_tool_lineup(norm)
    router = select_optimal_helper_and_thinking(
        norm,
        card=card_id,
        role=role,
        lane_id=estimate["lane"],
        sub_stage="" if estimate["stage"] == "CARD_LEVEL" else estimate["stage"],
        is_keypoint=cls["tier"] == "FLAGSHIP",
        utilization_5h_pct=utilization_5h_pct,
        exhaustion_risk=exhaustion_risk,
        changed_lines=0,
        multi_file=bool(estimate["multi_file"]),
    )
    tier_key = "flagship" if cls["tier"] == "FLAGSHIP" else "standard"
    main = MAIN_MODEL_TIERS[norm][tier_key]
    model_note = f"{tier_key} main of {norm}"
    if main not in tuple(lineup.get("all_reasoning_models") or ()):
        main = str(router["designated_reasoning_model"])
        model_note = f"{tier_key} model absent from lineup; router main kept"
    helper = str(lineup.get("primary_helper_model") or router["designated_helper_model"])
    small = int(estimate["expected_tokens"]) <= int(estimate["band_edges"][0])
    helper_effort = "Low" if (cls["tier"] == "MECHANICAL" or small) else "Medium"
    display = lineup.get("model_display_names") or {}
    rationale = (
        f"importance={estimate['importance']} complexity={estimate['complexity']} "
        f"(design={estimate['design_difficulty']} impl={estimate['impl_difficulty']}) -> {cls['tier']} [{cls['rule']}]; "
        f"size {estimate['expected_tokens']} tok from {estimate['size_source']}; {model_note}; "
        f"helper {'one slice' if small else 'multi-slice'} -> {helper_effort}"
        + ("; flagship demoted (IMMINENT_EXHAUSTION)" if cls["demoted_for_exhaustion"] else "")
        + budget_note
    )
    return {
        "schema": ASSIGNMENT_SCHEMA,
        "tool": norm,
        "rerouted_from": origin if norm != origin else None,
        "budget_routed": allowance is not None,
        "role": role,
        "tier": cls["tier"],
        "score": cls["score"],
        "main_model": main,
        "main_model_display": display.get(main, main),
        "main_effort": cls["effort"],
        "main_effort_param": {str(lineup.get("thinking_param_name") or "effort"): cls["effort"].lower()},
        "helper_model": helper,
        "helper_model_display": display.get(helper, helper),
        "helper_effort": helper_effort,
        "calculator": f"ollama:{lineup.get('calculator_model', 'qwen2.5-coder:7b')}",
        "ollama_cli_task": router["ollama_cli_task"],
        "estimate": estimate,
        "rationale": rationale,
        "router_baseline": {
            "reasoning_model": router["designated_reasoning_model"],
            "reasoning_thinking_level": router["reasoning_thinking_level"],
            "helper_model": router["designated_helper_model"],
            "helper_thinking_level": router["helper_thinking_level"],
        },
    }


# ---------------------------------------------------------------------------------------------------------------
# Card table parsing (the schedule is "written" from a card manual's `## Cards` table)


def parse_card_table(md_text: str) -> list[dict[str, Any]]:
    """Rows of a `| Card | Item | Lane | Author | Judge | Allowed files |` table."""
    cards: list[dict[str, Any]] = []
    header: list[str] | None = None
    for line in md_text.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            header = None  # a table ends at the first non-table line
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            low = [c.lower() for c in cells]
            if low and low[0] == "card":
                header = low
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(header, cells))
        head = row.get("card", "")
        m = re.match(r"(U\d+(?:-[A-Z0-9]+)?)\s*(.*)", head)
        if not m:
            continue
        author_cell = row.get("author (claude session)", row.get("author", ""))
        judge_cell = row.get("judge", "")
        allowed = row.get("allowed files", "")
        cards.append({
            "card_id": m.group(1),
            "title": m.group(2).strip() or m.group(1),
            "item": row.get("item", ""),
            "lane": row.get("lane", "").split("→")[-1].strip().upper(),
            "lane_raw": row.get("lane", ""),
            "author": _first_tool(author_cell),
            "judge": _first_tool(judge_cell),
            "files": len(re.findall(r"`[^`]+`", allowed)),
            "text": " ".join(cells),
        })
    return cards


def _first_tool(cell: str) -> str:
    low = cell.lower()
    for name in ("antigravity", "codex", "claude"):
        if name in low:
            return name
    return ""


# ---------------------------------------------------------------------------------------------------------------
# Persistence: atomic writes under one lock, backup before overwrite


@contextmanager
def _locked(desk: Path, timeout_s: float = 30.0) -> Iterator[None]:
    lock = Path(desk) / ".coord" / "schedule_planner.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                # A lock older than the timeout is a crashed writer's; one writer at a time still holds.
                if time.time() - lock.stat().st_mtime > timeout_s:
                    lock.unlink()
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"schedule planner lock busy: {lock}")
            time.sleep(0.02)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _backup(desk: Path, path: Path) -> None:
    if not path.is_file():
        return
    day = time.strftime("%Y%m%d", time.localtime())
    dst_dir = Path(desk) / ".work" / f"backup_{day}" / "u304c"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / path.name
    if not dst.exists():
        shutil.copy2(path, dst)


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{time.time_ns()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # Windows: a reader holding the file blocks replace for a moment.
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def _paths(desk: Path) -> tuple[Path, Path]:
    return desk / ".coord" / "master_schedule.json", desk / ".coord" / "sub_process_schedule.json"


# ---------------------------------------------------------------------------------------------------------------
# Detailed (sub) schedule: plan + live driver


def _stage_tool(stage: str, author: str, judge: str) -> tuple[str, str]:
    if stage == "SP4_INDEPENDENT_VERIFY":
        return judge, "reviewer"
    if stage == "SP5_MERGE_AND_RUNTIME":
        # Merge priority 1 Antigravity, 2 Codex (UAOS card loop); never the author's own merge when avoidable.
        return ("antigravity" if author != "antigravity" else "codex"), "merger"
    return author, "implementer"


def _new_card_steps(card: dict[str, Any]) -> list[dict[str, Any]]:
    steps = []
    prev = ""
    for idx, stage in enumerate(SUB_PROCESS_STAGES, start=1):
        sid = f"{card['card_id']}:{stage}"
        steps.append({"sub_id": sid, "step_index": idx, "stage": stage, "state": "READY" if idx == 1 else "PLANNED",
                      "depends_on": [prev] if prev else []})
        prev = sid
    return steps


def _import_capacity_card(c: dict[str, Any]) -> dict[str, Any]:
    pid = str(c.get("phase_id") or "")
    author = normalize_tool_name(str(c.get("assigned_executor") or "antigravity"))
    judge = normalize_tool_name(str(c.get("assigned_verifier") or ("claude" if author != "claude" else "antigravity")))
    steps = []
    for sp in c.get("sub_processes") or []:
        if not isinstance(sp, dict):
            continue
        sid = str(sp.get("sub_id") or "")
        stage = sid.split(":", 1)[1] if ":" in sid else ""
        if stage not in SUB_PROCESS_STAGES:
            continue
        steps.append({"sub_id": sid, "step_index": int(sp.get("step_index") or len(steps) + 1), "stage": stage,
                      "state": str(sp.get("state") or "PLANNED").upper(),
                      "depends_on": list(sp.get("depends_on") or [])})
    return {"card_id": pid, "title": pid, "lane": "", "author": author, "judge": judge, "files": 0,
            "text": " ".join(str(sp.get("stage_name") or "") for sp in c.get("sub_processes") or [] if isinstance(sp, dict)),
            "source": "capacity_planner:card_sub_schedules", "steps": steps}


def _master_phase_text(master: dict[str, Any]) -> dict[str, str]:
    out = {}
    for p in master.get("phases") or []:
        if isinstance(p, dict):
            pid = str(p.get("phase_id") or "")
            out[pid] = f"{p.get('title') or ''} {p.get('note') or ''} {p.get('lane') or ''}"
    return out


def _assign_card(card: dict[str, Any], history: dict[str, Any], engines: dict[str, Any] | None,
                 keypoints: set[str], allowance: dict[str, dict[str, Any]]) -> None:
    def _risk(t: str) -> str:
        pred = (((engines or {}).get(t) or {}).get("predictive_exhaustion")) or {}
        return str(pred.get("exhaustion_risk") or "SAFE")

    for step in card["steps"]:
        tool, role = _stage_tool(step["stage"], card["author"], card["judge"])
        lane = infer_lane_from_card_metadata(sub_stage=step["stage"])
        est = estimate_step(text=f"{card.get('title', '')} {card.get('text', '')}", stage=step["stage"], lane=lane,
                            card_id=card["card_id"], files=int(card.get("files") or 0),
                            keypoint=card["card_id"] in keypoints, history=history)
        # author != judge: an author stage is never rerouted to the card's judge, the verdict never to its author.
        other = card["author"] if role == "reviewer" else card["judge"]
        step["assignment"] = assign_step(tool, est, card_id=card["card_id"], role=role, exhaustion_risk=_risk(tool),
                                         allowance=allowance,
                                         no_reroute=(normalize_tool_name(other),) if other else ())
        step["acting_tool"] = step["assignment"]["tool"]
        step["role"] = role


def _sync_master(master: dict[str, Any], driver: dict[str, Any]) -> None:
    by_id = {str(p.get("phase_id") or ""): p for p in master.get("phases") or [] if isinstance(p, dict)}
    for cid, card in driver["cards"].items():
        phase = by_id.get(cid)
        if phase is None:
            continue
        done = sum(1 for s in card["steps"] if s["state"] == "DONE")
        active = next((s["sub_id"] for s in card["steps"] if s["state"] == "ACTIVE"), None)
        phase["sub_progress"] = f"{done}/{len(card['steps'])}"
        phase["current_sub_step"] = active


def _write_both(desk: Path, master: dict[str, Any], driver: dict[str, Any]) -> None:
    master_path, sub_path = _paths(desk)
    driver["updated_at"] = _now_iso()
    master["sub_schedule_driver"] = driver
    _sync_master(master, driver)
    sub = _read_json(sub_path)
    sub.setdefault("schema", "uaos-sub-process-schedule-v1")
    sub["live_driver"] = driver
    for c in sub.get("card_sub_schedules") or []:
        if not isinstance(c, dict):
            continue
        dcard = driver["cards"].get(str(c.get("phase_id") or ""))
        if not dcard:
            continue
        by_sid = {s["sub_id"]: s for s in dcard["steps"]}
        for sp in c.get("sub_processes") or []:
            if isinstance(sp, dict) and sp.get("sub_id") in by_sid:
                sp["u304c_assignment"] = by_sid[sp["sub_id"]].get("assignment")
                sp["state"] = by_sid[sp["sub_id"]]["state"]
    for path in (master_path, sub_path):
        _backup(desk, path)
    _atomic_write(master_path, master)
    _atomic_write(sub_path, sub)


def plan_sub(
    project: str | Path,
    *,
    card_file: str | Path | None = None,
    engines: dict[str, Any] | None = None,
    keypoints: list[str] | tuple[str, ...] = (),
    dry_run: bool = False,
    budget: dict[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Create/refresh the live detailed schedule and assign model/effort/helper to every step.

    `budget` (U304-D budget_snapshot shape) is required: missing or stale -> BudgetUnavailable, nothing written.
    """
    allowance = paced_allowance(validate_budget(budget, now=now), now=now)
    desk = shared_desk(Path(project))
    master_path, sub_path = _paths(desk)
    with _locked(desk):
        master = _read_json(master_path)
        phases = [p for p in master.get("phases") or [] if isinstance(p, dict)]
        history = load_history(desk, phases)
        driver = master.get("sub_schedule_driver")
        if not isinstance(driver, dict) or driver.get("schema") != DRIVER_SCHEMA:
            driver = {"schema": DRIVER_SCHEMA, "created_at": _now_iso(), "cards": {}}
        texts = _master_phase_text(master)
        for c in _read_json(sub_path).get("card_sub_schedules") or []:
            if isinstance(c, dict) and c.get("phase_id") and str(c["phase_id"]) not in driver["cards"]:
                imported = _import_capacity_card(c)
                imported["text"] = f"{texts.get(imported['card_id'], '')} {imported['text']}"
                driver["cards"][imported["card_id"]] = imported
        if card_file:
            text = Path(card_file).read_text(encoding="utf-8")
            for row in parse_card_table(text):
                if not row["author"]:
                    continue  # review-only rows (no author session) have no own detailed schedule
                existing = driver["cards"].get(row["card_id"])
                card = {**row, "judge": row["judge"] or ("antigravity" if row["author"] != "antigravity" else "claude"),
                        "source": str(card_file)}
                card["steps"] = existing["steps"] if existing else _new_card_steps(row)
                driver["cards"][row["card_id"]] = card
        # Keypoints declared when the schedule is written are kept, so a later re-plan still sees them.
        declared = set(driver.get("keypoints") or []) | {str(k) for k in keypoints}
        driver["keypoints"] = sorted(declared)
        start = {t: a["flagship_tokens_left"] for t, a in allowance.items()}
        for card in driver["cards"].values():
            _assign_card(card, history, engines, declared, allowance)
        driver["budget"] = _budget_record(allowance, start)
        if not dry_run:
            _write_both(desk, master, driver)
    return {"ok": True, "desk": str(desk), "dry_run": dry_run, "history": {k: history[k] for k in ("rows", "band_edges", "band_source")},
            "budget": driver["budget"],
            "cards": {cid: [_step_line(s) for s in c["steps"]] for cid, c in driver["cards"].items()}}


def _budget_record(allowance: dict[str, dict[str, Any]], start: dict[str, int]) -> dict[str, Any]:
    return {t: {"plan": a["plan"], "measured_at": a["measured_at"], "paced_tokens": a["paced_tokens"],
                "share": a["share"], "flagship_tokens_granted": int(start[t]) - int(a["flagship_tokens_left"]),
                "flagship_tokens_left": a["flagship_tokens_left"]} for t, a in allowance.items()}


def _step_line(step: dict[str, Any]) -> dict[str, Any]:
    a = step.get("assignment") or {}
    return {"sub_id": step["sub_id"], "state": step["state"], "tool": step.get("acting_tool"), "tier": a.get("tier"),
            "main": a.get("main_model"), "effort": a.get("main_effort"), "helper": a.get("helper_model"),
            "helper_effort": a.get("helper_effort")}


def advance_sub(
    project: str | Path,
    *,
    card: str,
    step: str | None = None,
    to: str = "DONE",
) -> dict[str, Any]:
    """Live driver: set one step's state (default: close the ACTIVE step) and open the next ready step."""
    to = str(to or "DONE").upper()
    if to not in _STEP_STATES:
        raise ValueError(f"unknown state {to}; allowed {_STEP_STATES}")
    desk = shared_desk(Path(project))
    master_path, _ = _paths(desk)
    with _locked(desk):
        master = _read_json(master_path)
        driver = master.get("sub_schedule_driver")
        if not isinstance(driver, dict) or card not in (driver.get("cards") or {}):
            raise KeyError(f"card {card} is not in the live sub schedule; run `coord schedule --sub plan` first")
        steps = driver["cards"][card]["steps"]
        if step:
            sid = step if ":" in step else f"{card}:{step}"
            target = next((s for s in steps if s["sub_id"] == sid), None)
        else:
            target = next((s for s in steps if s["state"] == "ACTIVE"), None) or next(
                (s for s in steps if s["state"] == "READY"), None)
            if target is not None and target["state"] == "READY" and to == "DONE":
                to = "ACTIVE"  # nothing running yet: advancing starts the first ready step
        if target is None:
            raise KeyError(f"no step to advance in {card}")
        target["state"] = to
        target[f"{to.lower()}_at"] = _now_iso()
        opened = None
        done = {s["sub_id"] for s in steps if s["state"] == "DONE"}
        if not any(s["state"] == "ACTIVE" for s in steps):
            for s in steps:
                if s["state"] in ("PLANNED", "READY") and all(d in done for d in s.get("depends_on") or []):
                    s["state"] = "ACTIVE"
                    s["active_at"] = _now_iso()
                    opened = s["sub_id"]
                    break
        for s in steps:
            if s["state"] == "PLANNED" and all(d in done for d in s.get("depends_on") or []):
                s["state"] = "READY"
        _write_both(desk, master, driver)
    return {"ok": True, "card": card, "changed": target["sub_id"], "state": to, "opened": opened,
            "steps": [_step_line(s) for s in steps]}


def show_sub(project: str | Path) -> dict[str, Any]:
    desk = shared_desk(Path(project))
    driver = _read_json(_paths(desk)[0]).get("sub_schedule_driver") or {}
    return {"ok": True, "updated_at": driver.get("updated_at"),
            "cards": {cid: [_step_line(s) for s in c["steps"]] for cid, c in (driver.get("cards") or {}).items()}}


# ---------------------------------------------------------------------------------------------------------------
# Master schedule: assignment per non-DONE phase


def plan_master(
    project: str | Path,
    *,
    card_file: str | Path | None = None,
    engines: dict[str, Any] | None = None,
    keypoints: list[str] | tuple[str, ...] = (),
    dry_run: bool = False,
    budget: dict[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    allowance = paced_allowance(validate_budget(budget, now=now), now=now)
    start = {t: a["flagship_tokens_left"] for t, a in allowance.items()}
    desk = shared_desk(Path(project))
    master_path, _ = _paths(desk)

    def _risk(t: str) -> str:
        pred = (((engines or {}).get(t) or {}).get("predictive_exhaustion")) or {}
        return str(pred.get("exhaustion_risk") or "SAFE")

    with _locked(desk):
        master = _read_json(master_path)
        master.setdefault("phases", [])
        phases = [p for p in master["phases"] if isinstance(p, dict)]
        added = []
        if card_file:
            known = {str(p.get("phase_id") or "") for p in phases}
            for row in parse_card_table(Path(card_file).read_text(encoding="utf-8")):
                if row["card_id"] in known:
                    continue
                owner = row["author"] or row["judge"] or "claude"
                phase = {"phase_id": row["card_id"], "title": row["title"], "owner_tool": owner,
                         "author_tool": row["author"] or owner, "judge": row["judge"], "reviewer": row["judge"],
                         "lane": row["lane"], "state": "READY", "depends_on": [], "card": str(card_file),
                         "files": row["files"], "note": f"U304-C schedule planner from card table: {row['item']}"}
                master["phases"].append(phase)
                phases.append(phase)
                added.append(row["card_id"])
        history = load_history(desk, phases)
        out = []
        for p in phases:
            if str(p.get("state") or "").upper() == "DONE":
                continue
            pid = str(p.get("phase_id") or "")
            owner = normalize_tool_name(str(p.get("owner_tool") or p.get("owner") or "antigravity"))
            text = f"{p.get('title') or ''} {p.get('note') or ''}"
            lane = str(p.get("lane") or "").upper()
            est = estimate_step(text=text, lane=lane if lane in ("IMPL_CODE", "VERIFY_AUDIT", "ARCH_DESIGN",
                                                                 "MERGE_RELEASE", "RECOVERY_OPS") else "",
                                card_id=pid, files=int(p.get("files") or 0),
                                keypoint=bool(p.get("keypoint") or p.get("codex_exclusive") or pid in keypoints),
                                history=history)
            judge = str(p.get("judge") or p.get("reviewer") or "")
            p["model_assignment"] = assign_step(owner, est, card_id=pid, exhaustion_risk=_risk(owner),
                                                allowance=allowance,
                                                no_reroute=(normalize_tool_name(judge),) if judge else ())
            out.append({"phase_id": pid, **{k: p["model_assignment"][k] for k in
                                            ("tool", "tier", "main_model", "main_effort", "helper_model", "helper_effort")}})
        master["schedule_budget"] = _budget_record(allowance, start)
        if not dry_run:
            _backup(desk, master_path)
            master["updated_at"] = _now_iso()
            _atomic_write(master_path, master)
    return {"ok": True, "desk": str(desk), "dry_run": dry_run, "added_phases": added,
            "budget": master["schedule_budget"], "phases": out}


def show_master(project: str | Path) -> dict[str, Any]:
    """Assignments already written on the master phases (no re-plan, so no budget needed)."""
    master = _read_json(_paths(shared_desk(Path(project)))[0])
    phases = [p for p in master.get("phases") or [] if isinstance(p, dict) and p.get("model_assignment")]
    return {"ok": True, "budget": master.get("schedule_budget"),
            "phases": [{"phase_id": p.get("phase_id"), "state": p.get("state"),
                        **{k: p["model_assignment"].get(k) for k in
                           ("tool", "tier", "main_model", "main_effort", "helper_model", "helper_effort")}}
                       for p in phases]}


ADVANCE_ORDER = ("PLANNED", "READY", "ACTIVE", "REVIEW", "DONE")


def advance_master(project: str | Path, *, phase: str, to: str | None = None) -> dict[str, Any]:
    """Move one master phase forward one state (or to `to`) and point `current_phase_id` at it while open."""
    desk = shared_desk(Path(project))
    master_path, _ = _paths(desk)
    with _locked(desk):
        master = _read_json(master_path)
        target = next((p for p in master.get("phases") or [] if isinstance(p, dict) and p.get("phase_id") == phase), None)
        if target is None:
            raise KeyError(f"phase {phase} not in master schedule")
        cur = str(target.get("state") or "READY").upper()
        if to:
            new = to.upper()
            if new not in _STEP_STATES:
                raise ValueError(f"unknown state {new}")
        else:
            idx = ADVANCE_ORDER.index(cur) if cur in ADVANCE_ORDER else 0
            new = ADVANCE_ORDER[min(idx + 1, len(ADVANCE_ORDER) - 1)]
        target["state"] = new
        target["updated_at"] = _now_iso()
        if new in ("ACTIVE", "REVIEW"):
            master["current_phase_id"] = phase
        _backup(desk, master_path)
        _atomic_write(master_path, master)
    return {"ok": True, "phase": phase, "from": cur, "to": new}
===END===

===FILE: tests/test_u304c_schedule_planner.py===
"""U304-C: schedule-time model/effort/helper assignment and the live detailed-schedule driver (fixture-only)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from v7_harness.coord import schedule_planner as sp
from v7_harness.coord.helper_thinking_router import SUB_PROCESS_STAGES, get_official_tool_lineup

REPO = Path(__file__).resolve().parents[1]

CARD_MD = """# Fixture card

## Cards

| Card | Item | Lane | Author (Claude session) | Judge | Allowed files |
|---|---|---|---|---|---|
| U900-A Scheduler estimator design + router | 3 | ARCH_DESIGN→IMPL_CODE | claude `u900a` | antigravity | `a.py`, `b.py`, `c.py`, `d.py`, `tests/t.py` |
| U900-B Typo fix in readme | 1 | IMPL_CODE | antigravity `u900b` | claude | `README.md` |
| U900-E Cross review | all | VERIFY_AUDIT | — | — | read-only |

## After
not a table line
"""


def _budget(now: float | None = None, *, age_s: float = 60.0, rem5: int = 10_000_000, week: int = 100_000_000,
            week_h: float = 50.0, five_h_min: float = 120.0, **per_tool: dict) -> dict:
    """Fixture budget in the U304-D budget_snapshot shape (generous unless overridden)."""
    now = time.time() if now is None else now
    out = {}
    for tool, plan in (("codex", "plus"), ("claude", "pro"), ("antigravity", "ultra")):
        out[tool] = {"remaining_5h_tokens": rem5, "remaining_week_tokens": week,
                     "reset_5h_at": now + five_h_min * 60, "reset_week_at": now + week_h * 3600,
                     "measured_at": now - age_s, "plan": plan, **per_tool.get(tool, {})}
    return out


def _ledger_rows() -> list[dict]:
    rows = []
    for i, tok in enumerate((1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000)):
        rows.append({"work_id": f"U800-L{i}", "input_tokens": tok, "output_tokens": 0, "wall_time_s": 10.0 + i})
    rows.append({"work_id": "U900-L1", "input_tokens": 60000, "output_tokens": 0})
    rows.append({"work_id": "U900-L2", "input_tokens": 70000, "output_tokens": 0})
    rows.append({"work_id": "U777-skip", "input_tokens": 0, "output_tokens": 0})
    return rows


def _make_desk(root: Path) -> Path:
    coord = root / ".coord"
    (coord / "usage").mkdir(parents=True)
    master = {
        "schedule_id": "FIXTURE",
        "keep_me": {"untouched": True},
        "current_phase_id": "U800",
        "phases": [
            {"phase_id": "U800", "title": "old done", "state": "DONE", "owner_tool": "codex", "lane": "IMPL_CODE"},
            {"phase_id": "U850", "title": "Release merge and runtime reinstall", "state": "READY",
             "owner_tool": "antigravity", "lane": "MERGE_RELEASE"},
        ],
    }
    (coord / "master_schedule.json").write_text(json.dumps(master), encoding="utf-8")
    sub = {
        "schema": "uaos-sub-process-schedule-v1",
        "card_sub_schedules": [{
            "phase_id": "U850", "assigned_executor": "antigravity", "assigned_verifier": "claude",
            "sub_processes": [
                {"sub_id": f"U850:{st}", "step_index": i + 1, "stage_name": st, "state": "DONE" if i == 0 else "ACTIVE" if i == 1 else "PLANNED",
                 "depends_on": [f"U850:{SUB_PROCESS_STAGES[i - 1]}"] if i else []}
                for i, st in enumerate(SUB_PROCESS_STAGES)
            ],
        }],
    }
    (coord / "sub_process_schedule.json").write_text(json.dumps(sub), encoding="utf-8")
    (coord / "usage" / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _ledger_rows()) + "\nnot json\n", encoding="utf-8")
    (root / "card.md").write_text(CARD_MD, encoding="utf-8")
    return root


class EstimatorTests(unittest.TestCase):
    def test_history_bands_are_measured_quartiles_and_family_median(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            h = sp.load_history(desk, [])
            self.assertEqual(h["rows"], 10)  # zero-token row excluded, bad json skipped
            self.assertEqual(h["band_source"], "measured")
            self.assertEqual(h["by_family"]["U900"]["median_tokens"], 65000)
            e1, e2, e3 = h["band_edges"]
            self.assertTrue(e1 < e2 < e3)

    def test_fallback_bands_with_tiny_ledger(self) -> None:
        h = sp.summarize_history([{"family": "U1", "lane": "", "tokens": 5, "wall_s": None}])
        self.assertEqual(h["band_source"], "fallback")
        self.assertEqual(tuple(h["band_edges"]), tuple(sp.THRESHOLDS["size_bands"]["fallback"]))

    def test_flagship_only_when_importance_and_difficulty_high(self) -> None:
        hist = sp.summarize_history([])
        hi = sp.estimate_step(text="Scheduler architecture estimator router design", stage="SP2_MIA_DESIGN_AUDIT",
                              lane="ARCH_DESIGN", card_id="U1", keypoint=True, history=hist)
        self.assertGreaterEqual(hi["importance"], 2)
        self.assertGreaterEqual(hi["complexity"], 2)
        a = sp.assign_step("claude", hi, card_id="U1")
        self.assertEqual((a["tier"], a["main_model"], a["main_effort"]), ("FLAGSHIP", "claude-opus-5-5", "High"))
        for tool, flag in (("codex", "gpt-6-astra"), ("antigravity", "gemini-4-argon")):
            self.assertEqual(sp.assign_step(tool, hi)["main_model"], flag)

        # Same design burden, not important: High effort on the cheaper main, never the flagship.
        lo_imp = sp.estimate_step(text="Scheduler architecture estimator router design", stage="SP2_MIA_DESIGN_AUDIT",
                                  lane="ARCH_DESIGN", card_id="U1", history=hist)
        self.assertLess(lo_imp["importance"], 2)
        b = sp.assign_step("claude", lo_imp)
        self.assertEqual((b["tier"], b["main_model"], b["main_effort"]), ("STANDARD_HIGH", "claude-sonnet-5-5", "High"))

    def test_mechanical_merge_gets_low_effort(self) -> None:
        est = sp.estimate_step(text="merge the PR", stage="SP5_MERGE_AND_RUNTIME", lane="MERGE_RELEASE",
                               history=sp.summarize_history([]))
        a = sp.assign_step("antigravity", est)
        self.assertEqual((a["tier"], a["main_effort"], a["helper_effort"]), ("MECHANICAL", "Low", "Low"))
        self.assertEqual(a["main_effort_param"], {"thinking_level": "low"})

    def test_exhaustion_demotes_flagship(self) -> None:
        est = sp.estimate_step(text="security gate design architecture", stage="SP2_MIA_DESIGN_AUDIT",
                               lane="ARCH_DESIGN", keypoint=True, history=sp.summarize_history([]))
        a = sp.assign_step("codex", est, exhaustion_risk="IMMINENT_EXHAUSTION")
        self.assertEqual((a["tier"], a["main_model"]), ("STANDARD_HIGH", "gpt-6-sol"))
        self.assertIn("demoted", a["rationale"])

    def test_one_helper_per_tool_and_never_high(self) -> None:
        hist = sp.summarize_history([])
        for tool in ("codex", "claude", "antigravity"):
            helpers, efforts = set(), set()
            for stage in SUB_PROCESS_STAGES:
                for kp in (False, True):
                    est = sp.estimate_step(text="design architecture security", stage=stage, keypoint=kp,
                                           files=6, history=hist)
                    a = sp.assign_step(tool, est)
                    helpers.add(a["helper_model"])
                    efforts.add(a["helper_effort"])
                    self.assertIn(a["main_model"], get_official_tool_lineup(tool)["all_reasoning_models"])
                    self.assertTrue(a["rationale"])
                    self.assertIn("router_baseline", a)
            self.assertEqual(helpers, {get_official_tool_lineup(tool)["primary_helper_model"]})
            self.assertNotIn("High", efforts)

    def test_every_threshold_has_a_reason(self) -> None:
        for name, entry in sp.THRESHOLDS.items():
            self.assertIn("why", entry, name)
            self.assertTrue(entry["why"].strip(), name)

    def test_parse_card_table(self) -> None:
        cards = sp.parse_card_table(CARD_MD)
        self.assertEqual([c["card_id"] for c in cards], ["U900-A", "U900-B", "U900-E"])
        a = cards[0]
        self.assertEqual((a["author"], a["judge"], a["lane"], a["files"]), ("claude", "antigravity", "IMPL_CODE", 5))
        self.assertEqual(cards[2]["author"], "")


def _heavy(keypoint: bool) -> dict:
    est = sp.estimate_step(text="Scheduler architecture estimator router design security gate", stage="SP2_MIA_DESIGN_AUDIT",
                           lane="ARCH_DESIGN", card_id="U1", keypoint=keypoint, history=sp.summarize_history([]))
    est["expected_tokens"] = 10_000
    return est


class BudgetTests(unittest.TestCase):
    def test_fail_closed_without_fresh_budget_and_nothing_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            paths = [desk / ".coord" / n for n in ("master_schedule.json", "sub_process_schedule.json")]
            before = [p.read_bytes() for p in paths]
            stale = _budget(age_s=sp.THRESHOLDS["budget_freshness_s"]["value"] + 1)
            partial = _budget()
            del partial["codex"]["remaining_week_tokens"]
            week_passed = _budget(week_h=-1)
            for bad in (None, {}, stale, partial, week_passed):
                for fn in (sp.plan_sub, sp.plan_master):
                    with self.assertRaises(sp.BudgetUnavailable):
                        fn(desk, card_file=desk / "card.md", budget=bad)
            self.assertEqual([p.read_bytes() for p in paths], before)
            self.assertFalse(list(desk.glob(".work/backup_*")))

    def test_paced_allowance_spreads_the_weekly_pool(self) -> None:
        now = 1_000_000.0
        b = _budget(now, rem5=50_000, week=1_000_000, week_h=50)  # 10 windows left -> 100k per window
        a = sp.paced_allowance(sp.validate_budget(b, now=now), now=now)
        self.assertEqual(a["claude"]["paced_tokens"], 50_000)  # 5h remaining binds
        self.assertEqual(a["antigravity"]["flagship_tokens_left"], 25_000)
        self.assertEqual(a["codex"]["flagship_tokens_left"], 5_000)
        refilled = _budget(now, rem5=50_000, week=1_000_000, week_h=50, five_h_min=-1)
        a2 = sp.paced_allowance(sp.validate_budget(refilled, now=now), now=now)
        self.assertEqual(a2["claude"]["paced_tokens"], 100_000)  # 5h reset passed: weekly pace only

    def test_heavy_step_prefers_argon_and_20_dollar_flagship_is_keypoint_only(self) -> None:
        now = 1_000_000.0
        allow = sp.paced_allowance(sp.validate_budget(_budget(now), now=now), now=now)
        a = sp.assign_step("claude", _heavy(False), allowance=allow)
        self.assertEqual((a["tool"], a["main_model"], a["main_effort"], a["rerouted_from"]),
                         ("antigravity", "gemini-4-argon", "High", "claude"))
        k = sp.assign_step("codex", _heavy(True), allowance=allow)
        self.assertEqual((k["tool"], k["main_model"]), ("codex", "gpt-6-astra"))
        # The judge is never the rerouted author: no Argon, High effort on the cheaper own main.
        j = sp.assign_step("claude", _heavy(False), allowance=allow, no_reroute=("antigravity",))
        self.assertEqual((j["tool"], j["tier"], j["main_model"], j["main_effort"]),
                         ("claude", "STANDARD_HIGH", "claude-sonnet-5-5", "High"))
        empty = sp.paced_allowance(sp.validate_budget(_budget(now, rem5=0), now=now), now=now)
        e = sp.assign_step("claude", _heavy(True), allowance=empty)
        self.assertEqual((e["tool"], e["tier"]), ("claude", "STANDARD_HIGH"))
        self.assertIn("withheld", e["rationale"])

    def test_argon_grants_five_times_the_20_dollar_flagship(self) -> None:
        now = 1_000_000.0
        b = _budget(now, rem5=100_000, week=1_000_000, week_h=50)  # paced 100k each tool
        allow = sp.paced_allowance(sp.validate_budget(b, now=now), now=now)
        argon = sum(sp.assign_step("antigravity", _heavy(False), allowance=allow)["tier"] == "FLAGSHIP"
                    for _ in range(20))
        opus = sum(sp.assign_step("claude", _heavy(True), allowance=allow)["main_model"] == "claude-opus-5-5"
                   for _ in range(20))
        self.assertEqual((argon, opus), (5, 1))


class DriverTests(unittest.TestCase):
    def test_plan_sub_writes_driver_assignments_and_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            res = sp.plan_sub(desk, card_file=desk / "card.md", keypoints=["U900-A"], budget=_budget())
            self.assertEqual(set(res["cards"]), {"U850", "U900-A", "U900-B"})  # review-only row has no own steps
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(master["keep_me"], {"untouched": True})
            driver = master["sub_schedule_driver"]
            self.assertEqual(driver["schema"], sp.DRIVER_SCHEMA)
            self.assertEqual(driver["keypoints"], ["U900-A"])
            a_steps = {s["stage"]: s for s in driver["cards"]["U900-A"]["steps"]}
            self.assertEqual(a_steps["SP2_MIA_DESIGN_AUDIT"]["assignment"]["tier"], "FLAGSHIP")
            self.assertEqual(a_steps["SP4_INDEPENDENT_VERIFY"]["acting_tool"], "antigravity")
            self.assertEqual(a_steps["SP5_MERGE_AND_RUNTIME"]["acting_tool"], "antigravity")
            b_steps = {s["stage"]: s for s in driver["cards"]["U900-B"]["steps"]}
            self.assertNotEqual(b_steps["SP2_MIA_DESIGN_AUDIT"]["assignment"]["tier"], "FLAGSHIP")
            self.assertEqual(b_steps["SP5_MERGE_AND_RUNTIME"]["acting_tool"], "codex")  # author never self-merges
            self.assertEqual(a_steps["SP1_RESEARCH_DRAFT"]["state"], "READY")
            # imported capacity card keeps its live states
            u850 = {s["stage"]: s["state"] for s in driver["cards"]["U850"]["steps"]}
            self.assertEqual(u850["SP2_MIA_DESIGN_AUDIT"], "ACTIVE")
            sub = json.loads((desk / ".coord" / "sub_process_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(sub["live_driver"]["cards"].keys(), driver["cards"].keys())
            sp850 = sub["card_sub_schedules"][0]["sub_processes"][1]
            self.assertEqual(sp850["u304c_assignment"]["schema"], sp.ASSIGNMENT_SCHEMA)
            self.assertTrue(list((desk / ".work").glob("backup_*/u304c/master_schedule.json")))

            # Keypoints persist across a re-plan without the flag.
            sp.plan_sub(desk, budget=_budget())
            master2 = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(master2["sub_schedule_driver"]["keypoints"], ["U900-A"])

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            before = (desk / ".coord" / "master_schedule.json").read_bytes()
            sp.plan_sub(desk, card_file=desk / "card.md", dry_run=True, budget=_budget())
            self.assertEqual((desk / ".coord" / "master_schedule.json").read_bytes(), before)

    def test_advance_walks_the_dag_and_syncs_master(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            sp.plan_sub(desk, card_file=desk / "card.md", budget=_budget())
            sp.plan_master(desk, card_file=desk / "card.md", budget=_budget())
            r = sp.advance_sub(desk, card="U900-A")  # nothing ACTIVE: start the first ready step
            self.assertEqual((r["changed"], r["state"]), ("U900-A:SP1_RESEARCH_DRAFT", "ACTIVE"))
            r = sp.advance_sub(desk, card="U900-A")
            self.assertEqual(r["state"], "DONE")
            self.assertEqual(r["opened"], "U900-A:SP2_MIA_DESIGN_AUDIT")
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            phase = next(p for p in master["phases"] if p["phase_id"] == "U900-A")
            self.assertEqual((phase["sub_progress"], phase["current_sub_step"]), ("1/5", "U900-A:SP2_MIA_DESIGN_AUDIT"))
            r = sp.advance_sub(desk, card="U900-A", step="SP2_MIA_DESIGN_AUDIT", to="BLOCKED")
            self.assertIsNone(r["opened"])  # SP3 depends on SP2, so it stays closed
            states = {s["sub_id"]: s["state"] for s in r["steps"]}
            self.assertEqual(states["U900-A:SP3_CODE_EXECUTION"], "PLANNED")
            with self.assertRaises(KeyError):
                sp.advance_sub(desk, card="NOPE")
            with self.assertRaises(ValueError):
                sp.advance_sub(desk, card="U900-A", to="WHATEVER")

    def test_plan_master_assigns_open_phases_and_advance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            res = sp.plan_master(desk, card_file=desk / "card.md", keypoints=["U900-A"], budget=_budget())
            self.assertEqual(res["added_phases"], ["U900-A", "U900-B", "U900-E"])
            ids = [p["phase_id"] for p in res["phases"]]
            self.assertNotIn("U800", ids)  # DONE phases are not re-planned
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            u850 = next(p for p in master["phases"] if p["phase_id"] == "U850")
            self.assertEqual(u850["model_assignment"]["tool"], "antigravity")
            self.assertNotIn("model_assignment", master["phases"][0])
            r = sp.advance_master(desk, phase="U850")
            self.assertEqual((r["from"], r["to"]), ("READY", "ACTIVE"))
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(master["current_phase_id"], "U850")

    def test_parallel_advances_lose_no_update(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            sp.plan_sub(desk, card_file=desk / "card.md", budget=_budget())
            cards = ["U900-A", "U900-B"]

            def walk(card: str) -> None:
                for _ in range(1 + 2 * len(SUB_PROCESS_STAGES)):
                    try:
                        sp.advance_sub(desk, card=card)
                    except KeyError:
                        return

            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(walk, cards))
            driver = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))["sub_schedule_driver"]
            for card in cards:
                self.assertEqual({s["state"] for s in driver["cards"][card]["steps"]}, {"DONE"}, card)
            self.assertFalse((desk / ".coord" / "schedule_planner.lock").exists())


class CliTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "v7_harness.cli", "coord", "schedule", *args],
                              cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_cli_plan_show_advance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            bf = desk / "budget.json"
            bf.write_text(json.dumps(_budget(age_s=10_000)), encoding="utf-8")
            before = (desk / ".coord" / "master_schedule.json").read_bytes()
            p = self._run("plan", "--sub", "--project", str(desk), "--card-file", str(desk / "card.md"),
                          "--budget-file", str(bf))
            self.assertEqual(p.returncode, 2)  # stale measured budget: fail closed
            self.assertIn("old", json.loads(p.stdout)["error"])
            self.assertEqual((desk / ".coord" / "master_schedule.json").read_bytes(), before)
            bf.write_text(json.dumps(_budget()), encoding="utf-8")
            p = self._run("plan", "--sub", "--project", str(desk), "--card-file", str(desk / "card.md"),
                          "--budget-file", str(bf))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("antigravity", json.loads(p.stdout)["budget"])
            self.assertIn("U900-A", json.loads(p.stdout)["cards"])
            p = self._run("advance", "--sub", "--project", str(desk), "--card", "U900-B")
            self.assertEqual(p.returncode, 0, p.stderr)
            p = self._run("show", "--sub", "--project", str(desk))
            states = [s["state"] for s in json.loads(p.stdout)["cards"]["U900-B"]]
            self.assertEqual(states[0], "ACTIVE")
            p = self._run("advance", "--sub", "--project", str(desk))
            self.assertEqual(p.returncode, 2)
            p = self._run("plan", "--master", "--project", str(desk), "--dry-run", "--budget-file", str(bf))
            self.assertEqual(p.returncode, 0, p.stderr)
            p = self._run("show", "--master", "--project", str(desk))
            self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
===END===

===FILE: .coord/tasks/U304-C-schedule-planner.md===
# U304-C — 스케줄 기반 모델·추론강도·도우미 자동지정 + 세부 스케줄 실 세션

- Parent card: `.coord/tasks/U304-hud-uaos-os-revision.md` (items 3, 5). Lane ARCH_DESIGN→IMPL_CODE. Author claude, judge antigravity.
- Conductor note: written while Codex is LIMITED (until 2026-11-04 22:03 KST); marked `CODEX_REREV`.
- Deliverable class: maintained (recorded intent below + `tests/test_u304c_*.py`).

## Stage 0 — research (cited)

| Source | What it fixes in this design |
|---|---|
| OpenAI Codex config reference, `model_reasoning_effort` (https://developers.openai.com/codex/config-reference ; template default `medium`: https://github.com/openai/codex/pull/7449/files) | Codex effort values are `low/medium/high` (+ model-dependent `minimal/xhigh`); default `medium`. The planner emits only `low/medium/high`, so every value is valid on every Codex model. |
| Anthropic effort parameter (https://platform.claude.com/docs/en/build-with-claude/effort) | `output_config.effort` trades thoroughness for tokens; `high` = complex reasoning / hard coding, `medium` = balanced, `low` = classification/lookups/high volume. This is the semantic used for the three effort classes below. |
| Gemini thinking (https://ai.google.dev/gemini-api/docs/thinking) | `thinking_level` low/medium/high; some models accept only low/high. The planner never emits a level the router's lineup does not list, and emits `MEDIUM` only for models the router already uses at `Medium`. |
| RouteLLM (https://github.com/lm-sys/RouteLLM) | Route to the strong model only when the expected quality gain beats a cost threshold; the threshold is calibrated on own traffic. Here: flagship only when BOTH importance and difficulty are high; thresholds are recorded with reasons and band edges are calibrated on the measured ledger (`.coord/usage/runs.jsonl`). |

Alternatives compared: (a) keep static per-stage branches (today; no estimate — rejected, it is the receipt), (b) learned router like RouteLLM `mf` (needs preference data we do not have — No-Go now), (c) deterministic feature score + ledger-calibrated bands (Go: explainable, testable, 0 paid tokens).

## Design

Module `v7_harness/coord/schedule_planner.py` (new). Reuses `helper_thinking_router` (U304-B owns it, called only):
`select_optimal_helper_and_thinking` (lane, Ollama task, baseline), `get_official_tool_lineup` (helper, model validation),
`infer_lane_from_card_metadata`, `SUB_PROCESS_STAGES`.

1. **Estimate** (per step): `importance` 0–3, `design_difficulty` 0–3, `impl_difficulty` 0–3, `expected_tokens`, `files`, `risk`, `lane`.
   - importance = 1 (every scheduled card is ordered work) + 1 keypoint words (security, authority, evaluator, gate, schema, canonical, 권한, 보안, 평가기, 정본…) + 1 emphasis (explicit `keypoint`/`codex_exclusive`/P1/`TOP-EMPHASIS`/강조). SP1 research and SP5 merge get −1: their mistakes are cheap to redo and are re-checked by SP2/SP4.
   - design_difficulty = number of distinct design words (architecture, concurrency, atomic, algorithm, estimator, router, 설계, 동시성…), +1 in ARCH_DESIGN, clamp 3.
   - expected_tokens = median of measured ledger rows of the same card family (e.g. `U304*`) → else median of rows of the same lane → else lane prior (only with an empty ledger).
   - impl_difficulty = quartile band of expected_tokens against all measured ledger rows (q25/q50/q75 edges), +1 when the card allows ≥4 files.
   - stage complexity: SP1 = min(1, design), SP2 = design, SP3 = impl, SP4 = max(design, impl), SP5 = 1 if risk words else 0.
2. **Score → tier** (both axes 0–3):
   - `FLAGSHIP` importance ≥2 AND complexity ≥2 → flagship main + `High`.
   - `STANDARD_HIGH` one axis ≥2 → standard main + `High`.
   - `MECHANICAL` complexity 0 and importance ≤1 → standard main + `Low`.
   - else `STANDARD_MEDIUM` → standard main + `Medium`.
   - `IMMINENT_EXHAUSTION` of the acting tool demotes FLAGSHIP to STANDARD_HIGH (same rule as the router's `imminent`).
3. **Assign**: main model from `MAIN_MODEL_TIERS` (codex gpt-6-astra/gpt-6-sol, claude opus-5-5/sonnet-5-5, antigravity gemini-4-argon/gemini-3.1-pro), validated against the lineup; helper = lineup `primary_helper_model` (one per tool, U304-B 1:1); helper effort `Low` when the step fits one Ollama/helper slice (expected_tokens ≤ q25) or is MECHANICAL, else `Medium`; never `High` (high reasoning is the main model's job). Router selection is kept as `router_baseline` for comparison.
4. **Live sub-schedule driver**: `coord schedule --sub plan|advance|complete|show`. Durable state lives in `master_schedule.json["sub_schedule_driver"]` (capacity_planner rewrites `sub_process_schedule.json` whole, while master is read-modify-write and keeps extra keys) and is mirrored to `sub_process_schedule.json["live_driver"]` for the HUD. `plan` imports `card_sub_schedules` cards and, with `--card-file`, the card table rows; `advance` closes the ACTIVE step and opens the next dependency-ready one; master phase gets `sub_progress`/`current_sub_step`. Writes are atomic (tmp + `os.replace`) under an exclusive lock file, after a backup copy in `.work/backup_<date>/`.
5. `coord schedule --master plan` writes `model_assignment` on every non-DONE phase (and with `--card-file` adds missing card phases as READY).
6. **Measured budget is a required input** (윤겸스 2026-11-04 2nd order, card Item 7; routing rule same day). `plan_sub`/`plan_master` take `budget` = {tool: {remaining_5h_tokens, remaining_week_tokens, reset_5h_at, reset_week_at, measured_at, plan}} (U304-D `budget_snapshot()` shape; CLI `--budget-file`, else `usage_budget.budget_snapshot()` once U304-D lands).
   - Fail closed: missing, partial, unparseable, older than `budget_freshness_s` (900 s) or past its weekly reset → `BudgetUnavailable`, nothing written (exit 2).
   - Paced headroom per tool = min(5h remaining, weekly remaining ÷ 5h windows left to the weekly reset); a passed 5h reset leaves only the weekly pace.
   - Flagship allowance = paced headroom × `flagship_pace_share` (Antigravity Ultra 0.5, Codex/Claude $20 plans 0.1 → Argon gets 5× the grants); each grant spends the step's expected tokens.
   - FLAGSHIP routing: Antigravity steps → Gemini 4 Argon High within its share; Codex/Claude flagship (GPT-6 Astra / Opus 5.5) only for declared keypoints within their own share; any other heavy step is rerouted to Antigravity Argon High when its share fits and Antigravity is not the step's judge (author ≠ judge); otherwise STANDARD_HIGH on its own tool ("flagship withheld"). The grant ledger is written to `sub_schedule_driver.budget` / `master.schedule_budget`.

Non-goals: no edit of `helper_thinking_router.py` / `capacity_planner.py`; no paid calls; no measured-savings claim (UNMEASURED).

HUD request (to U304-A by letter): render `live_driver` steps and their `assignment` in the schedule panel and keep `live_driver` when capacity_planner rewrites the sub file.
===END===

===FILE: .coord/results/U304-C.md===
# U304-C — 스케줄 기반 모델·추론강도·도우미 자동지정 + 세부 스케줄 실 세션 result (2026-11-04)

RESULT U304-C | PR PENDING | MERGEABLE pending | tests 18/0 (u304c) | blocker none (awaiting Antigravity verdict)

- What now works: `coord schedule --sub plan --card-file <card> --budget-file <snapshot> [--keypoint ID]` estimates every detailed step (importance, design/impl difficulty, ledger-calibrated size, risk, lane) and writes {main model, effort, helper, helper effort, rationale}; `coord schedule --sub advance|show` is the live driver of `.coord/sub_process_schedule.json` (durable state in `master_schedule.json["sub_schedule_driver"]`, mirrored to `sub_process_schedule.json["live_driver"]`); `coord schedule --master plan|advance|show` assigns open master phases.
- Budget (Item 7): a fresh measured budget snapshot is required; missing/stale → fail closed, nothing written. Flagship grants are paced (min(5h remaining, weekly ÷ windows left) × share: Antigravity Ultra 0.5, $20 plans 0.1 → Gemini 4 Argon High gets 5× the grants of Opus 5.5 / GPT-6 Astra, which stay keypoint-only; heavy non-keypoint steps reroute to Argon unless Antigravity is the judge).
- Live run (shared desk, 2026-11-04, before Item 7): 8 cards planned; ledger 1080 rows → size bands q25/q50/q75 = 3563/9124/27121 tokens; U304-C SP1 DONE, SP2 DONE, SP3 ACTIVE. After Item 7, a real plan without a measured snapshot exits 2 (no U304-D provider yet; local quota logs have no token calibration) — the fail-closed path; fixture-budget dry run in `.work/u304c/live_budget_dryrun.json`.
- Pilot: classify() = Ollama U304-C-L1 PASS, paced_allowance() = Ollama U304-C-L3 PASS, live driver after failed Ollama U304-C-L2 → apply bundle U304-C-A2. Design and citations: `.coord/tasks/U304-C-schedule-planner.md`. Savings: UNMEASURED.
- Open dependency: HUD rendering of `live_driver` (letter to U304-A); U304-D wires `usage_budget.budget_snapshot()` after merge. Marked `CODEX_REREV` (written while Codex LIMITED).
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


=======
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_coord_schedule(args: argparse.Namespace) -> int:
    from .coord import schedule_planner as sp

    project = Path(args.project)
    try:
        if args.action == "plan":
            # U304 item 7: the measured budget is a required input; no file and no provider -> fail closed.
            budget = None
            if args.budget_file:
                budget = json.loads(Path(args.budget_file).read_text(encoding="utf-8"))
            else:
                try:
                    from .coord import usage_budget  # U304-D provider, wired once it lands
                except ImportError:
                    usage_budget = None
                if usage_budget is not None and hasattr(usage_budget, "budget_snapshot"):
                    budget = usage_budget.budget_snapshot()
            fn = sp.plan_sub if args.sub else sp.plan_master
            payload = fn(project, card_file=args.card_file, keypoints=tuple(args.keypoint or ()),
                         dry_run=bool(args.dry_run), budget=budget)
        elif args.action == "show":
            payload = sp.show_sub(project) if args.sub else sp.show_master(project)
        else:
            if not args.card:
                raise ValueError("--card is required to advance")
            if args.sub:
                payload = sp.advance_sub(project, card=args.card, step=args.step, to=args.to or "DONE")
            else:
                payload = sp.advance_master(project, phase=args.card, to=args.to)
    except (KeyError, ValueError, OSError, TimeoutError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_hm.set_defaults(func=cmd_coord_helper_matrix)
=======
    p_coord_hm.set_defaults(func=cmd_coord_helper_matrix)

    # U304-C: schedule-time model/effort/helper assignment and the live driver of the detailed schedule.
    p_coord_sched = p_coord_subs.add_parser(
        "schedule",
        help="U304-C: assign main model, effort, helper per master/sub step from estimates; drive the sub schedule",
    )
    p_coord_sched.add_argument("action", choices=["plan", "advance", "show"])
    p_coord_sched.add_argument("--project", default=".", help="Project root (default: .)")
    sched_scope = p_coord_sched.add_mutually_exclusive_group(required=True)
    sched_scope.add_argument("--master", action="store_true", help="Master schedule (.coord/master_schedule.json)")
    sched_scope.add_argument("--sub", action="store_true", help="Detailed schedule (.coord/sub_process_schedule.json)")
    p_coord_sched.add_argument("--card-file", default=None, help="Card manual whose `## Cards` table is scheduled")
    p_coord_sched.add_argument("--card", default=None, help="Card (sub advance) or phase id (master advance)")
    p_coord_sched.add_argument("--step", default=None, help="Sub step id or stage code (default: the ACTIVE step)")
    p_coord_sched.add_argument("--to", default=None, help="Target state (default: DONE for sub, next state for master)")
    p_coord_sched.add_argument("--keypoint", action="append", default=[],
                               help="Card/phase id the conductor declares a keypoint (user emphasis); repeatable")
    p_coord_sched.add_argument("--dry-run", action="store_true", help="Plan without writing")
    p_coord_sched.add_argument("--budget-file", default=None,
                               help="Measured budget snapshot JSON (U304-D shape); plan fails closed without one")
    p_coord_sched.set_defaults(func=cmd_coord_schedule)
>>>>>>> REPLACE
===END===

