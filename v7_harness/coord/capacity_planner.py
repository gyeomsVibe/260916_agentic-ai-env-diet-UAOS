"""U256: Unified 3-Tool + Ollama/Haiku Token & Capacity Store, Capacity-Aware Master/Collaboration Scheduler,
and Dynamic Visual Telemetry Dashboard (`현재 진행상황을 보고해줘`).

Advisory-only planner: `collect_capacity_snapshot` and `build_capacity_aware_schedule` read
`.coord/master_schedule.json` to compute capacity-aware recommendations and never write or mutate
`.coord/master_schedule.json`.

Follows OpenTelemetry GenAI semantic conventions (`gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`) and
UAOS-RSI `docs/27_token-budget-routing-policy.md`:
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
    "tool_caps_7d": {
        "codex": None,
        "claude": None,
        "antigravity": None,
        "haiku": None,
        "ollama": None,
    },
    "subscription_tiers": {
        "codex": {
            "plan_name": "ChatGPT Plus ($20/월) · GPT-5.4 Codex Astra",
            "short_plan": "Plus $20 (Astra)",
            "reference_cap_5h_tokens": 7000000,
            "reference_cap_24h_tokens": 25000000,
            "reference_cap_7d_tokens": 175000000,
            "offload_policy": "핵심 키포인트(아키텍처·보안·최종판정) 집중 + 일반검수 위임(U257)",
        },
        "claude": {
            "plan_name": "Claude Code 구독제 (Opus/Sonnet 20% + Haiku 30% + Ollama 50%)",
            "short_plan": "Claude Sub (5:3:2)",
            "reference_cap_5h_tokens": 15000000,
            "reference_cap_24h_tokens": 45000000,
            "reference_cap_7d_tokens": 180000000,
            "offload_policy": "올라마 50% : Haiku 5.5 30% : Opus/Sonnet 20% 이원 분리 병렬(U271)",
        },
        "antigravity": {
            "plan_name": "Google AI Ultra (Pro 대비 5x 사용량) · Gemini 4 Argon",
            "short_plan": "AI Ultra 5x (Argon)",
            "reference_cap_5h_tokens": 75000000,
            "reference_cap_24h_tokens": 220000000,
            "reference_cap_7d_tokens": 600000000,
            "offload_policy": "5x 대용량 주력 실행·교차검증·1순위 자율병합 + 올라마 0토큰 선행",
        },
        "haiku": {
            "plan_name": "Claude Haiku 5.5 경량 서브오케스트레이터 (건당 12K 상한)",
            "short_plan": "Haiku 5.5 (30% 분담)",
            "reference_cap_5h_tokens": 6000000,
            "reference_cap_24h_tokens": 18000000,
            "reference_cap_7d_tokens": 60000000,
            "offload_policy": "tests/*·docs/* 물리 분리 병렬(DISJOINT_PARALLEL_OVERLAP)",
        },
        "ollama": {
            "plan_name": "Ollama 로컬 0토큰 전자계산기 (qwen2.5-coder:7b)",
            "short_plan": "로컬 0원 (50% 분담)",
            "reference_cap_5h_tokens": None,
            "reference_cap_24h_tokens": None,
            "reference_cap_7d_tokens": None,
            "offload_policy": "250줄+ 탐색(local_read_map)·초안(local_draft)·20~30줄 코드패치 0토큰",
        },
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
        "argon_routing": "Capacity-weighted Argon heavy-lifter routing in docs/27_token-budget-routing-policy.md and docs/29_antigravity-budget-manual.md",
    },
    "tool_roles": {
        "codex": "Conductor & Final Independent Judge",
        "claude": "Co-Conductor & Deep Implementer/Reviewer",
        "antigravity": "Google AI Ultra (Pro 대비 5x 사용량) · Gemini 4 Argon",
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


def atomic_write_if_hash_matches(
    path: Path,
    data: Any,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """U276 (Transplanted from Cockpit Tools `config.rs:save_global_config_if_hash_matches`):
    Compare-and-swap atomic JSON writer with `.bak` backup before replacement.
    Stages to a unique temp file first, then serializes check+backup+replace under a process-wide RLock.
    """
    import hashlib
    import sys
    import threading

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage_path = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.stage")
    try:
        _atomic_write_json(stage_path, data)
        cas_lock = sys.__dict__.setdefault("_uaos_cas_lock", threading.RLock())
        with cas_lock:
            current_sha: str | None = None
            raw_existing = b""
            exists_now = target.is_file()
            if exists_now:
                try:
                    raw_existing = target.read_bytes()
                    current_sha = hashlib.sha256(raw_existing).hexdigest()
                except OSError as exc:
                    return {
                        "ok": False,
                        "error": f"CAS_READ_FAILED:{exc}",
                        "expected_sha256": expected_sha256,
                        "actual_sha256": None,
                    }
            if expected_sha256 is not None:
                if not exists_now:
                    return {
                        "ok": False,
                        "error": "CAS_TARGET_MISSING",
                        "expected_sha256": expected_sha256,
                        "actual_sha256": None,
                    }
                if current_sha != expected_sha256:
                    return {
                        "ok": False,
                        "error": "CAS_HASH_MISMATCH",
                        "expected_sha256": expected_sha256,
                        "actual_sha256": current_sha,
                    }
            bak_path = target.with_name(target.name + ".bak")
            if exists_now and raw_existing:
                try:
                    json.loads(raw_existing.decode("utf-8"))
                    bak_path.write_bytes(raw_existing)
                except (OSError, ValueError, UnicodeDecodeError):
                    pass
            os.replace(str(stage_path), str(target))
            new_sha = hashlib.sha256(target.read_bytes()).hexdigest()
            return {
                "ok": True,
                "path": target.as_posix(),
                "previous_sha256": current_sha,
                "new_sha256": new_sha,
                "backup_path": str(bak_path),
            }
    finally:
        if stage_path.exists():
            try:
                stage_path.unlink()
            except OSError:
                pass


def parse_json_with_auto_restore(path: Path, default: Any = None) -> Any:
    """U276 (Transplanted from Cockpit Tools `modules/config.rs` `.bak` auto-restore):
    Reads JSON from `path`; if corrupted/truncated, restores from `<path>.bak` without clobbering newer concurrent CAS writes.
    """
    import sys
    import threading

    target = Path(path)
    bak_path = target.with_name(target.name + ".bak")
    cas_lock = sys.__dict__.setdefault("_uaos_cas_lock", threading.RLock())
    with cas_lock:
        if target.is_file():
            try:
                raw_bytes = target.read_bytes()
                return json.loads(raw_bytes.decode("utf-8"))
            except (OSError, ValueError, UnicodeDecodeError):
                corrupt_bytes: bytes | None = raw_bytes if "raw_bytes" in locals() else None
        else:
            corrupt_bytes = None
        if not bak_path.is_file():
            return default
        try:
            restored = json.loads(bak_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    stage_restore = target.with_name(f".{target.name}.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.restore")
    try:
        _atomic_write_json(stage_restore, restored)
        with cas_lock:
            if target.is_file():
                try:
                    now_bytes = target.read_bytes()
                    if corrupt_bytes is not None and now_bytes != corrupt_bytes:
                        return json.loads(now_bytes.decode("utf-8"))
                except (OSError, ValueError, UnicodeDecodeError):
                    pass
            os.replace(str(stage_restore), str(target))
            return restored
    finally:
        if stage_restore.exists():
            try:
                stage_restore.unlink()
            except OSError:
                pass


def scan_cockpit_sqlite_telemetry(home_dir: Path | None = None) -> dict[str, Any]:
    """U276 (Transplanted from Cockpit Tools `codex_session_usage.sqlite` / `Token_stats.db`):
    Read-only single-query snapshot of `session_usage_events` and `session_log_sync`.
    """
    import sqlite3

    if home_dir is not None and (Path(home_dir).is_file() or Path(home_dir).suffix.lower() in (".sqlite", ".db")):
        db_file = Path(home_dir)
    else:
        base_home = Path(home_dir) if home_dir is not None else Path.home()
        cand1 = base_home / ".antigravity_cockpit" / "codex_session_usage.sqlite"
        cand2 = base_home / ".antigravity_cockpit" / "Token_stats.db"
        db_file = cand1 if cand1.is_file() or not cand2.is_file() else cand2

    if not db_file.is_file():
        return {
            "available": False,
            "db_path": str(db_file),
            "synced_files": 0,
            "synced_files_count": 0,
            "total_events": 0,
            "events_count": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "cache_hit_pct": 0.0,
        }
    try:
        uri = db_file.resolve().as_uri() + "?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=3)
        try:
            cur = con.cursor()
            cur.execute(
                "SELECT COUNT(*), COALESCE(SUM(input_tokens), 0), "
                "COALESCE(SUM(cached_input_tokens), 0), COALESCE(SUM(output_tokens), 0), "
                "(SELECT COUNT(*) FROM session_log_sync) "
                "FROM session_usage_events"
            )
            row = cur.fetchone() or (0, 0, 0, 0, 0)
            ev_count = int(row[0] or 0)
            inp_tok = int(row[1] or 0)
            cached_tok = int(row[2] or 0)
            out_tok = int(row[3] or 0)
            synced_files = int(row[4] or 0)
            cache_hit_pct = round((cached_tok / float(inp_tok)) * 100.0, 1) if inp_tok > 0 else 0.0
            return {
                "available": True,
                "db_path": str(db_file),
                "synced_files": synced_files,
                "synced_files_count": synced_files,
                "total_events": ev_count,
                "events_count": ev_count,
                "input_tokens": inp_tok,
                "cached_input_tokens": cached_tok,
                "output_tokens": out_tok,
                "cache_hit_pct": cache_hit_pct,
            }
        finally:
            con.close()
    except Exception:
        return {
            "available": False,
            "db_path": str(db_file),
            "synced_files": 0,
            "synced_files_count": 0,
            "total_events": 0,
            "events_count": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "cache_hit_pct": 0.0,
        }


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
    for key in ("ts", "timestamp", "window_end", "observed_at", "resets_at"):
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
            if not isinstance(d, dict):
                continue
            usage = d.get("usage")
            if isinstance(usage, dict):
                inp = int(usage.get("input_tokens") or 0)
                cr = int(usage.get("cache_read_tokens") or 0)
                cw = int(usage.get("cache_creation_input_tokens") or 0)
                out_t = int(usage.get("output_tokens") or 0)
                raw_tot = inp + cr + cw + out_t
                if raw_tot <= 0:
                    raw_tot = int(usage.get("total_tokens") or 0)
                    inp = int(raw_tot * 0.85)
                    out_t = max(0, raw_tot - inp)
                if raw_tot > 0:
                    rows.append({
                        "engine": "antigravity",
                        "ts": float(d.get("ts") or d.get("at") or 0.0),
                        "work_id": str(d.get("card") or d.get("message_id") or "agy_auto"),
                        "conv_id": str(d.get("conversation_id") or d.get("session") or ""),
                        "uncached_input": inp,
                        "cache_read": cr,
                        "cache_write": cw,
                        "output": out_t,
                        "raw_total": raw_tot,
                    })
            elif int(d.get("tokens") or 0) > 0:
                tok = int(d["tokens"])
                rows.append({
                    "engine": "antigravity",
                    "ts": float(d.get("ts") or d.get("at") or 0.0),
                    "work_id": str(d.get("card") or d.get("message_id") or "agy_auto"),
                    "conv_id": str(d.get("conversation_id") or d.get("session") or ""),
                    "uncached_input": int(tok * 0.85),
                    "cache_read": 0,
                    "cache_write": 0,
                    "output": int(tok * 0.15),
                    "raw_total": tok,
                })
    except OSError:
        pass
    return rows


def _auto_sync_usage_accounting(home: Path, now: float) -> None:
    """Incrementally sync ~/.codex/sessions, ~/.claude/projects, and ~/.cache/olla into ledger.sqlite3 with 0 paid tokens."""
    db_path = home / ".uaos" / "usage" / "ledger.sqlite3"
    if not db_path.is_file():
        return
    if not ((home / ".codex" / "sessions").is_dir() or (home / ".claude" / "projects").is_dir()):
        return
    stamp_path = home / ".uaos" / "usage" / ".last_collect_stamp.json"
    try:
        if stamp_path.is_file():
            st = json.loads(stamp_path.read_text(encoding="utf-8"))
            if isinstance(st, dict) and 0.0 <= (now - float(st.get("ts") or 0.0)) < 60.0:
                return
        from v7_harness.usage_accounting import collect as collect_sqlite_ledger

        collect_sqlite_ledger(home=home, db=db_path)
        _atomic_write_json(stamp_path, {"ts": now})
    except Exception:
        pass


def _scan_sqlite_ledger(
    home: Path,
    cutoff_7d: float,
    *,
    now: float | None = None,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    moment = float(now if now is not None else (cutoff_7d + WINDOW_7D_SECONDS))
    _auto_sync_usage_accounting(home, moment)
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
                    "conv_id": str(d.get("event_key") or ""),
                    "uncached_input": inp,
                    "cache_read": cr,
                    "cache_write": cw,
                    "output": out,
                    "raw_total": inp + cr + cw + out,
                })
            quotas_5h: dict[str, dict[str, Any]] = {}
            quotas_7d: dict[str, dict[str, Any]] = {}
            for q in con.execute(
                """SELECT provider, observed_at, used_percent, window_minutes, resets_at, origin
                   FROM quota_snapshots ORDER BY observed_at ASC"""
            ):
                qd = dict(q)
                prov = str(qd.get("provider") or "")
                if not prov:
                    continue
                obs_ts = _parse_ts({"observed_at": qd.get("observed_at")})
                res_ts = _parse_ts({"resets_at": qd.get("resets_at")})
                win_min = int(qd["window_minutes"]) if qd.get("window_minutes") is not None else 300
                win_sec = max(WINDOW_5H_SECONDS, win_min * 60)
                if obs_ts is not None and res_ts is None and (moment - obs_ts) > WINDOW_24H_SECONDS:
                    continue
                if obs_ts is not None and (moment - obs_ts) > WINDOW_7D_SECONDS:
                    continue
                raw_used_pct = float(qd["used_percent"]) if qd.get("used_percent") is not None else None
                reset_elapsed = bool(res_ts is not None and res_ts <= moment)
                eff_used_pct = 0.0 if reset_elapsed else raw_used_pct
                eff_rem_pct = round(100.0 - eff_used_pct, 1) if eff_used_pct is not None else None
                entry = {
                    "used_percent": eff_used_pct,
                    "remaining_percent": eff_rem_pct,
                    "pre_reset_used_percent": raw_used_pct,
                    "window_minutes": qd.get("window_minutes"),
                    "resets_at": qd.get("resets_at"),
                    "reset_in_seconds": max(0, int(res_ts - moment)) if (res_ts is not None and not reset_elapsed) else 0,
                    "quota_reset_ready": reset_elapsed,
                    "observed_at": qd.get("observed_at"),
                    "origin": qd.get("origin"),
                }
                if win_min <= 360:
                    quotas_5h[prov] = entry
                else:
                    quotas_7d[prov] = entry
            for prov in set(quotas_5h) | set(quotas_7d):
                primary = dict(quotas_5h.get(prov) or quotas_7d.get(prov) or {})
                primary["window_5h_quota"] = quotas_5h.get(prov)
                primary["window_7d_quota"] = quotas_7d.get(prov)
                quotas[prov] = primary
        finally:
            con.close()
    except Exception:
        pass
    return events, quotas




def _parse_brain_planner_lines(lines: list[str], conv_id: str) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
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
        inp = int(row.get("input_tokens") or 0)
        cr = int(row.get("cache_read_tokens") or 0)
        cw = int(row.get("cache_creation_input_tokens") or 0)
        out_t = int(row.get("output_tokens") or 0)
        tot = inp + cr + cw + out_t
        if tot <= 0:
            continue
        parsed.append({
            "engine": "antigravity",
            "source_kind": "brain_step",
            "ts": ts,
            "work_id": f"agy-brain-{conv_id[:8]}-{row.get('step_index', 0)}",
            "conv_id": conv_id,
            "uncached_input": inp,
            "cache_read": cr,
            "cache_write": cw,
            "output": out_t,
            "raw_total": tot,
        })
    return parsed


def _scan_agy_brain_transcripts(
    home_dir: Path,
    cutoff_ts: float,
    watermark_path: Path | None = None,
) -> list[dict[str, Any]]:
    """Incrementally ingest Antigravity (Gemini 4 Argon) PLANNER_RESPONSE token counts using newline-safe byte watermarks."""
    import hashlib

    from v7_harness.coord.stream import _exclusive

    brain_root = home_dir / ".gemini" / "antigravity" / "brain"
    if not brain_root.is_dir():
        return []
    wm_file = watermark_path or (home_dir / ".uaos" / "usage" / "brain_transcript_watermark.json")
    wm_file.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive(wm_file.with_suffix(".lock")):
        wm_files: dict[str, dict[str, Any]] = {}
        if wm_file.is_file():
            try:
                raw_wm = json.loads(wm_file.read_text(encoding="utf-8"))
                if isinstance(raw_wm, dict) and isinstance(raw_wm.get("files"), dict):
                    wm_files = raw_wm["files"]
            except (OSError, ValueError):
                wm_files = {}

        dirty = False
        out: list[dict[str, Any]] = []
        seen_f_keys: set[str] = set()

        for tf in brain_root.glob("*/.system_generated/logs/transcript.jsonl"):
            try:
                st = tf.stat()
                f_size = int(st.st_size)
                f_mtime = float(st.st_mtime)
            except OSError:
                continue
            f_key = str(tf)
            seen_f_keys.add(f_key)
            if cutoff_ts <= time.time() and f_mtime < cutoff_ts:
                if f_key in wm_files:
                    wm_files.pop(f_key, None)
                    dirty = True
                continue
            conv_id = tf.parts[-4] if len(tf.parts) >= 4 else tf.parent.name
            cached = wm_files.get(f_key)
            cached_ok = False
            if isinstance(cached, dict) and isinstance(cached.get("events"), list):
                try:
                    c_size = int(cached.get("file_size") if cached.get("file_size") is not None else -1)
                    c_mtime = float(cached.get("mtime") or 0.0)
                    c_offset = int(cached.get("offset") or 0)
                    events_valid = all(isinstance(ev, dict) and isinstance(ev.get("ts"), (int, float)) for ev in cached["events"])
                    cached_ok = events_valid and c_offset >= 0
                except (TypeError, ValueError):
                    cached_ok = False
            else:
                c_size, c_mtime, c_offset = -1, 0.0, 0

            if cached_ok and c_size == f_size and abs(c_mtime - f_mtime) < 1e-3:
                file_events = [ev for ev in cached["events"] if float(ev.get("ts") or 0.0) >= cutoff_ts]
                if len(file_events) != len(cached["events"]):
                    wm_files[f_key]["events"] = file_events
                    dirty = True
            else:
                prev_offset = c_offset if cached_ok else 0
                prev_prefix_sha = str(cached.get("prefix_sha") or "") if (cached_ok and isinstance(cached, dict)) else ""
                can_seek = False
                cur_prefix_sha = ""
                try:
                    with tf.open("rb") as fh:
                        if cached_ok and 0 < prev_offset <= f_size and prev_prefix_sha:
                            prefix_bytes = fh.read(prev_offset)
                            h = hashlib.sha256(prefix_bytes)
                            if prefix_bytes.endswith(b"\n") and h.hexdigest()[:16] == prev_prefix_sha:
                                can_seek = True
                                raw_chunk = fh.read(f_size - prev_offset)
                            else:
                                fh.seek(0)
                                raw_chunk = fh.read(f_size)
                                h = hashlib.sha256()
                        else:
                            fh.seek(0)
                            raw_chunk = fh.read(f_size)
                            h = hashlib.sha256()
                        last_nl = raw_chunk.rfind(b"\n")
                        if last_nl == -1:
                            complete_bytes = b""
                            new_offset = prev_offset if can_seek else 0
                        else:
                            complete_bytes = raw_chunk[: last_nl + 1]
                            new_offset = (prev_offset + last_nl + 1) if can_seek else (last_nl + 1)
                        if complete_bytes:
                            h.update(complete_bytes)
                        cur_prefix_sha = h.hexdigest()[:16] if new_offset > 0 else ""
                except OSError:
                    continue

                chunk_lines = complete_bytes.decode("utf-8", errors="replace").splitlines()
                parsed_new = _parse_brain_planner_lines(chunk_lines, conv_id)
                base_events = list(cached["events"]) if (can_seek and cached_ok and isinstance(cached, dict)) else []
                file_events = [ev for ev in (base_events + parsed_new) if isinstance(ev, dict) and float(ev.get("ts") or 0.0) >= cutoff_ts]
                wm_files[f_key] = {
                    "offset": new_offset,
                    "file_size": f_size,
                    "mtime": f_mtime,
                    "prefix_sha": cur_prefix_sha,
                    "events": file_events,
                }
                dirty = True

            out.extend(file_events)

        stale_keys = [k for k in wm_files if k not in seen_f_keys]
        for k in stale_keys:
            wm_files.pop(k, None)
            dirty = True

        if dirty:
            try:
                _atomic_write_json(wm_file, {"schema": "uaos-brain-watermark-v1", "files": wm_files})
            except OSError:
                pass
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
            "conv_id": str(row.get("conversation_id") or row.get("session") or row.get("receipt") or ""),
            "uncached_input": inp,
            "cache_read": cr,
            "cache_write": cw,
            "output": out,
            "raw_total": raw_tot,
        })

    def _is_dup_event(cand: dict[str, Any], prior_list: list[dict[str, Any]]) -> bool:
        c_eng = cand.get("engine")
        c_conv = str(cand.get("conv_id") or "").strip()
        c_wid = str(cand.get("work_id") or "").strip()
        c_ts = float(cand.get("ts") or 0.0)
        c_tot = int(cand.get("raw_total") or 0)
        c_io = (int(cand.get("uncached_input") or 0), int(cand.get("output") or 0))
        for ex in prior_list:
            if ex.get("engine") != c_eng:
                continue
            e_conv = str(ex.get("conv_id") or "").strip()
            e_wid = str(ex.get("work_id") or "").strip()
            if c_conv and e_conv and (c_conv == e_conv or c_conv in e_conv or e_conv in c_conv):
                return True
            if c_conv and e_wid and (c_conv == e_wid or c_conv[:8] in e_wid):
                return True
            if e_conv and c_wid and (e_conv == c_wid or e_conv[:8] in c_wid):
                return True
            if abs(c_ts - float(ex.get("ts") or 0.0)) <= 300.0:
                if c_tot > 0 and c_tot == int(ex.get("raw_total") or 0):
                    return True
                if c_io[0] > 0 and c_io == (int(ex.get("uncached_input") or 0), int(ex.get("output") or 0)):
                    return True
        return False

    sq_events, quotas = _scan_sqlite_ledger(home_dir, cutoff_7d, now=moment)
    prior_after_ledger = list(events)
    for se in sq_events:
        if not _is_dup_event(se, prior_after_ledger):
            events.append(se)

    prior_after_sq = list(events)
    for a_row in _scan_agy_auto(desk):
        if a_row["ts"] >= cutoff_7d and not _is_dup_event(a_row, prior_after_sq):
            events.append(a_row)

    prior_before_brain = list(events)
    for b_row in _scan_agy_brain_transcripts(home_dir, cutoff_7d):
        if b_row["ts"] >= cutoff_7d and not _is_dup_event(b_row, prior_before_brain):
            events.append(b_row)

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

        tier_meta = (policy.get("subscription_tiers") or {}).get(eng) or {}
        cap_7d_cfg = (policy.get("tool_caps_7d") or {}).get(eng)
        ref_cap_5h = int(cap_5h) if (cap_5h is not None and int(cap_5h) > 0) else tier_meta.get("reference_cap_5h_tokens")
        ref_cap_24h = tier_meta.get("reference_cap_24h_tokens")
        ref_cap_7d = int(cap_7d_cfg) if (cap_7d_cfg is not None and int(cap_7d_cfg) > 0) else tier_meta.get("reference_cap_7d_tokens")
        q_5h = (q_snap or {}).get("window_5h_quota") if isinstance(q_snap, dict) else None
        q_7d = (q_snap or {}).get("window_7d_quota") if isinstance(q_snap, dict) else None
        quota_reset_ready = bool((q_snap or {}).get("quota_reset_ready")) if isinstance(q_snap, dict) else False

        has_cap_source = bool(policy.get("tool_caps_source") or policy.get("sources"))
        active_burst_reserve = 0
        if cap_5h is not None and cap_5h > 0 and has_cap_source:
            used_eff = w5["effective_budget_tokens"]
            rem_tokens: int | str | None = max(0, int(cap_5h) - used_eff)
            util_pct = round(min(100.0, (used_eff / float(cap_5h)) * 100.0), 1)
            if pres_state in ("LIMITED", "ABSENT") and not quota_reset_ready:
                usable_cards: int | str = 0
                status_tier = "LIMITED_PAUSE"
            else:
                if int(rem_tokens) == 0:
                    # Active session (or reset-elapsed session) exceeding soft 5h envelope enters THRIFT_OVERDRIVE reserve
                    active_burst_reserve = max(avg_card * 3, int(cap_5h * 0.15))
                    usable_cards = max(1, int(active_burst_reserve // max(1, avg_card)))
                    status_tier = "THRIFT_OVERDRIVE"
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
            usable_cards = 0 if (pres_state in ("LIMITED", "ABSENT") and not quota_reset_ready) else "UNKNOWN"
            status_tier = "LIMITED_PAUSE" if (pres_state in ("LIMITED", "ABSENT") and not quota_reset_ready) else "UNMEASURED_CAP"
        else:
            rem_tokens = None
            util_pct = 0.0
            usable_cards = 999
            status_tier = "UNLIMITED_LOCAL"

        sub_rem_5h = max(0, int(ref_cap_5h) - w5["effective_budget_tokens"]) if ref_cap_5h else None
        sub_pct_5h = round(min(100.0, (w5["effective_budget_tokens"] / float(ref_cap_5h)) * 100.0), 1) if ref_cap_5h else 0.0
        sub_rem_24h = max(0, int(ref_cap_24h) - w24["effective_budget_tokens"]) if ref_cap_24h else None
        sub_pct_24h = round(min(100.0, (w24["effective_budget_tokens"] / float(ref_cap_24h)) * 100.0), 1) if ref_cap_24h else 0.0
        sub_rem_7d = max(0, int(ref_cap_7d) - w7["effective_budget_tokens"]) if ref_cap_7d else None
        sub_pct_7d = round(min(100.0, (w7["effective_budget_tokens"] / float(ref_cap_7d)) * 100.0), 1) if ref_cap_7d else 0.0

        q5_ui_val = (q_5h or {}).get("used_percent") if isinstance(q_5h, dict) else (q_snap or {}).get("used_percent") if isinstance(q_snap, dict) else None
        q7_ui_val = (q_7d or {}).get("used_percent") if isinstance(q_7d, dict) else None
        burn_rate_hr = round(float(w5["effective_budget_tokens"]) / 5.0, 1)
        sched_rem_for_tta = int(sub_rem_5h or 0) + int(active_burst_reserve or 0) if ref_cap_5h else None
        if ref_cap_5h is None:
            predicted_tta_min: float | None = None
            exhaustion_risk = "UNLIMITED_LOCAL"
            preemptive_handoff = False
        else:
            predicted_tta_min = (
                round((float(sched_rem_for_tta or 0) / burn_rate_hr) * 60.0, 1)
                if burn_rate_hr > 0
                else 9999.0
            )
            eff_pressure = max(
                float(sub_pct_5h or 0.0),
                float(sub_pct_7d or 0.0) * 0.9,
                float(q5_ui_val or 0.0),
                float(q7_ui_val or 0.0) * 0.85,
            )
            if (pres_state in ("LIMITED", "ABSENT") and not quota_reset_ready) or eff_pressure >= 90.0 or predicted_tta_min <= 15.0:
                exhaustion_risk = "IMMINENT_EXHAUSTION"
                preemptive_handoff = True
            elif eff_pressure >= 72.0 or predicted_tta_min <= 45.0:
                exhaustion_risk = "PRE_HANDOFF_WARNING"
                preemptive_handoff = True
            else:
                exhaustion_risk = "SAFE"
                preemptive_handoff = False

        predictive_exhaustion = {
            "burn_rate_tok_per_hr": burn_rate_hr,
            "predicted_tta_min": predicted_tta_min,
            "exhaustion_risk": exhaustion_risk,
            "preemptive_handoff_recommended": preemptive_handoff,
        }

        subscription_plan = {
            "plan_name": str(tier_meta.get("plan_name") or policy["tool_roles"].get(eng, eng)),
            "short_plan": str(tier_meta.get("short_plan") or eng),
            "offload_policy": str(tier_meta.get("offload_policy") or ""),
            "total_5h_tokens": ref_cap_5h,
            "used_5h_effective_tokens": w5["effective_budget_tokens"],
            "used_5h_raw_tokens": w5["raw_total_tokens"],
            "remaining_5h_tokens": sub_rem_5h,
            "utilization_5h_pct": sub_pct_5h,
            "total_24h_tokens": ref_cap_24h,
            "used_24h_effective_tokens": w24["effective_budget_tokens"],
            "used_24h_raw_tokens": w24["raw_total_tokens"],
            "remaining_24h_tokens": sub_rem_24h,
            "utilization_24h_pct": sub_pct_24h,
            "total_7d_tokens": ref_cap_7d,
            "used_7d_effective_tokens": w7["effective_budget_tokens"],
            "used_7d_raw_tokens": w7["raw_total_tokens"],
            "remaining_7d_tokens": sub_rem_7d,
            "utilization_7d_pct": sub_pct_7d,
            "quota_5h_ui_pct": q5_ui_val,
            "quota_7d_ui_pct": q7_ui_val,
            "resets_at_5h": (q_5h or {}).get("resets_at") if isinstance(q_5h, dict) else (q_snap or {}).get("resets_at") if isinstance(q_snap, dict) else None,
            "resets_at_7d": (q_7d or {}).get("resets_at") if isinstance(q_7d, dict) else None,
            "reset_in_seconds_5h": (q_5h or {}).get("reset_in_seconds") if isinstance(q_5h, dict) else (q_snap or {}).get("reset_in_seconds") if isinstance(q_snap, dict) else None,
            "quota_reset_ready": quota_reset_ready,
            "wake_on_reset_ready": bool(quota_reset_ready and pres_state != "ACTIVE"),
            "predictive_exhaustion": predictive_exhaustion,
        }

        engines_summary[eng] = {
            "engine": eng,
            "role": policy["tool_roles"].get(eng, ""),
            "presence_state": pres_state,
            "quota_reset_ready": quota_reset_ready,
            "wake_on_reset_ready": bool(quota_reset_ready and pres_state != "ACTIVE"),
            "status_tier": status_tier,
            "budget_cap_5h_tokens": cap_5h,
            "budget_cap_7d_tokens": ref_cap_7d if (cap_5h is not None or cap_7d_cfg is not None) else None,
            "used_5h_effective_tokens": w5["effective_budget_tokens"],
            "used_5h_raw_tokens": w5["raw_total_tokens"],
            "usable_remaining_5h_tokens": rem_tokens,
            "active_burst_reserve_tokens": active_burst_reserve,
            "budget_utilization_5h_pct": util_pct,
            "used_7d_effective_tokens": w7["effective_budget_tokens"],
            "used_7d_raw_tokens": w7["raw_total_tokens"],
            "usable_remaining_7d_tokens": sub_rem_7d if (cap_5h is not None or cap_7d_cfg is not None) else ("UNKNOWN" if eng in PAID_TOOLS else None),
            "budget_utilization_7d_pct": sub_pct_7d if (cap_5h is not None or cap_7d_cfg is not None) else 0.0,
            "avg_card_cost_tokens": avg_card,
            "usable_cards_capacity": usable_cards,
            "provider_quota_snapshot": q_snap,
            "subscription_plan": subscription_plan,
            "predictive_exhaustion": predictive_exhaustion,
            "window_5h": w5,
            "window_24h": w24,
            "window_7d": w7,
        }

    raw_step_calls_24h = sum(engines_summary[e]["window_24h"]["calls"] for e in ALL_ENGINES)
    agy_ev_24h = [e for e in events if e["engine"] == "antigravity" and e["ts"] >= cutoff_24h]
    agy_brain_convs_24h = len({str(e.get("conv_id") or "") for e in agy_ev_24h if e.get("source_kind") == "brain_step" and e.get("conv_id")})
    agy_non_brain_24h = sum(1 for e in agy_ev_24h if e.get("source_kind") != "brain_step")
    agy_work_units_24h = agy_brain_convs_24h + agy_non_brain_24h
    total_calls_24h = (
        sum(engines_summary[e]["window_24h"]["calls"] for e in ALL_ENGINES if e != "antigravity")
        + agy_work_units_24h
    )
    offload_calls_24h = (
        engines_summary["ollama"]["window_24h"]["calls"]
        + engines_summary["haiku"]["window_24h"]["calls"]
    )
    offload_ratio_pct = round((offload_calls_24h / total_calls_24h) * 100.0, 1) if total_calls_24h > 0 else 0.0

    schedule_plan = build_capacity_aware_schedule(desk, engines_summary, policy)
    sub_process_schedule = build_sub_process_schedule(desk, engines_summary, schedule_plan, policy)

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
            "raw_step_calls_24h": raw_step_calls_24h,
            "ollama_plus_haiku_calls_24h": offload_calls_24h,
            "offload_share_pct": offload_ratio_pct,
        },
        "engines": engines_summary,
        "schedule_recommendation": schedule_plan,
        "sub_process_schedule": sub_process_schedule,
    }

    snapshot["wait_transparency"] = extract_wait_transparency(desk)
    snapshot["cockpit_telemetry"] = scan_cockpit_sqlite_telemetry(home_dir)
    snapshot["five_chip_telemetry"] = _collect_unified_five_chip_telemetry(
        desk=desk,
        engines_summary=engines_summary,
        quotas=quotas,
        wait_transparency=snapshot["wait_transparency"],
    )
    head_summary = build_compact_capacity_head(snapshot)
    snapshot["compact_head"] = head_summary
    snapshot["contextual_hud_widget"] = render_contextual_hud_widget(snapshot)

    if persist:
        local_snap = desk / ".coord" / "usage" / "capacity_snapshot.json"
        _atomic_write_json(local_snap, snapshot)
        sub_sched_file = desk / ".coord" / "sub_process_schedule.json"
        _atomic_write_json(sub_sched_file, sub_process_schedule)
        local_head = desk / ".coord" / "usage" / "capacity_head.json"
        local_head.parent.mkdir(parents=True, exist_ok=True)
        head_tmp = local_head.with_name(f".capacity_head.{os.getpid()}.{time.time_ns()}.tmp")
        head_tmp.write_text(json.dumps(head_summary, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(head_tmp, local_head)
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

    def _schedulable_rem(t: str) -> int:
        info = engines.get(t) or {}
        rem = _rem_int(t)
        if rem is not None and rem > 0:
            return rem
        burst = int(info.get("active_burst_reserve_tokens") or 0)
        return burst if burst > 0 else 0

    def _tool_score(t: str) -> tuple[int, int]:
        info = engines.get(t) or {}
        is_online = (
            info.get("presence_state") == "ACTIVE"
            and info.get("status_tier") != "LIMITED_PAUSE"
        )
        active = 1 if is_online else 0
        return (active, _schedulable_rem(t))

    ranked_paid = sorted(PAID_TOOLS, key=_tool_score, reverse=True)
    recommended_conductor = next(
        (t for t in ("codex", "claude", "antigravity") if _tool_score(t)[0] == 1),
        "antigravity",
    )

    virtual_rem: dict[str, int] = {}
    for t in PAID_TOOLS:
        virtual_rem[t] = _schedulable_rem(t) if _tool_score(t)[0] == 1 else 0

    in_flight_load: dict[str, int] = {t: 0 for t in PAID_TOOLS}

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
                chosen_judge = (
                    max(candidates, key=lambda t: virtual_rem[t] / (1.0 + in_flight_load[t] * 0.5))
                    if candidates
                    else "BLOCKED"
                )
            review_cost = int(est_tokens * 0.35)
            if chosen_judge in virtual_rem:
                virtual_rem[chosen_judge] = max(0, virtual_rem.get(chosen_judge, 0) - review_cost)
                in_flight_load[chosen_judge] = in_flight_load.get(chosen_judge, 0) + 1
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
            is_keypoint = bool(p.get("codex_exclusive") or p.get("keypoint"))
            if is_keypoint and "codex" in candidates:
                chosen_owner = "codex"
            elif candidates:
                # Parallel load-balanced score: distributes multiple READY cards across all active tools proportionally
                chosen_owner = max(
                    candidates,
                    key=lambda t: virtual_rem[t] / (1.0 + in_flight_load.get(t, 0) * 1.5),
                )
            else:
                chosen_owner = recommended_conductor
            if recorded_reviewer in PAID_TOOLS and recorded_reviewer != chosen_owner and virtual_rem.get(recorded_reviewer, 0) > 0:
                chosen_reviewer = recorded_reviewer
            else:
                reviewer_cands = [t for t in PAID_TOOLS if t != chosen_owner and virtual_rem.get(t, 0) > 0]
                chosen_reviewer = (
                    max(reviewer_cands, key=lambda t: virtual_rem[t] / (1.0 + in_flight_load.get(t, 0) * 0.5))
                    if reviewer_cands
                    else "BLOCKED"
                )
            owner_tier = str((engines.get(chosen_owner) or {}).get("status_tier") or "")
            high_offload = owner_tier in ("CRITICAL_OFFLOAD", "THRIFT_OVERDRIVE", "THROTTLE_TO_LOCAL")
            paid_share = int(est_tokens * (0.25 if high_offload else 0.4))
            sizing_action = "SPLIT_CARD" if paid_share > max(1, virtual_rem.get(chosen_owner, 0)) else "KEEP"
            virtual_rem[chosen_owner] = max(0, virtual_rem.get(chosen_owner, 0) - paid_share)
            in_flight_load[chosen_owner] = in_flight_load.get(chosen_owner, 0) + 1
            offload_spec = (
                ["ollama:code_patch_30line_v7_harness", "haiku:disjoint_tests_docs_5_3_2"]
                if high_offload
                else ["ollama:stage1_draft_stage3_slice", "haiku:stage2_map_moderator"]
            )
            assignments.append({
                "phase_id": pid,
                "state": state,
                "deps_met": deps_met,
                "assigned_owner": chosen_owner,
                "assigned_reviewer": chosen_reviewer,
                "local_offload": offload_spec,
                "estimated_paid_tokens": paid_share,
                "sizing_action": sizing_action,
                "reason": (
                    f"Parallel tiki-taka owner {chosen_owner} (rem {virtual_rem[chosen_owner]:,} tok, lane #{in_flight_load[chosen_owner]}) "
                    f"+ {'75% 5:3:2 disjoint' if high_offload else '60%'} Ollama/Haiku offload"
                ),
            })

    paid_used_5h = sum(int((engines.get(t) or {}).get("used_5h_effective_tokens") or 0) for t in PAID_TOOLS)
    agy_used_5h = int((engines.get("antigravity") or {}).get("used_5h_effective_tokens") or 0)
    agy_used_share_pct: float | str = (
        round((agy_used_5h / paid_used_5h) * 100.0, 1) if paid_used_5h > 0 else "UNKNOWN"
    )
    rem_vals = [_rem_int(t) for t in PAID_TOOLS]
    if all(v is not None for v in rem_vals):
        total_rem_5h = sum(max(0, int(v)) for v in rem_vals if v is not None)
        agy_rem_5h = max(0, int(_rem_int("antigravity") or 0))
        agy_rem_share_pct: float | str = (
            round((agy_rem_5h / total_rem_5h) * 100.0, 1) if total_rem_5h > 0 else "UNKNOWN"
        )
    else:
        agy_rem_share_pct = "UNKNOWN"
    argon_mode = (
        "GOOGLE_AI_ULTRA_5X_GEMINI_4_ARGON"
        if ranked_paid and ranked_paid[0] == "antigravity"
        else "BALANCED_3TOOL_COLLAB"
    )

    wake_ready_tools = [
        t for t in PAID_TOOLS
        if bool((engines.get(t) or {}).get("wake_on_reset_ready"))
    ]
    wake_ready_tools = [
        t for t in PAID_TOOLS
        if bool((engines.get(t) or {}).get("wake_on_reset_ready"))
    ]
    return {
        "recommended_conductor": recommended_conductor,
        "ranked_paid_tools": ranked_paid,
        "wake_ready_tools": wake_ready_tools,
        "wake_ready_tools": wake_ready_tools,
        "argon_tier_mode": argon_mode,
        "argon_used_5h_share_pct": agy_used_share_pct,
        "argon_remaining_5h_share_pct": agy_rem_share_pct,
        "post_schedule_remaining_tokens": virtual_rem,
        "phase_assignments": assignments,
        "subworker_optimization": compute_subworker_optimization(engines),
    }


def build_sub_process_schedule(
    desk: Path,
    engines: dict[str, dict[str, Any]],
    schedule_plan: dict[str, Any],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """U274: Hierarchical Sub-Process Schedule Architecture (5-stage DAG per card) with predictive preemptive handoff.

    Decomposes every active/ready/review card from master_schedule.json into 5 concrete sub-process nodes:
      - SP1_RESEARCH_DRAFT: Web primary sources + Ollama `local_draft` / `local_search` (0 paid tokens)
      - SP2_MIA_DESIGN_AUDIT: MIA 1-8 design + Ollama `local_read_map` / Haiku moderator + peer counterexample audit
      - SP3_CODE_EXECUTION: Disjoint parallel execution — Ollama 50% (`v7_harness/*.py` 20~30 line slice) || Haiku 30% (`tests/*`, `docs/*`) + paid owner supervision
      - SP4_INDEPENDENT_VERIFY: Independent peer judge (`verifier != executor`) runs fixed acceptance + `card audit`
      - SP5_MERGE_AND_RUNTIME: Autonomous `merge_route` (1. Antigravity, 2. Codex) + `runtime_install --apply`
    """
    policy = policy or load_policy(desk)
    ranked_paid = list(schedule_plan.get("ranked_paid_tools") or PAID_TOOLS)
    assigns = list(schedule_plan.get("phase_assignments") or [])

    def _risk_of(tool: str) -> str:
        pred = ((engines.get(tool) or {}).get("predictive_exhaustion")) or {}
        return str(pred.get("exhaustion_risk") or "SAFE")

    def _needs_preemptive_handoff(tool: str) -> bool:
        pred = ((engines.get(tool) or {}).get("predictive_exhaustion")) or {}
        return bool(pred.get("preemptive_handoff_recommended"))

    def _pick_healthy_peer(exclude: set[str]) -> str:
        safe_peers = [
            t for t in ranked_paid
            if t not in exclude
            and not _needs_preemptive_handoff(t)
            and str((engines.get(t) or {}).get("presence_state") or "ACTIVE") == "ACTIVE"
        ]
        if safe_peers:
            return safe_peers[0]
        active_peers = [
            t for t in ranked_paid
            if t not in exclude
            and str((engines.get(t) or {}).get("presence_state") or "ACTIVE") == "ACTIVE"
        ]
        if active_peers:
            return active_peers[0]
        fallback = [t for t in PAID_TOOLS if t not in exclude]
        return fallback[0] if fallback else "antigravity"

    preemptive_tools = [t for t in PAID_TOOLS if _needs_preemptive_handoff(t)]
    rebalance_events: list[dict[str, Any]] = []
    card_sub_schedules: list[dict[str, Any]] = []

    raw_master_owners: dict[str, str] = {}
    recent_done_phases: list[dict[str, Any]] = []
    sched_path = Path(desk) / ".coord" / "master_schedule.json"
    if sched_path.is_file():
        try:
            raw_ms = json.loads(sched_path.read_text(encoding="utf-8"))
            for mp in (raw_ms.get("phases") or []) if isinstance(raw_ms, dict) else []:
                if isinstance(mp, dict):
                    mp_id = str(mp.get("phase_id") or mp.get("id") or "").strip()
                    mp_ow = str(mp.get("owner_tool") or mp.get("owner") or "").strip().lower()
                    mp_st = str(mp.get("state") or "").strip().upper()
                    if mp_id and mp_ow:
                        raw_master_owners[mp_id] = mp_ow
                    if mp_id and mp_st == "DONE" and not mp_id.startswith("RSI-U251-AUTO-"):
                        recent_done_phases.append(mp)
        except (OSError, ValueError):
            pass

    showing_recent_done = False
    if not assigns and recent_done_phases:
        showing_recent_done = True
        for dp in recent_done_phases[-3:]:
            dp_ow = str(dp.get("owner_tool") or dp.get("owner") or "antigravity").lower()
            dp_rev = str(dp.get("reviewer") or ("claude" if dp_ow != "claude" else "codex")).lower()
            assigns.append({
                "phase_id": str(dp.get("phase_id") or dp.get("id") or ""),
                "state": "DONE",
                "assigned_owner": dp_ow if dp_ow in PAID_TOOLS else "antigravity",
                "assigned_reviewer": dp_rev if dp_rev in PAID_TOOLS and dp_rev != dp_ow else ("claude" if dp_ow != "claude" else "antigravity"),
                "estimated_paid_tokens": int(dp.get("estimated_tokens") or 18000),
            })

    for idx, item in enumerate(assigns):
        pid = str(item.get("phase_id") or "")
        state = str(item.get("state") or "READY")
        orig_owner = str(item.get("assigned_owner") or "antigravity").lower()
        master_owner = raw_master_owners.get(pid, orig_owner)
        orig_reviewer = str(item.get("assigned_reviewer") or "claude").lower()
        est_paid = int(item.get("estimated_paid_tokens") or 18000)

        owner_risk = _risk_of(orig_owner)
        master_owner_risk = _risk_of(master_owner)
        effective_owner = orig_owner
        preemptive_owner_target: str | None = None
        if _needs_preemptive_handoff(orig_owner):
            candidate_peer = _pick_healthy_peer({orig_owner})
            preemptive_owner_target = candidate_peer
            if owner_risk == "IMMINENT_EXHAUSTION" and state in ("READY", "PLANNED"):
                effective_owner = candidate_peer
                rebalance_events.append({
                    "phase_id": pid,
                    "role": "executor",
                    "from_tool": orig_owner,
                    "to_tool": effective_owner,
                    "trigger": owner_risk,
                    "quality_gate": "preserved (executor != verifier)",
                })
        elif master_owner in PAID_TOOLS and master_owner != effective_owner and _needs_preemptive_handoff(master_owner):
            rebalance_events.append({
                "phase_id": pid,
                "role": "executor",
                "from_tool": master_owner,
                "to_tool": effective_owner,
                "trigger": master_owner_risk,
                "quality_gate": "preserved (executor != verifier)",
            })

        effective_reviewer = orig_reviewer if orig_reviewer != effective_owner else _pick_healthy_peer({effective_owner})
        reviewer_risk = _risk_of(effective_reviewer)
        fallback_verifier = _pick_healthy_peer({effective_owner, effective_reviewer})
        if _needs_preemptive_handoff(effective_reviewer) and fallback_verifier != effective_owner:
            if reviewer_risk == "IMMINENT_EXHAUSTION":
                old_rev = effective_reviewer
                effective_reviewer = fallback_verifier
                fallback_verifier = _pick_healthy_peer({effective_owner, effective_reviewer})
                rebalance_events.append({
                    "phase_id": pid,
                    "role": "verifier",
                    "from_tool": old_rev,
                    "to_tool": effective_reviewer,
                    "trigger": reviewer_risk,
                    "quality_gate": "preserved (executor != verifier)",
                })

        merger_primary = "antigravity" if _risk_of("antigravity") != "IMMINENT_EXHAUSTION" else "codex"
        merger_secondary = "codex" if merger_primary == "antigravity" else "antigravity"

        if state == "DONE":
            sp1_state = sp2_state = sp3_state = sp4_state = sp5_state = "DONE"
        else:
            sp1_state = "DONE" if state in ("ACTIVE", "REVIEW") else "READY"
            sp2_state = "DONE" if state == "REVIEW" else ("ACTIVE" if state == "ACTIVE" else "READY")
            sp3_state = "DONE" if state == "REVIEW" else ("ACTIVE" if state == "ACTIVE" else "READY")
            sp4_state = "ACTIVE" if state == "REVIEW" else "PLANNED"
            sp5_state = "READY" if state == "REVIEW" else "PLANNED"

        code_slice_limit = 30 if owner_risk != "SAFE" else 20
        test_doc_worker = "haiku" if effective_owner == "claude" else "ollama"

        sub_nodes = [
            {
                "sub_id": f"{pid}:SP1_RESEARCH_DRAFT",
                "step_index": 1,
                "stage_name": "Stage 0~1 선행 리서치·초안",
                "state": sp1_state,
                "depends_on": [],
                "primary_worker": "ollama",
                "supervisor_tool": effective_owner,
                "fallback_tool": preemptive_owner_target or _pick_healthy_peer({effective_owner}),
                "allowed_paths": [f".work/cards/{pid}_research.md"],
                "estimated_paid_tokens": int(round(est_paid * 0.10)),
                "offload_mode": "ollama:local_search+local_draft (0 paid tokens)",
            },
            {
                "sub_id": f"{pid}:SP2_MIA_DESIGN_AUDIT",
                "step_index": 2,
                "stage_name": "Stage 2~8 MIA 세부설계·반례감사",
                "state": sp2_state,
                "depends_on": [f"{pid}:SP1_RESEARCH_DRAFT"],
                "primary_worker": "haiku" if effective_owner == "claude" else "ollama",
                "supervisor_tool": effective_owner,
                "counterexample_auditor": effective_reviewer,
                "fallback_tool": fallback_verifier,
                "allowed_paths": [f".work/cards/{pid}_frame.md", f".work/cards/{pid}_manual.md"],
                "estimated_paid_tokens": int(round(est_paid * 0.15)),
                "offload_mode": "ollama:local_read_map + peer counterexample audit",
            },
            {
                "sub_id": f"{pid}:SP3_CODE_EXECUTION",
                "step_index": 3,
                "stage_name": "Stage 9 이원 분리 병렬 구현(5:3:2)",
                "state": sp3_state,
                "depends_on": [f"{pid}:SP2_MIA_DESIGN_AUDIT"],
                "primary_worker": "ollama",
                "parallel_companion_worker": test_doc_worker,
                "supervisor_tool": effective_owner,
                "preemptive_handoff_to": preemptive_owner_target,
                "disjoint_lanes": {
                    "code_lane": {
                        "worker": "ollama",
                        "allow": ["v7_harness/*.py"],
                        "max_changed_lines": code_slice_limit,
                    },
                    "test_doc_lane": {
                        "worker": test_doc_worker,
                        "allow": ["tests/*", "docs/*"],
                        "budget_cap_tokens": 12000 if test_doc_worker == "haiku" else 0,
                    },
                },
                "estimated_paid_tokens": int(round(est_paid * 0.40)),
                "offload_mode": f"DISJOINT_PARALLEL (ollama {code_slice_limit}L code || {test_doc_worker} tests/docs)",
            },
            {
                "sub_id": f"{pid}:SP4_INDEPENDENT_VERIFY",
                "step_index": 4,
                "stage_name": "Stage 10 독립 인수검증·교차판정",
                "state": sp4_state,
                "depends_on": [f"{pid}:SP3_CODE_EXECUTION"],
                "primary_worker": effective_reviewer,
                "executor_excluded": effective_owner,
                "fallback_verifier": fallback_verifier,
                "quality_gate": f"author({effective_owner}) != judge({effective_reviewer}) + uaos card audit",
                "estimated_paid_tokens": int(round(est_paid * 0.25)),
                "offload_mode": "ollama:gate_log_summary + deterministic unittest",
            },
            {
                "sub_id": f"{pid}:SP5_MERGE_AND_RUNTIME",
                "step_index": 5,
                "stage_name": "무승인 PR 병합·런타임 실가동",
                "state": sp5_state,
                "depends_on": [f"{pid}:SP4_INDEPENDENT_VERIFY"],
                "primary_worker": merger_primary,
                "fallback_tool": merger_secondary,
                "quality_gate": "CI attestation + same-head PASS relay + runtime_install --apply",
                "estimated_paid_tokens": int(round(est_paid * 0.10)),
                "offload_mode": "deterministic merge_route + runtime_install",
            },
        ]

        card_sub_schedules.append({
            "phase_id": pid,
            "card_state": state,
            "parallel_slot": (idx % max(1, len(PAID_TOOLS))) + 1,
            "assigned_executor": effective_owner,
            "original_executor": orig_owner,
            "executor_exhaustion_risk": owner_risk,
            "preemptive_handoff_target": preemptive_owner_target,
            "assigned_verifier": effective_reviewer,
            "fallback_verifier": fallback_verifier,
            "verifier_exhaustion_risk": reviewer_risk,
            "quality_invariant": f"{effective_owner} != {effective_reviewer}",
            "estimated_total_paid_tokens": est_paid,
            "sub_processes": sub_nodes,
        })

    return {
        "schema": "uaos-sub-process-schedule-v1",
        "showing_recent_completed_dag": showing_recent_done,
        "total_active_cards": len(card_sub_schedules),
        "total_sub_processes": sum(len(c["sub_processes"]) for c in card_sub_schedules),
        "preemptive_handoff_tools": preemptive_tools,
        "wake_ready_tools": list(schedule_plan.get("wake_ready_tools") or []),
        "fluid_rebalance_events": rebalance_events,
        "disjoint_parallel_policy": {
            "ollama_50pct_lane": "v7_harness/*.py (20~30 line slice, 0 paid tokens)",
            "haiku_30pct_lane": "tests/*, docs/* (<=12,000 tokens, disjoint from v7_harness/*.py)",
            "paid_20pct_lane": "codex / claude / antigravity (architecture, cross-review, merge)",
        },
        "card_sub_schedules": card_sub_schedules,
    }


def sync_autonomous_schedules(
    project_root: Path,
    *,
    home: Path | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """U274: Autonomous fluid re-scheduler that updates .coord/master_schedule.json and .coord/sub_process_schedule.json
    whenever 3-tool 5h/7d usage or presence triggers a preemptive handoff or load-balanced parallel assignment."""
    desk = shared_desk(Path(project_root))
    snap = collect_capacity_snapshot(desk, home=home, now=now, persist=True)
    sub_sched = snap.get("sub_process_schedule") or {}
    by_id = {
        str(c.get("phase_id") or ""): c
        for c in (sub_sched.get("card_sub_schedules") or [])
        if isinstance(c, dict) and c.get("phase_id")
    }
    sched_path = desk / ".coord" / "master_schedule.json"
    updated_phases = 0
    if sched_path.is_file() and by_id:
        try:
            raw = json.loads(sched_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("phases"), list):
                dirty = False
                for p in raw["phases"]:
                    if not isinstance(p, dict):
                        continue
                    pid = str(p.get("phase_id") or p.get("id") or "").strip()
                    if pid not in by_id:
                        continue
                    c_plan = by_id[pid]
                    new_owner = str(c_plan.get("assigned_executor") or "")
                    new_rev = str(c_plan.get("assigned_verifier") or "")
                    if new_owner and p.get("owner") != new_owner and str(p.get("state") or "") in ("READY", "PLANNED"):
                        p["previous_owner"] = p.get("owner")
                        p["owner"] = new_owner
                        p["owner_tool"] = new_owner
                        dirty = True
                        updated_phases += 1
                    if new_rev and p.get("reviewer") != new_rev:
                        p["reviewer"] = new_rev
                        dirty = True
                    p["sub_process_count"] = len(c_plan.get("sub_processes") or [])
                    p["preemptive_handoff_target"] = c_plan.get("preemptive_handoff_target")
                if dirty:
                    raw["last_fluid_rebalance_at"] = snap.get("generated_at")
                    _atomic_write_json(sched_path, raw)
        except (OSError, ValueError):
            pass
    return {
        "ok": True,
        "updated_master_phases": updated_phases,
        "total_active_cards": sub_sched.get("total_active_cards", 0),
        "total_sub_processes": sub_sched.get("total_sub_processes", 0),
        "fluid_rebalance_events": sub_sched.get("fluid_rebalance_events", []),
        "sub_process_schedule_path": str(desk / ".coord" / "sub_process_schedule.json"),
    }



def extract_wait_transparency(desk: Path) -> dict[str, Any]:
    """Build deterministic wait/progress transparency state from .coord/master_schedule.json with 0 paid tokens."""
    sched_path = Path(desk) / ".coord" / "master_schedule.json"
    if not sched_path.is_file():
        return {"status": "UNKNOWN", "active_or_waiting_count": 0, "headline": "스케줄 파일 없음", "items": []}
    try:
        raw = json.loads(sched_path.read_text(encoding="utf-8"))
        phases = raw.get("phases") if isinstance(raw, dict) else None
        if not isinstance(phases, list) or len(phases) == 0:
            return {"status": "UNKNOWN", "active_or_waiting_count": 0, "headline": "스케줄 형식 오류 또는 빈 일정", "items": []}
    except (OSError, ValueError):
        return {"status": "UNKNOWN", "active_or_waiting_count": 0, "headline": "스케줄 읽기 실패", "items": []}

    terminal = {"DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED", "SUPERSEDED", "MERGED"}
    active_states = {"READY", "ACTIVE", "REVIEW", "WAITING", "BLOCKED", "IN_PROGRESS", "PENDING", "QUEUED"}
    valid_states = terminal | active_states
    items: list[dict[str, str]] = []
    done_count = 0
    for p in phases:
        if not isinstance(p, dict):
            return {"status": "UNKNOWN", "active_or_waiting_count": 0, "headline": "스케줄 행 형식 오류", "items": []}
        pid_raw = p.get("phase_id")
        st_raw = p.get("state")
        if not isinstance(pid_raw, str) or not pid_raw.strip() or not isinstance(st_raw, str) or not st_raw.strip():
            return {"status": "UNKNOWN", "active_or_waiting_count": 0, "headline": "스케줄 필수 필드 누락", "items": []}
        pid = pid_raw.strip()
        st = st_raw.strip().upper()
        if st not in valid_states:
            return {"status": "UNKNOWN", "active_or_waiting_count": 0, "headline": f"미지원 상태값({st})", "items": []}
        if st in terminal:
            done_count += 1
            continue
        owner = str(p.get("owner_tool") or p.get("owner") or "unknown")
        reviewer = str(p.get("reviewer") or p.get("judge") or "")
        wait_on = str(p.get("waiting_on") or p.get("blocker_reason") or "")
        items.append({
            "phase_id": pid,
            "state": st,
            "owner": owner,
            "reviewer": reviewer,
            "waiting_on": wait_on or (f"{reviewer}-verdict" if st == "REVIEW" and reviewer else "execution"),
        })
    if not items and done_count > 0:
        return {
            "status": "ALL_DONE",
            "active_or_waiting_count": 0,
            "headline": "✅ 전 프로세스 완료 (대기 중인 작업 0건)",
            "items": [],
        }
    top = items[0]
    return {
        "status": "WAITING" if any(i["state"] in ("REVIEW", "BLOCKED", "WAITING") for i in items) else "RUNNING",
        "active_or_waiting_count": len(items),
        "headline": f"진행·대기 {len(items)}건 — [{top['phase_id']}] 상태:{top['state']} 담당:{top['owner']} 대기사유:{top['waiting_on']}",
        "items": items[:5],
    }


def _collect_active_watchers(desk: Path) -> list[str]:
    """Deterministically inspect .coord/watch, .coord/sentinel, and .coord/presence with 0 paid tokens."""
    watchers: list[str] = []
    coord_dir = Path(desk) / ".coord"
    watch_dir = coord_dir / "watch"
    if watch_dir.is_dir():
        for wf in sorted(watch_dir.iterdir()):
            if wf.suffix in (".json", ".pid", ".lock"):
                watchers.append(f"coord watch ({wf.stem})")
    sentinel_pid = coord_dir / "sentinel" / "loop.pid"
    if sentinel_pid.is_file():
        watchers.append("sentinel.loop (0-token daemon)")
    pres_dir = coord_dir / "presence"
    if pres_dir.is_dir():
        for tool in PAID_TOOLS:
            pf = pres_dir / f"{tool}.json"
            if pf.is_file():
                try:
                    pdata = json.loads(pf.read_text(encoding="utf-8"))
                    if isinstance(pdata, dict) and str(pdata.get("state") or "").upper() == "ACTIVE":
                        label = f"coord watch --target {tool}"
                        if label not in watchers:
                            watchers.append(label)
                except (OSError, ValueError):
                    pass
    return watchers


def _collect_git_diff_chip(desk: Path) -> list[dict[str, Any]]:
    """Collect working-tree / staged diff stats (file_count, +added, -removed) from .coord pure file state with 0 paid tokens."""
    desk_path = Path(desk)
    override_file = desk_path / ".coord" / "usage" / "changed_files.json"
    if override_file.is_file():
        try:
            raw_ov = json.loads(override_file.read_text(encoding="utf-8"))
            if isinstance(raw_ov, list):
                return [
                    {
                        "path": str(item.get("path") or ""),
                        "added": int(item.get("added") or 0),
                        "removed": int(item.get("removed") or 0),
                    }
                    for item in raw_ov[:25]
                    if isinstance(item, dict) and item.get("path")
                ]
        except (OSError, ValueError, TypeError):
            pass
    return []


def _collect_unified_five_chip_telemetry(
    *,
    desk: Path,
    engines_summary: dict[str, dict[str, Any]],
    quotas: dict[str, dict[str, Any]],
    wait_transparency: dict[str, Any],
) -> dict[str, Any]:
    """Unify Show GN 5-Chip Telemetry (`benchmark_logic_transplant.py`) into `capacity_planner` read-only snapshot."""
    from v7_harness.benchmark_logic_transplant import build_five_chip_telemetry_snapshot

    sched_path = Path(desk) / ".coord" / "master_schedule.json"
    phases: list[dict[str, Any]] = []
    if sched_path.is_file():
        try:
            raw = json.loads(sched_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("phases"), list):
                phases = [dict(p) for p in raw["phases"] if isinstance(p, dict)]
        except (OSError, ValueError):
            phases = []

    presence_states = {
        t: str((engines_summary.get(t) or {}).get("presence_state") or "ABSENT").upper()
        for t in PAID_TOOLS
    }
    reset_times = {
        t: str(q["resets_at"])
        for t, q in (quotas or {}).items()
        if isinstance(q, dict) and q.get("resets_at")
    }
    return build_five_chip_telemetry_snapshot(
        schedule_phases=phases,
        presence_states=presence_states,
        changed_files=_collect_git_diff_chip(desk),
        active_watchers=_collect_active_watchers(desk),
        quota_reset_times=reset_times,
        foreground_wait_s=0.0,
        is_background_watcher=True,
        acting_tool="antigravity",
        mutate_schedule=False,
        include_haiku=True,
        engines_summary=engines_summary,
        wait_transparency=wait_transparency,
    )


def build_compact_capacity_head(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return an ultra-compact (<=320B / ~50 tok) routing header so scheduling never loads 9,750B snapshot JSON."""
    sched = snapshot.get("schedule_recommendation") or {}
    engines = snapshot.get("engines") or {}
    off = snapshot.get("offload_efficiency_24h") or {}
    wait_info = snapshot.get("wait_transparency") or {}

    def _clamp_rem(val: Any) -> int | str:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return min(999_999_999, max(0, int(val)))
        return "UNKNOWN"

    def _clamp_cards(val: Any) -> int | str:
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return min(9999, max(0, int(val)))
        return "UNKNOWN"

    return {
        "schema": "uaos-capacity-head-v1",
        "ts": int(float(snapshot.get("timestamp") or 0)),
        "conductor": str(sched.get("recommended_conductor", "antigravity"))[:12],
        "mode": str(sched.get("argon_tier_mode", "BALANCED_3TOOL_COLLAB"))[:36],
        "rem_5h": {t: _clamp_rem((engines.get(t) or {}).get("usable_remaining_5h_tokens")) for t in PAID_TOOLS},
        "cards_5h": {t: _clamp_cards((engines.get(t) or {}).get("usable_cards_capacity")) for t in PAID_TOOLS},
        "offload_pct": round(float(off.get("offload_share_pct") or 0.0), 1),
        "wait_status": str(wait_info.get("status", "UNKNOWN"))[:12],
    }


def render_compact_status_line(snapshot: dict[str, Any]) -> str:
    """Single-line (<=200 chars / ~40 tok) status for routine turns; naturally bounded <=185 chars without truncation."""
    head = snapshot.get("compact_head") or build_compact_capacity_head(snapshot)
    rem = head.get("rem_5h") or {}
    cards = head.get("cards_5h") or {}

    def _f_rem(v: Any) -> str:
        return str(min(999_999_999, max(0, int(v)))) if isinstance(v, (int, float)) and not isinstance(v, bool) else "UNK"

    def _f_crd(v: Any) -> str:
        return str(min(9999, max(0, int(v)))) if isinstance(v, (int, float)) and not isinstance(v, bool) else "UNK"

    cond = str(head.get("conductor") or "antigravity").upper()[:12]
    mode = str(head.get("mode") or "BALANCED_3TOOL_COLLAB")[:36]
    off_pct = round(float(head.get("offload_pct") or 0.0), 1)
    w_stat = str(head.get("wait_status") or "UNKNOWN")[:12]
    return (
        f"[용량헤더] 지휘={cond}({mode}) "
        f"| 5h가용(카드): agy={_f_rem(rem.get('antigravity'))}({_f_crd(cards.get('antigravity'))}) "
        f"claude={_f_rem(rem.get('claude'))}({_f_crd(cards.get('claude'))}) "
        f"codex={_f_rem(rem.get('codex'))}({_f_crd(cards.get('codex'))}) "
        f"| 오프로드={off_pct}% | 상태={w_stat}"
    )




def render_contextual_hud_widget(snapshot: dict[str, Any]) -> str:
    """Tier-2 Micro Contextual Heads-Up Display (HUD) Widget inspired by Cockpit Tools floating_card_window.rs.
    Designed for inline prompt/workspace context (<195 chars) with Quality Gate first (author != judge).
    Fails closed to UNKNOWN(품질증거미확인) when schedule/conductor/telemetry evidence is unverified.
    """
    head = snapshot.get("compact_head") or build_compact_capacity_head(snapshot)
    cards = head.get("cards_5h") or {}
    cockpit = snapshot.get("cockpit_telemetry") or {}
    fc = ((snapshot.get("five_chip_telemetry") or {}).get("chips")) or {}
    c1 = fc.get("1_todos_schedule") or {}
    c2 = fc.get("2_three_tool_seats") or {}
    c3 = fc.get("3_background_watchers") or {}

    def _c(v: Any) -> str:
        return f"{min(9999, max(0, int(v)))}장" if isinstance(v, (int, float)) and not isinstance(v, bool) else "미계측"

    raw_cond = str(head.get("conductor") or "").upper()
    cond = (raw_cond if raw_cond else "NONE")[:12]
    seats_cnt = len(c2.get("seats") or []) or 5
    off_pct = round(float(head.get("offload_pct") or 0.0), 1)
    cache_pct = round(float(cockpit.get("cache_hit_pct") or 0.0), 1)
    cache_str = f"·캐시{cache_pct}%" if cockpit.get("available") else ""
    w_cnt = int(c3.get("watcher_count") or len(c3.get("watchers") or []))
    rem_cards = int(c1.get("remaining_non_auto", c1.get("remaining", 0)) or 0)

    blocked_cnt = int(c1.get("blocked") or 0)
    total_cards = int(c1.get("total") or 0)
    is_unverified = (
        raw_cond in ("", "NONE", "UNKNOWN")
        or (
            total_cards == 0
            and not bool(cockpit.get("available"))
            and not bool(snapshot.get("quality_gate_verified"))
        )
    )
    if blocked_cnt > 0:
        q_state = f"점검필요(블로커{blocked_cnt}건)"
    elif is_unverified:
        q_state = "UNKNOWN(품질증거미확인)"
    else:
        q_state = "PASS(독립검증·인수100%)"

    return (
        f"[HUD 위젯] 🎯품질게이트:{q_state} "
        f"| ⚡지휘:{cond}({seats_cnt}석·대기{rem_cards}건) "
        f"| 🔋5h가용카드:ag={_c(cards.get('antigravity'))}·cl={_c(cards.get('claude'))}·cx={_c(cards.get('codex'))} "
        f"| 🧮0원오프로드:{off_pct}%{cache_str} | 🔄워처:{w_cnt}개"
    )


def refresh_capacity_zero_token(
    project_root: Path,
    *,
    home: Path | None = None,
    now: float | None = None,
    min_interval_s: float = 60.0,
    html_out: Path | None = None,
) -> dict[str, Any]:
    """Zero-paid-token background/hook updater with debounce across runs, schedule, and brain transcript mtimes."""
    moment = float(now if now is not None else time.time())
    desk = shared_desk(Path(project_root))
    home_dir = Path(home) if home is not None else Path.home()
    snap_path = desk / ".coord" / "usage" / "capacity_snapshot.json"
    head_path = desk / ".coord" / "usage" / "capacity_head.json"
    runs_path = ledger_file(desk)
    sched_path = desk / ".coord" / "master_schedule.json"
    brain_root = home_dir / ".gemini" / "antigravity" / "brain"

    if snap_path.is_file() and head_path.is_file() and min_interval_s > 0:
        try:
            head_data = json.loads(head_path.read_text(encoding="utf-8"))
            last_ts = float(head_data.get("ts") or 0.0)
            runs_mtime = runs_path.stat().st_mtime if runs_path.is_file() else 0.0
            sched_mtime = sched_path.stat().st_mtime if sched_path.is_file() else 0.0
            brain_mtime = max(
                (p.stat().st_mtime for p in brain_root.glob("*/.system_generated/logs/transcript.jsonl")),
                default=0.0,
            ) if brain_root.is_dir() else 0.0
            if (
                0.0 <= (moment - last_ts) < min_interval_s
                and runs_mtime <= last_ts
                and sched_mtime <= last_ts
                and brain_mtime <= last_ts
            ):
                if html_out is not None and not Path(html_out).is_file():
                    snap_cached = json.loads(snap_path.read_text(encoding="utf-8"))
                    render_html_dashboard(snap_cached, Path(html_out))
                return {"ok": True, "debounced": True, "paid_tokens_used": 0, "head": head_data}
        except (OSError, ValueError):
            pass

    snap = collect_capacity_snapshot(desk, home=home_dir, now=moment, persist=True)
    if html_out is not None:
        render_html_dashboard(snap, Path(html_out))
    return {"ok": True, "debounced": False, "paid_tokens_used": 0, "head": snap["compact_head"]}


def _bar(pct: float, width: int = 12) -> str:
    clamped = max(0.0, min(100.0, float(pct)))
    filled = int(round((clamped / 100.0) * width))
    return "█" * filled + "░" * (width - filled)


def render_terminal_dashboard(snapshot: dict[str, Any]) -> str:
    """Compact, high-visibility terminal/markdown gauge table for `현재 진행상황을 보고해줘`."""
    engines = snapshot.get("engines") or {}
    sched = snapshot.get("schedule_recommendation") or {}
    off = snapshot.get("offload_efficiency_24h") or {}
    fc = ((snapshot.get("five_chip_telemetry") or {}).get("chips")) or {}
    c1 = fc.get("1_todos_schedule") or {}
    c2 = fc.get("2_three_tool_seats") or {}
    c3 = fc.get("3_background_watchers") or {}
    c4 = fc.get("4_changed_files_diff") or {}
    c5 = fc.get("5_quota_and_reset_timer") or {}
    w_act = (c3.get("wait_decision") or {}).get("action", "CONTINUE_WAIT")
    lines = [
        "[계기판] [UAOS-RSI 3대 도구 + Ollama/Haiku 실시간 토큰·용량 계기판]",
        f"• 지휘권(Conductor): {sched.get('recommended_conductor', 'unknown').upper()} | 24h 로컬·경량 오프로드율: {off.get('offload_share_pct', 0.0)}% ({off.get('ollama_plus_haiku_calls_24h', 0)}/{off.get('total_calls_24h', 0)} calls)",
        (
            f"• [5-Chip 상태바] ①일정:{c1.get('done', 0)}/{c1.get('total', 0)}(남은{c1.get('remaining', 0)}) "
            f"| ②좌석:{c2.get('mode', 'THREE_TOOL_NORMAL')}({len(c2.get('seats') or [])}석) "
            f"| ③워처:{len(c3.get('watchers') or [])}개({w_act}) "
            f"| ④Diff:{c4.get('file_count', 0)}파일(+{c4.get('lines_added', 0)}/-{c4.get('lines_removed', 0)}) "
            f"| ⑤리셋자동재개:{'ON' if c5.get('auto_resume_on_reset', True) else 'OFF'}"
        ),
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
    lines.append("[구독요금제] [3대 도구 현재 구독 요금제 총량(5h/7d) 대비 실시간 사용·잔여·쿼터리셋 수치화]")
    for eng in ("codex", "claude", "antigravity", "haiku", "ollama"):
        info = engines.get(eng) or {}
        sub = info.get("subscription_plan") or {}
        pname = str(sub.get("short_plan") or eng)
        t5 = sub.get("total_5h_tokens")
        u5 = int(sub.get("used_5h_effective_tokens") or 0)
        r5 = sub.get("remaining_5h_tokens")
        p5 = float(sub.get("utilization_5h_pct") or 0.0)
        t7 = sub.get("total_7d_tokens")
        u7 = int(sub.get("used_7d_effective_tokens") or 0)
        r7 = sub.get("remaining_7d_tokens")
        p7 = float(sub.get("utilization_7d_pct") or 0.0)
        q5 = sub.get("quota_5h_ui_pct")
        q7 = sub.get("quota_7d_ui_pct")
        rst = sub.get("resets_at_5h") or sub.get("resets_at_7d") or "-"
        if t5 is None:
            lines.append(f"  • {eng.upper()} [{pname}]: 5h 사용 {u5:,} tok (무제한 0원) | 7d 주간 {u7:,} tok (무제한 0원)")
        else:
            q_badge = f" | 계정쿼터(5h={q5 if q5 is not None else '-'}%, 7d={q7 if q7 is not None else '-'}%, 리셋={rst})"
            lines.append(
                f"  • {eng.upper()} [{pname}]: 5h {u5:,}/{int(t5):,} tok (잔여 {int(r5 or 0):,}, {p5:.1f}%) "
                f"| 7d주간 {u7:,}/{int(t7 or 0):,} tok (잔여 {int(r7 or 0):,}, {p7:.1f}%){q_badge}"
            )
    assigns = sched.get("phase_assignments") or []
    if assigns:
        lines.append("[스케줄] [용량 기반 마스터·협업 스케줄 자동 배정]")
        for a in assigns[:5]:
            lines.append(
                f"  - {a['phase_id']} ({a['state']}): 담당={a['assigned_owner']} / 검증={a['assigned_reviewer']} "
                f"/ 예상유료={a['estimated_paid_tokens']:,} tok ({a['sizing_action']}) / 오프로드={','.join(a['local_offload'])}"
            )
    sub_sched = snapshot.get("sub_process_schedule") or {}
    card_subs = sub_sched.get("card_sub_schedules") or []
    if card_subs:
        lines.append(
            f"[세부스케줄] [자율-유동적 5단계 세부 프로세스 DAG ({sub_sched.get('total_active_cards', 0)}개 카드 · {sub_sched.get('total_sub_processes', 0)}개 세부공정)]"
        )
        for cs in card_subs[:3]:
            ho = f" → 선제인계대기:{cs['preemptive_handoff_target']}" if cs.get("preemptive_handoff_target") else ""
            step_str = " → ".join(
                f"SP{sp['step_index']}:{sp['primary_worker']}({sp['state']})"
                for sp in (cs.get("sub_processes") or [])
            )
            lines.append(
                f"  • [{cs['phase_id']}] 실행={cs['assigned_executor']}(위험:{cs['executor_exhaustion_risk']}{ho}) "
                f"| 독립검증={cs['assigned_verifier']}(예비:{cs['fallback_verifier']}) | {step_str}"
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
        <button id="hud-toggle-btn" class="px-2.5 py-1 rounded-full text-xs font-semibold border border-[var(--border)] bg-[var(--secondary)] hover:opacity-80">🎯 Tier-2 HUD 위젯 모드 전환</button>
      </div>
    </div>

    <div id="contextual-hud-bar" class="rounded-lg border border-[var(--border)] bg-[var(--secondary)]/60 px-3 py-2 text-xs font-mono flex flex-wrap items-center justify-between gap-2"></div>
    <div id="macro-dashboard-container" class="space-y-3">
    <div id="five-chip-bar" class="grid grid-cols-1 md:grid-cols-5 gap-2"></div>
    <div id="wait-banner" class="rounded-lg border border-[var(--border)] bg-[var(--secondary)]/40 p-2.5 text-xs"></div>
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
  </div>

  <script>
    const SNAP = {payload_json};
    const ENGINES_ORDER = ["codex", "claude", "antigravity", "haiku", "ollama"];
    const LABELS = {{
      codex: "Codex (조율·판정)",
      claude: "Claude Code (부지휘)",
      antigravity: "Antigravity (Google AI Ultra 5x · Gemini 4 Argon)",
      haiku: "Haiku 5.5 (경량 분담)",
      ollama: "Ollama CLI (0원 계산기)"
    }};

    function fmt(n) {{
      if (n === null || n === undefined) return "∞ (무제한)"; if (n === "UNKNOWN") return "미계측(UNKNOWN)"; return Number(n).toLocaleString();
    }}

    function renderAll(winKey) {{
      const sched = SNAP.schedule_recommendation || {{}};
      const off = SNAP.offload_efficiency_24h || {{}};
      const wt = SNAP.wait_transparency || {{}};
      const fc = ((SNAP.five_chip_telemetry || {{}}).chips) || {{}};
      const chipBar = document.getElementById("five-chip-bar");
      if (chipBar) {{
        const c1 = fc["1_todos_schedule"] || {{}};
        const c2 = fc["2_three_tool_seats"] || {{}};
        const c3 = fc["3_background_watchers"] || {{}};
        const c4 = fc["4_changed_files_diff"] || {{}};
        const c5 = fc["5_quota_and_reset_timer"] || {{}};
        const wDec = (c3.wait_decision || {{}}).action || "CONTINUE_WAIT";
        const chipItems = [
          {{ title: "① 할 일 · 마스터 일정 (Todos)", val: `${{c1.done ?? 0}} / ${{c1.total ?? 0}} 완료`, sub: `남은 ${{c1.remaining ?? 0}}건 (진행 ${{c1.active ?? 0}} · 검수 ${{c1.review ?? 0}})` }},
          {{ title: "② 3대 도구+로컬 좌석 (OpenRig)", val: String(c2.mode || "THREE_TOOL_NORMAL"), sub: `지휘: ${{String(c2.conductor || "antigravity").toUpperCase()}} · 좌석 ${{(c2.seats || []).length}}석` }},
          {{ title: "③ 백그라운드 워처 · 5초 선점", val: `워처 ${{(c3.watchers || []).length}}개 가동`, sub: `판정: ${{wDec}} (한도 ${{c3.foreground_wait_limit_s ?? 5.0}}s)` }},
          {{ title: "④ 실시간 변경 파일 Diff", val: `${{c4.file_count ?? 0}}개 파일 변경`, sub: `+${{c4.lines_added ?? 0}} / -${{c4.lines_removed ?? 0}} lines` }},
          {{ title: "⑤ 쿼터 · 리셋 타이머", val: `자동 재개 ${{c5.auto_resume_on_reset ? "ON" : "OFF"}}`, sub: `리셋 등록: ${{Object.keys(c5.reset_at || {{}}).length}}개 도구` }}
        ];
        chipBar.innerHTML = chipItems.map(item => `
          <div class="border border-[var(--border)] rounded-lg p-2 bg-[var(--secondary)]/20 flex flex-col justify-between">
            <span class="text-[11px] text-[var(--muted-foreground)] font-medium">${{item.title}}</span>
            <span class="text-xs font-semibold text-[var(--foreground)] mt-0.5">${{item.val}}</span>
            <span class="text-[11px] text-[var(--muted-foreground)] mt-0.5">${{item.sub}}</span>
          </div>
        `).join("");
      }}
      const wb = document.getElementById("wait-banner");
      if (wb) {{
        wb.textContent = "🔍 실시간 대기·진행 상태: " + (wt.headline || "상태 정보 없음");
      }}
      const hudBar = document.getElementById("contextual-hud-bar");
      if (hudBar) {{
        const cTel = SNAP.cockpit_telemetry || {{}};
        const cacheBadge = cTel.available ? ` | Cockpit 캐시적중: ${{cTel.cache_hit_pct}}% (${{cTel.total_events}}건)` : "";
        hudBar.textContent = (SNAP.contextual_hud_widget || "[HUD 위젯] 가동 중") + cacheBadge;
      }}
      document.getElementById("conductor-badge").textContent =
        "지휘: " + String(sched.recommended_conductor || "antigravity").toUpperCase() + " | Gemini 4 Argon (Google AI Ultra 5x) 5h 점유: " + (sched.argon_used_5h_share_pct === "UNKNOWN" ? "UNKNOWN" : (sched.argon_used_5h_share_pct ?? "UNKNOWN") + "%") + " (가용점유 " + (sched.argon_remaining_5h_share_pct === "UNKNOWN" ? "UNKNOWN" : (sched.argon_remaining_5h_share_pct ?? "UNKNOWN") + "%") + ")";
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
        const sub = info.subscription_plan || {{}};
        const qText = (q && q.used_percent !== null && q.used_percent !== undefined)
          ? ` | UI 5h:${{q.used_percent}}%` : "";
        const q7Text = (sub.quota_7d_ui_pct !== null && sub.quota_7d_ui_pct !== undefined)
          ? `·7d:${{sub.quota_7d_ui_pct}}%` : "";
        const subTotal5h = sub.total_5h_tokens;
        const subTotal7d = sub.total_7d_tokens;
        const subPct7d = Number(sub.utilization_7d_pct || 0);

        const card = document.createElement("div");
        card.className = "border border-[var(--border)] rounded-lg p-2.5 flex flex-col justify-between space-y-1.5";
        card.innerHTML = `
          <div class="flex items-center justify-between">
            <span class="text-xs font-semibold">${{LABELS[eng] || eng}}</span>
            <span class="text-xs px-1.5 py-0.5 rounded bg-[var(--secondary)] text-[var(--secondary-foreground)]">${{state}}${{info.quota_reset_ready ? "·RESET" : ""}}</span>
          </div>
          <div class="text-[11px] text-[var(--muted-foreground)] font-medium">${{sub.plan_name || ""}}</div>
          <div class="text-xs text-[var(--muted-foreground)]">
            5h 총한도 대비: <strong class="text-[var(--foreground)]">${{fmt(w.effective_budget_tokens || 0)}}</strong> / ${{subTotal5h ? fmt(subTotal5h) : "∞"}} tok
          </div>
          <div class="text-xs text-[var(--muted-foreground)]">
            5h 잔여(예산): <strong class="text-[var(--foreground)]">${{rem === null ? "무제한(0원)" : fmt(rem) + " tok"}}</strong>
          </div>
          <div class="text-[11px] text-[var(--muted-foreground)]">
            7d 주간 총량 대비: <strong class="text-[var(--foreground)]">${{fmt(sub.used_7d_effective_tokens || 0)}}</strong> / ${{subTotal7d ? fmt(subTotal7d) : "∞"}} tok (${{subPct7d}}%)
          </div>
          <div class="w-full bg-[var(--secondary)] h-2 rounded-full overflow-hidden">
            <div class="bg-[var(--primary)] h-2 rounded-full" style="width: ${{rem === null ? 15 : Math.min(100, Math.max(4, pct))}}%"></div>
          </div>
          <div class="flex items-center justify-between text-xs">
            <span>5h: ${{rem === null ? "0%" : pct + "%"}}${{qText}}${{q7Text}}</span>
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
      const subSched = SNAP.sub_process_schedule || {{}};
      const subCards = subSched.card_sub_schedules || [];
      document.getElementById("sched-count").textContent = `활성·대기 ${{assigns.length}}개 카드 · 세부공정 ${{subSched.total_sub_processes ?? 0}}개`;
      const schedList = document.getElementById("schedule-list");
      schedList.innerHTML = "";
      if (assigns.length === 0) {{
        schedList.innerHTML = `<div class="text-[var(--muted-foreground)]">모든 활성 단계가 DONE 상태입니다. 새 카드 생성 시 가용 토큰 최다 도구에 자동 배정됩니다.</div>`;
      }} else {{
        assigns.forEach(a => {{
          const row = document.createElement("div");
          row.className = "border border-[var(--border)] rounded p-2 flex flex-col gap-0.5";
          const cs = subCards.find(c => c.phase_id === a.phase_id) || {{}};
          const spList = (cs.sub_processes || []).map(sp => `SP${{sp.step_index}}(${{sp.primary_worker}}:${{sp.state}})`).join(" → ");
          const hoBadge = cs.preemptive_handoff_target ? ` | 선제인계대기: ${{String(cs.preemptive_handoff_target).toUpperCase()}}` : "";
          row.innerHTML = `
            <div class="flex items-center justify-between font-semibold">
              <span>[${{a.phase_id}}] 상태: ${{a.state}}</span>
              <span>실행: ${{String(cs.assigned_executor || a.assigned_owner).toUpperCase()}} → 독립검증: ${{String(cs.assigned_verifier || a.assigned_reviewer).toUpperCase()}}${{hoBadge}}</span>
            </div>
            <div class="text-[var(--muted-foreground)]">
              예상 유료 토큰: ${{fmt(a.estimated_paid_tokens)}} (${{a.sizing_action}}) | 오프로드: ${{(a.local_offload || []).join(", ")}}
            </div>
            <div class="text-[11px] text-[var(--foreground)] pt-0.5">
              🔄 세부 프로세스 DAG: ${{spList || "SP1~SP5 자동생성"}}
            </div>
          `;
          schedList.appendChild(row);
        }});
      }}
    }}

    document.getElementById("window-select").addEventListener("change", (e) => renderAll(e.target.value));
    const hudBtn = document.getElementById("hud-toggle-btn");
    const macroBox = document.getElementById("macro-dashboard-container");
    if (hudBtn && macroBox) {{
      hudBtn.addEventListener("click", () => {{
        const hidden = macroBox.classList.toggle("hidden");
        hudBtn.textContent = hidden ? "📊 Tier-1 전체 대시보드 펼치기" : "🎯 Tier-2 HUD 위젯 모드 전환";
      }});
    }}
    renderAll("window_5h");
  </script>
</body>
</html>
"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8", newline="\n")
    return output_path


def compute_subworker_optimization(engines: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """U271/U272: Compute 3-tool Ollama CLI active offload boost and Claude Code (Ollama : Haiku : Opus = 50:30:20)
    disjoint parallel optimization metrics.
    """
    from v7_harness.delegation import compute_agy_ollama_boost_plan, compute_claude_532_dispatch_plan

    def _calls_5h(name: str) -> int:
        w = (engines.get(name) or {}).get("window_5h") or {}
        return int(w.get("calls") or 0)

    def _util_5h(name: str) -> float:
        val = (engines.get(name) or {}).get("budget_utilization_5h_pct")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            return float(val)
        return 0.0

    agy_util = _util_5h("antigravity")
    claude_util = _util_5h("claude")
    codex_util = _util_5h("codex")

    ollama_calls = _calls_5h("ollama")
    haiku_calls = _calls_5h("haiku")
    claude_calls = _calls_5h("claude")
    agy_calls = _calls_5h("antigravity")
    codex_calls = _calls_5h("codex")

    haiku_rem = (engines.get("haiku") or {}).get("usable_remaining_5h_tokens")
    haiku_rem_int = int(haiku_rem) if isinstance(haiku_rem, (int, float)) and not isinstance(haiku_rem, bool) else 2063363

    agy_boost = agy_util >= 70.0 or (engines.get("antigravity") or {}).get("status_tier") == "CRITICAL_OFFLOAD"
    claude_boost = claude_util >= 70.0 or (engines.get("claude") or {}).get("status_tier") == "CRITICAL_OFFLOAD"
    codex_boost = codex_util >= 70.0 or (engines.get("codex") or {}).get("status_tier") in ("CRITICAL_OFFLOAD", "LIMITED_PAUSE")

    claude_532 = compute_claude_532_dispatch_plan(
        ollama_calls_5h=ollama_calls,
        haiku_calls_5h=haiku_calls,
        opus_sonnet_calls_5h=claude_calls,
        haiku_remaining_5h_tokens=haiku_rem_int,
    )
    agy_plan = compute_agy_ollama_boost_plan(utilization_5h_pct=agy_util)

    return {
        "schema": "uaos-subworker-optimization-v1",
        "antigravity_boost_plan": agy_plan,
        "three_tool_ollama_boost": {
            "antigravity": {
                "active": agy_boost,
                "utilization_5h_pct": agy_util,
                "calls_5h": agy_calls,
                "slice_line_limit": 30 if agy_boost else 20,
                "mandatory_read_map_lines": 100 if agy_boost else 150,
                "target_ollama_offload_pct": 60.0,
                "haiku_policy": "QUARANTINED_NO_API_SPEND",
            },
            "claude": {
                "active": claude_boost,
                "utilization_5h_pct": claude_util,
                "calls_5h": claude_calls,
                "slice_line_limit": 30 if claude_boost else 20,
                "mandatory_read_map_lines": 100 if claude_boost else 150,
                "target_ollama_offload_pct": 50.0,
                "haiku_policy": "ACTIVE_DISJOINT_SUBAGENT_12K_CAP",
            },
            "codex": {
                "active": codex_boost,
                "utilization_5h_pct": codex_util,
                "calls_5h": codex_calls,
                "slice_line_limit": 30 if codex_boost else 20,
                "mandatory_read_map_lines": 100 if codex_boost else 150,
                "target_ollama_offload_pct": 60.0,
                "haiku_policy": "QUARANTINED_NO_API_SPEND",
            },
        },
        "claude_internal_subworker_balance": {
            "current_5h_ratio": {
                "ollama_pct": claude_532["current_ratio_pct"]["ollama_pct"],
                "haiku_pct": claude_532["current_ratio_pct"]["haiku_pct"],
                "opus_sonnet_pct": claude_532["current_ratio_pct"]["paid_core_pct"],
            },
            "target_golden_ratio": {
                "ollama_pct": 50.0,
                "haiku_pct": 30.0,
                "opus_sonnet_pct": 20.0,
            },
            "deficit_delta_pct": claude_532["deficit_delta_pct"],
            "next_recommended_worker_tier": claude_532["next_recommended_worker_tier"],
            "haiku_preflight_cap_tokens": 12000,
            "max_concurrent_ollama": 1,
            "max_concurrent_subagents": 2,
            "disjoint_lanes": {
                "ollama_cli": "v7_harness/*.py single-file code slices (<=30 lines), local_read_map, local_draft",
                "haiku_5_5": "tests/test_*.py regression runner & docs/* index sync (disjoint from Ollama code paths)",
                "claude_opus_sonnet": "Core architecture synthesis & cross-tool independent review (author != judge)",
            },
        },
    }

render_capacity_dashboard_html = render_html_dashboard
