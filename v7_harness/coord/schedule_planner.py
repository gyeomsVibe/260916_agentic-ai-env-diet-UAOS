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
