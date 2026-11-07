"""U303: measured account quota, calibrated token capacity, and model/effort facts for the HUD.

Every number here comes from a local file the provider tools already write (read-only, zero paid tokens,
no credential is opened or printed):

- Codex: `~/.codex/sessions/**/rollout-*.jsonl` `token_count.rate_limits` (limit_id `codex`):
  primary = 300-minute window, secondary = 10080-minute window, `used_percent`, `resets_at` (epoch s).
- Antigravity: the cockpit-tools quota cache (jlcodes99/cockpit-tools, reverse-engineered in docs/131)
  `~/.antigravity_cockpit/cache/quota_api_v1_plugin/authorized/*.json` -> `payload.models[*].quotaInfo`
  (`remainingFraction`, `resetTime`) plus `cache/quota_history/*.json` time series.
- Claude: Claude Code statusLine stdin `rate_limits.five_hour/seven_day` recorded by U303-B into
  `~/.uaos/usage/claude_rate_limits.jsonl` (one JSON object per line).
- Models/effort: `~/.codex/config.toml`, rollout `turn_context`; `~/.claude/settings.json` and the recorder row;
  `~/.gemini/antigravity/antigravity_state.pbtxt` `last_selected_agent_model` mapped through the cockpit model list.

Provider percentages stay the authority. Token capacity is calibrated, never asserted: tokens-per-1 % =
(tokens the local ledger counted inside the current reset window) / (provider used %), or the median of
consecutive sample pairs when a history exists. The basis, sample count and sample age travel with each value.
"""

from __future__ import annotations

import glob
import hashlib
import json
import math
import os
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .helper_telemetry import designated_helper_names, designated_helper_view

FIVE_HOUR_MIN = 300  # Codex primary and Claude five_hour window length (minutes), from the rollout payload
SEVEN_DAY_MIN = 10080  # Codex secondary and Claude seven_day window length (minutes)
ROLLOUT_SCAN_FILES = 60  # newest rollouts scanned; 66 exist on this PC and each holds hundreds of rows
CLAUDE_LIMITS_FILE = Path(".uaos") / "usage" / "claude_rate_limits.jsonl"
COCKPIT_DIR = Path(".antigravity_cockpit")

# Antigravity "thinkingLevel" integers seen in the cockpit model list (Opus High=3, Sonnet Low=1).
THINKING_WORDS = {0: "none", 1: "low", 2: "medium", 3: "high"}


def _epoch(value: Any) -> float | None:
    """Epoch seconds from epoch s/ms numbers or ISO strings; None when the value is absent."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _iso(ts: float | None) -> str | None:
    return None if ts is None else datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


# S1 (2026-11-07): how old a reading may be and still admit paid work. Reasons are measured rates, not guesses.
MAX_OBSERVATION_AGE = {
    # Error bounds below are hypotheses from single-user rates; concurrent sessions can move faster (Codex REVISE).
    FIVE_HOUR_MIN: {"seconds": 15 * 60, "reason": "5h window moved ~11 %/h at heavy use (Claude 19 % in ~1.7 h, "
                    "2026-11-07); 15 min bounds the error to ~3 points"},
    SEVEN_DAY_MIN: {"seconds": 6 * 3600, "reason": "weekly window moved <=1.2 %/h (Codex 79 % in 63 h, 2026-11-07); "
                    "6 h bounds the error to ~7 points, inside the 10-point AMBER band"},
}
WINDOW_STATES = ("FRESH", "STALE", "RESET_UNOBSERVED", "MISSING")


def _max_age_s(window_min: int) -> int:
    entry = MAX_OBSERVATION_AGE.get(int(window_min))
    if entry is None:  # unknown window length: the shorter (stricter) limit applies
        entry = MAX_OBSERVATION_AGE[FIVE_HOUR_MIN]
    return int(entry["seconds"])


CLOCK_SKEW_S = 120  # a reading stamped more than 2 min in the future is a clock or replay error, not a reading


def _invalid_reason(raw: float, reset_ts: float | None, window_min: int, observed: float | None, now: float) -> str | None:
    """Why a record cannot be trusted at all (None when it can)."""
    if not math.isfinite(raw) or raw < 0.0 or raw > 100.0:
        return "used_pct not a finite 0..100 value"
    if observed is not None and observed > now + CLOCK_SKEW_S:
        return "observation stamped in the future"
    if reset_ts is not None and observed is not None:
        if reset_ts <= observed:
            # the provider always reports the NEXT reset; a reset at or before the reading is a re-recorded old window
            return "reset not after the observation (stale window re-recorded)"
        if reset_ts - observed > window_min * 60 + CLOCK_SKEW_S:
            return "reset further away than the window length"
    return None


def window_fact(used_pct: float | None, resets_at: Any, window_min: int, observed: float | None, now: float,
                source: str | None = None) -> dict[str, Any] | None:
    """One quota window with its freshness state.

    A reset time in the past with no reading taken after it is RESET_UNOBSERVED: the value is unknown (None),
    never assumed refilled. Only FRESH admits paid work; STALE and RESET_UNOBSERVED fail closed.
    """
    if used_pct is None:
        return None
    reset_ts = _epoch(resets_at)
    try:
        raw = float(used_pct)
    except (TypeError, ValueError):
        raw = math.nan
    invalid = _invalid_reason(raw, reset_ts, int(window_min), observed, now)
    elapsed = bool(reset_ts is not None and reset_ts <= now)
    unobserved = not invalid and elapsed
    age = None if observed is None else max(0, int(now - observed))
    if invalid:
        state = "INVALID"
    elif unobserved:
        state = "RESET_UNOBSERVED"
    elif age is None or age > _max_age_s(window_min):
        state = "STALE"
    else:
        state = "FRESH"
    used = None if (invalid or unobserved) else raw
    return {
        "state": state,
        "invalid_reason": invalid,
        # Codex REVISE 2026-11-07: FRESH is necessary, not sufficient; an exhausted window denies too
        "admit_paid": state == "FRESH" and used is not None and used < 100.0,
        "used_pct": None if used is None else round(used, 1),
        "remaining_pct": None if used is None else round(100.0 - used, 1),
        "observed_used_pct": None if not math.isfinite(raw) else round(raw, 1),
        "window_min": int(window_min),
        "resets_at": _iso(reset_ts),
        "reset_in_s": 0 if (reset_ts is None or elapsed) else int(reset_ts - now),
        "reset_elapsed": elapsed,
        "observed_at": _iso(observed),
        "age_s": age,
        "max_age_s": _max_age_s(window_min),
        "source": source,
    }


def window_state(window: dict[str, Any] | None) -> str:
    return "MISSING" if not window else str(window.get("state") or "STALE")


VERIFIED_EVIDENCE = "provider_payload"  # written by the provider's own tool (rollout, statusLine stdin, cockpit cache)
CLAUDE_VERIFIED_PRODUCERS = frozenset({"claude_statusline_rate_limits"})  # explicit allowlist (relay_acd9ea77)


def pool_id(provider: str, plan: Any, model_pool: Any, home: Path | None) -> str:
    """provider:plan:model_pool:home_tag — one reading admits only its own pool (Codex relay_5f05bc5d).

    home_tag is a short hash of the tool home folder path. It is NOT an account identity: it never reads an
    account id or credential (Safety), and two logins sharing one home folder get the same tag. A login change
    inside one home is therefore not isolated here; only the max-age gate bounds it (Codex relay_acd9ea77).
    """
    tag = hashlib.sha256(str(Path(home).resolve()).encode("utf-8")).hexdigest()[:8] if home is not None else "unknown"
    return f"{provider}:{plan or 'unknown'}:{model_pool or 'unknown'}:{tag}"


def admit_paid(account: dict[str, Any] | None, pool: str | None = None) -> bool:
    """Paid work is admitted only when both windows are present, FRESH, not exhausted and provider-verified.

    With `pool`, the reading must belong to that exact pool (provider, plan, model pool and account tag).
    A row whose evidence is an operator-typed CLI label (or that carries no evidence) is advisory only and
    never admits paid work; there is deliberately no override here (Codex REVISE relay_19bd9932/relay_5f05bc5d).
    """
    if not isinstance(account, dict):
        return False
    if pool is not None and account.get("account_pool") != pool:
        return False
    if account.get("evidence") != VERIFIED_EVIDENCE:
        return False
    return all(bool((account.get(k) or {}).get("admit_paid")) for k in ("five_hour", "seven_day"))


# ---------------------------------------------------------------- Codex
def codex_rollouts(home: Path) -> list[str]:
    files = glob.glob(str(home / ".codex" / "sessions" / "**" / "rollout-*.jsonl"), recursive=True)
    return sorted(files, key=os.path.getmtime)[-ROLLOUT_SCAN_FILES:]


def codex_quota(home: Path, now: float) -> dict[str, Any] | None:
    """Newest `codex` rate-limit row with a measured primary window, plus the model/effort it ran with."""
    best: tuple[float, dict[str, Any]] | None = None
    model = effort = None
    for path in codex_rollouts(home):
        try:
            fh = open(path, encoding="utf-8", errors="ignore")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"turn_context"' in line:
                    try:
                        p = json.loads(line).get("payload") or {}
                        model, effort = p.get("model") or model, p.get("effort") or effort
                    except ValueError:
                        pass
                if '"used_percent"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                rl = (row.get("payload") or {}).get("rate_limits") or {}
                if not isinstance(rl.get("primary"), dict):
                    continue
                if rl.get("limit_id") not in (None, "codex"):
                    continue
                ts = _epoch(row.get("timestamp"))
                if ts is not None and ts <= now + CLOCK_SKEW_S and (best is None or ts >= best[0]):
                    best = (ts, rl)
    if best is None:
        return None
    ts, rl = best
    pri, sec = rl.get("primary") or {}, rl.get("secondary") or {}
    return {
        "source": "codex_rollout_rate_limits",
        "plan_type": rl.get("plan_type"),
        "account_pool": pool_id("codex", rl.get("plan_type"), rl.get("limit_id") or "codex", home),
        "evidence": "provider_payload",
        "five_hour": window_fact(pri.get("used_percent"), pri.get("resets_at"), int(pri.get("window_minutes") or FIVE_HOUR_MIN), ts, now,
                                 "codex_rollout_rate_limits"),
        "seven_day": window_fact(sec.get("used_percent"), sec.get("resets_at"), int(sec.get("window_minutes") or SEVEN_DAY_MIN), ts, now,
                                 "codex_rollout_rate_limits")
        if sec else None,
        "last_model": model,
        "last_effort": effort,
    }


def codex_config(home: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cfg = home / ".codex" / "config.toml"
    if not cfg.is_file():
        return out
    for line in cfg.read_text(encoding="utf-8", errors="ignore").splitlines():
        if line.startswith("["):
            break  # top-level keys only; tables start after them
        m = re.match(r'\s*(model|model_reasoning_effort)\s*=\s*"([^"]*)"', line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


# ---------------------------------------------------------------- Antigravity (cockpit-tools cache)
def _newest(pattern: str) -> Path | None:
    files = glob.glob(pattern)
    return Path(max(files, key=os.path.getmtime)) if files else None


def cockpit_models(home: Path) -> tuple[dict[str, Any], float | None]:
    """cockpit-tools authorized quota cache: model key -> model entry, and its updatedAt (epoch s)."""
    path = _newest(str(home / COCKPIT_DIR / "cache" / "quota_api_v1_plugin" / "*" / "*.json"))
    if path is None:
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, None
    models = ((data.get("payload") or {}).get("models")) or {}
    return (models if isinstance(models, dict) else {}), _epoch(data.get("updatedAt")) or path.stat().st_mtime


def antigravity_selected_model(home: Path) -> str | None:
    state = home / ".gemini" / "antigravity" / "antigravity_state.pbtxt"
    if not state.is_file():
        return None
    m = re.search(r"last_selected_agent_model:\s*(\S+)", state.read_text(encoding="utf-8", errors="ignore"))
    return m.group(1) if m else None


def antigravity_quota(home: Path, now: float) -> dict[str, Any] | None:
    """Quota pools from the cockpit cache: models sharing one remainingFraction+resetTime share one pool."""
    models, updated = cockpit_models(home)
    if not models:
        return None
    selected = antigravity_selected_model(home)
    pools: dict[tuple, dict[str, Any]] = {}
    selected_entry: dict[str, Any] | None = None
    for key, m in models.items():
        if not isinstance(m, dict):
            continue
        q = m.get("quotaInfo") or {}
        if m.get("model") == selected:
            selected_entry = {"key": key, **m}
        if "remainingFraction" not in q or not m.get("displayName"):
            continue
        sig = (round(float(q["remainingFraction"]), 6), q.get("resetTime"))
        pool = pools.setdefault(sig, {"models": [], "remaining_fraction": sig[0], "reset_time": sig[1]})
        pool["models"].append(m["displayName"])
    if not pools:
        return None
    pool_list = []
    for p in pools.values():
        reset_ts = _epoch(p["reset_time"])
        # cockpit history shows the countdown starts at ~5 h (countdownSeconds 17869 at first point): the
        # window length is read from the reset distance, never assumed, when the reset is under 6 h away.
        win = FIVE_HOUR_MIN if (reset_ts is not None and reset_ts - (updated or now) <= 6 * 3600) else SEVEN_DAY_MIN
        fact = window_fact(round((1.0 - p["remaining_fraction"]) * 100.0, 4), p["reset_time"], win, updated, now,
                           "cockpit_quota_cache")
        pool_list.append({"models": sorted(p["models"]), **(fact or {})})
    # unknown (reset unobserved) pools sort first: the scarcest known-or-unknown pool is shown before a full one
    pool_list.sort(key=lambda f: -1.0 if f.get("remaining_pct") is None else f["remaining_pct"])
    sel_name = (selected_entry or {}).get("displayName")
    sel_pool = next((p for p in pool_list if sel_name and sel_name in p["models"]), None)
    return {
        "source": "cockpit_tools_quota_cache",
        "pools": pool_list,
        "selected_model": sel_name or selected,
        "selected_effort": THINKING_WORDS.get((selected_entry or {}).get("thinkingLevel"), None),
        "selected_pool": sel_pool,
        "observed_at": _iso(updated),
    }


def cockpit_history(home: Path, label_hint: str | None = None) -> list[dict[str, Any]]:
    """cockpit quota_history points (timestamp ms, remainingPercentage, resetTime ms) for one pool."""
    path = _newest(str(home / COCKPIT_DIR / "cache" / "quota_history" / "*.json"))
    if path is None:
        return []
    try:
        models = (json.loads(path.read_text(encoding="utf-8")).get("models")) or {}
    except (OSError, ValueError):
        return []
    chosen = None
    for m in models.values():
        label = str(m.get("label") or "")
        if label_hint and label and label.split()[0].lower() in label_hint.lower():
            chosen = m
            break
    if chosen is None and models:
        chosen = max(models.values(), key=lambda m: len(m.get("points") or []))
    pts = []
    for p in (chosen or {}).get("points") or []:
        ts, rem = _epoch(p.get("timestamp")), p.get("remainingPercentage")
        if ts is not None and rem is not None:
            pts.append({"ts": ts, "used_pct": 100.0 - float(rem), "resets_at": _epoch(p.get("resetTime"))})
    return pts


# ---------------------------------------------------------------- Claude (statusLine recorder)
def claude_quota(home: Path, now: float) -> dict[str, Any] | None:
    path = home / CLAUDE_LIMITS_FILE
    if not path.is_file():
        return None
    last = None
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or (row.get("five_hour_used_pct") is None and row.get("seven_day_used_pct") is None):
            continue
        ts = _epoch(row.get("ts"))
        # S1 replay guard: the newest observation wins, not the last line; a future stamp is not a reading
        if ts is None or ts > now + CLOCK_SKEW_S:
            continue
        if last is None or ts >= _epoch(last.get("ts")):
            last = row
    if last is None:
        return None
    ts = _epoch(last.get("ts"))
    # explicit producer allowlist (Codex relay_acd9ea77): only the statusLine recorder copies a provider payload;
    # the desktop feed is an operator-typed label, and an unknown or missing (legacy) source stays advisory
    src = str(last.get("source") or "unknown_legacy_row")
    if src in CLAUDE_VERIFIED_PRODUCERS:
        evidence = VERIFIED_EVIDENCE
    elif src == "claude_desktop_get_usage":
        evidence = "operator_reported (CLI label, not verified)"
    else:
        evidence = "unverified_producer (advisory only)"
    return {
        "source": src,
        # provider+plan only: the account id is a credential-adjacent value and is never read (Safety)
        "account_pool": pool_id("claude", "subscription", "all-models", home),
        "evidence": evidence,
        "five_hour": window_fact(last.get("five_hour_used_pct"), last.get("five_hour_resets_at"), FIVE_HOUR_MIN, ts, now, src),
        "seven_day": window_fact(last.get("seven_day_used_pct"), last.get("seven_day_resets_at"), SEVEN_DAY_MIN, ts, now, src),
        "last_model": last.get("model"),
        "last_effort": last.get("effort"),
    }


def claude_history(home: Path) -> list[dict[str, Any]]:
    path = home / CLAUDE_LIMITS_FILE
    pts: list[dict[str, Any]] = []
    if not path.is_file():
        return pts
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ts = _epoch(row.get("ts")) if isinstance(row, dict) else None
        if ts is not None and row.get("five_hour_used_pct") is not None:
            pts.append({"ts": ts, "used_pct": float(row["five_hour_used_pct"]), "resets_at": _epoch(row.get("five_hour_resets_at"))})
    return pts


def claude_settings(home: Path) -> dict[str, Any]:
    p = home / ".claude" / "settings.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {"model": d.get("model"), "effortLevel": d.get("effortLevel")}


# ---------------------------------------------------------------- calibration
def calibrate(window: dict[str, Any] | None, events: Iterable[dict[str, Any]], now: float,
              history: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """Tokens per 1 % of one provider window, from the provider's own % and the ledger's token counts.

    pairs:  for consecutive history samples inside one reset window with Δused% ≥ 1, tokens counted between
            them / Δused%; the median of all pairs (needs ≥ 3 pairs).
    window: tokens counted since the window opened (resets_at - window length) / observed used %.
    Then capacity = tokens_per_pct × 100 and remaining = tokens_per_pct × remaining %.
    """
    if not window:
        return None
    evs = sorted(((float(e["ts"]), int(e.get("raw_total") or 0)) for e in events if e.get("ts") is not None), key=lambda x: x[0])

    def tokens_between(a: float, b: float) -> int:
        return sum(t for ts, t in evs if a < ts <= b)

    ratios: list[float] = []
    hist = sorted(history or [], key=lambda p: p["ts"])
    for p0, p1 in zip(hist, hist[1:]):
        if p0.get("resets_at") != p1.get("resets_at"):
            continue
        d_pct = p1["used_pct"] - p0["used_pct"]
        tok = tokens_between(p0["ts"], p1["ts"])
        if d_pct >= 1.0 and tok > 0:
            ratios.append(tok / d_pct)
    basis, n, tpp = None, 0, None
    if len(ratios) >= 3:
        tpp, n, basis = statistics.median(ratios), len(ratios), "pairs_median"
    else:
        obs_used = float(window.get("observed_used_pct") or 0.0)
        reset_ts = _epoch(window.get("resets_at"))
        obs_ts = _epoch(window.get("observed_at")) or now
        if reset_ts is not None and obs_used > 0:
            start = reset_ts - window["window_min"] * 60
            tok = tokens_between(start, obs_ts)
            if tok > 0:
                tpp, n, basis = tok / obs_used, 1, "window_integral"
    if tpp is None:
        return {"basis": "no_paired_tokens", "samples": 0, "tokens_per_pct": None,
                "capacity_tokens": None, "remaining_tokens": None,
                "formula": "Δtokens(ledger) / Δused%(provider)"}
    return {
        "basis": basis,
        "samples": n,
        "tokens_per_pct": int(round(tpp)),
        "capacity_tokens": int(round(tpp * 100.0)),
        # S1: a reset-unobserved window has no known remaining %, so no remaining tokens either
        "remaining_tokens": None if window.get("remaining_pct") is None
        else int(round(tpp * float(window["remaining_pct"]))),
        "formula": "Δtokens(ledger) / Δused%(provider)" if basis == "pairs_median"
        else "tokens since window start / observed used %",
    }


# ---------------------------------------------------------------- assembly
def ledger_history(home: Path, provider: str, window_min: int) -> list[dict[str, Any]]:
    """UAOS ledger quota_snapshots rows (already synced from native transcripts) as a calibration history."""
    db = home / ".uaos" / "usage" / "ledger.sqlite3"
    if not db.is_file():
        return []
    import sqlite3
    try:
        con = sqlite3.connect(str(db), timeout=5)
        try:
            rows = con.execute(
                "SELECT observed_at, used_percent, resets_at FROM quota_snapshots "
                "WHERE provider=? AND window_minutes=? ORDER BY observed_at", (provider, window_min)).fetchall()
        finally:
            con.close()
    except Exception:
        return []
    out = []
    for obs, used, reset in rows:
        ts = _epoch(obs)
        if ts is not None and used is not None:
            out.append({"ts": ts, "used_pct": float(used), "resets_at": _epoch(reset)})
    return out


def model_mix_7d(home: Path, now: float) -> dict[str, list[dict[str, Any]]]:
    """Calls per (provider, model) in the last 7 days from the UAOS ledger: the measured main and helper models."""
    db = home / ".uaos" / "usage" / "ledger.sqlite3"
    mix: dict[str, list[dict[str, Any]]] = {}
    if not db.is_file():
        return mix
    import sqlite3
    cut = _iso(now - SEVEN_DAY_MIN * 60)
    try:
        con = sqlite3.connect(str(db), timeout=5)
        try:
            rows = con.execute(
                "SELECT provider, model, COUNT(DISTINCT event_key), SUM(output) FROM contributions "
                "WHERE timestamp >= ? GROUP BY provider, model ORDER BY 3 DESC", (cut,)).fetchall()
        finally:
            con.close()
    except Exception:
        return mix
    for prov, model, calls, out in rows:
        if model and str(model).upper() != "UNKNOWN":
            mix.setdefault(str(prov), []).append({"model": str(model), "calls": int(calls or 0), "output_tokens": int(out or 0)})
    return mix


# Claude Code docs: with no `effortLevel`, the 5.5 generation runs at medium effort.
CLAUDE_DEFAULT_EFFORT = "medium"


def measured_accounts(home: Path, now: float, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Per paid tool: measured windows, calibrated token capacity, and the model/effort facts."""
    events = events or []
    by_eng = lambda eng: [e for e in events if e.get("engine") == eng]  # noqa: E731
    out: dict[str, Any] = {}

    cx = codex_quota(home, now) or {}
    cfg = codex_config(home)
    cx_hist = ledger_history(home, "codex", FIVE_HOUR_MIN)
    out["codex"] = {
        **cx,
        "model": cfg.get("model") or cx.get("last_model"),
        "effort": cx.get("last_effort") or cfg.get("model_reasoning_effort"),
        "calibration_5h": calibrate(cx.get("five_hour"), by_eng("codex"), now, cx_hist),
        "calibration_7d": calibrate(cx.get("seven_day"), by_eng("codex"), now),
    }

    ag = antigravity_quota(home, now) or {}
    sel_pool = ag.get("selected_pool")
    out["antigravity"] = {
        **ag,
        "model": ag.get("selected_model"),
        "effort": ag.get("selected_effort"),
        "calibration": calibrate(sel_pool, by_eng("antigravity"), now, cockpit_history(home, ag.get("selected_model"))),
    }

    cl = claude_quota(home, now) or {}
    st = claude_settings(home)
    effort = cl.get("last_effort") or st.get("effortLevel")
    out["claude"] = {
        **cl,
        "model": cl.get("last_model") or st.get("model"),
        "effort": effort or CLAUDE_DEFAULT_EFFORT,
        "effort_basis": "statusline/settings" if effort else "default (effortLevel unset)",
        "calibration_5h": calibrate(cl.get("five_hour"), by_eng("claude"), now, claude_history(home)),
        "calibration_7d": calibrate(cl.get("seven_day"), by_eng("claude"), now),
    }

    mix = model_mix_7d(home, now)
    for eng in ("codex", "claude"):
        rows = mix.get(eng, [])
        main = rows[0]["model"] if rows else None
        out[eng]["model_mix_7d"] = rows
        # U304-B: the helper line shows the tool's one designated helper, never "every other model" (Sonnet).
        out[eng]["helpers"] = designated_helper_view(eng, rows)
        out[eng]["main_model_7d"] = main
    # Antigravity's helper quota is the pool that holds its designated helper model (U304-B).
    pools = ag.get("pools") or []
    names = designated_helper_names("antigravity")
    helper_pool = next((p for p in pools if p is not None and names & set(p.get("models") or [])), None)
    if helper_pool is None:
        # A cockpit snapshot that omits the helper's name still bills it to its family's shared pool ("Gemini").
        family = {n.split()[0] for n in names if " " in n}
        helper_pool = next((p for p in pools if p is not None
                            and any(str(m).split(" ")[0] in family for m in p.get("models") or [])), None)
    out["antigravity"]["helper_pool"] = helper_pool
    out["antigravity"]["helpers"] = designated_helper_view("antigravity")
    return out


def _usable_tokens(window: dict[str, Any] | None, cal: dict[str, Any] | None, ref_cap: int | None) -> tuple[int | None, str]:
    """Remaining tokens: calibrated when the ledger allows, else the policy reference cap x measured remaining %."""
    if cal and cal.get("remaining_tokens") is not None:
        return int(cal["remaining_tokens"]), f"calibrated:{cal['basis']}(n={cal['samples']})"
    # Global rule: a remaining-quota percentage is never converted to tokens. Without a calibration pair the
    # provider % is the only number shown.
    return None, ("uncalibrated: provider % only" if window else "no_window")


def apply_measured_quota(engines: dict[str, dict[str, Any]], measured: dict[str, Any], policy: dict[str, Any],
                         dispatch_pools: dict[str, str] | None = None) -> None:
    """Write measured windows, calibrated tokens and model facts into the snapshot engines (in place).

    Haiku runs on Claude's subscription, so it reads Claude's measured windows. Ollama stays local and unlimited.
    """
    tiers = policy.get("subscription_tiers") or {}
    for eng in ("codex", "claude", "antigravity", "haiku"):
        info = engines.get(eng)
        m = measured.get("claude" if eng == "haiku" else eng) or {}
        if info is None or not isinstance(m, dict):
            continue
        sub = info.setdefault("subscription_plan", {})
        if eng == "antigravity":
            w5, w7 = m.get("selected_pool"), None
            if m.get("helper_pool"):
                sub["helper_quota"] = m["helper_pool"]
            cal5, cal7 = m.get("calibration"), None
        else:
            w5, w7 = m.get("five_hour"), m.get("seven_day")
            cal5, cal7 = m.get("calibration_5h"), m.get("calibration_7d")
        tier = tiers.get(eng) or {}
        rem5, basis5 = _usable_tokens(w5, cal5, tier.get("reference_cap_5h_tokens"))
        rem7, basis7 = _usable_tokens(w7, cal7, tier.get("reference_cap_7d_tokens"))
        for key, w in (("5h", w5), ("7d", w7)):
            if w:
                sub[f"quota_{key}_ui_pct"] = w["used_pct"]
                sub[f"resets_at_{key}"] = w["resets_at"]
                sub[f"reset_in_seconds_{key}"] = w["reset_in_s"]
        known = [float(w["remaining_pct"]) for w in (w5, w7) if w and w.get("remaining_pct") is not None]
        unknown = any(w and w.get("remaining_pct") is None for w in (w5, w7))
        left = min(known or [100.0])
        if eng == "antigravity":  # one cockpit pool window (provider cache); no weekly window exists to bind
            sub["quota_admit_paid"] = bool(w5 and w5.get("admit_paid"))
        else:  # both windows + verified evidence + the pool the dispatch really uses (relay_acd9ea77)
            expected = (dispatch_pools or {}).get(eng)
            sub["quota_admit_paid"] = bool(expected) and admit_paid(m, pool=expected)
            if not expected:  # ambiguous dispatch pool fails closed
                sub["quota_admit_reason"] = "POOL_UNBOUND"
        if left <= 0:  # a window at 0 % blocks the tool whatever the other window says
            rem5 = 0 if rem5 is not None else rem5
            rem7 = 0 if rem7 is not None else rem7
        card_cost = int(info.get("avg_card_cost_tokens") or policy.get("default_card_cost_tokens") or 1)
        if rem5 is not None:
            cap5 = (cal5 or {}).get("capacity_tokens")
            sub["total_5h_tokens"], sub["remaining_5h_tokens"] = cap5, rem5
            info["usable_remaining_5h_tokens"] = rem5
            info["budget_cap_5h_tokens"] = cap5
            info["usable_cards_capacity"] = int(rem5 // max(1, card_cost))
        elif w5 or w7:
            # measured window, no calibration: tokens are not claimed, the provider % stands alone
            sub["total_5h_tokens"] = sub["remaining_5h_tokens"] = None
            info["usable_remaining_5h_tokens"] = None
        if rem7 is not None:
            cap7 = (cal7 or {}).get("capacity_tokens")
            sub["total_7d_tokens"], sub["remaining_7d_tokens"] = cap7, rem7
            info["usable_remaining_7d_tokens"] = rem7
        elif w7:
            sub["total_7d_tokens"] = sub["remaining_7d_tokens"] = None
            info["usable_remaining_7d_tokens"] = None
        if w5 or w7:
            info["status_tier"] = ("LIMITED_UNTIL_RESET" if left <= 0 else "CRITICAL_OFFLOAD" if left <= 10
                                   else "THROTTLE_TO_LOCAL" if left <= 30
                                   else "RESET_UNOBSERVED" if unknown else "HEALTHY")
            if left <= 0:
                info["usable_cards_capacity"] = 0
        # An expired heartbeat says nothing; the measured quota does. A tool at 0 % left is LIMITED until its
        # reset, otherwise it is IDLE (able to work, no live session). The basis is kept next to the state.
        if str(info.get("presence_state") or "").upper() in ("", "UNKNOWN") and (w5 or w7):
            info["presence_state"] = "LIMITED" if left <= 0 else "IDLE"
            info["presence_basis"] = "measured quota (heartbeat expired)"
        helpers = m.get("helpers") or []
        if eng == "haiku":
            hk = [h for h in helpers if "haiku" in h.get("model", "")]
            model, effort, helpers = (hk[0]["model"] if hk else "claude-haiku-5-5"), m.get("effort"), []
        else:
            model, effort = m.get("model"), m.get("effort")
        info["measured"] = {
            "source": m.get("source") or ("claude_settings_json (no statusLine row yet)" if eng in ("claude", "haiku")
                                          else "local_ledger_only"),
            "model": model,
            "effort": effort,
            "effort_basis": m.get("effort_basis"),
            "helpers": helpers[:3],
            "window_5h": w5,
            "window_7d": w7,
            "tokens_5h_basis": basis5,
            "tokens_7d_basis": basis7,
            "calibration_5h": cal5,
            "calibration_7d": cal7,
            "plan_type": m.get("plan_type"),
        }
