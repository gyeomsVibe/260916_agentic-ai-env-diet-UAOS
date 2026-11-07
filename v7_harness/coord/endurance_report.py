"""S6: weekly three-tool endurance report, deterministic and zero paid tokens.

Question it answers (three-tool sustain plan, 2026-11-07): does each paid tool (Claude Code, Codex, Antigravity)
last through its 5-hour and weekly quota windows, and where did its steps go?

Per tool, from local files only (no network, no model call, no credential is opened):

- measured 5h / weekly used % and a freshness state, from `quota_sources.measured_accounts` (U303);
- Δ = used % − elapsed % of the window. Positive means the tool burns quota faster than the clock and will hit the
  limit before the reset; negative means headroom at the reset;
- the step mix of Ollama, helper and main steps in the desk usage ledger (`.coord/usage/runs.jsonl`) over the
  last 7 days, with pass rates per class;
- hours the tool sat idle because a window was exhausted, from the quota history series each provider leaves.

The scheduled `rsi watch` (U157, Windows Task Scheduler, every 15 min) calls `maybe_write_weekly`, which writes
`<desk>/.coord/reports/endurance_<YYYY-MM-DD>.md` at most once per 7 days. Same inputs and `now` give the same bytes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from . import quota_sources as qs
from .helper_telemetry import LANES, designated_helper_names

TOOLS = ("claude", "codex", "antigravity")
REPORT_DAYS = 7  # one weekly quota window (Codex/Claude seven_day = 10080 min); also the report cadence
REPORT_WINDOW_S = REPORT_DAYS * 86400
# A reading older than 1 h is STALE: 1 h is 20 % of the 5 h window, so an older 5 h reading can be off by more
# than a fifth of the window's elapsed time. rsi watch runs every 15 min, so a live recorder stays well inside it.
FRESH_MAX_AGE_S = 3600
# Providers report integer or 4-decimal percents; 99.5 rounds to 100 % on every HUD, the point where calls refuse.
EXHAUSTED_PCT = 99.5
# Ledger actors that name a tool; coordinator/conductor/unknown rows have no single owning tool.
ACTOR_TOOL = {"claude": "claude", "codex": "codex", "antigravity": "antigravity", "agy": "antigravity"}
OLLAMA_WORKERS = {"ollama", "local"}
OLLAMA_KIND_PREFIXES = ("olla", "local_", "ollama")
STEP_CLASSES = ("ollama", "helper", "main")
REPORT_PREFIX = "endurance_"


# ---------------------------------------------------------------- quota windows
def _window_view(window: dict[str, Any] | None) -> dict[str, Any]:
    """used %, elapsed %, Δ and freshness of one measured window (None → MISSING)."""
    if not window:
        return {"freshness": "MISSING", "used_pct": None, "elapsed_pct": None, "delta_pct": None, "age_s": None}
    win_s = int(window.get("window_min") or 0) * 60
    elapsed_pct = None
    if window.get("reset_elapsed"):
        freshness = "RESET_ELAPSED"  # the provider refilled after the reading: used 0 % is inferred, not observed
    elif window.get("age_s") is None:
        freshness = "STALE"
    else:
        freshness = "FRESH" if int(window["age_s"]) <= FRESH_MAX_AGE_S else "STALE"
    if win_s > 0 and window.get("resets_at") and not window.get("reset_elapsed"):
        remaining_s = max(0, min(win_s, int(window.get("reset_in_s") or 0)))
        elapsed_pct = round(100.0 * (win_s - remaining_s) / win_s, 1)
    used = window.get("used_pct")
    delta = None if (used is None or elapsed_pct is None) else round(float(used) - elapsed_pct, 1)
    return {"freshness": freshness, "used_pct": used, "elapsed_pct": elapsed_pct, "delta_pct": delta,
            "age_s": window.get("age_s"), "resets_at": window.get("resets_at")}


def tool_windows(measured: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """{tool: {"5h": view, "weekly": view}} from `measured_accounts` output.

    Antigravity reports quota pools, not named windows: its selected model's pool is the 5 h or weekly window by
    the length `antigravity_quota` read from the reset distance.
    """
    out: dict[str, dict[str, Any]] = {}
    for tool in ("claude", "codex"):
        acct = measured.get(tool) or {}
        out[tool] = {"5h": _window_view(acct.get("five_hour")), "weekly": _window_view(acct.get("seven_day"))}
    pool = (measured.get("antigravity") or {}).get("selected_pool")
    five = pool if pool and int(pool.get("window_min") or 0) == qs.FIVE_HOUR_MIN else None
    week = pool if pool and int(pool.get("window_min") or 0) == qs.SEVEN_DAY_MIN else None
    out["antigravity"] = {"5h": _window_view(five), "weekly": _window_view(week)}
    return out


# ---------------------------------------------------------------- ledger step mix
def _helper_models() -> set[str]:
    names: set[str] = set()
    for tool in TOOLS:
        names |= designated_helper_names(tool)
    return {n.lower() for n in names}


def row_tool(row: dict[str, Any]) -> str | None:
    """The tool that owns a ledger row: a helper row's caller, else its actor; None when no tool owns it."""
    who = row.get("caller") if row.get("kind") == "helper" else row.get("actor")
    return ACTOR_TOOL.get(str(who or "").strip().lower())


def step_class(row: dict[str, Any], helper_models: set[str] | None = None) -> str:
    """ollama (local model, 0 paid tokens), helper (a tool's one designated cheap model) or main (the paid tool)."""
    helper_models = _helper_models() if helper_models is None else helper_models
    lane = row.get("helper_lane")
    worker = str(row.get("worker") or "").lower()
    kind = str(row.get("kind") or "").lower()
    if lane == "ollama" or worker in OLLAMA_WORKERS or kind.startswith(OLLAMA_KIND_PREFIXES):
        return "ollama"
    if (lane in LANES) or str(row.get("model") or "").lower() in helper_models:
        return "helper"
    return "main"


def read_ledger(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def step_mix(rows: Iterable[dict[str, Any]], now: float, window_s: float = REPORT_WINDOW_S) -> dict[str, Any]:
    """Per tool (plus `unattributed`) and per step class: steps, outcomes recorded, PASS count and pass rate."""
    helper_models = _helper_models()
    buckets = {t: {c: {"steps": 0, "with_outcome": 0, "passed": 0} for c in STEP_CLASSES}
               for t in (*TOOLS, "unattributed")}
    for row in rows:
        ts = row.get("ts")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not (now - window_s <= ts <= now):
            continue
        b = buckets[row_tool(row) or "unattributed"][step_class(row, helper_models)]
        b["steps"] += 1
        if row.get("outcome") not in (None, ""):
            b["with_outcome"] += 1
            b["passed"] += 1 if str(row["outcome"]).upper() == "PASS" else 0
    for classes in buckets.values():
        total = sum(c["steps"] for c in classes.values())
        for c in classes.values():
            c["share"] = round(c["steps"] / total, 3) if total else None
            c["pass_rate"] = round(c["passed"] / c["with_outcome"], 3) if c["with_outcome"] else None
    return buckets


# ---------------------------------------------------------------- idle hours at the limit
def limit_spans(samples: Iterable[dict[str, Any]], start: float, end: float) -> list[tuple[float, float]]:
    """Intervals inside [start, end] during which one window series was exhausted.

    An exhausted sample (used ≥ EXHAUSTED_PCT) opens an interval that ends at the earlier of its `resets_at` and the
    next sample of the same series below the limit (an early reset is a real refill). With neither, it runs to `end`.
    """
    pts = sorted((s for s in samples if s.get("ts") is not None), key=lambda s: s["ts"])
    spans: list[tuple[float, float]] = []
    for i, s in enumerate(pts):
        if float(s.get("used_pct") or 0.0) < EXHAUSTED_PCT:
            continue
        stops = [float(s["resets_at"])] if s.get("resets_at") is not None else []
        below = next((p["ts"] for p in pts[i + 1:] if float(p.get("used_pct") or 0.0) < EXHAUSTED_PCT), None)
        if below is not None:
            stops.append(float(below))
        a, b = max(start, float(s["ts"])), min(end, min(stops) if stops else end)
        if b > a:
            spans.append((a, b))
    return spans


def limit_idle_hours(series: Iterable[Iterable[dict[str, Any]]], start: float, end: float) -> float:
    """Hours inside [start, end] during which any of a tool's windows was exhausted (overlaps counted once:
    a 5 h limit inside an exhausted weekly window is the same idle hour)."""
    spans = [span for samples in series for span in limit_spans(samples, start, end)]
    total, cur = 0.0, None
    for a, b in sorted(spans):
        if cur is None or a > cur[1]:
            if cur:
                total += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur:
        total += cur[1] - cur[0]
    return round(total / 3600.0, 2)


def _claude_series(home: Path) -> list[dict[str, Any]]:
    """Both Claude windows from the statusLine recorder, one sample per window per row."""
    path = home / qs.CLAUDE_LIMITS_FILE
    pts: list[dict[str, Any]] = []
    if not path.is_file():
        return pts
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ts = qs._epoch(row.get("ts")) if isinstance(row, dict) else None
        if ts is None:
            continue
        for key in ("five_hour", "seven_day"):
            if row.get(f"{key}_used_pct") is not None:
                pts.append({"ts": ts, "used_pct": float(row[f"{key}_used_pct"]),
                            "resets_at": qs._epoch(row.get(f"{key}_resets_at")), "series": key})
    return pts


def quota_series(home: Path) -> dict[str, list[list[dict[str, Any]]]]:
    """Per tool, the quota history series each provider leaves locally (one list per window)."""
    claude = _claude_series(home)
    return {
        "claude": [[p for p in claude if p["series"] == k] for k in ("five_hour", "seven_day")],
        "codex": [qs.ledger_history(home, "codex", qs.FIVE_HOUR_MIN), qs.ledger_history(home, "codex", qs.SEVEN_DAY_MIN)],
        "antigravity": [qs.cockpit_history(home)],
    }


# ---------------------------------------------------------------- assembly
def build_report(project: Path, home: Path, now: float, *, measured: dict[str, Any] | None = None,
                 rows: list[dict[str, Any]] | None = None,
                 series: dict[str, list[list[dict[str, Any]]]] | None = None) -> dict[str, Any]:
    from .usage_ledger import ledger_file

    measured = qs.measured_accounts(home, now) if measured is None else measured
    rows = read_ledger(ledger_file(Path(project))) if rows is None else rows
    series = quota_series(home) if series is None else series
    start = now - REPORT_WINDOW_S
    windows = tool_windows(measured)
    mix = step_mix(rows, now)
    tools = {}
    for tool in TOOLS:
        tools[tool] = {
            "windows": windows[tool],
            "steps": mix[tool],
            "idle_limit_hours": limit_idle_hours(series.get(tool, []), start, now),
        }
    return {"schema": "uaos-endurance-report-v1", "generated_at": qs._iso(now), "window_days": REPORT_DAYS,
            "tools": tools, "unattributed_steps": mix["unattributed"]}


def _fmt(value: Any, suffix: str = "") -> str:
    return "—" if value is None else f"{value}{suffix}"


def _signed(value: Any) -> str:
    return "—" if value is None else f"{value:+.1f}"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [f"# 3도구 지속력 주간 보고서 (endurance) — {report['generated_at']}", "",
             f"최근 {report['window_days']}일, 로컬 파일만 읽은 결정적(deterministic) 계산, 유료 토큰 0.", "",
             "Δ = 사용% − 경과%: 양수면 리셋 전에 한도에 닿는 속도, 음수면 리셋 시점에 여유.", "",
             "## 쿼터 창 (quota windows)", "",
             "| 도구 | 창 | 사용% | 경과% | Δ | 신선도 | 측정 나이(초) |", "|---|---|---|---|---|---|---|"]
    for tool, t in report["tools"].items():
        for name, w in t["windows"].items():
            lines.append(f"| {tool} | {name} | {_fmt(w['used_pct'])} | {_fmt(w['elapsed_pct'])} | "
                         f"{_signed(w['delta_pct'])} | {w['freshness']} | {_fmt(w['age_s'])} |")
    lines += ["", "## 단계 구성과 통과율 (step mix, pass rate)", "",
              "| 도구 | 분류 | 단계 | 비중 | 결과 기록 | PASS | 통과율 |", "|---|---|---|---|---|---|---|"]
    groups = [(tool, t["steps"]) for tool, t in report["tools"].items()] + [("unattributed", report["unattributed_steps"])]
    for tool, classes in groups:
        for cls in STEP_CLASSES:
            c = classes[cls]
            lines.append(f"| {tool} | {cls} | {c['steps']} | {_fmt(c['share'])} | {c['with_outcome']} | "
                         f"{c['passed']} | {_fmt(c['pass_rate'])} |")
    lines += ["", "## 한도 때문에 멈춘 시간 (idle at limit)", "", "| 도구 | 시간(h) |", "|---|---|"]
    for tool, t in report["tools"].items():
        lines.append(f"| {tool} | {t['idle_limit_hours']} |")
    lines += ["", "신선도: FRESH ≤ 1시간, STALE > 1시간, RESET_ELAPSED = 측정 뒤 리셋됨(0% 추정), MISSING = 측정 없음.",
              "unattributed = coordinator/conductor처럼 한 도구에 속하지 않는 장부 행.", ""]
    return "\n".join(lines)


def _report_dir(project: Path) -> Path:
    from .hook_context import shared_desk

    return shared_desk(Path(project)) / ".coord" / "reports"


def _date(now: float) -> str:
    return datetime.fromtimestamp(now).strftime("%Y-%m-%d")


def write_report(project: Path, home: Path, now: float, **inputs: Any) -> Path:
    out_dir = _report_dir(project)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{REPORT_PREFIX}{_date(now)}.md"
    text = render_markdown(build_report(project, home, now, **inputs))
    tmp = target.with_suffix(f".md.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return target


def latest_report_date(project: Path) -> str | None:
    out_dir = _report_dir(project)
    if not out_dir.is_dir():
        return None
    dates = []
    for p in out_dir.glob(f"{REPORT_PREFIX}*.md"):
        stem = p.stem[len(REPORT_PREFIX):]
        try:
            datetime.strptime(stem, "%Y-%m-%d")
        except ValueError:
            continue
        dates.append(stem)
    return max(dates) if dates else None


def maybe_write_weekly(project: Path, home: Path, now: float, *, force: bool = False, **inputs: Any) -> dict[str, Any]:
    """Write the report when none exists from the last 7 days (or `force`); else NOT_DUE. Never raises past I/O."""
    last = latest_report_date(project)
    if not force and last is not None:
        age_days = (datetime.strptime(_date(now), "%Y-%m-%d") - datetime.strptime(last, "%Y-%m-%d")).days
        if age_days < REPORT_DAYS:
            return {"status": "NOT_DUE", "last": last, "next_due_in_days": REPORT_DAYS - age_days}
    path = write_report(project, home, now, **inputs)
    return {"status": "WRITTEN", "path": str(path)}
