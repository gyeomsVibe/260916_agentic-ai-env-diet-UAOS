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
import json
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


def window_fact(used_pct: float | None, resets_at: Any, window_min: int, observed: float | None, now: float) -> dict[str, Any] | None:
    """One quota window. A reset time already in the past means the provider refilled it: used 0 %."""
    if used_pct is None:
        return None
    reset_ts = _epoch(resets_at)
    elapsed = bool(reset_ts is not None and reset_ts <= now)
    used = 0.0 if elapsed else max(0.0, min(100.0, float(used_pct)))
    return {
        "used_pct": round(used, 1),
        "remaining_pct": round(100.0 - used, 1),
        "observed_used_pct": round(float(used_pct), 1),
        "window_min": int(window_min),
        "resets_at": _iso(reset_ts),
        "reset_in_s": 0 if (reset_ts is None or elapsed) else int(reset_ts - now),
        "reset_elapsed": elapsed,
        "observed_at": _iso(observed),
        "age_s": None if observed is None else max(0, int(now - observed)),
    }


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
                if ts is not None and (best is None or ts >= best[0]):
                    best = (ts, rl)
    if best is None:
        return None
    ts, rl = best
    pri, sec = rl.get("primary") or {}, rl.get("secondary") or {}
    return {
        "source": "codex_rollout_rate_limits",
        "plan_type": rl.get("plan_type"),
        "five_hour": window_fact(pri.get("used_percent"), pri.get("resets_at"), int(pri.get("window_minutes") or FIVE_HOUR_MIN), ts, now),
        "seven_day": window_fact(sec.get("used_percent"), sec.get("resets_at"), int(sec.get("window_minutes") or SEVEN_DAY_MIN), ts, now)
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
        fact = window_fact(round((1.0 - p["remaining_fraction"]) * 100.0, 4), p["reset_time"], win, updated, now)
        pool_list.append({"models": sorted(p["models"]), **(fact or {})})
    pool_list.sort(key=lambda f: f.get("remaining_pct", 100.0))
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
        if isinstance(row, dict) and (row.get("five_hour_used_pct") is not None or row.get("seven_day_used_pct") is not None):
            last = row
    if last is None:
        return None
    ts = _epoch(last.get("ts"))
    return {
        "source": "claude_statusline_rate_limits",
        "five_hour": window_fact(last.get("five_hour_used_pct"), last.get("five_hour_resets_at"), FIVE_HOUR_MIN, ts, now),
        "seven_day": window_fact(last.get("seven_day_used_pct"), last.get("seven_day_resets_at"), SEVEN_DAY_MIN, ts, now),
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
        "remaining_tokens": int(round(tpp * float(window["remaining_pct"]))),
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


def apply_measured_quota(engines: dict[str, dict[str, Any]], measured: dict[str, Any], policy: dict[str, Any]) -> None:
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
        left = min([float(w["remaining_pct"]) for w in (w5, w7) if w] or [100.0])
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
                                   else "THROTTLE_TO_LOCAL" if left <= 30 else "HEALTHY")
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
