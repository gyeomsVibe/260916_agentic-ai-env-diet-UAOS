"""U304-D: per-subscription usage ledger, measured work-split allocator and flagship ("한방처방") gate.

Purpose (윤겸스 2026-11-04, item 7): make the three subscriptions last to their resets without lowering result
quality. Every schedule writer (master and detailed) MUST read `budget_snapshot()`; a schedule stamped without a
fresh snapshot fails closed (`validate_schedule_budget`). Manual: docs/108.

Sources (read-only, zero paid tokens, no credential opened or printed):
- Provider windows and calibration: `quota_sources.measured_accounts` (U303) through the capacity snapshot.
- Claude windows when the statusLine recorder is absent: rows written by `coord budget observe` from the Claude
  desktop usage card (`get_usage`) or `/usage`; the source label travels with each row.
- Per-model calls: `~/.uaos/usage/ledger.sqlite3` `contributions` (U303 `model_mix_7d`).
- Ollama/helper offload per calling tool: `~/.uaos/usage/invocations.sqlite3` `attempts` (the Ollama/Haiku journal).
- Antigravity accounts: `agy_accounts.antigravity_accounts` (U286) plus each cockpit quota cache file.

The ledger itself is `~/.uaos/usage/budget_ledger.sqlite3` (WAL). SQLite serialises writers across processes, so
parallel appends from three tools on Windows lose no rows (tests/test_u304d_usage_budget.py runs real processes).

Rules carried from the global policy: a remaining % becomes tokens only through a calibrated tokens-per-1 % with
its sample count; an unmeasured ratio is reported UNMEASURED and never replaced by a guess.
"""

from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .quota_sources import _epoch, _iso, calibrate, window_fact

SCHEMA = "uaos-budget-snapshot-v1"
LEDGER_FILE = Path(".uaos") / "usage" / "budget_ledger.sqlite3"
SNAPSHOT_FILE = Path(".coord") / "usage" / "budget_snapshot.json"
TOOLS = ("claude", "codex", "antigravity")

# A schedule may use a snapshot for 15 minutes. The fastest measured burn on this PC is Claude's 5 h window
# (58 % in ~4.1 h on 2026-11-04 = ~14 %/h), so 15 min of drift is ~3.5 points: under the 5-point step at which the
# pacing verdict can change. The HUD refresher collects about every few minutes, so 15 min also never forces a
# second paid collection.
FRESH_S = 900
# An observation older than 6 h no longer describes a 5 h window; the reading is kept but labelled stale.
OBS_STALE_S = 6 * 3600
# Burn slope needs two points of one reset window at least 10 min apart: shorter spans are rounding noise
# (provider % is an integer for Claude and Codex, so 1 point over 2 min would read as 30 %/h).
SLOPE_MIN_SPAN_S = 600
# ...and a rise of at least 3 points: integer readings carry +-1 point of rounding, so 3 points bound the slope
# error to a third. Receipt 2026-11-04: Claude weekly 82 -> 83 % in 11 min read as 5.5 %/h, 6x its window average.
SLOPE_MIN_DELTA_PCT = 3.0
SLOPE_LOOKBACK_S = 6 * 3600  # one 5 h window plus margin: older points describe a different working pace
RESET_MATCH_S = 600  # resets_at of one window drifts by seconds to minutes between samples (rolling clocks)

# Split bounds, common to all three tools. They are the user's own label for Claude ("Ollama 50 : helper 30 :
# core 20") read as quality limits, not as a target: Ollama may take at most half of the steps (it only does
# fixed-input mechanical operations, global rule), the helper at most 30 %, and at least 20 % of steps stay on the
# paid core model because design, judging and acceptance are paid-model work (global rule "paid models
# design/judge/accept"). Each tool's actual split is computed from its own measured mix and pace.
LOCAL_CEIL = 0.50
HELPER_CEIL = 0.30
CORE_FLOOR = 0.20

# Scarce flagship ("한방처방") cap on the $20 plans, as a share of paid steps in one window: one keypoint step per
# UAOS card; a card runs the 11 MIA stages, 1/11 = 9 %, rounded to 10 %.
FLAGSHIP_SHARE_CAP = {"pro_20": 0.10}
# Google AI Ultra is designed differently (윤겸스 correction 2026-11-04): it allows ~5x the top-model usage of the
# $20 plans, so Argon High is the system's MAIN route for high-quality work, used as often as the measured weekly
# pool allows, with no scarce entry rules. Its planned frequency is at least 5x the $20 flagship cap: 5 x 10 % = 50 %
# of paid steps is the planning target; the measured pacing below is the hard limit (unpaced use drains the pool in
# ~2 days, receipt ULTRA_ARGON_HIGH_RECEIPT).
ULTRA_TARGET_MULTIPLE = 5.0
# Weekly points never planned for flagship/main-route high effort. 10 points = one card's judge + verification run;
# on Ultra it is also ~4.8 h of continuous Argon High (100 % / 48 h receipt), i.e. one 5 h working session kept
# for the end of the week so the pool never hits 0 before its reset.
WEEKLY_RESERVE_PCT = 10.0
FLAGSHIP_MIN_5H_PCT = 20.0  # below 20 % left in the 5 h window the remaining run is kept for verification
# Entry threshold on a 1-5 x 1-5 scale: 16 = both factors at least "high" (4 x 4); 3 x 5 = 15 fails on purpose so
# one dimension alone never buys the flagship.
FLAGSHIP_MIN_SCORE = 16
KEYPOINT_CLASSES = ("architecture_decision", "final_verdict", "security_review", "merge_gate",
                    "root_cause_after_two_failures")

ULTRA_ARGON_HIGH_RECEIPT = {
    # 윤겸스 receipt 2026-11-04: Argon High alone drains the Ultra weekly pool in ~2 days = 100 % / 48 h.
    "tool": "antigravity", "model": "gemini-4-argon", "effort": "high", "pct_per_hour": round(100.0 / 48.0, 3),
    "window": "7d", "basis": "user_receipt", "observed_at": "2026-11-04T00:00:00Z",
    "note": "Argon High drains the Ultra weekly pool in ~2 days (user receipt)",
}
# OpenAI Codex pricing page (https://learn.chatgpt.com/docs/pricing, read 2026-11-04): estimated local messages per
# 5 h on Plus. The midpoints give the official quota weight per message relative to the core model (GPT-6.1 Sol).
CODEX_MSGS_PER_5H = {"gpt-6-astra": (5, 45), "gpt-6.1-sol": (15, 160), "gpt-6.1-terra": (35, 285),
                     "gpt-6-sol": (15, 150), "gpt-6-luna": (350, 3000)}
CODEX_PRICING_URL = "https://learn.chatgpt.com/docs/pricing"

PLANS: dict[str, dict[str, Any]] = {
    "claude": {"plan": "Claude Pro", "usd_month": 20, "tier": "pro_20", "pro_multiple": 1.0,
               "core": "claude-opus-5-5", "core_effort": "medium", "helper": "claude-haiku-5-5",
               "flagship": "claude-opus-5-5", "flagship_effort": "xhigh", "accounts": 1},
    "codex": {"plan": "ChatGPT Plus", "usd_month": 20, "tier": "pro_20", "pro_multiple": 1.0,
              "core": "gpt-6.1-sol", "core_effort": "medium", "helper": "gpt-6-luna",
              "flagship": "gpt-6-astra", "flagship_effort": "high", "accounts": 1},
    # The Ultra badge reads "Pro 대비 5x 사용량" (user screenshot 2026-11-04); 5x is a label, never a token figure.
    # high_route "main": Argon High is the paced main route for high-quality work, not a scarce flagship.
    "antigravity": {"plan": "Google AI Ultra", "usd_month": None, "tier": "ultra", "pro_multiple": 5.0,
                    "core": "gemini-4-argon", "core_effort": "medium", "helper": "gemini-3.5-flash-lite",
                    "flagship": "gemini-4-argon", "flagship_effort": "high", "accounts": 5, "high_route": "main"},
}
LOCAL_PREFIXES = ("qwen", "llama", "gemma", "mistral", "phi", "deepseek", "nomic")


class BudgetSnapshotError(RuntimeError):
    """A schedule tried to use a missing, stale or foreign budget snapshot (fail closed)."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


# ---------------------------------------------------------------- ledger (append-safe, parallel processes)
_DDL = """
CREATE TABLE IF NOT EXISTS observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tool TEXT NOT NULL, account TEXT NOT NULL, plan TEXT,
  window TEXT NOT NULL, window_min INTEGER, used_pct REAL NOT NULL, resets_at TEXT, observed_at TEXT NOT NULL,
  source TEXT NOT NULL, recorded_at TEXT NOT NULL,
  UNIQUE(tool, account, window, observed_at, source));
CREATE TABLE IF NOT EXISTS burn_receipts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, tool TEXT NOT NULL, model TEXT NOT NULL, effort TEXT,
  pct_per_hour REAL NOT NULL, window TEXT, basis TEXT NOT NULL, observed_at TEXT NOT NULL, note TEXT,
  UNIQUE(tool, model, effort, basis, observed_at));
CREATE TABLE IF NOT EXISTS snapshots (
  id TEXT PRIMARY KEY, generated_at TEXT NOT NULL, summary TEXT NOT NULL);
"""


def ledger_path(home: Path | None = None) -> Path:
    return (Path(home) if home is not None else Path.home()) / LEDGER_FILE


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + 30.0
    while True:
        try:
            con = sqlite3.connect(str(path), timeout=30.0)
            con.execute("PRAGMA busy_timeout=30000")
            con.execute("PRAGMA journal_mode=WAL")  # readers never block the writer
            con.executescript(_DDL)
            return con
        except sqlite3.OperationalError:
            # first creation races (journal_mode switch needs a moment alone); retry until the deadline
            if time.time() > deadline:
                raise
            time.sleep(0.05)


def record_observation(tool: str, window: str, used_pct: float, resets_at: Any, observed_at: Any, source: str,
                       *, account: str = "primary", plan: str | None = None, window_min: int | None = None,
                       home: Path | None = None) -> bool:
    """Append one provider window reading. Returns False when the same reading was already recorded."""
    if tool not in TOOLS or window not in ("5h", "7d"):
        raise ValueError(f"unknown tool/window {tool}/{window}")
    obs = _iso(_epoch(observed_at) or time.time())
    con = _connect(ledger_path(home))
    try:
        with con:
            cur = con.execute(
                "INSERT OR IGNORE INTO observations(tool, account, plan, window, window_min, used_pct, resets_at, "
                "observed_at, source, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (tool, account, plan or PLANS[tool]["plan"], window,
                 int(window_min or (300 if window == "5h" else 10080)), float(used_pct),
                 _iso(_epoch(resets_at)), obs, source, _iso(time.time())))
            return cur.rowcount == 1
    finally:
        con.close()


def record_burn_receipt(receipt: dict[str, Any], home: Path | None = None) -> bool:
    con = _connect(ledger_path(home))
    try:
        with con:
            cur = con.execute(
                "INSERT OR IGNORE INTO burn_receipts(tool, model, effort, pct_per_hour, window, basis, observed_at, "
                "note) VALUES (?,?,?,?,?,?,?,?)",
                (receipt["tool"], receipt["model"], receipt.get("effort"), float(receipt["pct_per_hour"]),
                 receipt.get("window"), receipt["basis"], receipt["observed_at"], receipt.get("note")))
            return cur.rowcount == 1
    finally:
        con.close()


def read_observations(tool: str, window: str, *, account: str = "primary", home: Path | None = None,
                      since: float | None = None) -> list[dict[str, Any]]:
    path = ledger_path(home)
    if not path.is_file():
        return []
    con = _connect(path)
    try:
        rows = con.execute(
            "SELECT used_pct, resets_at, observed_at, source FROM observations WHERE tool=? AND window=? "
            "AND account=? ORDER BY observed_at", (tool, window, account)).fetchall()
    finally:
        con.close()
    out = []
    for used, reset, obs, src in rows:
        ts = _epoch(obs)
        if ts is not None and (since is None or ts >= since):
            out.append({"ts": ts, "used_pct": float(used), "resets_at": _epoch(reset), "source": src})
    return out


def read_burn_receipts(tool: str, home: Path | None = None) -> list[dict[str, Any]]:
    path = ledger_path(home)
    if not path.is_file():
        return []
    con = _connect(path)
    try:
        rows = con.execute("SELECT model, effort, pct_per_hour, window, basis, observed_at, note FROM burn_receipts "
                           "WHERE tool=? ORDER BY observed_at", (tool,)).fetchall()
    finally:
        con.close()
    keys = ("model", "effort", "pct_per_hour", "window", "basis", "observed_at", "note")
    return [dict(zip(keys, r)) for r in rows]


# ---------------------------------------------------------------- pacing
def pace(window: dict[str, Any] | None, history: list[dict[str, Any]], now: float) -> dict[str, Any] | None:
    """Sustainable burn (remaining % / hours to reset) against the measured burn of the same reset window.

    headroom = sustainable / measured: >= 1 lasts to the reset, < 1 runs out first (projected at exhaust_in_h).
    Measured burn: slope of ledger readings of this reset window (>= 10 min apart, last 6 h), else the window
    average (used % / hours since the window opened). No reading: headroom None (neutral, never optimistic).
    """
    if not window:
        return None
    used = float(window.get("used_pct") or 0.0)
    remaining = max(0.0, 100.0 - used)
    reset_ts = _epoch(window.get("resets_at"))
    win_h = float(window.get("window_min") or 300) / 60.0
    hours_left = None if reset_ts is None else max(0.0, (reset_ts - now) / 3600.0)
    out: dict[str, Any] = {"used_pct": round(used, 1), "remaining_pct": round(remaining, 1),
                           "resets_at": _iso(reset_ts), "hours_to_reset": None if hours_left is None
                           else round(hours_left, 2), "window_min": int(window.get("window_min") or 300),
                           "observed_at": window.get("observed_at"), "age_s": window.get("age_s"),
                           "stale": bool((window.get("age_s") or 0) > OBS_STALE_S and not window.get("reset_elapsed"))}
    if remaining <= 0:
        out.update(state="LIMITED", sustainable_pct_per_h=0.0, burn_pct_per_h=None, burn_basis="exhausted",
                   headroom=0.0, exhaust_in_h=0.0)
        return out
    sustainable = remaining / hours_left if hours_left else None
    burn, basis = None, "no_reading"
    if not window.get("reset_elapsed"):
        pts = [p for p in history if p.get("resets_at") is not None and reset_ts is not None
               and abs(p["resets_at"] - reset_ts) <= RESET_MATCH_S and p["ts"] >= now - SLOPE_LOOKBACK_S]
        pts.sort(key=lambda p: p["ts"])
        d_used = (pts[-1]["used_pct"] - pts[0]["used_pct"]) if len(pts) >= 2 else 0.0
        obs_ts = _epoch(window.get("observed_at")) or now
        # hours the window had been open when the reading was taken (not now: the reading may be hours old)
        open_h = None if reset_ts is None else win_h - max(0.0, (reset_ts - obs_ts) / 3600.0)
        if len(pts) >= 2 and pts[-1]["ts"] - pts[0]["ts"] >= SLOPE_MIN_SPAN_S and d_used >= SLOPE_MIN_DELTA_PCT:
            burn, basis = d_used / ((pts[-1]["ts"] - pts[0]["ts"]) / 3600.0), f"ledger_slope(n={len(pts)})"
        elif open_h is not None and open_h >= 0.1:
            burn, basis = used / open_h, "window_average"
    headroom = None
    if sustainable is not None and burn is not None:
        headroom = math.inf if burn == 0 else sustainable / burn
    out.update(state="OK", sustainable_pct_per_h=None if sustainable is None else round(sustainable, 3),
               burn_pct_per_h=None if burn is None else round(burn, 3), burn_basis=basis,
               headroom=None if headroom is None else (999.0 if math.isinf(headroom) else round(headroom, 3)),
               exhaust_in_h=None if not burn else round(remaining / burn, 2))
    if headroom is not None and headroom < 1.0:
        out["state"] = "BEHIND_PACE"
    return out


def binding_headroom(paces: list[dict[str, Any] | None]) -> float | None:
    """The tighter window decides: any exhausted window blocks, otherwise the smallest measured headroom."""
    vals = [p for p in paces if p]
    if any(p["state"] == "LIMITED" for p in vals):
        return 0.0
    hs = [p["headroom"] for p in vals if p.get("headroom") is not None]
    return min(hs) if hs else None


# ---------------------------------------------------------------- allocator
def derive_split(mix: dict[str, float], helper_cost: float | None, headroom: float | None) -> dict[str, Any]:
    """Shares of steps (local, helper, core) so the paid burn per step fits the measured headroom.

    Cost per step: core 1, helper `helper_cost` (measured/official ratio; unmeasured = 1, no saving claimed),
    local 0. With headroom >= 1 (or unmeasured) the measured mix stands, only clamped to the quality bounds.
    Below 1 the burn must fall to headroom x today's: move core -> helper (keeps quality closer to core), then
    core -> local, then helper -> local, never past the bounds. What is still missing becomes a slower paid pace
    (`paid_step_rate` < 1) instead of a quality cut.
    """
    tot = sum(max(0.0, float(mix.get(k) or 0.0)) for k in ("local", "helper", "core"))
    if tot <= 0:
        loc, hlp, core = 0.0, 0.0, 1.0
    else:
        loc, hlp, core = (max(0.0, float(mix.get(k) or 0.0)) / tot for k in ("local", "helper", "core"))
    # quality bounds first: excess local/helper share returns to core
    over_l, over_h = max(0.0, loc - LOCAL_CEIL), max(0.0, hlp - HELPER_CEIL)
    loc, hlp, core = loc - over_l, hlp - over_h, core + over_l + over_h
    c_h = 1.0 if helper_cost is None else max(0.0, float(helper_cost))

    def cost(lo: float, he: float, co: float) -> float:
        return co + he * c_h

    base = cost(loc, hlp, core)
    target = base if (headroom is None or headroom >= 1.0) else base * max(0.0, headroom)
    if core < CORE_FLOOR and base > 0:  # measured mix below the core floor: lift it, quality first
        take = CORE_FLOOR - core
        from_l = min(loc, take)
        loc, core = loc - from_l, core + from_l
        hlp, core = hlp - (take - from_l), core + (take - from_l)
    moves = []
    gap = cost(loc, hlp, core) - target
    if gap > 1e-9 and c_h < 1.0:
        x = min(gap / (1.0 - c_h), HELPER_CEIL - hlp, core - CORE_FLOOR)
        if x > 0:
            hlp, core, gap = hlp + x, core - x, gap - x * (1.0 - c_h)
            moves.append(f"core->helper {x:.2f}")
    if gap > 1e-9:
        y = min(gap, LOCAL_CEIL - loc, core - CORE_FLOOR)
        if y > 0:
            loc, core, gap = loc + y, core - y, gap - y
            moves.append(f"core->local {y:.2f}")
    if gap > 1e-9 and c_h > 0:
        z = min(gap / c_h, LOCAL_CEIL - loc, hlp)
        if z > 0:
            loc, hlp, gap = loc + z, hlp - z, gap - z * c_h
            moves.append(f"helper->local {z:.2f}")
    final = cost(loc, hlp, core)
    rate = 1.0 if final <= target + 1e-9 or final <= 0 else target / final
    shares = {"local": round(loc, 3), "helper": round(hlp, 3), "core": round(core, 3)}
    return {
        "shares": shares,
        "label": f"Ollama {round(loc * 100)} : helper {round(hlp * 100)} : core {round(core * 100)}",
        "helper_cost": None if helper_cost is None else round(c_h, 4),
        "paid_cost_per_step": round(final, 4),
        "paid_step_rate": round(rate, 3),
        "moves": moves,
    }


def flagship_allowance(tool: str, paces: dict[str, dict[str, Any] | None], headroom: float | None,
                       flagship_ratio: float | None, receipts: list[dict[str, Any]],
                       steps_per_5h: float | None) -> dict[str, Any]:
    """Share of paid steps the flagship may take in this window, and the per-5 h step cap.

    With a per-model burn receipt (%/h when run continuously): duty = sustainable %/h x (1 - reserve) / receipt.
    Otherwise from spare headroom: converting share s of core steps to a flagship that costs f x core raises the
    burn by s x (f - 1), so s <= (headroom - 1) / (f - 1). Both are capped by the plan cap.
    """
    plan = PLANS[tool]
    cap = FLAGSHIP_SHARE_CAP.get(plan["tier"], FLAGSHIP_SHARE_CAP["pro_20"])
    weekly, five = paces.get("7d"), paces.get("5h")
    reasons: list[str] = []
    share = 0.0
    basis = "none"
    if headroom is None:
        reasons.append("headroom unmeasured: flagship waits for a measured pace")
    elif headroom < 1.0:
        reasons.append(f"behind pace (headroom {headroom:.2f} < 1)")
    else:
        rec = next((r for r in reversed(receipts) if r.get("model") == plan["flagship"]
                    and (r.get("effort") or "") == plan["flagship_effort"]), None)
        sus = (weekly or {}).get("sustainable_pct_per_h")
        rem_w = (weekly or {}).get("remaining_pct")
        if rec and sus is not None and rem_w:
            usable = max(0.0, rem_w - WEEKLY_RESERVE_PCT) / rem_w
            share, basis = sus * usable / float(rec["pct_per_hour"]), f"burn_receipt:{rec['basis']}"
        elif flagship_ratio and flagship_ratio > 1.0:
            share, basis = (min(headroom, 999.0) - 1.0) / (flagship_ratio - 1.0), "spare_headroom/ratio"
        else:
            reasons.append("flagship cost ratio unmeasured")
    if weekly and weekly.get("remaining_pct", 0.0) <= WEEKLY_RESERVE_PCT:
        share = 0.0
        reasons.append(f"weekly left {weekly.get('remaining_pct')} % <= reserve {WEEKLY_RESERVE_PCT} %")
    if five and five.get("remaining_pct", 100.0) < FLAGSHIP_MIN_5H_PCT:
        share = 0.0
        reasons.append(f"5h left {five.get('remaining_pct')} % < {FLAGSHIP_MIN_5H_PCT} %")
    share = max(0.0, min(cap, share))
    max_steps = 0
    if share > 0:
        # at least one keypoint shot when the budget allows any flagship at all ("한방")
        max_steps = max(1, int(share * steps_per_5h)) if steps_per_5h else 1
    return {"model": plan["flagship"], "effort": plan["flagship_effort"], "plan_cap": cap,
            "share": round(share, 3), "basis": basis, "max_steps_5h": max_steps,
            "ratio_vs_core": None if flagship_ratio is None else round(flagship_ratio, 3), "blocked_by": reasons}


def main_route_allowance(tool: str, paces: dict[str, dict[str, Any] | None], mix: dict[str, Any],
                         calibration: dict[str, Any] | None, receipts: list[dict[str, Any]]) -> dict[str, Any]:
    """Ultra plan: how often Argon High may run as the main high-quality route until the weekly reset.

    frequency (steps/h) = (measured remaining % - reserve) / measured cost of one step / hours to reset.
    The step cost is calibrated tokens per step / tokens per 1 % when both are measured (the token form of the
    rule), else the measured window burn (%/h) / measured paid steps per hour: the same quantity in % units, so no
    remaining % is ever turned into tokens without a calibration. share = frequency / measured paid steps per hour.
    """
    plan = PLANS[tool]
    weekly, five = paces.get("7d"), paces.get("5h")
    target = min(1.0, ULTRA_TARGET_MULTIPLE * FLAGSHIP_SHARE_CAP["pro_20"])
    out: dict[str, Any] = {"route": "main", "model": plan["flagship"], "effort": plan["flagship_effort"],
                           "plan_cap": 1.0, "target_share": round(target, 3), "share": 0.0, "basis": "none",
                           "steps_per_h": None, "pct_per_step": None, "max_steps_5h": 0, "blocked_by": [],
                           "reserve_pct": WEEKLY_RESERVE_PCT}
    reasons = out["blocked_by"]
    paid7 = int(mix.get("core") or 0) + int(mix.get("helper") or 0)
    measured_rate = paid7 / 168.0 if paid7 else None
    if not weekly or not weekly.get("hours_to_reset"):
        reasons.append("weekly pool unmeasured: main route waits for a measured reading")
        return out
    rem, hours = float(weekly.get("remaining_pct") or 0.0), float(weekly["hours_to_reset"])
    usable = max(0.0, rem - WEEKLY_RESERVE_PCT)
    tpp = (calibration or {}).get("tokens_per_pct")
    tok_step = mix.get("tokens_per_step")
    burn = weekly.get("burn_pct_per_h")
    costs: list[tuple[float, str]] = []
    if tpp and tok_step:
        costs.append((float(tok_step) / float(tpp), f"calibrated_tokens(n={(calibration or {}).get('samples')})"))
    if burn and measured_rate:
        costs.append((float(burn) / measured_rate, f"window_burn/steps_7d({weekly.get('burn_basis')})"))
    if not costs:
        reasons.append("cost per step unmeasured (no calibration and no burn/step count)")
        return out
    # When both measurements exist they can disagree (2026-11-04: 0.019 vs 0.047 %/step, calibration n=1); pacing
    # by the costlier one is the side on which the pool still lasts to its reset.
    pct_step, basis = max(costs, key=lambda c: c[0])
    out["pct_per_step"], out["basis"] = round(pct_step, 5), basis
    out["cost_measurements"] = {b: round(c, 5) for c, b in costs}
    if usable <= 0:
        reasons.append(f"weekly left {rem} % <= reserve {WEEKLY_RESERVE_PCT} %")
        return out
    if five and five.get("remaining_pct", 100.0) <= 0.0:
        reasons.append("5h pool exhausted until its reset")
        return out
    freq = usable / pct_step / hours
    out["steps_per_h"] = round(freq, 3)
    out["max_steps_5h"] = int(freq * 5.0)
    out["share"] = round(min(1.0, freq / measured_rate), 3) if measured_rate else 0.0
    if out["max_steps_5h"] < 1:
        out["share"] = 0.0
        reasons.append(f"pace allows {freq:.3f} steps/h (< 1 per 5 h)")
    # the measured pool is the hard limit; falling short of the 5x planning target is reported, never overridden
    out["meets_5x_target"] = out["share"] >= target
    if 0 < out["share"] < target:
        out["note"] = f"below 5x target {target:.2f}: measured pool allows {out['share']:.3f}"
    rec = next((r for r in reversed(receipts) if r.get("model") == plan["flagship"]
                and (r.get("effort") or "") == plan["flagship_effort"]), None)
    if rec and weekly.get("sustainable_pct_per_h") is not None:
        # cross-check only: the duty a continuous Argon High run could keep (sustainable / receipt burn)
        out["receipt_duty"] = round(float(weekly["sustainable_pct_per_h"]) * usable / rem / float(rec["pct_per_hour"]), 3) if rem else 0.0
    return out


def flagship_gate(snapshot: dict[str, Any], tool: str, *, importance: int, difficulty: int,
                  cheaper_route_failed: str | None = None, keypoint_class: str | None = None,
                  used_steps_5h: int = 0, now: float | None = None) -> dict[str, Any]:
    """Written entry requirements for the high-effort route (docs/108 §6).

    $20 plans (Opus 5.5 xhigh, GPT-6 Astra High), scarce "한방처방": R0 fresh snapshot; R1 importance x difficulty
    >= 16; R2 a failed cheaper attempt (its work_id) or a keypoint class; R3 budget: the allocator grants a share and
    the 5 h step cap is not used up. Ultra main route (Argon High): R0 and R3 only - any high-quality step may use it
    while the measured pace allows. Any failed rule routes the step to the cost-efficient core model.
    """
    require_fresh_snapshot(snapshot, now=now)
    t = (snapshot.get("tools") or {}).get(tool) or {}
    fl = t.get("flagship") or {}
    plan = PLANS[tool]
    main = plan.get("high_route") == "main"
    failed: list[str] = []
    score = int(importance) * int(difficulty)
    if not (1 <= int(importance) <= 5 and 1 <= int(difficulty) <= 5):
        raise ValueError("importance and difficulty are 1-5")
    if not main and score < FLAGSHIP_MIN_SCORE:
        failed.append(f"R1 score {score} < {FLAGSHIP_MIN_SCORE}")
    if not main and not cheaper_route_failed and keypoint_class not in KEYPOINT_CLASSES:
        failed.append("R2 no failed cheaper attempt and no keypoint class")
    if not fl.get("share"):
        failed.append("R3 no flagship budget: " + ("; ".join(fl.get("blocked_by") or []) or "share 0"))
    elif used_steps_5h >= int(fl.get("max_steps_5h") or 0):
        failed.append(f"R3 5h flagship cap used ({used_steps_5h}/{fl.get('max_steps_5h')})")
    allow = not failed
    return {"allow": allow, "tool": tool, "score": score,
            "model": plan["flagship"] if allow else plan["core"],
            "effort": plan["flagship_effort"] if allow else plan["core_effort"],
            "failed_rules": failed, "snapshot_id": snapshot.get("id")}


# ---------------------------------------------------------------- measured inputs
def _is_local(model: str) -> bool:
    return str(model or "").lower().startswith(LOCAL_PREFIXES)


def offload_attempts(home: Path, now: float) -> dict[str, dict[str, int]]:
    """Ollama and helper attempts per calling tool in 7 days, from the Ollama/Haiku journal."""
    db = home / ".uaos" / "usage" / "invocations.sqlite3"
    out: dict[str, dict[str, int]] = {}
    if not db.is_file():
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute("SELECT caller, model, outcome, COUNT(*), SUM(COALESCE(input_tokens,0)"
                               "+COALESCE(output_tokens,0)) FROM attempts WHERE started_at >= ? "
                               "GROUP BY 1,2,3", (now - 7 * 86400,)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return out
    for caller, model, outcome, n, tok in rows:
        d = out.setdefault(str(caller or "unknown"), {"local_ok": 0, "local_failed": 0, "local_tokens": 0,
                                                     "helper_ok": 0, "helper_failed": 0})
        kind = "local" if _is_local(model) else "helper"
        if outcome == "SUCCEEDED":
            d[f"{kind}_ok"] += int(n or 0)
            if kind == "local":
                d["local_tokens"] += int(tok or 0)
        elif outcome == "FAILED":
            d[f"{kind}_failed"] += int(n or 0)
    return out


def claude_events(home: Path, now: float) -> list[dict[str, Any]]:
    """Claude token events (ts, raw_total) from the UAOS ledger, for calibrating the Claude windows."""
    db = home / ".uaos" / "usage" / "ledger.sqlite3"
    if not db.is_file():
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        try:
            rows = con.execute(
                "SELECT timestamp, COALESCE(uncached_input,0)+COALESCE(cache_read,0)+COALESCE(cache_write,0)"
                "+COALESCE(output,0) FROM contributions WHERE provider='claude' AND timestamp >= ?",
                (_iso(now - 7 * 86400),)).fetchall()
        finally:
            con.close()
    except sqlite3.Error:
        return []
    return [{"ts": _epoch(t), "raw_total": int(n or 0)} for t, n in rows if _epoch(t) is not None]


def _window_from_ledger(tool: str, window: str, home: Path, now: float) -> dict[str, Any] | None:
    rows = read_observations(tool, window, home=home)
    if not rows:
        return None
    last = rows[-1]
    fact = window_fact(last["used_pct"], last["resets_at"], 300 if window == "5h" else 10080, last["ts"], now)
    if fact:
        fact["source"] = f"budget_ledger:{last['source']}"
    return fact


def _mask(email: str | None) -> str | None:
    if not email or "@" not in email:
        return email
    name, dom = email.split("@", 1)
    return f"{name[:2]}***{name[-2:]}@{dom}"  # first and last two characters: distinct, never the full address


def antigravity_account_pools(home: Path, now: float, registry: dict[str, Any] | None) -> list[dict[str, Any]]:
    """One row per Antigravity account: plan/kind (U286 registry) and its own cockpit quota pools."""
    caches: dict[str, dict[str, Any]] = {}
    for path in glob.glob(str(home / ".antigravity_cockpit" / "cache" / "quota_api_v1_plugin" / "*" / "*.json")):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        updated = _epoch(data.get("updatedAt")) or os.path.getmtime(path)
        pools: dict[tuple, dict[str, Any]] = {}
        for m in ((data.get("payload") or {}).get("models") or {}).values():
            q = (m or {}).get("quotaInfo") or {}
            if "remainingFraction" not in q or not q.get("resetTime"):
                continue
            sig = (round(float(q["remainingFraction"]), 6), q.get("resetTime"))
            pools.setdefault(sig, {"models": []})["models"].append(m.get("displayName") or "?")
        facts = []
        for (frac, reset), p in pools.items():
            reset_ts = _epoch(reset)
            win = 300 if (reset_ts is not None and reset_ts - updated <= 6 * 3600) else 10080
            f = window_fact(round((1.0 - frac) * 100.0, 4), reset, win, updated, now)
            if f:
                f["models"] = sorted(set(p["models"]))[:4]
                facts.append(f)
        caches[str(data.get("email") or Path(path).stem)] = {"observed_at": _iso(updated), "pools": facts,
                                                             "age_s": int(now - updated)}
    rows = []
    for acc in (registry or {}).get("accounts") or []:
        email = acc.get("email")
        c = caches.pop(email, None) or {}
        rows.append({"account": _mask(email), "plan": acc.get("plan"), "kind": acc.get("kind"),
                     "signed_in": acc.get("signed_in"), "blocked_429": acc.get("blocked"),
                     "resets_at_429": acc.get("resets_at"), "cache_observed_at": c.get("observed_at"),
                     "cache_age_s": c.get("age_s"), "cache_stale": bool(c and c["age_s"] > OBS_STALE_S),
                     "pools": c.get("pools") or []})
    for email, c in caches.items():  # a cache with no registry row is still shown, unidentified
        rows.append({"account": _mask(email), "plan": None, "kind": "unregistered", "cache_observed_at":
                     c["observed_at"], "cache_age_s": c["age_s"], "cache_stale": c["age_s"] > OBS_STALE_S,
                     "pools": c["pools"]})
    return rows


def _core_family(tool: str, model: str) -> str:
    p = PLANS[tool]
    m = str(model or "").lower()
    if tool == "codex" and m.startswith("gpt-6-astra"):
        return "flagship"
    if m.startswith(p["core"]) or (tool == "claude" and m.startswith("claude-opus")):
        return "core"
    return "helper"


def measured_mix(tool: str, measured: dict[str, Any], engines: dict[str, Any],
                 offload: dict[str, dict[str, int]]) -> dict[str, Any]:
    """7-day step mix of one tool: local (its Ollama successes), helper and core (paid model calls)."""
    off = offload.get(tool) or {}
    m = measured.get(tool) or {}
    core = helper = flagship = 0
    core_out = helper_out = 0
    helper_models: dict[str, int] = {}
    rows = m.get("model_mix_7d") or []
    for r in rows:
        fam = _core_family(tool, r.get("model"))
        if fam == "core":
            core, core_out = core + int(r["calls"]), core_out + int(r.get("output_tokens") or 0)
        elif fam == "flagship":
            flagship += int(r["calls"])
        else:
            helper, helper_out = helper + int(r["calls"]), helper_out + int(r.get("output_tokens") or 0)
            helper_models[str(r.get("model"))] = helper_models.get(str(r.get("model")), 0) + int(r["calls"])
    basis = "ledger.contributions(7d)"
    if not rows:  # Antigravity has no per-model ledger: its steps come from the capacity snapshot (brain steps)
        core = int((((engines.get(tool) or {}).get("window_7d")) or {}).get("calls") or 0)
        helper = int(off.get("helper_ok") or 0)
        basis = "capacity.window_7d.calls + journal helper attempts"
    local = int(off.get("local_ok") or 0)
    return {"local": local, "helper": helper, "core": core + flagship, "flagship": flagship, "basis": basis,
            "helper_models": helper_models,
            "core_output_per_call": round(core_out / core, 1) if core else None,
            "helper_output_per_call": round(helper_out / helper, 1) if helper and helper_out else None,
            "local_failed": int(off.get("local_failed") or 0), "local_tokens": int(off.get("local_tokens") or 0)}


def helper_cost_ratio(tool: str, mix: dict[str, Any]) -> tuple[float | None, str]:
    """Quota cost of one helper step relative to one core step."""
    if tool == "codex":
        lo = CODEX_MSGS_PER_5H
        mid = lambda k: sum(lo[k]) / 2.0  # noqa: E731
        core = mid(PLANS["codex"]["core"])
        # call-weighted over the helpers actually used (Luna, Terra); an unlisted model weighs like the core
        used = {k: n for k, n in (mix.get("helper_models") or {}).items() if n}
        if used:
            w = sum(n * (core / mid(k) if k in lo else 1.0) for k, n in used.items()) / sum(used.values())
            return w, f"official_msgs_per_5h(call-weighted):{CODEX_PRICING_URL}"
        return core / mid(PLANS["codex"]["helper"]), f"official_msgs_per_5h:{CODEX_PRICING_URL}"
    a, b = mix.get("helper_output_per_call"), mix.get("core_output_per_call")
    if a and b:
        # output tokens per call is measured; the quota weight per token is not published, so this ratio can only
        # overstate the helper's cost (a cheaper model's token weighs no more than the core's)
        return a / b, "measured_output_tokens_per_call (upper bound: quota weight unpublished)"
    return None, "UNMEASURED"


def flagship_cost_ratio(tool: str) -> tuple[float | None, str]:
    if tool == "codex":
        lo = CODEX_MSGS_PER_5H
        return (sum(lo["gpt-6.1-sol"]) / 2.0) / (sum(lo["gpt-6-astra"]) / 2.0), f"official_msgs_per_5h:{CODEX_PRICING_URL}"
    if tool == "claude":
        # No published Opus xhigh-vs-medium ratio: borrow the only official measurement (Codex Astra vs Sol, 3.5x),
        # which also is the largest measured ratio, so the allowance errs small.
        return flagship_cost_ratio("codex")[0], "borrowed:codex_official_ratio (Claude ratio unpublished)"
    return None, "burn_receipt (see receipts)"


def offload_headroom(tool: str, mix: dict[str, Any], cal: dict[str, Any] | None) -> dict[str, Any]:
    """Weekly points the Ollama offload kept off the paid pool: local tokens / calibrated tokens-per-1 %.

    The local tokens are measured (journal); the like-for-like premise is that the same text would have been read
    and written by the core model at least once, so this is a floor. The helper's saving needs a quota weight per
    token that no provider publishes, except Codex's official per-message estimates.
    """
    tpp = (cal or {}).get("tokens_per_pct")
    loc_tok = int(mix.get("local_tokens") or 0)
    out = {"local_steps_7d": mix.get("local"), "local_tokens_7d": loc_tok, "helper_steps_7d": mix.get("helper"),
           "tokens_per_pct": tpp, "calibration": None if not cal else f"{cal.get('basis')}(n={cal.get('samples')})"}
    out["local_headroom_pct_7d"] = round(loc_tok / tpp, 3) if tpp else None
    if tool == "codex" and mix.get("helper"):
        c_h, _ = helper_cost_ratio("codex", mix)
        out["helper_saved_core_steps_7d"] = round(mix["helper"] * (1.0 - c_h), 1)
    else:
        out["helper_saved_core_steps_7d"] = None
    out["helper_basis"] = "official_msgs_per_5h" if tool == "codex" else "UNMEASURED (quota weight unpublished)"
    return out


# ---------------------------------------------------------------- snapshot
def _capacity(project_root: Path, home: Path, now: float) -> dict[str, Any]:
    from .capacity_planner import collect_capacity_snapshot
    from .hook_context import shared_desk
    persisted = shared_desk(Path(project_root)) / ".coord" / "usage" / "capacity_snapshot.json"
    try:
        snap = json.loads(persisted.read_text(encoding="utf-8"))
        if now - float(snap.get("timestamp") or 0) <= FRESH_S and home == Path.home():
            return snap
    except (OSError, ValueError):
        pass
    return collect_capacity_snapshot(Path(project_root), home=home, now=now, persist=False)


def _tool_windows(tool: str, measured: dict[str, Any], home: Path, now: float) -> dict[str, Any]:
    m = measured.get(tool) or {}
    if tool == "antigravity":
        # Argon (core and flagship) and Flash-Lite (helper) draw on the Gemini pool; the Claude/GPT-OSS pool inside
        # Antigravity is a different pool and does not bind the Gemini models. Pools are chosen by their models and
        # window length, not by the last selected model (that key is often empty).
        pools = [p for p in (m.get("pools") or []) if p]
        gem = [p for p in pools if any("gemini" in str(x).lower() for x in p.get("models") or [])]
        pick = lambda wm: next((p for p in gem if p.get("window_min") == wm), None)  # noqa: E731
        return {"7d": pick(10080), "5h": pick(300)}
    out = {"5h": m.get("five_hour"), "7d": m.get("seven_day")}
    for key in ("5h", "7d"):
        led = _window_from_ledger(tool, key, home, now)
        cur = out[key]
        # the newer reading wins; the statusLine/rollout source and the manual observation share one scale
        if led and (not cur or (_epoch(led.get("observed_at")) or 0) > (_epoch(cur.get("observed_at")) or 0)):
            out[key] = led
    return out


def _calibrations(tool: str, measured: dict[str, Any], windows: dict[str, Any], home: Path,
                  now: float) -> dict[str, Any]:
    m = measured.get(tool) or {}
    if tool == "antigravity":
        # U303 calibrated the selected pool only; reuse it only when that pool is the one chosen here
        sel, w7 = m.get("selected_pool") or {}, windows.get("7d") or {}
        same = bool(sel and w7 and sel.get("resets_at") == w7.get("resets_at"))
        return {"7d": m.get("calibration") if same else None, "5h": None}
    cal = {"5h": m.get("calibration_5h"), "7d": m.get("calibration_7d")}
    if tool == "claude" and (not cal["5h"] or not cal["7d"]):
        evs = claude_events(home, now)
        hist = read_observations("claude", "5h", home=home)
        cal["5h"] = cal["5h"] or calibrate(windows.get("5h"), evs, now, hist)
        cal["7d"] = cal["7d"] or calibrate(windows.get("7d"), evs, now)
    return cal


def _tokens(pct: float | None, cal: dict[str, Any] | None) -> int | None:
    tpp = (cal or {}).get("tokens_per_pct")
    return None if (pct is None or not tpp) else int(round(tpp * pct))


def build_snapshot(project_root: Path, *, home: Path | None = None, now: float | None = None,
                   capacity: dict[str, Any] | None = None, record: bool = True) -> dict[str, Any]:
    """Compute the budget snapshot from measured sources and append its readings to the ledger."""
    moment = float(now if now is not None else time.time())
    home_dir = Path(home) if home is not None else Path.home()
    cap = capacity if capacity is not None else _capacity(Path(project_root), home_dir, moment)
    measured = cap.get("measured_accounts") or {}
    engines = cap.get("engines") or {}
    if record:
        record_burn_receipt(ULTRA_ARGON_HIGH_RECEIPT, home=home_dir)
    offload = offload_attempts(home_dir, moment)
    tools: dict[str, Any] = {}
    for tool in TOOLS:
        windows = _tool_windows(tool, measured, home_dir, moment)
        if record:
            for key, w in windows.items():
                if w and w.get("observed_used_pct") is not None and w.get("observed_at"):
                    src = str(w.get("source") or (measured.get(tool) or {}).get("source") or "measured")
                    if not src.startswith("budget_ledger:"):
                        record_observation(tool, key, w["observed_used_pct"], w.get("resets_at"), w["observed_at"],
                                           src, window_min=w.get("window_min"), home=home_dir)
        cals = _calibrations(tool, measured, windows, home_dir, moment)
        paces = {k: pace(w, read_observations(tool, k, home=home_dir, since=moment - SLOPE_LOOKBACK_S), moment)
                 for k, w in windows.items()}
        for k, p in paces.items():
            if p:
                p["remaining_tokens"] = _tokens(p["remaining_pct"], cals.get(k))
                p["capacity_tokens"] = (cals.get(k) or {}).get("capacity_tokens")
                p["sustainable_tokens_per_h"] = _tokens(p.get("sustainable_pct_per_h"), cals.get(k))
                p["calibration"] = None if not cals.get(k) else (
                    f"{cals[k].get('basis')}(n={cals[k].get('samples')})")
        head = binding_headroom(list(paces.values()))
        mix = measured_mix(tool, measured, engines, offload)
        c_h, c_h_basis = helper_cost_ratio(tool, mix)
        split = derive_split(mix, c_h if (c_h is not None and c_h < 1.0) else None, head)
        split["helper_cost_basis"] = c_h_basis
        split["helper_cost_measured"] = None if c_h is None else round(c_h, 4)
        steps_5h = None
        total7 = mix["local"] + mix["helper"] + mix["core"]
        if total7:
            steps_5h = round((mix["core"] + mix["helper"]) * 300.0 / 10080.0, 1)
        if PLANS[tool].get("high_route") == "main":
            w7 = ((engines.get(tool) or {}).get("window_7d")) or {}
            # raw_total is the token count the U303 calibration divides by Δ%, so both sides share one unit
            if w7.get("raw_total_tokens") and w7.get("calls"):
                mix["tokens_per_step"] = round(float(w7["raw_total_tokens"]) / float(w7["calls"]), 1)
            fl = main_route_allowance(tool, paces, mix, cals.get("7d"), read_burn_receipts(tool, home=home_dir))
        else:
            f_ratio, f_basis = flagship_cost_ratio(tool)
            fl = flagship_allowance(tool, paces, head, f_ratio, read_burn_receipts(tool, home=home_dir), steps_5h)
            fl["ratio_basis"] = f_basis
        state = "LIMITED" if head == 0.0 else ("BEHIND_PACE" if head is not None and head < 1.0
                                                else "UNMEASURED" if head is None else "ON_PACE")
        tools[tool] = {
            "plan": PLANS[tool]["plan"], "pro_multiple": PLANS[tool]["pro_multiple"],
            "core_model": PLANS[tool]["core"], "helper_model": PLANS[tool]["helper"],
            "state": state, "headroom": head, "windows": paces, "measured_mix_7d": mix, "split": split,
            "paid_steps_per_5h_measured": steps_5h, "flagship": fl,
            "offload_headroom": offload_headroom(tool, mix, cals.get("7d") or cals.get("5h")),
        }
    tools["antigravity"]["accounts"] = antigravity_account_pools(home_dir, moment, cap.get("antigravity_accounts"))
    snap = {"schema": SCHEMA, "generated_at": _iso(moment), "timestamp": moment,
            "fresh_until": _iso(moment + FRESH_S), "project": str(project_root), "tools": tools,
            "capacity_generated_at": cap.get("generated_at"),
            "unattributed_local_steps_7d": (offload.get("unknown") or {}).get("local_ok", 0)}
    snap["id"] = hashlib.sha256(json.dumps(snap, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]
    if record:
        con = _connect(ledger_path(home_dir))
        try:
            with con:
                con.execute("INSERT OR IGNORE INTO snapshots(id, generated_at, summary) VALUES (?,?,?)",
                            (snap["id"], snap["generated_at"], json.dumps(
                                {t: {"state": v["state"], "headroom": v["headroom"], "split": v["split"]["label"],
                                     "flagship_share": v["flagship"]["share"]} for t, v in tools.items()})))
        finally:
            con.close()
    return snap


def budget_snapshot(project_root: Path, *, home: Path | None = None, now: float | None = None,
                    capacity: dict[str, Any] | None = None, persist: bool = True,
                    refresh: bool = False) -> dict[str, Any]:
    """The mandatory schedule input: a fresh persisted snapshot, else a newly built one (persisted)."""
    from .hook_context import shared_desk
    moment = float(now if now is not None else time.time())
    path = shared_desk(Path(project_root)) / SNAPSHOT_FILE
    if capacity is None and home is None and not refresh:
        try:
            snap = json.loads(path.read_text(encoding="utf-8"))
            if snap.get("schema") == SCHEMA and 0 <= moment - float(snap.get("timestamp") or 0) <= FRESH_S:
                return snap
        except (OSError, ValueError):
            pass
    snap = build_snapshot(Path(project_root), home=home, now=moment, capacity=capacity)
    if persist:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(snap, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, path)
    return snap


def require_fresh_snapshot(snapshot: dict[str, Any] | None, *, now: float | None = None,
                           max_age_s: float = FRESH_S) -> dict[str, Any]:
    moment = float(now if now is not None else time.time())
    if not isinstance(snapshot, dict) or not snapshot:
        raise BudgetSnapshotError("BUDGET_SNAPSHOT_MISSING", "schedule writers must call budget_snapshot() first")
    if snapshot.get("schema") != SCHEMA or not snapshot.get("id"):
        raise BudgetSnapshotError("BUDGET_SNAPSHOT_SCHEMA", f"expected {SCHEMA}")
    age = moment - float(snapshot.get("timestamp") or 0)
    if age < -60 or age > max_age_s:
        raise BudgetSnapshotError("BUDGET_SNAPSHOT_STALE", f"age {int(age)} s > {int(max_age_s)} s")
    return snapshot


def stamp_schedule(schedule: dict[str, Any], snapshot: dict[str, Any], *, now: float | None = None) -> dict[str, Any]:
    """Attach the budget reference a schedule was written from (fails closed on a stale snapshot)."""
    require_fresh_snapshot(snapshot, now=now)
    schedule["budget_snapshot"] = {
        "id": snapshot["id"], "generated_at": snapshot["generated_at"], "timestamp": snapshot["timestamp"],
        "splits": {t: v["split"]["shares"] for t, v in snapshot["tools"].items()},
        "paid_step_rate": {t: v["split"]["paid_step_rate"] for t, v in snapshot["tools"].items()},
        "flagship_share": {t: v["flagship"]["share"] for t, v in snapshot["tools"].items()},
    }
    return schedule


def validate_schedule_budget(schedule: dict[str, Any], *, now: float | None = None,
                             max_age_s: float = FRESH_S) -> dict[str, Any]:
    """A schedule written without a fresh budget snapshot is refused."""
    ref = (schedule or {}).get("budget_snapshot")
    if not isinstance(ref, dict) or not ref.get("id"):
        raise BudgetSnapshotError("BUDGET_SNAPSHOT_MISSING", "schedule has no budget_snapshot stamp")
    moment = float(now if now is not None else time.time())
    age = moment - float(ref.get("timestamp") or 0)
    if age < -60 or age > max_age_s:
        raise BudgetSnapshotError("BUDGET_SNAPSHOT_STALE", f"schedule stamped {int(age)} s ago > {int(max_age_s)} s")
    return ref


def schedule_budget(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """U304-C's per-tool budget input (schedule_planner.BUDGET_KEYS) from a fresh snapshot.

    `measured_at` is the oldest window reading, not the snapshot build time, so a stale /usage reading fails the
    schedule's own freshness check; a window without a tokens-per-% calibration stays None and fails closed there.
    """
    require_fresh_snapshot(snapshot)
    out: dict[str, dict[str, Any]] = {}
    for tool, entry in (snapshot.get("tools") or {}).items():
        wins = entry.get("windows") or {}
        five, week = wins.get("5h") or {}, wins.get("7d") or {}
        seen = [w["observed_at"] for w in (five, week) if w.get("observed_at")]
        out[tool] = {"plan": entry.get("plan"), "measured_at": min(seen) if seen else None,
                     "remaining_5h_tokens": five.get("remaining_tokens"),
                     "remaining_week_tokens": week.get("remaining_tokens"),
                     "reset_5h_at": five.get("resets_at"), "reset_week_at": week.get("resets_at"),
                     "budget_snapshot_id": snapshot.get("id")}
    return out


def schedule_budget_for(project_root: Path) -> dict[str, dict[str, Any]]:
    """`coord schedule plan`'s provider: the shared desk's snapshot as U304-C's budget (refusal -> ValueError, exit 2)."""
    try:
        return schedule_budget(budget_snapshot(Path(project_root)))
    except BudgetSnapshotError as exc:
        raise ValueError(str(exc)) from exc


# ---------------------------------------------------------------- report
def render_text(snap: dict[str, Any]) -> str:
    def f(v: Any, unit: str = "") -> str:
        return "-" if v is None else f"{v}{unit}"

    lines = [f"budget snapshot {snap['id']} at {snap['generated_at']} (fresh until {snap['fresh_until']})"]
    for tool, t in snap["tools"].items():
        lines.append(f"[{tool}] {t['plan']} state={t['state']} headroom={f(t['headroom'])}")
        for key, p in (t.get("windows") or {}).items():
            if not p:
                lines.append(f"  {key}: no reading")
                continue
            lines.append(
                f"  {key}: used {p['used_pct']} % left {p['remaining_pct']} % reset {p['resets_at']} "
                f"({f(p['hours_to_reset'], ' h')}) burn {f(p['burn_pct_per_h'], ' %/h')} [{p['burn_basis']}] "
                f"sustainable {f(p['sustainable_pct_per_h'], ' %/h')} tokens left {f(p['remaining_tokens'])} "
                f"[{p['calibration'] or 'uncalibrated'}]{' STALE' if p.get('stale') else ''}")
        mx, sp, fl, off = t["measured_mix_7d"], t["split"], t["flagship"], t["offload_headroom"]
        lines.append(f"  measured 7d steps: local {mx['local']} helper {mx['helper']} core {mx['core']} "
                     f"(flagship {mx['flagship']}) [{mx['basis']}]")
        lines.append(f"  split: {sp['label']} paid_step_rate {sp['paid_step_rate']} helper_cost "
                     f"{f(sp['helper_cost_measured'])} [{sp['helper_cost_basis']}] {' '.join(sp['moves'])}")
        if fl.get("route") == "main":
            lines.append(f"  main route {fl['model']}/{fl['effort']}: share {fl['share']} (5x target "
                         f"{fl['target_share']}) {f(fl['steps_per_h'], ' steps/h')} max {fl['max_steps_5h']}/5h "
                         f"cost {f(fl['pct_per_step'], ' %/step')} [{fl['basis']}] reserve {fl['reserve_pct']} % "
                         f"{'; '.join(fl['blocked_by'] + ([fl['note']] if fl.get('note') else []))}")
        else:
            lines.append(f"  flagship {fl['model']}/{fl['effort']}: share {fl['share']} (cap {fl['plan_cap']}) "
                         f"max {fl['max_steps_5h']}/5h [{fl['basis']}] {'; '.join(fl['blocked_by'])}")
        lines.append(f"  offload: local tokens 7d {off['local_tokens_7d']} = {f(off['local_headroom_pct_7d'], ' %')} "
                     f"of pool; helper saved core steps {f(off['helper_saved_core_steps_7d'])} [{off['helper_basis']}]")
    for acc in snap["tools"]["antigravity"].get("accounts") or []:
        pools = ", ".join(f"{p['window_min'] // 60}h-pool used {p['used_pct']} %" for p in acc.get("pools") or [])
        lines.append(f"  agy account {acc['account']} {acc.get('plan')}/{acc.get('kind')} cache "
                     f"{acc.get('cache_observed_at')}{' STALE' if acc.get('cache_stale') else ''} {pools}")
    return "\n".join(lines)
