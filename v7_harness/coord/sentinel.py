"""U23 S3: Local Sentinel - Deterministic Health Checks, Triage, and Wake-on-P1 Gatekeeper.

Operates at 0 paid API token cost. Deterministic rules decide actionable state;
local models can summarize/triage but cannot approve, delete, or suppress a required alert.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import sqlite3
import sys
import time
import uuid
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
    from ..pilot_dirs import live

    # U262: repo copies under .work/ carry historical summaries; only live pilot dirs raise NEEDS_RECONCILIATION.
    return sorted({task for pilot_dir in live(project_root) for task in check_ledger_reconciliation(pilot_dir)})


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


def _family(step: str) -> str:
    """U116: retry family of a step: drop `-R<n>`, `-P`, `-agy`, then the digits after a lettered last segment.

    U113-D3 -> U113-D, U106-A2-P -> U106-A, U115-L2 -> U115-L; a card id such as U86 stays U86 (its digits follow `U`
    at the start, not a lettered `-X` segment), so a sibling step like U86-F1 (family U86-F) never clears U86.
    """
    import re

    step = re.sub(r"-(R\d+|P|agy)$", "", step)
    return re.sub(r"(-[A-Za-z]+)\d+$", r"\1", step)


def _apply_after_links(project_root: Path) -> dict[str, str]:
    """U116: work_id -> failed work_id it replaced, read from `.coord/tasks/*.md` contract manuals (U98-D)."""
    links: dict[str, str] = {}
    for manual in sorted((project_root / ".coord" / "tasks").glob("*.md")):
        try:
            head = manual.read_text(encoding="utf-8")[:2000]
        except OSError:
            continue
        fields = dict(line.split(":", 1) for line in head.splitlines() if line.startswith(("work_id:", "apply_after:")))
        if "work_id" in fields and "apply_after" in fields:
            links[fields["work_id"].strip()] = fields["apply_after"].strip()
    return links


def _last_pass_by_step(project_root: Path) -> dict[str, float]:
    """U88: latest ledger PASS time per step; a `-R<n>` retry also counts for the step it retries.

    Seen 2026-09-29: the P1 wake still listed U80 and U86 after U80-R1 and U86-R1 passed, and it grew with every BLOCKED
    message ever sent, so the one P1 at each session start carried no signal. An unreadable ledger proves nothing.
    """
    import re

    try:
        from ..rsi import load_rows

        rows = load_rows(project_root)
    except Exception:  # noqa: BLE001 - no evidence means every alert stays
        return {}
    passed: dict[str, float] = {}
    links = _apply_after_links(project_root)  # U116: an apply run also passes the delegate it replaced
    for row in rows:
        work_id, ts = row.get("work_id"), row.get("ts")
        if row.get("outcome") != "PASS" or not isinstance(work_id, str):
            continue
        if not isinstance(ts, (int, float)) or isinstance(ts, bool):
            continue
        linked = links.get(work_id)
        steps = {work_id, re.sub(r"-R\d+$", "", work_id), _family(work_id)}
        for step in steps | ({linked, _family(linked)} if linked else set()):
            passed[step] = max(passed.get(step, 0.0), float(ts))
    return passed


def _passed_since(passed: dict[str, float], payload: dict[str, Any]) -> bool:
    """U88: the message's own step passed after the message was written. A missing or unreadable time keeps the alert."""
    from datetime import datetime

    step, stamp = payload.get("step"), payload.get("ts")
    if not isinstance(step, str) or not isinstance(stamp, str):
        return False
    done = max(passed.get(step, 0.0), passed.get(_family(step), 0.0))  # U116: a later retry of its family counts
    if not done:
        return False
    try:
        blocked_at = datetime.fromisoformat(stamp).timestamp()
    except ValueError:
        return False
    return done > blocked_at


_TERMINAL_PHASE_STATES = frozenset({"DONE", "DONE_SCOPED", "DONE_ELSEWHERE", "RETIRED"})


def _schedule_closed_since(project_root: Path, payload: dict[str, Any]) -> bool:
    """U260: the master schedule closed the letter's step, or its card (`U241C` for `U241C-S4`), after the letter.

    Most cards close through a merged PR, never a ledger PASS, so U88 alone kept 212 stale letters in every P1 wake.
    The phase's own `updated_at` is its close time, else the schedule's; no time, an open phase or an unreadable
    schedule keeps the alert.
    """
    from datetime import datetime

    step, stamp = payload.get("step"), payload.get("ts")
    if not isinstance(step, str) or not isinstance(stamp, str):
        return False
    try:
        blocked_at = datetime.fromisoformat(stamp).timestamp()
        schedule = json.loads((project_root / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    phases = schedule.get("phases") if isinstance(schedule, dict) else None
    if not isinstance(phases, list):
        return False
    card = re.match(r"U\d+[A-Za-z]?(?=-|$)", step)
    wanted = {step.upper(), card.group(0).upper()} if card else {step.upper()}
    for phase in phases:
        if not isinstance(phase, dict) or str(phase.get("phase_id", "")).upper() not in wanted:
            continue
        if phase.get("state") not in _TERMINAL_PHASE_STATES:
            continue
        closed = phase.get("updated_at") or schedule.get("updated_at")
        try:
            closed_at = float(closed) if isinstance(closed, (int, float)) and not isinstance(closed, bool) \
                else datetime.fromisoformat(str(closed)).timestamp()
        except ValueError:
            continue
        if closed_at > blocked_at:
            return True
    return False


EXHAUSTED_SCHEMA = "u190b-exhausted-v1"
WAKE_SEEN_SCHEMA = "u189-wake-seen-v1"
_HEX64 = re.compile(r"[0-9a-f]{64}")


def _event_keys(events: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for event in events:
        kind = event.get("kind")
        if kind == "mailbox_p1":
            keys.add(f"mailbox_p1:{event.get('message_id')}")
        elif kind == "stale_lock":
            keys.add(f"stale_lock:{event.get('reason')}")
        elif kind == "needs_reconciliation":
            keys.update(f"needs_reconciliation:{task}" for task in event.get("tasks", []))
    return keys


def _create_exclusive(path: Path, data: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    with open(temp, "x", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(temp, path)
    except FileExistsError:
        return False
    finally:
        temp.unlink()
    return True


def _episode_id(record: dict[str, Any]) -> str:
    episode = {key: record[key] for key in ("schema", "tool", "wake_base", "event_fingerprint", "desk")}
    episode["event_keys"] = sorted(set(record["event_keys"]))
    return hashlib.sha256(json.dumps(episode, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _read_json(path: Path) -> Any:
    """None when absent; ValueError marks a present file that is not JSON."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError) as exc:
        raise ValueError(str(exc)) from exc


def _consumed_valid(marker: Any, tool: str, record_id: str, record: dict[str, Any]) -> bool:
    return (isinstance(marker, dict) and marker.get("schema") == "u190b-consumed-v1" and marker.get("tool") == tool
            and marker.get("record_id") == record_id and marker.get("wake_base") == record["wake_base"]
            and marker.get("event_fingerprint") == record["event_fingerprint"]
            and marker.get("event_keys") == sorted(set(record["event_keys"])) and marker.get("desk") == record["desk"]
            and marker.get("resolved_by") in ("NEW_DESK", "RECEIPT", "ALERT_CHANGED"))


def _letter_payload(box: Mailbox, message_id: str) -> Any:
    paths = [box.inbox_dir / f"{message_id}.json", *box._claimed_files(message_id), box.ack_dir / f"{message_id}.json"]
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("message_id") == message_id:
            return data.get("payload")
    return None


def _parse_exhausted(raw: bytes, tool: str) -> dict[str, Any]:
    from .deliver import UUID_RE

    data = json.loads(raw.decode("utf-8"))
    fp = data.get("event_fingerprint") if isinstance(data, dict) else None
    ok = (isinstance(data, dict) and data.get("schema") == EXHAUSTED_SCHEMA and data.get("tool") == tool
          and isinstance(fp, str) and bool(_HEX64.fullmatch(fp)) and data.get("wake_base") == f"wake_{fp[:24]}"
          and isinstance(data.get("event_keys"), list) and all(isinstance(k, str) for k in data["event_keys"]))
    desk = data.get("desk") if ok else None
    if ok and desk is not None:
        ok = (isinstance(desk, dict) and isinstance(desk.get("thread"), str) and bool(UUID_RE.fullmatch(desk["thread"]))
              and type(desk.get("generation")) is int)
    if not ok:
        raise ValueError("EXHAUSTED_RECORD_CORRUPT")
    return data


def _wake_payload(box: Mailbox, message_id: str) -> dict[str, Any]:
    for folder in (box.inbox_dir, box.ack_dir):
        try:
            data = json.loads((folder / f"{message_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict):
            return payload
    return {}


def _receipt_proves(presence_dir: Path, box: Mailbox, tool: str, record: dict[str, Any]) -> bool:
    desk, wake, fp = record["desk"], record["wake_base"], record["event_fingerprint"]
    if _wake_payload(box, wake).get("event_fingerprint") != fp:
        return False
    try:
        data = json.loads((presence_dir / "wake_seen" / tool / desk["thread"] / f"{wake}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (isinstance(data, dict) and data.get("schema") == WAKE_SEEN_SCHEMA and data.get("message_id") == wake
            and data.get("tool") == tool and data.get("session") == desk["thread"]
            and type(data.get("generation")) is int and data.get("generation") == desk["generation"]
            and data.get("event_fingerprint") == fp)


def _consume_one(project_root: Path, box: Mailbox, tool: str, current_keys: set[str]) -> dict[str, Any]:
    from . import desk_sync

    presence_dir = project_root / ".coord" / "presence"
    try:
        raw = (presence_dir / f"p1_retry_exhausted_{tool}.json").read_bytes()
    except FileNotFoundError:
        return {"status": "NONE"}
    except OSError:
        return {"status": "UNREADABLE"}
    try:
        record = _parse_exhausted(raw, tool)
    except ValueError:
        return {"status": "CORRUPT"}
    record_id = _episode_id(record)
    consumed = presence_dir / "p1_retry_consumed" / tool / f"{record_id}.json"

    def settled() -> dict[str, Any]:
        try:
            marker = _read_json(consumed)
        except ValueError:
            marker = "unreadable"
        if _consumed_valid(marker, tool, record_id, record):
            return {"status": "CONSUMED", "resolved_by": marker["resolved_by"], "record_id": record_id}
        return {"status": "MARKER_INVALID", "marker": str(consumed), "record_id": record_id}

    if consumed.exists():
        return settled()
    desk_status, identity = desk_sync.desk_identity(project_root, tool)
    bound = desk_status == "PROJECT_BOUND"
    trigger = None
    if bound and identity != record["desk"]:
        trigger = "NEW_DESK"
    elif bound and _receipt_proves(presence_dir, box, tool, record):
        trigger = "RECEIPT"
    elif set(record["event_keys"]) != current_keys:
        trigger = "ALERT_CHANGED"
    if trigger:
        try:
            made = _create_exclusive(consumed, {"schema": "u190b-consumed-v1", "tool": tool, "record_id": record_id,
                                                "wake_base": record["wake_base"],
                                                "event_fingerprint": record["event_fingerprint"],
                                                "event_keys": sorted(set(record["event_keys"])),
                                                "desk": record["desk"], "resolved_by": trigger, "at": time.time()})
        except OSError:
            return {"status": "RESET_FAILED", "trigger": trigger, "record_id": record_id}
        if not made:
            return settled()
        return {"status": "RESUMED", "trigger": trigger, "record_id": record_id}
    state = {"status": "EXHAUSTED", "record_id": record_id, "desk_status": desk_status, "repaired_consumer": "UNKNOWN"}
    if not bound:
        return dict(state, handoff="UNDELIVERABLE")
    handoff = presence_dir / "p1_handoff" / tool / f"{record_id}.json"
    letter = f"handoff_{record_id[:24]}_{tool}"
    keys = sorted(set(record["event_keys"]))
    payload = {"kind": "P1_RETRY_EXHAUSTED", "recipient": tool, "requested_target": tool, "wake_class": "ACTIONABLE",
               "wake_base": record["wake_base"], "event_fingerprint": record["event_fingerprint"],
               "event_keys": keys, "receiver": record["desk"], "record_id": record_id, "actor": "sentinel",
               "delta": f"P1 retry exhausted {record['wake_base']}: {len(keys)} alert(s)"}
    expected = {"schema": "u190b-handoff-v1", "tool": tool, "record_id": record_id, "wake_base": record["wake_base"],
                "receiver": record["desk"], "letter_id": letter}

    def queued() -> str:
        try:
            marker = _read_json(handoff)
        except ValueError:
            return "HANDOFF_INVALID"
        exact = isinstance(marker, dict) and all(marker.get(k) == v for k, v in expected.items())
        return "ALREADY_QUEUED" if exact and _letter_payload(box, letter) == payload else "HANDOFF_INVALID"

    if handoff.exists():
        return dict(state, handoff=queued())
    try:
        if box.has_message(letter):
            if _letter_payload(box, letter) != payload:
                return dict(state, handoff="HANDOFF_INVALID")
        else:
            box.publish(message_id=letter, payload=payload)
        made = _create_exclusive(handoff, dict(expected, at=time.time()))
    except (OSError, ValueError):
        return dict(state, handoff="HANDOFF_FAILED")
    return dict(state, handoff="QUEUED" if made else queued())


def consume_exhaustion(project_root: Path, box: Mailbox, current_keys: set[str]) -> dict[str, dict[str, Any]]:
    from . import desk_sync
    from .stream import _try_lock, _unlock

    lock_path = project_root / ".coord" / "presence" / "p1_exhaustion.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
    try:
        deadline = time.monotonic() + 30.0
        while not _try_lock(fd):
            if time.monotonic() > deadline:
                return {tool: {"status": "LOCK_BUSY"} for tool in desk_sync.TOOLS}
            time.sleep(0.01)
        try:
            return {tool: _consume_one(project_root, box, tool, current_keys) for tool in desk_sync.TOOLS}
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def run_sentinel_cycle(
    project_root: Path,
    box: Mailbox,
    recipient: str = "codex",
    *,
    ring: bool = False,
    runner: Any = None,
    sessions_dir: Path | None = None,
    drain_runner: Any = None,
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

    passed = _last_pass_by_step(project_root)
    p1_superseded: list[str] = []
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
        if payload.get("kind") == "BLOCKED" and not payload.get("is_p1") and (
            _passed_since(passed, payload) or _schedule_closed_since(project_root, payload)
        ):
            p1_superseded.append(str(payload.get("step")))
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
                    # U141-B: producer adaptation; the structured watcher routes by requested_target and wakes only on
                    # wake_class, so a P1 wake carries both (its id still comes from the events, never repeated).
                    "requested_target": recipient,
                    "wake_class": "ACTIONABLE",
                    "delta": "; ".join(p1_reasons)[:200],
                    "wake_reason": "; ".join(p1_reasons),
                    "event_fingerprint": event_fingerprint,
                    "actor": "sentinel",
                },
            )
            p1_wake_emitted = True

    exhaustion = consume_exhaustion(project_root, box, _event_keys(p1_events))

    rsi_published: list[str] = []
    rsi_error = None
    try:
        # RSI observe step: a finished window of runs becomes one review message (never P1, never repeated).
        from ..rsi import analyze, load_policy, load_rows, rsi_review_messages

        from .presence import conductor, read_all

        policy = load_policy(project_root)
        # U125: the review goes to whoever conducts now; an UNKNOWN desk keeps it mailbox-only (fail closed).
        lead = conductor(read_all(project_root))["conductor"]
        target = lead if lead in ("codex", "claude", "antigravity") else None
        analysis = analyze(load_rows(project_root), policy)
        for message_id, payload in rsi_review_messages(project_root, analysis, policy, target=target):
            if not box.has_message(message_id):
                box.publish(message_id=message_id, payload=payload)
                rsi_published.append(message_id)
    except Exception as exc:  # noqa: BLE001 - a broken ledger line must not stop the operator
        rsi_error = f"{type(exc).__name__}: {exc}"[:200]

    # U197: the zero-paid work-transition controller (outbox, retry, P1 escalation, UNKNOWN-desk notice).
    try:
        from .transition import run_transitions

        transition_res: dict[str, Any] = run_transitions(project_root, box)
    except Exception as exc:  # noqa: BLE001 - a broken outbox record must not stop the operator
        transition_res = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    # U200: the resident loop answers Antigravity letters parked at an earlier Seoul day's cap; before this only a hook
    # turn did, so after midnight they waited for a person. backlog_ready stays false while today's cap is spent.
    try:
        from .agy_dispatch import backlog_ready
        from .presence import _drain_agy_backlog

        agy_backlog: Any = backlog_ready(project_root)
        if agy_backlog:
            _drain_agy_backlog(project_root, drain_runner, None)
    except Exception as exc:  # noqa: BLE001 - a broken backlog entry must not stop the operator
        agy_backlog = f"{type(exc).__name__}: {exc}"[:200]

    # U203: the resident loop also runs the U166 stall scan, so a reroute does not wait for some tool's next turn
    try:
        from . import stall

        stall_res: Any = stall.scan(project_root, None)["adopted"]
    except Exception as exc:  # noqa: BLE001 - a broken stall state must not stop the operator
        stall_res = f"{type(exc).__name__}: {exc}"[:200]

    # U205: wake the owner of a ready step nobody started; the U166/U203 scan covers only waiting states
    try:
        from .owner_wake import wake_owners

        owner_res: Any = wake_owners(project_root, box, now=time.time())
    except Exception as exc:  # noqa: BLE001 - a broken schedule must not stop the operator
        owner_res = f"{type(exc).__name__}: {exc}"[:200]

    try:
        from ..disjoint_mediator import run_independent_flagman_pulse

        flagman_3tool: Any = run_independent_flagman_pulse(project_root, auto_heal=True)["self_healing_receipt"]
    except Exception as exc:  # noqa: BLE001
        flagman_3tool = {"error": f"{type(exc).__name__}: {exc}"[:200]}

    bell = ring_bell(project_root, box, runner=runner, sessions_dir=sessions_dir) if ring else {"rung": False, "reason": "RING_OFF"}

    wall_time_s = time.time() - t0
    return {
        "wall_time_s": wall_time_s,
        "paid_api_calls": 0,
        "p1_wake_emitted": p1_wake_emitted,
        "p1_superseded": sorted(set(p1_superseded)),
        "exhaustion": exhaustion,
        "lock_status": lock_info["status"],
        "reconcile_tasks": reconcile_tasks,
        "recovered_claims": recovered,
        "sync_error": sync_error,
        "rsi_review_published": rsi_published,
        "rsi_error": rsi_error,
        "bell": bell,
        "transition": transition_res,
        "agy_backlog": agy_backlog,
        "owner_wake": owner_res,
        "flagman_3tool": flagman_3tool,
    }
