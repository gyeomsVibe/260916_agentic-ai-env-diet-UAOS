"""U256: Unified 3-Tool + Ollama/Haiku Token & Capacity Store, Capacity-Aware Master/Collaboration Scheduler,
and Dynamic Visual Telemetry Dashboard (`현재 진행상황을 보고해줘`).

Advisory-only planner: `collect_capacity_snapshot` and `build_capacity_aware_schedule` read
`.coord/master_schedule.json` to compute capacity-aware recommendations and never write or mutate
`.coord/master_schedule.json`.

Follows OpenTelemetry GenAI semantic conventions (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`) and
UAOS-RSI `docs/35_token-budget-routing-policy.md`:
- Measured token counts and provider quota percentages are kept in distinct fields and never converted into one another.
- Caps in `tool_caps_5h` require a recorded measured source (`tool_caps_source`); without a recorded source,
  `usable_remaining_5h_tokens` is reported as `"UNKNOWN"` and the planner does not rank on unmeasured token caps.
- Stores unified snapshots in both `<project>/.coord/usage/capacity_snapshot.json` and
  `~/.uaos/usage/global_capacity_registry.json` so all 3 tools (Codex, Claude Code, Antigravity) across any project
  can query remaining usable budget tokens, card capacity, and schedule assignments in <5ms.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any

from .hook_context import shared_desk
from .next_card import TERMINAL
from .presence import TOOLS, read_all as read_all_presence
from .usage_ledger import _rows, ledger_file

ALL_ENGINES = ("codex", "claude", "antigravity", "haiku", "ollama")
PAID_TOOLS = ("codex", "claude", "antigravity")
WINDOW_5H_SECONDS = 5 * 3600
WINDOW_24H_SECONDS = 24 * 3600
WINDOW_7D_SECONDS = 7 * 86400

DEFAULT_POLICY: dict[str, Any] = {
    "schema": "uaos-capacity-policy-v1",
    "window_5h_seconds": WINDOW_5H_SECONDS,
    "cache_read_weight": 0.1,
    "cache_write_weight": 1.25,
    "output_weight": 3.0,
    "default_card_cost_tokens": 45000,
    "offload_threshold_pct": 70.0,
    "critical_threshold_pct": 90.0,
    "tool_caps_5h": {
        "codex": None,
        "claude": None,
        "antigravity": None,
        "haiku": None,
        "ollama": None,
    },
    "tool_caps_source": {
        "origin": "unmeasured_by_default",
        "policy_docs": [
            "docs/27_token-budget-routing-policy.md",
            "docs/28_claude-budget-manual.md",
            "docs/29_antigravity-budget-manual.md",
            "docs/30_ollama-calculator-manual.md",
        ],
        "notes": (
            "Paid tool 5h caps default to None (usable_remaining_5h_tokens='UNKNOWN') until a measured cap and "
            "source are recorded in .coord/usage/capacity_policy.json; never derived from provider quota percentages."
        ),
    },
    "sources": {
        "window_5h_seconds": "18000s (5h rolling provider window in docs/27_token-budget-routing-policy.md)",
        "weights": "Prompt-cache billing ratios in docs/27_token-budget-routing-policy.md",
        "default_card_cost_tokens": "45000 effective tokens baseline in docs/27_token-budget-routing-policy.md",
        "review_share_ratio": "0.35 judge/rework reservation share in docs/27_token-budget-routing-policy.md",
        "card_cost_clamp": "[5000, 250000] single-turn floor to per-run ceiling in docs/29_antigravity-budget-manual.md",
    },
    "tool_roles": {
        "codex": "Conductor & Final Independent Judge",
        "claude": "Co-Conductor & Deep Implementer/Reviewer",
        "antigravity": "Argon Primary Heavy-Lifter, Co-Conductor & Autonomous Merger (120k KRW Ultra)",
        "haiku": "Low-Cost Multi-Agent Sub-Orchestrator (claude-haiku-5-5)",
        "ollama": "0-Paid-Token Local Calculator (qwen2.5-coder:7b)",
    },
}


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(str(tmp_path), str(path))
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def load_policy(project_root: Path) -> dict[str, Any]:
    desk = shared_desk(Path(project_root))
    policy_path = desk / ".coord" / "usage" / "capacity_policy.json"
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    if policy_path.is_file():
        try:
            custom = json.loads(policy_path.read_text(encoding="utf-8"))
            if isinstance(custom, dict):
                for k, v in custom.items():
                    if isinstance(v, dict) and isinstance(policy.get(k), dict):
                        policy[k].update(v)
                    else:
                        policy[k] = v
        except (OSError, ValueError):
            pass
    return policy


def _parse_ts(row: dict[str, Any]) -> float | None:
    for key in ("ts", "timestamp", "window_end", "observed_at"):
        val = row.get(key)
        if isinstance(val, (int, float)) and not isinstance(val, bool) and val > 0:
            return float(val)
        if isinstance(val, str) and val.strip():
            try:
                return datetime.fromisoformat(val.strip().replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
    return None


def _classify_engine(row: dict[str, Any]) -> str:
    worker = str(row.get("worker") or row.get("actor") or row.get("provider") or "").lower().strip()
    model = str(row.get("model") or "").lower().strip()
    if "haiku" in model or worker == "haiku":
        return "haiku"
    if worker in ("ollama", "local", "cascade") or "qwen" in model or "llama" in model:
        return "ollama"
    if worker in ("agy", "antigravity") or "gemini" in model or "antigravity" in model:
        return "antigravity"
    if worker == "claude" or "claude" in model:
        return "claude"
    if worker == "codex" or "gpt" in model or "o1" in model or "o3" in model or "codex" in model:
        return "codex"
    return "unknown"


def _effective_tokens(inp: int, cache_read: int, cache_write: int, out: int, policy: dict[str, Any]) -> int:
    cr_w = float(policy.get("cache_read_weight", 0.1))
    cw_w = float(policy.get("cache_write_weight", 1.25))
    out_w = float(policy.get("output_weight", 3.0))
    return int(round(max(0, inp) + max(0, cache_read) * cr_w + max(0, cache_write) * cw_w + max(0, out) * out_w))


def _scan_agy_auto(desk: Path) -> list[dict[str, Any]]:
    auto_path = desk / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"
    rows: list[dict[str, Any]] = []
    if not auto_path.is_file():
        return rows
    try:
        for line in auto_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if isinstance(d, dict) and int(d.get("tokens") or 0) > 0:
                tok = int(d["tokens"])
                rows.append({
                    "engine": "antigravity",
                    "ts": float(d.get("ts") or d.get("at") or 0.0),
                    "work_id": str(d.get("card") or d.get("message_id") or "agy_auto"),
                    "uncached_input": int(tok * 0.85),
                    "cache_read": 0,
                    "cache_write": 0,
                    "output": int(tok * 0.15),
                    "raw_total": tok,
                })
    except OSError:
        pass
    return rows


def _scan_sqlite_ledger(home: Path, cutoff_7d: float) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    db_path = home / ".uaos" / "usage" / "ledger.sqlite3"
    events: list[dict[str, Any]] = []
    quotas: dict[str, dict[str, Any]] = {}
    if not db_path.is_file():
        return events, quotas
    import sqlite3
    try:
        con = sqlite3.connect(str(db_path), timeout=5)
        con.row_factory = sqlite3.Row
        try:
            iso_cut = datetime.fromtimestamp(cutoff_7d, timezone.utc).isoformat().replace("+00:00", "Z")
            for r in con.execute(
                """SELECT provider, event_key, MIN(timestamp) AS timestamp, MAX(model) AS model,
                          MAX(uncached_input) AS uncached_input, MAX(cache_read) AS cache_read,
                          MAX(cache_write) AS cache_write, MAX(output) AS output
                   FROM contributions
                   WHERE timestamp >= ?
                   GROUP BY provider, event_key""",
                (iso_cut,),
            ):
                d = dict(r)
                ts = _parse_ts(d)
                if ts is None:
                    continue
                eng = _classify_engine(d)
                inp = int(d.get("uncached_input") or 0)
                cr = int(d.get("cache_read") or 0)
                cw = int(d.get("cache_write") or 0)
                out = int(d.get("output") or 0)
                events.append({
                    "engine": eng,
                    "ts": ts,
                    "work_id": str(d.get("event_key") or "")[:12],
                    "uncached_input": inp,
                    "cache_read": cr,
                    "cache_write": cw,
                    "output": out,
                    "raw_total": inp + cr + cw + out,
                })
            for q in con.execute(
                """SELECT provider, observed_at, used_percent, window_minutes, resets_at, origin
                   FROM quota_snapshots ORDER BY observed_at ASC"""
            ):
                qd = dict(q)
                prov = str(qd.get("provider") or "")
                if prov:
                    quotas[prov] = {
                        "used_percent": float(qd["used_percent"]) if qd.get("used_percent") is not None else None,
                        "remaining_percent": round(100.0 - float(qd["used_percent"]), 1)
                        if qd.get("used_percent") is not None else None,
                        "window_minutes": qd.get("window_minutes"),
                        "resets_at": qd.get("resets_at"),
                        "observed_at": qd.get("observed_at"),
                        "origin": qd.get("origin"),
                    }
        finally:
            con.close()
    except Exception:
        pass
    return events, quotas




def _scan_agy_brain_transcripts(home_dir: Path, cutoff_ts: float) -> list[dict[str, Any]]:
    """Ingest native Antigravity (Argon) PLANNER_RESPONSE token usage from ~/.gemini/antigravity/brain/*/transcript.jsonl."""
    brain_root = home_dir / ".gemini" / "antigravity" / "brain"
    if not brain_root.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for tf in brain_root.glob("*/.system_generated/logs/transcript.jsonl"):
        try:
            if cutoff_ts <= time.time() and tf.stat().st_mtime < cutoff_ts:
                continue
            conv_id = tf.parts[-4] if len(tf.parts) >= 4 else tf.parent.name
            lines = tf.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for ln in lines:
            if "PLANNER_RESPONSE" not in ln:
                continue
            try:
                row = json.loads(ln)
            except ValueError:
                continue
            if not isinstance(row, dict) or row.get("type") != "PLANNER_RESPONSE":
                continue
            ca = row.get("created_at")
            if not isinstance(ca, str) or not ca:
                continue
            try:
                ts = datetime.fromisoformat(ca.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if ts < cutoff_ts:
                continue
            inp = int(row.get("input_tokens") or 0)
            cr = int(row.get("cache_read_tokens") or 0)
            cw = int(row.get("cache_creation_input_tokens") or 0)
            out_t = int(row.get("output_tokens") or 0)
            tot = inp + cr + cw + out_t
            if tot <= 0:
                continue
            out.append({
                "engine": "antigravity",
                "ts": ts,
                "work_id": f"agy-brain-{conv_id[:8]}-{row.get('step_index', 0)}",
                "uncached_input": inp,
                "cache_read": cr,
                "cache_write": cw,
                "output": out_t,
                "raw_total": tot,
            })
    return out


def collect_capacity_snapshot(
    project_root: Path,
    *,
    home: Path | None = None,
    now: float | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Compute unified 3-tool + Haiku + Ollama usage, remaining usable budget tokens, and card capacity."""
    moment = float(now if now is not None else time.time())
    desk = shared_desk(Path(project_root))
    home_dir = Path(home) if home is not None else Path.home()
    policy = load_policy(desk)
    presence = read_all_presence(desk, now=moment)

    cutoff_5h = moment - float(policy.get("window_5h_seconds", WINDOW_5H_SECONDS))
    cutoff_24h = moment - WINDOW_24H_SECONDS
    cutoff_7d = moment - WINDOW_7D_SECONDS

    events: list[dict[str, Any]] = []
    seen_call_keys: set[str] = set()

    l_file = ledger_file(desk)
    for line in _rows(l_file):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        ts = _parse_ts(row)
        if ts is None or ts < cutoff_7d or ts > moment + 60:
            continue
        eng = _classify_engine(row)
        if eng not in ALL_ENGINES:
            continue
        inp = int(row.get("input_tokens") or 0)
        cr = int(row.get("cache_read_input_tokens") or 0)
        cw = int(row.get("cache_creation_input_tokens") or 0)
        out = int(row.get("output_tokens") or 0)
        raw_tot = inp + cr + cw + out
        if raw_tot <= 0:
            continue
        dedup_key = f"{eng}:{row.get('work_id')}:{int(ts)}:{raw_tot}"
        if dedup_key in seen_call_keys:
            continue
        seen_call_keys.add(dedup_key)
        events.append({
            "engine": eng,
            "ts": ts,
            "work_id": str(row.get("work_id") or ""),
            "uncached_input": inp,
            "cache_read": cr,
            "cache_write": cw,
            "output": out,
            "raw_total": raw_tot,
        })

    for a_row in _scan_agy_auto(desk):
        if a_row["ts"] >= cutoff_7d:
            events.append(a_row)

    for b_row in _scan_agy_brain_transcripts(home_dir, cutoff_7d):
        if b_row["ts"] >= cutoff_7d:
            events.append(b_row)

    sq_events, quotas = _scan_sqlite_ledger(home_dir, cutoff_7d)
    for se in sq_events:
        events.append(se)

    engines_summary: dict[str, dict[str, Any]] = {}
    card_totals: dict[str, list[int]] = {e: [] for e in ALL_ENGINES}

    for eng in ALL_ENGINES:
        eng_events = [e for e in events if e["engine"] == eng]
        ev_5h = [e for e in eng_events if e["ts"] >= cutoff_5h]
        ev_24h = [e for e in eng_events if e["ts"] >= cutoff_24h]

        def _sum_window(ev_list: list[dict[str, Any]]) -> dict[str, int]:
            u_in = sum(e["uncached_input"] for e in ev_list)
            c_rd = sum(e["cache_read"] for e in ev_list)
            c_wr = sum(e["cache_write"] for e in ev_list)
            out_t = sum(e["output"] for e in ev_list)
            eff = _effective_tokens(u_in, c_rd, c_wr, out_t, policy)
            return {
                "calls": len(ev_list),
                "uncached_input_tokens": u_in,
                "cache_read_tokens": c_rd,
                "cache_write_tokens": c_wr,
                "output_tokens": out_t,
                "raw_total_tokens": u_in + c_rd + c_wr + out_t,
                "effective_budget_tokens": eff,
            }

        w5 = _sum_window(ev_5h)
        w24 = _sum_window(ev_24h)
        w7 = _sum_window(eng_events)

        by_card: dict[str, int] = {}
        for e in eng_events:
            cid = str(e.get("work_id") or "").split("-")[0]
            if cid.startswith("U") and len(cid) <= 6:
                eff_e = _effective_tokens(
                    e["uncached_input"], e["cache_read"], e["cache_write"], e["output"], policy
                )
                by_card[cid] = by_card.get(cid, 0) + eff_e
        if by_card:
            card_totals[eng] = list(by_card.values())

        cap_5h = policy["tool_caps_5h"].get(eng)
        default_card_cost = int(policy.get("default_card_cost_tokens", 45000))
        avg_card = (
            int(round(sum(card_totals[eng]) / len(card_totals[eng])))
            if card_totals[eng]
            else (default_card_cost if eng in PAID_TOOLS else 5000)
        )
        avg_card = max(5000, min(avg_card, 250000))

        pres_state = (
            str((presence.get(eng) or {}).get("state") or "UNKNOWN").upper()
            if eng in TOOLS
            else "ACTIVE"
        )
        q_snap = quotas.get(eng)

        has_cap_source = bool(policy.get("tool_caps_source") or policy.get("sources"))
        if cap_5h is not None and cap_5h > 0 and has_cap_source:
            used_eff = w5["effective_budget_tokens"]
            rem_tokens: int | str | None = max(0, int(cap_5h) - used_eff)
            util_pct = round(min(100.0, (used_eff / float(cap_5h)) * 100.0), 1)
            if pres_state in ("LIMITED", "ABSENT"):
                usable_cards: int | str = 0
                status_tier = "LIMITED_PAUSE"
            else:
                usable_cards = int(rem_tokens // max(1, avg_card))
                if util_pct >= float(policy.get("critical_threshold_pct", 90.0)):
                    status_tier = "CRITICAL_OFFLOAD"
                elif util_pct >= float(policy.get("offload_threshold_pct", 70.0)):
                    status_tier = "THROTTLE_TO_LOCAL"
                else:
                    status_tier = "HEALTHY"
        elif eng in PAID_TOOLS:
            rem_tokens = "UNKNOWN"
            util_pct = 0.0
            usable_cards = 0 if pres_state in ("LIMITED", "ABSENT") else "UNKNOWN"
            status_tier = "LIMITED_PAUSE" if pres_state in ("LIMITED", "ABSENT") else "UNMEASURED_CAP"
        else:
            rem_tokens = None
            util_pct = 0.0
            usable_cards = 999
            status_tier = "UNLIMITED_LOCAL"

        engines_summary[eng] = {
            "engine": eng,
            "role": policy["tool_roles"].get(eng, ""),
            "presence_state": pres_state,
            "status_tier": status_tier,
            "budget_cap_5h_tokens": cap_5h,
            "used_5h_effective_tokens": w5["effective_budget_tokens"],
            "used_5h_raw_tokens": w5["raw_total_tokens"],
            "usable_remaining_5h_tokens": rem_tokens,
            "budget_utilization_5h_pct": util_pct,
            "avg_card_cost_tokens": avg_card,
            "usable_cards_capacity": usable_cards,
            "provider_quota_snapshot": q_snap,
            "window_5h": w5,
            "window_24h": w24,
            "window_7d": w7,
        }

    total_calls_24h = sum(engines_summary[e]["window_24h"]["calls"] for e in ALL_ENGINES)
    offload_calls_24h = (
        engines_summary["ollama"]["window_24h"]["calls"]
        + engines_summary["haiku"]["window_24h"]["calls"]
    )
    offload_ratio_pct = round((offload_calls_24h / total_calls_24h) * 100.0, 1) if total_calls_24h > 0 else 0.0

    schedule_plan = build_capacity_aware_schedule(desk, engines_summary, policy)

    snapshot = {
        "schema": "uaos-capacity-snapshot-v1",
        "generated_at": datetime.fromtimestamp(moment, timezone.utc).isoformat().replace("+00:00", "Z"),
        "timestamp": moment,
        "project": str(desk),
        "units_note": (
            "effective_budget_tokens are measured from local transcripts/ledgers (OpenTelemetry gen_ai.usage.*); "
            "provider_quota_snapshot is observed UI/transcript rate-limit percentage and is never converted to tokens."
        ),
        "offload_efficiency_24h": {
            "total_calls_24h": total_calls_24h,
            "ollama_plus_haiku_calls_24h": offload_calls_24h,
            "offload_share_pct": offload_ratio_pct,
        },
        "engines": engines_summary,
        "schedule_recommendation": schedule_plan,
    }

    if persist:
        local_snap = desk / ".coord" / "usage" / "capacity_snapshot.json"
        _atomic_write_json(local_snap, snapshot)
        global_reg = home_dir / ".uaos" / "usage" / "global_capacity_registry.json"
        reg_data: dict[str, Any] = {
            "schema": "uaos-global-capacity-registry-v1",
            "updated_at": snapshot["generated_at"],
            "projects": {},
        }
        if global_reg.is_file():
            try:
                old_reg = json.loads(global_reg.read_text(encoding="utf-8"))
                if isinstance(old_reg, dict) and isinstance(old_reg.get("projects"), dict):
                    reg_data["projects"] = old_reg["projects"]
            except (OSError, ValueError):
                pass
        reg_data["updated_at"] = snapshot["generated_at"]
        reg_data["latest_engines"] = engines_summary
        reg_data["projects"][str(desk)] = {
            "updated_at": snapshot["generated_at"],
            "offload_share_pct": offload_ratio_pct,
            "recommended_conductor": schedule_plan["recommended_conductor"],
            "assignments": schedule_plan["phase_assignments"],
        }
        _atomic_write_json(global_reg, reg_data)

    return snapshot


def build_capacity_aware_schedule(
    desk: Path,
    engines: dict[str, dict[str, Any]],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assign ready/active/review phases across the 3 tools + Ollama/Haiku according to remaining capacity."""
    policy = policy or load_policy(desk)
    sched_path = Path(desk) / ".coord" / "master_schedule.json"
    phases: list[dict[str, Any]] = []
    if sched_path.is_file():
        try:
            raw = json.loads(sched_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("phases"), list):
                phases = [p for p in raw["phases"] if isinstance(p, dict)]
        except (OSError, ValueError):
            pass

    def _rem_int(t: str) -> int | None:
        raw_rem = (engines.get(t) or {}).get("usable_remaining_5h_tokens")
        if isinstance(raw_rem, (int, float)) and not isinstance(raw_rem, bool):
            return int(raw_rem)
        return None

    def _tool_score(t: str) -> tuple[int, int]:
        info = engines.get(t) or {}
        active = 1 if info.get("presence_state") == "ACTIVE" and info.get("status_tier") != "LIMITED_PAUSE" else 0
        rem = _rem_int(t)
        return (active, rem if rem is not None else 0)

    ranked_paid = sorted(PAID_TOOLS, key=_tool_score, reverse=True)
    recommended_conductor = next(
        (t for t in ("codex", "claude", "antigravity") if _tool_score(t)[0] == 1),
        "antigravity",
    )

    virtual_rem: dict[str, int] = {}
    for t in PAID_TOOLS:
        r_val = _rem_int(t)
        virtual_rem[t] = (r_val if r_val is not None else 0) if _tool_score(t)[0] == 1 else 0

    done_ids = {
        str(p.get("phase_id") or p.get("id") or "")
        for p in phases
        if str(p.get("state") or "") in TERMINAL
    }

    assignments: list[dict[str, Any]] = []
    for p in phases:
        state = str(p.get("state") or "")
        if state in TERMINAL:
            continue
        pid = str(p.get("phase_id") or p.get("id") or "").strip()
        if not pid or pid.startswith("STALL-"):
            continue
        deps = p.get("depends_on") or []
        deps_met = not (isinstance(deps, list) and any(str(d) not in done_ids for d in deps))
        est_tokens = int(p.get("estimated_tokens") or policy.get("default_card_cost_tokens", 45000))
        author = str(p.get("author_tool") or p.get("owner_tool") or p.get("owner") or "").lower()
        recorded_reviewer = str(p.get("reviewer") or "").lower()

        if state == "REVIEW":
            review_owner = author if author in PAID_TOOLS else (str(p.get("owner") or "antigravity").lower())
            if recorded_reviewer in PAID_TOOLS and recorded_reviewer != review_owner and virtual_rem.get(recorded_reviewer, 0) > 0:
                chosen_judge = recorded_reviewer
            else:
                candidates = [t for t in PAID_TOOLS if t != review_owner and virtual_rem.get(t, 0) > 0]
                chosen_judge = max(candidates, key=lambda t: virtual_rem[t]) if candidates else "BLOCKED"
            review_cost = int(est_tokens * 0.35)
            if chosen_judge in virtual_rem:
                virtual_rem[chosen_judge] = max(0, virtual_rem.get(chosen_judge, 0) - review_cost)
            assignments.append({
                "phase_id": pid,
                "state": state,
                "deps_met": deps_met,
                "assigned_owner": review_owner,
                "assigned_reviewer": chosen_judge,
                "local_offload": ["ollama:gate_log_summary", "haiku:pre_review_triage"],
                "estimated_paid_tokens": review_cost,
                "sizing_action": "KEEP" if chosen_judge != "BLOCKED" else "BLOCKED_NO_INDEPENDENT_JUDGE",
                "reason": (
                    f"Independent judge ({chosen_judge} != author {review_owner}) with {virtual_rem.get(chosen_judge, 0):,} rem tokens"
                    if chosen_judge != "BLOCKED"
                    else f"BLOCKED: no non-author paid tool != {review_owner} has remaining capacity"
                ),
            })
        elif state in ("READY", "ACTIVE", "PLANNED"):
            candidates = [t for t in PAID_TOOLS if virtual_rem.get(t, 0) > 0]
            chosen_owner = max(candidates, key=lambda t: virtual_rem[t]) if candidates else recommended_conductor
            if recorded_reviewer in PAID_TOOLS and recorded_reviewer != chosen_owner and virtual_rem.get(recorded_reviewer, 0) > 0:
                chosen_reviewer = recorded_reviewer
            else:
                reviewer_cands = [t for t in PAID_TOOLS if t != chosen_owner and virtual_rem.get(t, 0) > 0]
                chosen_reviewer = max(reviewer_cands, key=lambda t: virtual_rem[t]) if reviewer_cands else "BLOCKED"
            paid_share = int(est_tokens * 0.4)
            sizing_action = "SPLIT_CARD" if paid_share > max(1, virtual_rem.get(chosen_owner, 0)) else "KEEP"
            virtual_rem[chosen_owner] = max(0, virtual_rem.get(chosen_owner, 0) - paid_share)
            assignments.append({
                "phase_id": pid,
                "state": state,
                "deps_met": deps_met,
                "assigned_owner": chosen_owner,
                "assigned_reviewer": chosen_reviewer,
                "local_offload": ["ollama:stage1_draft_stage3_slice", "haiku:stage2_map_moderator"],
                "estimated_paid_tokens": paid_share,
                "sizing_action": sizing_action,
                "reason": f"Capacity-weighted owner {chosen_owner} (rem {virtual_rem[chosen_owner]:,} tok) + 60% Ollama/Haiku offload",
            })

    paid_used_5h = sum(int((engines.get(t) or {}).get("used_5h_effective_tokens") or 0) for t in PAID_TOOLS)
    agy_used_5h = int((engines.get("antigravity") or {}).get("used_5h_effective_tokens") or 0)
    agy_used_share_pct = round((agy_used_5h / paid_used_5h) * 100.0, 1) if paid_used_5h > 0 else 0.0
    total_rem_5h = sum(max(0, _rem_int(t) or 0) for t in PAID_TOOLS)
    agy_rem_5h = max(0, _rem_int("antigravity") or 0)
    agy_rem_share_pct = round((agy_rem_5h / total_rem_5h) * 100.0, 1) if total_rem_5h > 0 else 0.0
    argon_mode = (
        "ARGON_ULTRA_PRIMARY_HEAVY_LIFTER"
        if ranked_paid and ranked_paid[0] == "antigravity"
        else "BALANCED_3TOOL_COLLAB"
    )

    return {
        "recommended_conductor": recommended_conductor,
        "ranked_paid_tools": ranked_paid,
        "argon_tier_mode": argon_mode,
        "argon_used_5h_share_pct": agy_used_share_pct,
        "argon_remaining_5h_share_pct": agy_rem_share_pct,
        "post_schedule_remaining_tokens": virtual_rem,
        "phase_assignments": assignments,
    }


def _bar(pct: float, width: int = 12) -> str:
    clamped = max(0.0, min(100.0, float(pct)))
    filled = int(round((clamped / 100.0) * width))
    return "█" * filled + "░" * (width - filled)


def render_terminal_dashboard(snapshot: dict[str, Any]) -> str:
    """Compact, high-visibility terminal/markdown gauge table for `현재 진행상황을 보고해줘`."""
    engines = snapshot.get("engines") or {}
    sched = snapshot.get("schedule_recommendation") or {}
    off = snapshot.get("offload_efficiency_24h") or {}
    lines = [
        "[계기판] [UAOS-RSI 3대 도구 + Ollama/Haiku 실시간 토큰·용량 계기판]",
        f"• 지휘권(Conductor): {sched.get('recommended_conductor', 'unknown').upper()} | 24h 로컬·경량 오프로드율: {off.get('offload_share_pct', 0.0)}% ({off.get('ollama_plus_haiku_calls_24h', 0)}/{off.get('total_calls_24h', 0)} calls)",
        "┌──────────────┬─────────┬──────────────────┬──────────────┬──────────────┬──────────┐",
        "│ 도구(Engine) │ 상태    │ 5h 사용률 게이지 │ 5h 사용 토큰 │ 5h 가용 토큰 │ 가용카드 │",
        "├──────────────┼─────────┼──────────────────┼──────────────┼──────────────┼──────────┤",
    ]
    for eng in ALL_ENGINES:
        info = engines.get(eng) or {}
        st = str(info.get("presence_state") or "ACTIVE")[:7].ljust(7)
        used = int(info.get("used_5h_effective_tokens") or 0)
        rem = info.get("usable_remaining_5h_tokens")
        pct = float(info.get("budget_utilization_5h_pct") or 0.0)
        cards = info.get("usable_cards_capacity")
        q_snap = info.get("provider_quota_snapshot") or {}
        q_str = f" (UI {q_snap['used_percent']:.0f}%)" if q_snap.get("used_percent") is not None else ""
        if rem is None:
            bar_str = "░░░░░░░░░░ 로컬0원"
            rem_str = "   UNLIMITED"
            card_str = "     ∞"
        elif rem == "UNKNOWN":
            bar_str = "░░░░░░░░░░ 미계측 "
            rem_str = "     UNKNOWN"
            card_str = " UNKNOWN"
        else:
            bar_str = f"{_bar(pct, 10)} {pct:4.1f}%"
            rem_str = f"{int(rem):>12,}"
            card_str = f"{int(cards or 0):>5}장"
        lines.append(
            f"│ {eng.ljust(12)} │ {st} │ {bar_str.ljust(16)} │ {used:>12,} │ {rem_str} │ {card_str.ljust(8)} │{q_str}"
        )
    lines.append("└──────────────┴─────────┴──────────────────┴──────────────┴──────────────┴──────────┘")
    assigns = sched.get("phase_assignments") or []
    if assigns:
        lines.append("[스케줄] [용량 기반 마스터·협업 스케줄 자동 배정]")
        for a in assigns[:5]:
            lines.append(
                f"  - {a['phase_id']} ({a['state']}): 담당={a['assigned_owner']} / 검증={a['assigned_reviewer']} "
                f"/ 예상유료={a['estimated_paid_tokens']:,} tok ({a['sizing_action']}) / 오프로드={','.join(a['local_offload'])}"
            )
    return "\n".join(lines)


def render_html_dashboard(snapshot: dict[str, Any], output_path: Path) -> Path:
    """Render a self-contained Tailwind CSS + interactive SVG/JS dynamic dashboard widget (`generative_ui` compliant)."""
    payload_json = json.dumps(snapshot, ensure_ascii=False)
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>UAOS-RSI 3-Tool Token & Capacity Dashboard</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
</head>
<body class="bg-transparent text-[var(--foreground)] antialiased p-3">
  <div class="bg-[var(--card)] text-[var(--foreground)] border border-[var(--border)] rounded-xl p-4 shadow-sm space-y-3">
    <div class="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--border)] pb-2">
      <div>
        <h2 class="text-base font-semibold">⚡ UAOS-RSI 3대 도구 실시간 토큰·한도 및 협업 스케줄 계기판</h2>
        <p class="text-xs text-[var(--muted-foreground)]" id="subtitle">실측 트랜스크립트·장부 기반 5시간 롤링 예산 및 가용 카드 시뮬레이터</p>
      </div>
      <div class="flex items-center gap-2">
        <span id="conductor-badge" class="px-2.5 py-1 rounded-full text-xs font-medium bg-[var(--secondary)] text-[var(--secondary-foreground)]"></span>
        <span id="offload-badge" class="px-2.5 py-1 rounded-full text-xs font-medium border border-[var(--border)]"></span>
      </div>
    </div>

    <div id="gauges-grid" class="grid grid-cols-1 md:grid-cols-5 gap-2.5"></div>

    <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
      <div class="border border-[var(--border)] rounded-lg p-3 space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold">📈 가용 예산 대비 소비 토큰 (동적 비교 그래프)</span>
          <select id="window-select" class="text-xs bg-[var(--background)] border border-[var(--border)] rounded px-2 py-0.5">
            <option value="window_5h">최근 5시간 (롤링 한도)</option>
            <option value="window_24h">최근 24시간</option>
            <option value="window_7d">최근 7일</option>
          </select>
        </div>
        <div id="bars-container" class="space-y-2 pt-1"></div>
      </div>

      <div class="border border-[var(--border)] rounded-lg p-3 space-y-2">
        <div class="flex items-center justify-between">
          <span class="text-xs font-semibold">🗓️ 용량 연동 마스터·협업 스케줄 시뮬레이터</span>
          <span class="text-xs text-[var(--muted-foreground)]" id="sched-count"></span>
        </div>
        <div id="schedule-list" class="space-y-1.5 text-xs"></div>
      </div>
    </div>
  </div>

  <script>
    const SNAP = {payload_json};
    const ENGINES_ORDER = ["codex", "claude", "antigravity", "haiku", "ollama"];
    const LABELS = {{
      codex: "Codex (조율·판정)",
      claude: "Claude Code (부지휘)",
      antigravity: "Antigravity Argon (12만원 주력·중재)",
      haiku: "Haiku 5.5 (경량 분담)",
      ollama: "Ollama CLI (0원 계산기)"
    }};

    function fmt(n) {{
      if (n === null || n === undefined) return "∞ (무제한)"; if (n === "UNKNOWN") return "미계측(UNKNOWN)"; return Number(n).toLocaleString();
    }}

    function renderAll(winKey) {{
      const sched = SNAP.schedule_recommendation || {{}};
      const off = SNAP.offload_efficiency_24h || {{}};
      document.getElementById("conductor-badge").textContent =
        "지휘: " + String(sched.recommended_conductor || "antigravity").toUpperCase() + " | 아르곤 5h 작업점유: " + (sched.argon_used_5h_share_pct ?? 0) + "% (가용점유 " + (sched.argon_remaining_5h_share_pct ?? 0) + "%)";
      document.getElementById("offload-badge").textContent =
        "Ollama+Haiku 오프로드: " + (off.offload_share_pct ?? 0) + "% (" + (off.ollama_plus_haiku_calls_24h ?? 0) + "회)";

      const gaugesGrid = document.getElementById("gauges-grid");
      gaugesGrid.innerHTML = "";
      const barsContainer = document.getElementById("bars-container");
      barsContainer.innerHTML = "";

      let maxTokens = 1;
      ENGINES_ORDER.forEach(eng => {{
        const info = (SNAP.engines || {{}})[eng] || {{}};
        const w = info[winKey] || {{}};
        if ((w.effective_budget_tokens || 0) > maxTokens) maxTokens = w.effective_budget_tokens;
      }});

      ENGINES_ORDER.forEach(eng => {{
        const info = (SNAP.engines || {{}})[eng] || {{}};
        const w = info[winKey] || {{}};
        const pct = Number(info.budget_utilization_5h_pct || 0);
        const state = info.presence_state || "ACTIVE";
        const rem = info.usable_remaining_5h_tokens;
        const cards = info.usable_cards_capacity;
        const q = info.provider_quota_snapshot;
        const qText = (q && q.used_percent !== null && q.used_percent !== undefined)
          ? ` | 계정UI ${{q.used_percent}}%` : "";

        const card = document.createElement("div");
        card.className = "border border-[var(--border)] rounded-lg p-2.5 flex flex-col justify-between space-y-1.5";
        card.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold">${{LABELS[eng] || eng}}</span>
            <span class="text-xs px-1.5 py-0.5 rounded bg-[var(--secondary)] text-[var(--secondary-foreground)]">${{state}}</span>
          </div>
          <div class="text-xs text-[var(--muted-foreground)]">
            사용: <strong class="text-[var(--foreground)]">${{fmt(w.effective_budget_tokens || 0)}}</strong> tok
          </div>
          <div class="text-xs text-[var(--muted-foreground)]">
            가용: <strong class="text-[var(--foreground)]">${{rem === null ? "무제한(0원)" : fmt(rem) + " tok"}}</strong>
          </div>
          <div class="w-full bg-[var(--secondary)] h-2 rounded-full overflow-hidden">
            <div class="bg-[var(--primary)] h-2 rounded-full" style="width: ${{rem === null ? 15 : Math.min(100, Math.max(4, pct))}}%"></div>
          </div>
          <div class="flex items-center justify-between text-xs">
            <span>5h 소진율: ${{rem === null ? "0%" : pct + "%"}}${{qText}}</span>
            <span class="font-semibold">${{rem === null ? "∞ 카드" : "가용 " + cards + "장"}}</span>
          </div>
        `;
        gaugesGrid.appendChild(card);

        const relPct = Math.min(100, Math.max(3, Math.round(((w.effective_budget_tokens || 0) / maxTokens) * 100)));
        const barRow = document.createElement("div");
        barRow.className = "space-y-0.5";
        barRow.innerHTML = `
          <div class="flex justify-between text-xs">
            <span>${{LABELS[eng] || eng}} (${{w.calls || 0}} calls)</span>
            <span>유효 ${{fmt(w.effective_budget_tokens || 0)}} / 원본 ${{fmt(w.raw_total_tokens || 0)}} tok</span>
          </div>
          <div class="w-full bg-[var(--secondary)] h-2 rounded-full overflow-hidden">
            <div class="bg-[var(--primary)] h-2 rounded-full" style="width: ${{relPct}}%"></div>
          </div>
        `;
        barsContainer.appendChild(barRow);
      }});

      const assigns = sched.phase_assignments || [];
      document.getElementById("sched-count").textContent = `활성·대기 ${{assigns.length}}개 단계`;
      const schedList = document.getElementById("schedule-list");
      schedList.innerHTML = "";
      if (assigns.length === 0) {{
        schedList.innerHTML = `<div class="text-[var(--muted-foreground)]">모든 활성 단계가 DONE 상태입니다. 새 카드 생성 시 가용 토큰 최다 도구에 자동 배정됩니다.</div>`;
      }} else {{
        assigns.forEach(a => {{
          const row = document.createElement("div");
          row.className = "border border-[var(--border)] rounded p-2 flex flex-col gap-0.5";
          row.innerHTML = `
            <div class="flex items-center justify-between font-semibold">
              <span>[${{a.phase_id}}] 상태: ${{a.state}}</span>
              <span>담당: ${{a.assigned_owner.toUpperCase()}} → 검증: ${{a.assigned_reviewer.toUpperCase()}}</span>
            </div>
            <div class="text-[var(--muted-foreground)]">
              예상 유료 토큰: ${{fmt(a.estimated_paid_tokens)}} (${{a.sizing_action}}) | 오프로드: ${{(a.local_offload || []).join(", ")}}
            </div>
          `;
          schedList.appendChild(row);
        }});
      }}
    }}

    document.getElementById("window-select").addEventListener("change", (e) => renderAll(e.target.value));
    renderAll("window_5h");
  </script>
</body>
</html>
"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8", newline="\n")
    return output_path
