"""U23 S3: Local Sentinel - Deterministic Health Checks, Triage, and Wake-on-P1 Gatekeeper.

Operates at 0 paid API token cost. Deterministic rules decide actionable state;
local models can summarize/triage but cannot approve, delete, or suppress a required alert.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

from .mailbox import Mailbox
from .adapter import sync_stream_to_mailbox

# A consumer that crashed mid-delivery gets its message back after this long. Long consumers call Mailbox.renew().
CLAIM_LEASE_S = 600.0


def _is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE, False, pid)
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            ctypes.windll.kernel32.CloseHandle(handle)
            return exit_code.value == 259
        ctypes.windll.kernel32.CloseHandle(handle)
        return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def check_quiet_lock(project_root: Path, max_age_s: float = 3600.0) -> dict[str, Any]:
    lock_file = project_root / ".work" / "QUIET_LOCK"
    if not lock_file.is_file():
        return {"status": "CLEAN", "is_stale": False, "lock_data": None}

    try:
        raw = lock_file.read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception:
        return {"status": "STALE", "is_stale": True, "reason": "CORRUPTED_LOCK_FILE", "lock_data": None}

    raw_started = data.get("started_at", 0)
    try:
        started_at = float(raw_started)
    except (ValueError, TypeError):
        try:
            from datetime import datetime
            started_at = datetime.fromisoformat(str(raw_started)).timestamp()
        except Exception:
            started_at = 0.0
    pid = int(data.get("pid", 0))
    age = time.time() - started_at

    if age > max_age_s:
        return {"status": "STALE", "is_stale": True, "reason": f"AGE_EXCEEDED ({age:.1f}s > {max_age_s}s)", "lock_data": data}

    if not _is_pid_alive(pid):
        return {"status": "STALE", "is_stale": True, "reason": f"DEAD_PROCESS (pid={pid})", "lock_data": data}

    return {"status": "ACTIVE", "is_stale": False, "lock_data": data}


def needs_reconciliation(summary: dict[str, Any]) -> bool:
    """Same condition under which pilot.py tells the operator to run `pilot reconcile`.

    pilot writes NEEDS_RECONCILIATION into error_class, never into verdict_hint, so the old verdict_hint check
    never fired on a real run. `pilot reconcile` rewrites the summary to ABANDONED, which clears the alert.
    """
    if summary.get("verdict_hint") in ("NEEDS_RECONCILIATION", "UNKNOWN"):
        return True
    return summary.get("state") == "FAILED" and (
        summary.get("error_class") in ("TIMEOUT", "NEEDS_RECONCILIATION") or summary.get("effect_state") == "UNKNOWN"
    )


def _ledger_confirms_terminal_success(pilot_dir: Path, task_id: str) -> bool:
    """Return true only when a readable ledger has success and no attempt still needs reconciliation."""
    db_path = pilot_dir / "coord.sqlite3"
    if not db_path.is_file():
        return False
    connection = None
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        states = [row[0] for row in connection.execute(
            "SELECT state FROM attempts WHERE task_id=?", (task_id,)
        ).fetchall()]
    except (OSError, sqlite3.Error):
        return False
    finally:
        if connection is not None:
            connection.close()
    unresolved = {"PENDING", "RUNNING", "VERIFYING", "NEEDS_RECONCILIATION"}
    return "SUCCEEDED" in states and not unresolved.intersection(states)


def check_ledger_reconciliation(pilot_dir: Path) -> list[str]:
    runs_dir = pilot_dir / "runs"
    if not runs_dir.is_dir():
        return []

    needs_reconcile = []
    for item in runs_dir.iterdir():
        if item.is_dir():
            summary_file = item / "summary.json"
            if summary_file.is_file():
                try:
                    data = json.loads(summary_file.read_text(encoding="utf-8"))
                except Exception:
                    needs_reconcile.append(item.name)
                    continue
                if not isinstance(data, dict):
                    needs_reconcile.append(item.name)
                elif needs_reconciliation(data) and not _ledger_confirms_terminal_success(pilot_dir, item.name):
                    needs_reconcile.append(item.name)
    return sorted(needs_reconcile)


def check_all_pilot_dirs(project_root: Path) -> list[str]:
    from ..pilot_dirs import discover

    return sorted({task for pilot_dir in discover(project_root) for task in check_ledger_reconciliation(pilot_dir)})


def triage_failure(error_log: str, staging: Path | None = None) -> dict[str, Any]:
    from ..accept_triage import _CODE, _INFRA

    for pat in _CODE:
        if pat.search(error_log):
            return {"classification": "CODE", "is_p1": False, "summary": "Code defect detected"}

    for pat in _INFRA:
        if pat.search(error_log):
            return {"classification": "INFRA", "is_p1": True, "summary": "Infrastructure defect detected"}

    return {"classification": "UNKNOWN", "is_p1": False, "summary": "Unclassified failure"}


def generate_briefing(project_root: Path, box: Mailbox | None = None, max_lines: int = 60, max_bytes: int = 6144) -> str:
    lock_info = check_quiet_lock(project_root)
    lines = [
        "# Sentinel Briefing",
        "",
        f"- Status: Lock={lock_info['status']}",
    ]
    if lock_info["is_stale"]:
        lines.append(f"  Warning: Lock is STALE ({lock_info.get('reason')})")

    if box is not None:
        items = box.list_inbox()
        lines.append(f"- Mailbox Inbox: {len(items)} messages pending")
        wakes = [item for item in items if item.startswith("wake_")]
        if wakes:
            lines.append(f"  P1 wakes waiting: {', '.join(wakes[:3])}")
        bad = box.list_bad()
        if bad:
            lines.append(f"  Quarantined unreadable messages: {len(bad)} (.coord/mailbox/bad)")
        reviews = [item for item in items if item.startswith("rsi_review_")]
        if reviews:
            lines.append(f"  RSI reviews waiting: {', '.join(reviews[:3])} (python -m v7_harness.cli rsi propose)")

    from .presence import read_all

    desk = ", ".join(f"{tool}={info['state']}" for tool, info in read_all(project_root).items())
    lines.append(f"- Presence: {desk}")

    reconciles = check_all_pilot_dirs(project_root)
    if reconciles:
        lines.append(f"- Unreconciled Tasks: {', '.join(reconciles)}")
    else:
        lines.append("- Unreconciled Tasks: None")

    briefing = "\n".join(lines[:max_lines]) + "\n"
    encoded = briefing.encode("utf-8")
    if len(encoded) > max_bytes:
        briefing = encoded[:max_bytes].decode("utf-8", errors="ignore")
    return briefing


def ring_bell(project_root: Path, box: Mailbox, *, runner: Any = None, sessions_dir: Path | None = None) -> dict[str, Any]:
    """Ring the commander for P1 wakes still waiting in the mailbox.

    Rings only when Codex has a fresh ACTIVE heartbeat: AGENTS.md forbids sending into an absent or limited
    Codex window. Otherwise the wake simply waits in the mailbox and rings once Codex is back. `codex queue`
    wakes an idle session. notify() adds the rate limit and sends the same waiting set only once.
    """
    from .notify import NotifyRefused, notify, resolve_thread
    from .presence import read as read_presence

    pending = [(message_id, payload) for message_id, payload in box.peek() if message_id.startswith("wake_")]
    if not pending:
        return {"rung": False, "reason": "NO_PENDING_WAKE"}
    state = read_presence(project_root, "codex")["state"]
    if state != "ACTIVE":
        return {"rung": False, "reason": f"CODEX_{state}", "pending": len(pending)}
    thread = resolve_thread(project_root, sessions_dir=sessions_dir)
    if not thread:
        return {"rung": False, "reason": "NO_THREAD", "pending": len(pending)}
    ids = [message_id for message_id, _ in pending]
    first = pending[0][1] if isinstance(pending[0][1], dict) else {}
    headline = f"P1 {len(ids)}: {first.get('wake_reason', 'see mailbox')}"[:160]
    try:
        result = notify(
            project_root,
            thread=thread,
            actor="sentinel",
            brief_text="\n".join(ids),
            headline=headline,
            pending=ids,
            verdict_requested=True,
            dry_run=False,
            runner=runner,
        )
    except NotifyRefused as exc:
        return {"rung": False, "reason": str(exc), "pending": len(ids)}
    return {"rung": result.sent, "reason": result.reason, "pending": len(ids)}


def run_sentinel_cycle(
    project_root: Path,
    box: Mailbox,
    recipient: str = "codex",
    *,
    ring: bool = False,
    runner: Any = None,
    sessions_dir: Path | None = None,
) -> dict[str, Any]:
    import hashlib

    from .stream import StreamRejected

    t0 = time.time()
    lock_info = check_quiet_lock(project_root)
    reconcile_tasks = check_all_pilot_dirs(project_root)
    recovered = box.recover_stale_claims(stale_timeout_s=CLAIM_LEASE_S)

    sync_error = None
    try:
        # The cursor keeps already-synced events from being republished every cycle.
        sync_stream_to_mailbox(project_root, box, cursor_file=box.root / ".sync_cursor.json")
    except (StreamRejected, OSError) as exc:
        sync_error = f"{type(exc).__name__}: {exc}"[:200]

    p1_reasons: list[str] = []
    p1_events: list[dict[str, Any]] = []
    if lock_info["is_stale"]:
        reason_code = str(lock_info.get("reason", "STALE")).split(" (", 1)[0]
        p1_reasons.append(f"STALE_LOCK: {reason_code}")
        p1_events.append(
            {
                "kind": "stale_lock",
                "reason": reason_code,
                "lock_data": lock_info.get("lock_data"),
            }
        )
    if reconcile_tasks:
        stable_tasks = sorted(reconcile_tasks)
        p1_reasons.append(f"NEEDS_RECONCILIATION: {','.join(stable_tasks)}")
        p1_events.append({"kind": "needs_reconciliation", "tasks": stable_tasks})

    # Read only. Claiming to look hid each message from real consumers for the length of the check.
    for msg_id, payload in box.peek():
        if not isinstance(payload, dict):
            continue
        expires_at = payload.get("expires_at")
        if (
            isinstance(expires_at, (int, float))
            and not isinstance(expires_at, bool)
            and float(expires_at) <= t0
        ):
            continue
        if payload.get("kind") == "BLOCKED" or payload.get("is_p1"):
            p1_reasons.append(f"BLOCKED_TASK: {payload.get('step')}")
            p1_events.append(
                {
                    "kind": "mailbox_p1",
                    "message_id": msg_id,
                    "payload": payload,
                }
            )

    p1_wake_emitted = False
    if p1_events:
        canonical = json.dumps(
            {"recipient": recipient, "events": p1_events},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        event_fingerprint = hashlib.sha256(canonical).hexdigest()
        wake_id = f"wake_{event_fingerprint[:24]}"
        # has_message also sees a wake that someone has claimed but not yet acked, so it is not sent twice.
        if not box.has_message(wake_id):
            box.publish(
                message_id=wake_id,
                payload={
                    "recipient": recipient,
                    "p1_alert": True,
                    "wake_reason": "; ".join(p1_reasons),
                    "event_fingerprint": event_fingerprint,
                    "actor": "sentinel",
                },
            )
            p1_wake_emitted = True

    rsi_published: list[str] = []
    rsi_error = None
    try:
        # RSI observe step: a finished window of runs becomes one review message (never P1, never repeated).
        from ..rsi import analyze, load_policy, load_rows, rsi_review_messages

        policy = load_policy(project_root)
        for message_id, payload in rsi_review_messages(project_root, analyze(load_rows(project_root), policy), policy):
            if not box.has_message(message_id):
                box.publish(message_id=message_id, payload=payload)
                rsi_published.append(message_id)
    except Exception as exc:  # noqa: BLE001 - a broken ledger line must not stop the operator
        rsi_error = f"{type(exc).__name__}: {exc}"[:200]

    bell = ring_bell(project_root, box, runner=runner, sessions_dir=sessions_dir) if ring else {"rung": False, "reason": "RING_OFF"}

    wall_time_s = time.time() - t0
    return {
        "wall_time_s": wall_time_s,
        "paid_api_calls": 0,
        "p1_wake_emitted": p1_wake_emitted,
        "lock_status": lock_info["status"],
        "reconcile_tasks": reconcile_tasks,
        "recovered_claims": recovered,
        "sync_error": sync_error,
        "rsi_review_published": rsi_published,
        "rsi_error": rsi_error,
        "bell": bell,
    }
