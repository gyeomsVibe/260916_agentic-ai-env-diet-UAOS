"""U335: a new user desk takes over the conductor role from the old desk automatically (윤겸스 2026-11-20).

Receipt: desk [261120-1] handed [261120-2] its card sessions by hand (handoff file, notice to every card window, stop
dispatching). This module is that procedure as deterministic code; no LLM is needed (Ollama may only draft prose).

Contract
- detect: the tool's registered user desk (`user_desk_<tool>.json`, written by the hook / `claim-topmost-window`) differs
  from the recorded conductor desk -> a takeover is due.
- manifest: built from PLAN.md, `.coord/cards/*.json`, `windows.json`, unacked letters and open PRs (the last two are
  injected readers so tests never touch the network).
- takeover: one compare-and-swap under an OS file lock (`desk_conductor.lock`). The caller passes the epoch it observed;
  a stale epoch loses (`DESK_TAKEOVER_LOST`), so two new desks at once yield exactly one winner. The winner gets
  epoch+1 and a lease; the loser and the old desk become read-only: `check_dispatch` answers `DESK_SUPERSEDED`.
- notify: every card window gets one notice. A notice id is sha(handoff, card, tool) and a SENT row is written before
  the next attempt, so a repeat run never sends twice. Each send is capped by ACK_DEADLINE_S and never blocks the run.
- ack: second-signal rule. A reply alone is not an ACK; ACKED needs two distinct signals (e.g. `reply` + `window_active`).
- ledger: one JSON line per event in `.coord/desk_ledger.jsonl` (U332's ledger is not merged yet; this is the minimal
  record and the writer is the only place to swap when it lands).
Worst-case table: docs/U335_desk_handoff_worstcase.md. Every number below is explained where it is defined.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.stream import _try_lock, _unlock

TOOLS = ("codex", "claude", "antigravity")
# Authority order of CLAUDE.md: Codex conducts while ACTIVE, else Claude, Antigravity only when both are away.
AUTHORITY_ORDER = TOOLS
ACK_DEADLINE_S = 10.0  # 윤겸스 2026-11-20: a notice attempt must report within 10 s or be marked and left
REPLY_DEADLINE_S = 120.0  # a card window's reply is expected within 120 s; after that it is UNCONFIRMED, never awaited
LEASE_S = 900.0  # conductor lease: 15 min covers a long dispatch turn; a dead new desk frees the role after it
LOCK_TIMEOUT_S = 10.0  # same wait as desk_sync: a hook must not hang a session longer
REPLACE_TRIES = 40  # x 0.05 s: Windows readers hold os.replace off briefly
ACK_SIGNALS_NEEDED = 2
_THREAD_GUARD = threading.Lock()
_THREAD_LOCKS: dict[str, threading.Lock] = {}

Reader = Callable[[Path], list[dict[str, Any]]]
Sender = Callable[[dict[str, Any], str], bool]


def _root(project: Path) -> Path:
    return Path(project) / ".coord"


def _conductor_path(project: Path, tool: str) -> Path:
    if tool not in TOOLS:  # a misspelled tool must never build a fresh, empty record path (fail-open)
        raise ValueError(f"DESK_TOOL_INVALID {tool!r}")
    return _root(project) / "presence" / f"desk_conductor_{tool}.json"


def _handoff_dir(project: Path) -> Path:
    return _root(project) / "handoff"


def ledger_path(project: Path) -> Path:
    return _root(project) / "desk_ledger.jsonl"


@contextmanager
def _locked(project: Path, name: str = "desk_conductor"):
    path = _root(project) / "presence" / f"{name}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    with _THREAD_GUARD:
        guard = _THREAD_LOCKS.setdefault(os.path.normcase(os.path.realpath(path)), threading.Lock())
    # OS file locks do not exclude threads of one process on POSIX, so a per-path thread lock comes first.
    if not guard.acquire(timeout=LOCK_TIMEOUT_S):
        raise TimeoutError("DESK_LOCK_BUSY")
    try:
        yield from _file_locked(path, deadline)
    finally:
        guard.release()


def _file_locked(path: Path, deadline: float):
    fd = None
    try:
        while True:
            if fd is None:
                try:
                    fd = os.open(path, os.O_CREAT | os.O_RDWR)
                except PermissionError:
                    fd = None
            if fd is not None and _try_lock(fd):
                break
            if time.monotonic() > deadline:
                raise TimeoutError("DESK_LOCK_BUSY")
            time.sleep(0.01)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        if fd is not None:
            os.close(fd)


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    for _attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            time.sleep(0.05)
    temp.unlink(missing_ok=True)
    raise PermissionError(f"could not replace {path}")


def _read_json(path: Path) -> dict[str, Any]:
    """{} when absent; ValueError when present but unreadable (fail closed, never overwritten as if empty).
    A transient Windows PermissionError (a writer's os.replace in flight) is retried like _write_json does."""
    text = ""
    for attempt in range(REPLACE_TRIES):
        try:
            text = path.read_text(encoding="utf-8")
            break
        except FileNotFoundError:
            return {}
        except PermissionError as error:
            if attempt == REPLACE_TRIES - 1:
                raise ValueError(f"DESK_RECORD_UNREADABLE {path.name}") from error
            time.sleep(0.05)
        except OSError as error:
            raise ValueError(f"DESK_RECORD_UNREADABLE {path.name}") from error
    try:
        data = json.loads(text)
    except ValueError as error:
        raise ValueError(f"DESK_RECORD_CORRUPT {path.name}") from error
    if not isinstance(data, dict):
        raise ValueError(f"DESK_RECORD_CORRUPT {path.name}")
    return data


def append_ledger(project: Path, event: str, **fields: Any) -> None:
    """One line per event, appended under the lock (concurrent appends lose lines on Windows)."""
    row = {"ts": time.time(), "event": event, **fields}
    with _locked(project, "desk_ledger"):
        path = ledger_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------- conductor record

def conductor(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    """{desk, epoch, lease_until, state}; state is NONE | ACTIVE | EXPIRED. Epoch 0 means no handoff ever happened."""
    path = _conductor_path(project, tool)
    data = _read_json(path)
    if not data:
        # Missing and empty look alike to _read_json. A first takeover may create the file between the read and an
        # exists() check, so read once more: only a file that is still empty after that is corruption.
        if not path.exists():
            return {"desk": "", "epoch": 0, "lease_until": 0.0, "state": "NONE"}
        data = _read_json(path)
    desk, epoch, lease = data.get("desk"), data.get("epoch"), data.get("lease_until")
    # An existing record must carry all three keys; an empty or partial object is corruption, not "no handoff".
    if (not isinstance(desk, str) or not desk or type(epoch) is not int or epoch < 1
            or type(lease) not in (int, float)):
        raise ValueError(f"DESK_RECORD_CORRUPT {path.name}")
    moment = time.time() if now is None else now
    expired = float(lease) <= moment
    return {**data, "state": "EXPIRED" if expired else "ACTIVE"}


def detect_new_desk(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    """Compare the tool's registered user desk with the recorded conductor. No writes."""
    from v7_harness.coord import deliver

    status, thread = deliver.user_desk_state(Path(project), tool)
    try:
        cond = conductor(project, tool, now=now)
    except ValueError as error:  # corrupt record: no takeover is due until a human or recovery fixes it
        return {"tool": tool, "epoch": -1, "old_desk": "", "conductor_state": "CORRUPT", "new_desk": "", "due": False,
                "reason": str(error).split()[0]}
    base = {"tool": tool, "epoch": cond["epoch"], "old_desk": cond["desk"], "conductor_state": cond["state"]}
    if status != "OK":
        return {**base, "new_desk": "", "due": False, "reason": f"USER_DESK_{status}"}
    due = thread != cond["desk"]
    return {**base, "new_desk": thread, "due": due, "reason": "NEW_DESK" if due else "SAME_DESK"}


def authority(states: dict[str, str]) -> str:
    """Conducting tool: first of codex, claude, antigravity that is ACTIVE; '' when none is (UNKNOWN is no ground)."""
    for tool in AUTHORITY_ORDER:
        state = states.get(tool)
        if state == "ACTIVE":
            return tool
        if state not in ("LIMITED", "ABSENT"):
            return ""  # UNKNOWN/missing higher tool: it may be ACTIVE, so no lower tool may claim authority (fail closed)
    return ""


def check_dispatch(project: Path, tool: str, desk: str, *, now: float | None = None) -> dict[str, Any]:
    """Gate for every dispatch from a desk. Only the current conductor with a live lease may dispatch.

    Epoch 0 (no handoff ever recorded) allows everyone: the feature is opt-in per project until the first takeover."""
    try:
        cond = conductor(project, tool, now=now)
    except ValueError as error:  # unknown tool or corrupt record: a gate must close, not raise or open
        return {"ok": False, "reason": str(error).split()[0], "epoch": -1}
    if cond["epoch"] == 0:
        return {"ok": True, "reason": "NO_HANDOFF_RECORDED", "epoch": 0}
    if cond["desk"] != desk:
        return {"ok": False, "reason": "DESK_SUPERSEDED", "conductor": cond["desk"], "epoch": cond["epoch"]}
    if cond["state"] == "EXPIRED":
        return {"ok": False, "reason": "DESK_LEASE_EXPIRED", "conductor": desk, "epoch": cond["epoch"]}
    return {"ok": True, "reason": "CONDUCTOR", "epoch": cond["epoch"]}


def renew_lease(project: Path, tool: str, desk: str, epoch: int, *, now: float | None = None) -> dict[str, Any]:
    moment = time.time() if now is None else now
    try:
        with _locked(project):
            cond = conductor(project, tool, now=moment)
            if epoch == 0 or cond["desk"] != desk or cond["epoch"] != epoch:
                return {"ok": False, "reason": "DESK_SUPERSEDED", "epoch": cond["epoch"]}
            _write_json(_conductor_path(project, tool), {**{k: v for k, v in cond.items() if k != "state"},
                                                         "lease_until": moment + LEASE_S})
    except TimeoutError:
        return {"ok": False, "reason": "DESK_LOCK_BUSY", "epoch": -1}
    except ValueError as error:
        return {"ok": False, "reason": str(error).split()[0], "epoch": -1}
    return {"ok": True, "reason": "RENEWED", "epoch": epoch}


# ---------------------------------------------------------------- manifest

def _plan_cards(project: Path) -> dict[str, str]:
    """card id -> first PLAN.md line naming it (title). Deterministic text scan, no interpretation."""
    out: dict[str, str] = {}
    try:
        text = (_root(project) / "PLAN.md").read_text(encoding="utf-8")
    except OSError:
        return out
    for line in text.splitlines():
        for card in re.findall(r"\bU\d{2,4}(?:-[A-Z0-9]+)?\b", line):
            out.setdefault(card, line.strip()[:200])
    return out


def _card_jsons(project: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    folder = _root(project) / "cards"
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            out[path.stem] = data
    return out


def _windows(project: Path) -> dict[str, dict[str, Any]]:
    """Only a missing file is "no windows". An unreadable or corrupt one raises: a takeover on it would commit a
    manifest with 0 sessions and notify nobody."""
    path = _root(project) / "windows.json"
    if not path.exists():
        return {}
    data = _read_json(path)
    cards = data.get("cards")
    if not isinstance(cards, dict):
        raise ValueError("DESK_WINDOWS_CORRUPT windows.json")
    return cards


def build_manifest(project: Path, *, tool: str, old_desk: str, new_desk: str, epoch: int,
                   open_prs: Reader | None = None, unacked: Reader | None = None,
                   now: float | None = None) -> dict[str, Any]:
    """Deterministic: same files in, same manifest out (ordering is by card id)."""
    project = Path(project)
    plan = _plan_cards(project)
    cards = _card_jsons(project)
    wins = _windows(project)
    ids = sorted(set(wins) | set(cards))
    rows = []
    for card in ids:
        sessions = []
        for win_tool, entry in sorted((wins.get(card, {}).get("tools") or {}).items()):
            if not isinstance(entry, dict) or entry.get("state") in ("CLOSED", "RELEASED"):
                continue
            sessions.append({"tool": win_tool, "window_id": entry.get("window_id") or entry.get("id", ""),
                             "state": entry.get("state", ""), "native_id": entry.get("native_id", ""),
                             "worktree_path": entry.get("worktree_path", "")})
        rows.append({"card": card, "title": (wins.get(card, {}).get("title") or cards.get(card, {}).get("title")
                                             or plan.get(card, "")), "plan_line": plan.get(card, ""),
                     "sessions": sessions})
    prs = list(open_prs(project)) if open_prs else []
    letters = list(unacked(project)) if unacked else []
    # Merge order is not derivable from files; carried PRs keep the reader's order, so the manifest never invents one.
    return {"tool": tool, "from_desk": old_desk, "to_desk": new_desk, "epoch": epoch,
            "built_at": time.time() if now is None else now, "cards": rows, "open_prs": prs, "unacked_letters": letters,
            "rules": ["old desk stops dispatching (DESK_SUPERSEDED)", "report to the new desk only"]}


def render_manifest_md(manifest: dict[str, Any]) -> str:
    lines = [f"# Desk handoff {manifest['from_desk'] or '(none)'} -> {manifest['to_desk']} (epoch {manifest['epoch']})", "",
             "The new desk controls every card session below. The old desk stops dispatching.", "", "## Cards", ""]
    for row in manifest["cards"]:
        sess = ", ".join(f"{s['tool']}:{s['window_id'] or '-'}[{s['state']}]" for s in row["sessions"]) or "no session"
        lines.append(f"- {row['card']} {row['title']} — {sess}")
    lines += ["", "## Open PRs", ""] + [f"- {pr}" for pr in manifest["open_prs"]] + ["", "## Unacked letters", ""]
    lines += [f"- {item}" for item in manifest["unacked_letters"]]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- takeover

def takeover(project: Path, tool: str, new_desk: str, *, expected_epoch: int | None = None,
             states: dict[str, str] | None = None, manifest_args: dict[str, Any] | None = None,
             now: float | None = None) -> dict[str, Any]:
    """Atomic compare-and-swap of the conductor. Returns ok with handoff_id/epoch/manifest path, or a refusal reason.

    `expected_epoch` is the epoch the caller saw in detect_new_desk; None means "whatever is current" (single caller).
    `states` (tool -> ACTIVE|LIMITED|ABSENT|UNKNOWN) enforces the authority order for a cross-tool takeover: the desk
    of `tool` may take over only if `tool` is the authority."""
    project = Path(project)
    moment = time.time() if now is None else now
    if tool not in TOOLS or not new_desk:
        return {"ok": False, "reason": "INVALID_TOOL_OR_DESK"}
    if states is not None and authority(states) not in (tool, ""):
        # Antigravity or Claude must not conduct while a higher authority is ACTIVE; an all-away set is not UNKNOWN-proof
        return {"ok": False, "reason": "CROSS_TOOL_NOT_AUTHORITY", "authority": authority(states)}
    if states is not None and authority(states) == "":
        return {"ok": False, "reason": "AUTHORITY_UNKNOWN"}
    try:
        with _locked(project):
            cond = conductor(project, tool, now=moment)
            if expected_epoch is not None and cond["epoch"] != expected_epoch:
                return {"ok": False, "reason": "DESK_TAKEOVER_LOST", "conductor": cond["desk"], "epoch": cond["epoch"]}
            if cond["desk"] == new_desk and cond["state"] == "ACTIVE":
                return {"ok": True, "reason": "ALREADY_CONDUCTOR", "epoch": cond["epoch"], "handoff_id": cond.get("handoff_id", "")}
            epoch = cond["epoch"] + 1
            handoff_id = f"handoff_{tool}_{epoch}_{hashlib.sha256(f'{new_desk}{epoch}'.encode()).hexdigest()[:8]}"
            manifest = build_manifest(project, tool=tool, old_desk=cond["desk"], new_desk=new_desk, epoch=epoch,
                                      now=moment, **(manifest_args or {}))
            folder = _handoff_dir(project)
            _write_json(folder / f"{handoff_id}.json", manifest)
            (folder / f"{handoff_id}.md").write_text(render_manifest_md(manifest), encoding="utf-8")
            # The conductor record is the commit point: written last, after the manifest exists on disk.
            _write_json(_conductor_path(project, tool), {"desk": new_desk, "epoch": epoch, "lease_until": moment + LEASE_S,
                                                          "handoff_id": handoff_id, "previous_desk": cond["desk"],
                                                          "took_at": moment})
    except TimeoutError:
        return {"ok": False, "reason": "DESK_LOCK_BUSY"}
    except ValueError as error:  # corrupt conductor record or windows.json: refuse, change nothing
        return {"ok": False, "reason": str(error).split()[0]}
    ledger_ok = True
    try:  # the takeover is already committed; a busy ledger must not turn it into an exception
        append_ledger(project, "TAKEOVER", tool=tool, from_desk=cond["desk"], to_desk=new_desk, epoch=epoch,
                      handoff_id=handoff_id, cards=len(manifest["cards"]))
    except (TimeoutError, OSError):
        ledger_ok = False
    return {"ok": True, "reason": "TAKEN_OVER", "epoch": epoch, "handoff_id": handoff_id, "from_desk": cond["desk"],
            "manifest": str(folder / f"{handoff_id}.json"), "cards": len(manifest["cards"]), "ledger_ok": ledger_ok}


# ---------------------------------------------------------------- notify and ack

def notice_id(handoff_id: str, card: str, tool: str) -> str:
    return "notice_" + hashlib.sha256(f"{handoff_id}|{card}|{tool}".encode()).hexdigest()[:12]


def _notice_text(manifest: dict[str, Any], card: str, handoff_id: str) -> str:
    return (f"[{handoff_id}] Conductor of card {card} changed: desk {manifest['to_desk']} (epoch {manifest['epoch']}) now "
            f"controls you; desk {manifest['from_desk'] or 'none'} no longer dispatches (DESK_SUPERSEDED). Report to the "
            f"new desk. Reply ACK within {int(REPLY_DEADLINE_S)} s; keep working meanwhile.")


def _acks_path(project: Path, handoff_id: str) -> Path:
    return _handoff_dir(project) / f"{handoff_id}.acks.json"


def notify_all(project: Path, handoff_id: str, *, send_session: Sender | None = None, send_letter: Sender | None = None,
               now: float | None = None) -> dict[str, Any]:
    """One notice per (card, tool) session. Claude -> send_session (session messaging), codex/agy -> send_letter
    (`coord deliver`). A missing sender or a failing/slow one is recorded and never blocks the others."""
    project = Path(project)
    manifest = _read_json(_handoff_dir(project) / f"{handoff_id}.json")
    if not manifest:
        return {"ok": False, "reason": "HANDOFF_UNKNOWN"}
    jobs = [(row["card"], s) for row in manifest["cards"] for s in row["sessions"]]
    results: dict[str, str] = {}

    def attempt(card: str, session: dict[str, Any]) -> str:
        nid = notice_id(handoff_id, card, session["tool"])
        sender = send_session if session["tool"] == "claude" else send_letter
        if sender is None:
            return "NO_TRANSPORT"  # nothing claimed: a later run with a transport can still send this notice
        with _locked(project, "desk_notice"):  # claim before sending: a concurrent repeat run sees the claim and skips
            moment = time.time() if now is None else now  # one clock for the stranded check and the claim stamp
            acks = _read_json(_acks_path(project, handoff_id))
            old = acks.get(nid)
            # A SENDING row older than twice the send cap belongs to a crashed runner (the live one finishes within
            # ACK_DEADLINE_S): reclaim it so the notice is not stranded forever. Any other row is a real duplicate.
            stranded = (old is not None and old.get("status") == "SENDING"
                        and moment - float(old.get("sent_at", 0.0)) > 2 * ACK_DEADLINE_S)  # same clock as sent_at below
            if old is not None and not stranded:
                return "DUPLICATE_SKIPPED"
            acks[nid] = {"card": card, "tool": session["tool"], "window_id": session["window_id"], "status": "SENDING",
                         "signals": [], "sent_at": moment}
            _write_json(_acks_path(project, handoff_id), acks)
        box: dict[str, Any] = {}

        def call() -> None:
            try:
                box["ok"] = bool(sender({"card": card, **session}, _notice_text(manifest, card, handoff_id)))
            except Exception as error:  # a broken transport must not stop the other cards
                box["error"] = type(error).__name__

        # A daemon thread, not a pool: a stuck sender must not hold the interpreter's exit (pool threads are joined).
        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(timeout=ACK_DEADLINE_S)
        if worker.is_alive():
            status = "ACK_TIMEOUT"
        elif "error" in box:
            status = f"SEND_ERROR_{box['error']}"
        else:
            status = "SENT" if box.get("ok") else "SEND_FAILED"
        with _locked(project, "desk_notice"):
            acks = _read_json(_acks_path(project, handoff_id))
            acks[nid] = {**acks[nid], "status": status}
            _write_json(_acks_path(project, handoff_id), acks)
        return status

    with ThreadPoolExecutor(max_workers=max(1, min(8, len(jobs)))) as pool:  # parallel: one slow card never delays another
        futures = {pool.submit(attempt, card, s): (card, s["tool"]) for card, s in jobs}
        for future, key in futures.items():
            results[f"{key[0]}:{key[1]}"] = future.result()
    try:  # notices are already sent and persisted: a busy ledger must not turn that into a raised error
        append_ledger(project, "NOTIFIED", handoff_id=handoff_id, results=results)
        ledger_ok = True
    except (TimeoutError, OSError):
        ledger_ok = False
    return {"ok": True, "reason": "NOTIFIED", "handoff_id": handoff_id, "results": results, "ledger_ok": ledger_ok}


def record_ack(project: Path, handoff_id: str, card: str, tool: str, signal: str) -> dict[str, Any]:
    """Second-signal rule: ACKED only after two distinct signals (e.g. `reply`, `window_active`). A repeated signal is
    idempotent, so a duplicated reply never counts twice."""
    if not isinstance(signal, str) or not signal.strip():
        return {"ok": False, "reason": "SIGNAL_INVALID"}
    signal = signal.strip().lower()  # "reply" and " Reply " are one signal, never two
    nid = notice_id(handoff_id, card, tool)
    with _locked(project, "desk_notice"):
        acks = _read_json(_acks_path(project, handoff_id))
        row = acks.get(nid)
        if not row:
            return {"ok": False, "reason": "NOTICE_UNKNOWN"}
        signals = sorted(set(row.get("signals", [])) | {signal})
        row["signals"] = signals
        row["acked"] = len(signals) >= ACK_SIGNALS_NEEDED
        acks[nid] = row
        _write_json(_acks_path(project, handoff_id), acks)
    return {"ok": True, "acked": row["acked"], "signals": signals}


def ack_summary(project: Path, handoff_id: str, *, now: float | None = None) -> dict[str, Any]:
    """ACKED / PENDING (inside the reply window) / UNCONFIRMED (window passed without two signals). Never waits."""
    moment = time.time() if now is None else now
    acks = _read_json(_acks_path(project, handoff_id))
    out: dict[str, str] = {}
    for row in acks.values():
        if row.get("acked"):
            state = "ACKED"
        elif moment - float(row.get("sent_at", 0.0)) <= REPLY_DEADLINE_S:
            state = "PENDING"
        else:
            state = "UNCONFIRMED"
        out[f"{row['card']}:{row['tool']}"] = state
    return {"handoff_id": handoff_id, "states": out}


def run_handoff(project: Path, tool: str, *, states: dict[str, str] | None = None, send_session: Sender | None = None,
                send_letter: Sender | None = None, manifest_args: dict[str, Any] | None = None,
                now: float | None = None) -> dict[str, Any]:
    """detect -> takeover -> notify, never blocking past the deadlines. The CLI entry and the hook call this."""
    found = detect_new_desk(project, tool, now=now)
    if not found["due"]:
        return {"ok": True, "reason": found["reason"], "epoch": found["epoch"]}
    won = takeover(project, tool, found["new_desk"], expected_epoch=found["epoch"], states=states,
                   manifest_args=manifest_args, now=now)
    if not won["ok"] or won["reason"] == "ALREADY_CONDUCTOR":
        return won
    sent = notify_all(project, won["handoff_id"], send_session=send_session, send_letter=send_letter, now=now)
    return {**won, "notified": sent.get("results", {})}
