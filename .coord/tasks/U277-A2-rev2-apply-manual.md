```contract
work_id: U277-A2
worker: apply
goal: Apply the U277 rev 2 request registry and wiring (design docs/U277_verdict-wait-wake-gap-redesign.md), already judged 14/14 by the frozen judge v2 gate
inputs:
- v7_harness/coord/deliver.py sha256=23e43ae54243f2c5e1b7147688dabe682bf526d0302924d50d42f50912def565
- v7_harness/coord/watch.py sha256=eb025bee8f5b1d86e61808acfb0a7ebb02d0a9dc24059c1cee0f72b086e67bfe
- v7_harness/coord/stop_gate.py sha256=e022b1df68f97732adedb623c237de23e941ad289c7c768bd40aa62edb99282e
- v7_harness/coord/stall.py sha256=e7a28d3a609683439429d09fa6fe6859892744135bc1b043a3cee88bf761a9a6
allow:
- v7_harness/coord/requests.py
- v7_harness/coord/deliver.py
- v7_harness/coord/watch.py
- v7_harness/coord/stop_gate.py
- v7_harness/coord/stall.py
- tests/test_u277_request_wake.py
acceptance: python "D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.claude/worktrees/unapproved-nonstop-orchestration-903a95/.work/u277/judge_v2_test.py"
forbidden: design changes; edits outside allow; editing judge tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
apply_after: U277-L1
```

## Instructions for the worker

Apply the FILE blocks below exactly. Ollama slice U277-L1 failed SPLICE twice (same cause as U275-R8-L1); Haiku 5.5 wrote these files as the escalation and Antigravity judged them PASS (relay_b40e55f2).

===FILE: v7_harness/coord/requests.py===
"""U277 rev 2: the durable verdict-request registry (docs/U277_verdict-wait-wake-gap-redesign.md sections 5.1-5.6).

`deliver --verdict-requested` registers a request under its message id before any publish or dispatch. Only an answer
that names `request:<id>` (or an in-reply-to letter from the target) closes the wait. A fuzzy match is a hint that
never closes it. Every state change is a compare-and-set on `rev` under `requests/<id>.lock` and a whole-file atomic
replace. A wake is at-least-once; `ack` is the only close and it is idempotent.

Records live in `shared_desk(project)/.coord/requests/<id>.json` (a linked worktree shares the main desk, U59).
ACKED and CANCELLED records move to `requests/closed/`; nothing is deleted.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from v7_harness.coord import stream
from v7_harness.coord.presence import replace_with_retry

PENDING_DELIVERY = "PENDING_DELIVERY"
OPEN = "OPEN"
ANSWER_OBSERVED = "ANSWER_OBSERVED"
WAKE_PENDING = "WAKE_PENDING"
ACKED = "ACKED"
CANCELLED = "CANCELLED"
EXPIRED = "EXPIRED"
DELIVERY_FAILED = "DELIVERY_FAILED"
OPEN_STATES = (PENDING_DELIVERY, OPEN, ANSWER_OBSERVED, WAKE_PENDING)
# Exact answers are read only while the request still waits for its answer.
WAITING_STATES = (PENDING_DELIVERY, OPEN)
ANSWER_KINDS = ("VERDICT", "BLOCKED", "HANDOFF")
VERDICT_OUTCOMES = ("PASS", "REVISE", "FAIL")
DELIVERIES = ("DISPATCHED", "QUEUED")
REQUEST_TTL_S = 7 * 24 * 3600.0  # the weekly limit window; expiry is not an answer
WAKE_LEASE_S = 1800.0  # one cache lifetime
RECONCILE_WINDOW_S = 600.0  # two dispatch timeouts (DISPATCH_TIMEOUT_S = 300 s)
SKEW_S = 300.0  # clock skew tolerance for hints; exact answers are never time-filtered
LOCK_WAIT_S = 10.0
LOCK_STALE_S = 30.0
BINDING_FIELDS = ("request_id", "project_root", "repo", "requester", "requester_session", "target", "card",
                  "subject", "head")
_ID_RE = re.compile(r"[A-Za-z0-9_.-]+")
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_PR_NUMBER_RE = re.compile(r"/pull/(\d+)")
# Per-process caches. Archive files are immutable; letters are cached by mtime.
_ARCHIVE_CACHE: dict[str, tuple[tuple[int, int], list[dict[str, Any]]]] = {}
_LETTER_CACHE: dict[str, tuple[float, tuple[str, str, str] | None]] = {}


class RequestError(Exception):
    """A refused transition. `code` is the stable reason name (REQUEST_ID_CONFLICT, ACK_SESSION_MISMATCH, ...)."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def _now(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _desk(project: Path) -> Path:
    # U59: a linked worktree shares the main checkout's desk, the same root the stream uses.
    from v7_harness.coord.hook_context import shared_desk

    return shared_desk(Path(project))


def _base(project: Path) -> Path:
    return _desk(project) / ".coord" / "requests"


def _safe_id(request_id: str) -> str:
    text = str(request_id or "")
    if not _ID_RE.fullmatch(text) or text in (".", ".."):
        raise RequestError("REQUEST_ID_INVALID", repr(request_id))
    return text


def _path(project: Path, request_id: str, *, closed: bool = False) -> Path:
    base = _base(project) / "closed" if closed else _base(project)
    return base / f"{_safe_id(request_id)}.json"


def _process_created(pid: Any) -> int | None:
    from v7_harness.coord.watch import process_identity

    return process_identity(pid) if isinstance(pid, int) and not isinstance(pid, bool) else None


def _load(path: Path) -> dict[str, Any] | None:
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return row if isinstance(row, dict) else None


def _write(path: Path, row: dict[str, Any]) -> None:
    """Whole-file atomic replace: a reader sees the old record or the new one, never a torn one."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        replace_with_retry(tmp, path)
    except OSError as exc:
        raise RequestError("REQUEST_TRACKING_FAILED", str(exc)) from exc


def _lock_is_stale(path: Path) -> tuple[bool, str]:
    """(stale, raw text). A lock is stale when its owner is dead or it is older than LOCK_STALE_S."""
    try:
        raw = path.read_text(encoding="utf-8")
        age = time.time() - path.stat().st_mtime
    except (OSError, UnicodeDecodeError):
        return False, ""
    if age > LOCK_STALE_S:
        return True, raw
    try:
        record = json.loads(raw)
    except ValueError:
        return False, raw  # being written right now: fresh, wait for it
    if not isinstance(record, dict) or record.get("process_created") is None:
        return False, raw
    created = _process_created(record.get("pid"))
    return created != record.get("process_created"), raw


def _steal_lock(path: Path, observed: str) -> None:
    """Move a stale lock aside atomically, then remove it. If the moved file is not the stale one we read (a fresh
    lock was created in between), it is put back, so a live owner keeps its lock."""
    graveyard = path.with_name(f"{path.name}.stale.{uuid.uuid4().hex}")
    try:
        os.replace(path, graveyard)
    except OSError:
        return
    try:
        moved = graveyard.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        moved = ""
    if moved == observed:
        _unlink(graveyard)
        return
    try:
        os.replace(graveyard, path)
    except OSError:
        _unlink(graveyard)


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _release_lock(path: Path) -> None:
    """Remove our own lock file. On Windows a concurrent reader of the file (a waiting locker reading its owner) blocks
    the unlink for a moment, so retry briefly; a lock left behind would stall every other writer for LOCK_WAIT_S."""
    for _ in range(200):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.005)


@contextmanager
def _locked(project: Path, request_id: str) -> Iterator[None]:
    """Per-request O_EXCL lock with stale-owner recovery. Never nested for the same id."""
    base = _base(project)
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RequestError("REQUEST_TRACKING_FAILED", str(exc)) from exc
    path = base / f"{_safe_id(request_id)}.lock"
    owner = json.dumps({"pid": os.getpid(), "process_created": _process_created(os.getpid()),
                        "token": uuid.uuid4().hex, "at": time.time()})
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):
            # Windows reports PermissionError while a previous owner is deleting the lock file.
            if time.monotonic() > deadline:
                raise RequestError("REQUEST_LOCKED", request_id)
            stale, observed = _lock_is_stale(path)
            if stale:
                _steal_lock(path, observed)
            time.sleep(0.005)
        except OSError as exc:
            raise RequestError("REQUEST_TRACKING_FAILED", str(exc)) from exc
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(owner)
        yield
    finally:
        _release_lock(path)


def _project_root(project: Path) -> str:
    return str(_desk(project).resolve())


def _binding_hash(binding: dict[str, Any]) -> str:
    text = json.dumps({key: binding[key] for key in BINDING_FIELDS}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _check_session(row: dict[str, Any], session: str | None, code: str) -> None:
    want = str(row.get("requester_session") or "")
    if want and str(session or "") != want:
        raise RequestError(code, f"{row.get('request_id')} belongs to another session")


def _mutate(project: Path, request_id: str, fn: Callable[[dict[str, Any]], dict[str, Any] | None],
            *, archive: bool = False) -> tuple[dict[str, Any], bool]:
    """Compare-and-set: `fn` sees the current row under the lock and returns the new row, or None for no change.

    Returns (row after the call, changed). A row already archived to closed/ is passed to `fn` as a read-only copy.
    """
    with _locked(project, request_id):
        path = _path(project, request_id)
        row = _load(path)
        if row is None:
            settled = _load(_path(project, request_id, closed=True))
            if settled is None:
                raise RequestError("REQUEST_NOT_FOUND", request_id)
            fn(dict(settled))  # may raise a refusal (session mismatch); writes nothing
            return settled, False
        new = fn(dict(row))
        if new is None:
            return row, False
        new["rev"] = int(row.get("rev", 0)) + 1
        new["updated_at"] = time.time()
        if archive and new.get("state") in (ACKED, CANCELLED):
            _write(_path(project, request_id, closed=True), new)
            _unlink(path)
        else:
            _write(path, new)
        return new, True


def register(project: Path, *, request_id: str, requester: str, target: str, card: str, subject: str = "",
             head: str = "", requester_session: str = "", repo: str = "", now: float | None = None) -> dict[str, Any]:
    """Durably record a verdict request before anything is sent. Same id and binding: no-op. Different: refused."""
    _safe_id(request_id)
    moment = _now(now)
    binding = {"request_id": request_id, "project_root": _project_root(project), "repo": repo or "",
               "requester": requester, "requester_session": requester_session or "", "target": target,
               "card": card or "", "subject": subject or "", "head": (head or "").strip().lower()}
    digest = _binding_hash(binding)
    with _locked(project, request_id):
        for closed in (False, True):
            current = _load(_path(project, request_id, closed=closed))
            if current is not None:
                if current.get("binding_hash") != digest:
                    raise RequestError("REQUEST_ID_CONFLICT", request_id)
                return current
        row = {**binding, "created_at": moment, "updated_at": moment, "binding_hash": digest,
               "state": PENDING_DELIVERY, "delivery": "", "rev": 1, "answer_ref": "", "outcome": "",
               "observed_at": None, "waker": None, "claimed_at": None, "hints": []}
        _write(_path(project, request_id), row)
        return row


def mark_delivered(project: Path, request_id: str, delivery: str) -> dict[str, Any]:
    """PENDING_DELIVERY -> OPEN with the delivery fact. A request already answered keeps its state."""
    if delivery not in DELIVERIES:
        raise ValueError(f"unknown delivery: {delivery}")

    def fn(row: dict[str, Any]) -> dict[str, Any] | None:
        if row.get("state") == PENDING_DELIVERY or (row.get("state") == OPEN and row.get("delivery") != delivery):
            row["state"], row["delivery"] = OPEN, delivery
            return row
        return None

    return _mutate(project, request_id, fn)[0]


def get(project: Path, request_id: str) -> dict[str, Any] | None:
    try:
        return _load(_path(project, request_id)) or _load(_path(project, request_id, closed=True))
    except RequestError:
        return None


def open_request(project: Path, *, requester: str, target: str, card: str = "", refs: Any = (), message_id: str,
                 now: float | None = None, requester_session: str = "") -> dict[str, Any]:
    """Rev 1 entry name, kept for its callers: `register` with the subject (a PR URL) and head (a 40-hex sha) read from
    `refs`. The request starts PENDING_DELIVERY, which still holds the turn end and still waits for its answer."""
    texts = [str(ref).strip() for ref in refs or []]
    subject = next((text for text in texts if _PR_NUMBER_RE.search(text)), "")
    head = next((text.lower() for text in texts if _SHA_RE.fullmatch(text.lower())), "")
    return register(project, request_id=message_id, requester=requester, target=target, card=card, subject=subject,
                    head=head, requester_session=requester_session, now=now)


def open_requests(project: Path, requester: str) -> list[dict[str, Any]]:
    """Rev 1 name: the non-terminal requests of `requester` (any session)."""
    return open_for(project, requester)


def _rows(project: Path) -> list[dict[str, Any]]:
    base = _base(project)
    if not base.is_dir():
        return []
    return [row for row in (_load(path) for path in sorted(base.glob("*.json"))) if row is not None]


def open_for(project: Path, requester: str, session: str | None = None) -> list[dict[str, Any]]:
    """Non-terminal requests of `requester`; with `session`, only those bound to it (or bound to no session)."""
    found = []
    for row in _rows(project):
        if row.get("requester") != requester or row.get("state") not in OPEN_STATES:
            continue
        bound = str(row.get("requester_session") or "")
        if session and bound and bound != session:
            continue
        found.append(row)
    return found


def answered(project: Path) -> list[dict[str, Any]]:
    """Requests whose answer is seen but whose wake is not yet acknowledged: ANSWER_OBSERVED (unclaimed) and
    WAKE_PENDING (claimed; reclaimable once its waker is dead or its lease ended). A watch retries these on every scan,
    so an answer whose watcher died before acknowledging is never lost (at-least-once)."""
    return [row for row in _rows(project) if row.get("state") in (ANSWER_OBSERVED, WAKE_PENDING)]


def dispatched_open(project: Path) -> list[dict[str, Any]]:
    """OPEN requests whose letter was dispatched: the stall scan counts these as waits (U277 H2)."""
    return [row for row in _rows(project) if row.get("state") == OPEN and row.get("delivery") == "DISPATCHED"]


def _delivery_location(desk: Path, request_id: str) -> str:
    box = desk / ".coord" / "mailbox"
    if (box / "delivery" / "accepted" / f"{request_id}.json").is_file():
        return "DISPATCHED"
    if any((box / "delivery" / "queued").glob(f"*/{request_id}.json")) or (box / "inbox" / f"{request_id}.json").is_file():
        return "QUEUED"  # a letter in the inbox is delivered: it waits there for the target's next turn
    return ""


def reconcile(project: Path, now: float | None = None) -> list[dict[str, Any]]:
    """PENDING_DELIVERY -> OPEN from the mailbox receipts; DELIVERY_FAILED without a letter after the window;
    OPEN -> EXPIRED after REQUEST_TTL_S. Returns the transitions made."""
    moment = _now(now)
    desk = _desk(project)
    changes: list[dict[str, Any]] = []
    for row in _rows(project):
        request_id, state = str(row.get("request_id")), row.get("state")
        age = moment - float(row.get("created_at") or moment)
        if state == PENDING_DELIVERY:
            location = _delivery_location(desk, request_id)
            if location:
                def fn(cur: dict[str, Any], _loc: str = location) -> dict[str, Any] | None:
                    if cur.get("state") != PENDING_DELIVERY:
                        return None
                    cur["state"], cur["delivery"] = OPEN, _loc
                    return cur
            elif age > RECONCILE_WINDOW_S:
                def fn(cur: dict[str, Any]) -> dict[str, Any] | None:
                    if cur.get("state") != PENDING_DELIVERY:
                        return None
                    cur["state"] = DELIVERY_FAILED
                    return cur
            else:
                continue
        elif state == OPEN and age > REQUEST_TTL_S:
            def fn(cur: dict[str, Any]) -> dict[str, Any] | None:
                if cur.get("state") != OPEN:
                    return None
                cur["state"] = EXPIRED
                return cur
        else:
            continue
        new, changed = _mutate(project, request_id, fn)
        if changed:
            changes.append({"request_id": request_id, "state": new["state"], "delivery": new.get("delivery", "")})
    return changes


def _answer_outcome(event: dict[str, Any]) -> str | None:
    """The outcome an event gives a request, or None when it is not an answer (design 5.1)."""
    evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
    outcome = evidence.get("outcome")
    kind = event.get("kind")
    if kind == "BLOCKED":
        return outcome if isinstance(outcome, str) and outcome else "BLOCKED"
    if kind == "VERDICT":
        return outcome if outcome in VERDICT_OUTCOMES else None
    if kind == "HANDOFF":
        return outcome if isinstance(outcome, str) and outcome.strip() else None
    return None


def _read_jsonl(path: Path, *, cache: bool) -> list[dict[str, Any]]:
    try:
        stat = path.stat()
    except OSError:
        return []
    key = (stat.st_size, stat.st_mtime_ns)
    if cache:
        hit = _ARCHIVE_CACHE.get(str(path))
        if hit is not None and hit[0] == key:
            return hit[1]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn or corrupt line is skipped, never fatal
        if isinstance(row, dict):
            rows.append(row)
    if cache:
        _ARCHIVE_CACHE[str(path)] = (key, rows)
    return rows


def _stream_events(project: Path) -> list[dict[str, Any]]:
    """Every event in the live and archived stream files, ordered by (file name, line index), never by ts."""
    folder = stream.stream_dir(Path(project))
    if not folder.is_dir():
        return []
    files = [(path, False) for path in folder.glob("*.jsonl") if path.is_file()]
    archive = folder / "archive"
    if archive.is_dir():
        files.extend((path, True) for path in archive.glob("*.jsonl") if path.is_file())
    events: list[dict[str, Any]] = []
    for path, is_archive in sorted(files, key=lambda item: item[0].name):
        events.extend(_read_jsonl(path, cache=is_archive))
    return events


def _event_epoch(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return _dt.datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def _exact_stream_answer(row: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
    ref = f"request:{row['request_id']}"
    for event in events:
        refs = event.get("refs") if isinstance(event.get("refs"), list) else []
        if event.get("actor") != row.get("target") or ref not in refs:
            continue
        outcome = _answer_outcome(event)
        if outcome is not None:
            return {"ref": str(event.get("id") or ""), "outcome": outcome}
    return None


def _letter_reply(path: Path) -> tuple[str, str, str] | None:
    """(in_reply_to, actor, outcome) of a letter that answers another letter, cached by mtime."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    hit = _LETTER_CACHE.get(str(path))
    if hit is not None and hit[0] == mtime:
        return hit[1]
    result = None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        record = None
    payload = record.get("payload") if isinstance(record, dict) else None
    if isinstance(payload, dict) and isinstance(payload.get("in_reply_to"), str) and payload["in_reply_to"]:
        outcome = payload.get("outcome")
        result = (payload["in_reply_to"], str(payload.get("actor") or ""),
                  outcome if isinstance(outcome, str) and outcome else "REPLIED")
    _LETTER_CACHE[str(path)] = (mtime, result)
    return result


def _letter_answer(project: Path, row: dict[str, Any], replies: dict[str, list[tuple[str, str, str]]]) -> dict[str, Any] | None:
    for letter_id, actor, outcome in replies.get(str(row["request_id"]), []):
        if actor == row.get("target"):
            return {"ref": letter_id, "outcome": outcome}
    return None


def _letter_replies(project: Path, since: float) -> dict[str, list[tuple[str, str, str]]]:
    """in_reply_to -> [(letter id, actor, outcome)] for inbox and acked letters written at or after `since`."""
    box = _desk(project) / ".coord" / "mailbox"
    replies: dict[str, list[tuple[str, str, str]]] = {}
    for folder in (box / "inbox", box / "ack"):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            try:
                if path.stat().st_mtime < since:
                    continue
            except OSError:
                continue
            reply = _letter_reply(path)
            if reply is not None:
                replies.setdefault(reply[0], []).append((path.stem, reply[1], reply[2]))
    return replies


def _pr_pattern(subject: str) -> re.Pattern[str] | None:
    match = _PR_NUMBER_RE.search(subject or "")
    if not match:
        return None
    return re.compile(rf"(?:PR ?#?|#|pull/){match.group(1)}(?!\d)")


def _hint_matches(event: dict[str, Any], row: dict[str, Any]) -> bool:
    """Advisory only: the same target says something about this card, PR or head. Never closes the request."""
    if event.get("actor") != row.get("target"):
        return False
    refs = [str(ref) for ref in event.get("refs") or [] if isinstance(ref, str)]
    if any(ref.startswith("request:") for ref in refs):
        return False
    moment = _event_epoch(event.get("ts"))
    if moment is None or moment < float(row.get("created_at") or 0) - SKEW_S:
        return False
    card = str(row.get("card") or "")
    if card and str(event.get("step") or "") == card:
        return True
    text = " ".join([str(event.get("summary") or ""), *refs]).lower()
    pattern = _pr_pattern(str(row.get("subject") or ""))
    if pattern is not None and pattern.search(text):
        return True
    head = str(row.get("head") or "")
    return len(head) >= 7 and head[:7] in text


def scan(project: Path, now: float | None = None) -> list[dict[str, Any]]:
    """Move waiting requests to ANSWER_OBSERVED on an exact answer; record new hints. Returns the transitions.

    Exact: an event (or inbox letter) from the target that names `request:<id>` and carries an outcome.
    Hint: advisory fuzzy match; the request stays where it is and each (request, event) hints once.
    """
    moment = _now(now)
    reconcile(project, now=moment)
    rows = [row for row in _rows(project) if row.get("state") in WAITING_STATES]
    if not rows:
        return []
    events = _stream_events(project)
    since = min(float(row.get("created_at") or moment) for row in rows) - SKEW_S
    replies = _letter_replies(project, since)
    transitions: list[dict[str, Any]] = []
    for snapshot in rows:
        request_id = str(snapshot["request_id"])
        answer = _exact_stream_answer(snapshot, events) or _letter_answer(project, snapshot, replies)
        if answer is not None:
            def answered(cur: dict[str, Any], _ans: dict[str, Any] = answer) -> dict[str, Any] | None:
                if cur.get("state") not in WAITING_STATES:
                    return None
                cur.update(state=ANSWER_OBSERVED, answer_ref=_ans["ref"], outcome=_ans["outcome"], observed_at=moment)
                return cur

            _new, changed = _mutate(project, request_id, answered)
            if changed:
                transitions.append({"type": "ANSWER", "request_id": request_id, "event_id": answer["ref"],
                                    "outcome": answer["outcome"], "requester": snapshot.get("requester"),
                                    "requester_session": snapshot.get("requester_session") or ""})
            continue
        seen = set(snapshot.get("hints") or [])
        fresh = [event for event in events if event.get("id") and event["id"] not in seen
                 and _hint_matches(event, snapshot)]
        if not fresh:
            continue

        def hinted(cur: dict[str, Any], _fresh: list[dict[str, Any]] = fresh) -> dict[str, Any] | None:
            if cur.get("state") not in WAITING_STATES:
                return None
            known = set(cur.get("hints") or [])
            added = [event["id"] for event in _fresh if event["id"] not in known]
            if not added:
                return None
            cur["hints"] = [*(cur.get("hints") or []), *added]
            return cur

        new, changed = _mutate(project, request_id, hinted)
        if changed:
            known_before = set(snapshot.get("hints") or [])
            for event in fresh:
                if event["id"] not in known_before:
                    transitions.append({"type": "HINT", "request_id": request_id, "event_id": event["id"],
                                        "requester": snapshot.get("requester"),
                                        "requester_session": snapshot.get("requester_session") or ""})
    return transitions


def _reclaimable(row: dict[str, Any], moment: float, started_at: float | None) -> bool:
    """A WAKE_PENDING claim that another watcher may take over: its lease ended, or its waker died after the claim
    and this watcher started after that claim. A watcher that was already running when the claim was made is a sibling
    that is still waiting, so it never re-wakes for a waker that merely exited (one wake per claim)."""
    waker = row.get("waker")
    if not isinstance(waker, dict):
        return True
    lease = waker.get("lease_until")
    if isinstance(lease, (int, float)) and not isinstance(lease, bool) and lease <= moment:
        return True
    created = _process_created(waker.get("pid"))
    if created is not None and created == waker.get("process_created"):
        return False
    claimed = row.get("claimed_at")
    if started_at is None or not isinstance(claimed, (int, float)) or isinstance(claimed, bool):
        return True
    return started_at > claimed


def claim_wake(project: Path, request_id: str, *, session: str, now: float | None = None,
               started_at: float | None = None) -> bool:
    """CAS ANSWER_OBSERVED -> WAKE_PENDING for one watcher. True only for the claimant that moved the record."""
    moment = _now(now)

    def fn(cur: dict[str, Any]) -> dict[str, Any] | None:
        wanted = str(cur.get("requester_session") or "")
        if wanted and session and session != wanted:
            return None
        if cur.get("state") == ANSWER_OBSERVED or (cur.get("state") == WAKE_PENDING
                                                   and _reclaimable(cur, moment, started_at)):
            pid = os.getpid()
            cur.update(state=WAKE_PENDING, claimed_at=moment, waker={
                "pid": pid, "process_created": _process_created(pid), "session": session or "",
                "lease_until": moment + WAKE_LEASE_S})
            return cur
        return None

    try:
        _row, changed = _mutate(project, request_id, fn)
    except RequestError:
        return False
    return changed


def _settle(project: Path, request_id: str, session: str | None, *, states: tuple[str, ...], result: str,
            code: str) -> str:
    """Shared body of ack and cancel: session check, idempotent terminal, archive on success."""
    outcome: dict[str, str] = {}

    def fn(cur: dict[str, Any]) -> dict[str, Any] | None:
        _check_session(cur, session, code)
        if cur.get("state") in (ACKED, CANCELLED):
            outcome["out"] = "ALREADY"
            return None
        if cur.get("state") not in states:
            raise RequestError("REQUEST_NOT_ANSWERED", f"{request_id} is {cur.get('state')}")
        cur["state"] = result
        cur["settled_at"], cur["settled_session"] = time.time(), str(session or "")
        outcome["out"] = result
        return cur

    _mutate(project, request_id, fn, archive=True)
    return outcome.get("out", "ALREADY")


def ack(project: Path, request_id: str, session: str) -> str:
    """ACKED after the answer was observed. Idempotent; a foreign session is refused (ACK_SESSION_MISMATCH)."""
    return _settle(project, request_id, session, states=(ANSWER_OBSERVED, WAKE_PENDING, EXPIRED, DELIVERY_FAILED),
                   result=ACKED, code="ACK_SESSION_MISMATCH")


def cancel(project: Path, request_id: str, session: str) -> str:
    """CANCELLED by the requester only; the record is archived, not deleted."""
    return _settle(project, request_id, session, states=(PENDING_DELIVERY, OPEN, ANSWER_OBSERVED, WAKE_PENDING),
                   result=CANCELLED, code="CANCEL_SESSION_MISMATCH")


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m v7_harness.coord.requests")
    parser.add_argument("--project", default=".", help="any folder of the project (a worktree shares the desk)")
    commands = parser.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list")
    listing.add_argument("--requester", default="")
    for name in ("ack", "cancel"):
        sub = commands.add_parser(name)
        sub.add_argument("--id", required=True)
        sub.add_argument("--session", required=True)
    commands.add_parser("reconcile")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    try:
        if args.command == "list":
            rows = [row for row in _rows(project) if not args.requester or row.get("requester") == args.requester]
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        elif args.command == "ack":
            print(ack(project, args.id, args.session))
        elif args.command == "cancel":
            print(cancel(project, args.id, args.session))
        else:
            print(json.dumps(reconcile(project), ensure_ascii=False))
    except RequestError as exc:
        print(json.dumps({"error": exc.code, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
===FILE: v7_harness/coord/deliver.py===
"""coord deliver: 도구 간 직접 전달기 — 사용자 수동 릴레이 영구 제거.

근본 결함(2026-09-27 사용자 지적):
  사서함(mailbox)에 메시지를 넣은 뒤 사용자에게 "전달해달라"고 부탁하는 것은
  UAOS의 존재 이유를 부정하는 설계 결함이다.

해결:
  수신 도구를 자동 판별하여 직접 전달한다.
  - Codex ACTIVE → `codex queue --thread <session> --message <text>`
  - Claude ACTIVE → `claude -p "<text>" --allowedTools "Read" --output-format json`
  - 둘 다 부재 → 사서함에만 보존(사용자 릴레이 요청 금지)

불변식:
  1. 사용자에게 "전달해달라", "붙여넣기해달라" 등의 릴레이를 요청하지 않는다.
  2. 전달 실패 시 사서함에 보존하고, 실패 사실만 보고한다.
  3. 비밀(secret)은 전달하지 않는다.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from v7_harness.coord.stream import SECRET_PATTERNS, _try_lock, _unlock
from v7_harness.coord.mailbox import Mailbox


AGY_APP_HOME_ENV = "UAOS_AGY_APP_HOME"  # tests point this at a fixture; default ~/.gemini/antigravity


REPLACE_TRIES = 20  # Windows refuses os.replace while another process replaces the same file; 20 x 50 ms = 1 s


@dataclass(frozen=True)
class DeliverResult:
    delivered: bool
    target: str          # "codex" | "claude" | "mailbox_only"
    reason: str          # SENT | CLI_NOT_FOUND | DELIVERY_FAILED | ABSENT_ALL | ...
    command: tuple[str, ...]
    output: str
    message_id: str = ""
    digest: str = ""
    receipt: str = ""


# U64-F (Claude acting, 2026-09-28): whole tokens only. Substrings woke a paid cold turn for "inbox 140 (P1 0)",
# "STEP1" and "no ACTIONABLE_DELTA since last"; an ACK_ONLY marker always wins.
_TOKEN = r"(?<![A-Z0-9_=]){}(?![A-Z0-9_])"
_ACK_RE = re.compile(_TOKEN.format("ACK_ONLY"))
_NEGATED_RE = re.compile(r"\b(?:NO|NOT|WITHOUT|NON)[\s-]+(?:ACTIONABLE_DELTA|VERDICT_REQUESTED)\b")
_WAKE_RES = tuple(re.compile(_TOKEN.format(token)) for token in (
    "ACTIONABLE_DELTA",
    r"VERDICT_REQUESTED(?:=YES|(?!=NO\b|=FALSE\b|=0\b))",
    r"VERDICT[\s:_-]+(?:PASS|REWORK|REVISE|FAIL|APPROVE|PIVOT|ACCEPTED|NOT[\s_]+ACCEPTED)",
    "APPROVAL_REQUIRED",
    r"(?:PRIORITY|SEVERITY|P1)=(?:P1|YES|1)",
    r"READY[\s_]+FOR[\s_]+(?:PEER[\s_]+)?REVIEW",
    r"RECEIPT[\s_]+READY",
))
# U141-B: quoted data is never an instruction. Fenced blocks (``` or ~~~, an unclosed fence runs to the end) go first,
# then "...", curly quotes, 'single' quotes, `code` and "> " reply lines are blanked before the token scan. A single
# quote counts only with no word character outside it, so apostrophes (it's, tools') never open a span (U141-B2 REWORK).
_FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?(?:^[ \t]*\1[^\n]*$|\Z)", re.MULTILINE | re.DOTALL)
_QUOTED_RE = re.compile(r'"[^"\n]*"|“[^”\n]*”|(?<![\w\'])\'[^\'\n]*\'(?!\w)|`[^`\n]*`|^[ \t]*>.*$', re.MULTILINE)
DELTA_LIMIT = 200  # an inferred delta is the hook's one-line summary; the full text stays in `message`
# U188: a verdict a turn-based tool writes only as text never wakes its receiver. 98 of 198 codex->claude letters
# (2026-10-14) carried no waking class (26 NOTICE, 72 untagged without a token), among them the verdicts
# relay_f3fcef63 (REVISE) and relay_1be9792b (NOT ACCEPTED), which left Claude idle holding actionable work. Upper
# case whole tokens only, longest first, so "NOT ACCEPTED" wins over "ACCEPTED" and PASSWORD/BYPASS never match.
_VERDICT_TEXT_RE = re.compile(
    r"(?<![A-Za-z0-9_=-])(?:NOT ACCEPTED|ACCEPTED|PASS|FAIL|REVISE|REWORK|PIVOT|APPROVE|NO-GO)(?![A-Za-z0-9_-])")


def _unstructured_verdict(message: str, target: str | None, wake_class: str | None,
                          verdict_requested: bool | None, verdict: str | None) -> str:
    """U188: the verdict token of a codex/claude letter whose first unquoted line is a verdict without its field."""
    if target not in ("codex", "claude") or verdict is not None or verdict_requested is True \
            or wake_class == "ACTIONABLE":
        return ""
    text = _QUOTED_RE.sub(" ", _FENCE_RE.sub(" ", message))
    if _ACK_RE.search(text.upper()):
        return ""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    found = _VERDICT_TEXT_RE.search(first)
    return found.group(0) if found else ""


def _digest(actor: str, message: str, card: str = "", window: str | None = None,
            target: str | None = None, fields: dict[str, Any] | None = None) -> str:
    # U115: a card letter's id also covers its card and window, so the same text routed to another window is a new
    # letter instead of a mailbox collision; without a card the id is exactly today's.
    key = actor + "\0" + message + (f"\0{card}\0{window or ''}" if card else "")
    # U141-B: every structured field stored in the payload, explicit or inferred, joins the id (v3). A letter stored
    # before inference existed (v2, no fields) and its inferred retry are then two ids, never a collision or a shared
    # ACK (U141-B2 REWORK). Without fields the v2/legacy ids stay exactly as published.
    if fields:
        key = json.dumps(["uaos-relay-v3", actor, message, card, window or "" if card else "", target, fields],
                         ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    # Explicit destination is payload identity; None preserves legacy auto IDs.
    elif target is not None:
        key = json.dumps(["uaos-relay-v2", actor, message, card, window or "" if card else "", target],
                         ensure_ascii=False, separators=(",", ":"))
    if window and not card:
        key = json.dumps(["uaos-relay-native-v1", key, window], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _requires_wake(message: str) -> bool:
    """Only a real delta may spend a paid turn; ACK_ONLY, negated, incidental or quoted tokens never do."""
    upper = _QUOTED_RE.sub(" ", _FENCE_RE.sub(" ", message)).upper()
    if _ACK_RE.search(upper):
        return False
    upper = _NEGATED_RE.sub(" ", upper)
    return any(pattern.search(upper) for pattern in _WAKE_RES)


def _wants_wake(message: str, *, wake_class: str | None = None, verdict: str | None = None,
                verdict_requested: bool | None = None) -> bool:
    if wake_class in ("NOTICE", "ACK_ONLY") or verdict_requested is False or _ACK_RE.search(
            _QUOTED_RE.sub(" ", _FENCE_RE.sub(" ", message)).upper()):
        return False
    if wake_class == "ACTIONABLE" or bool(verdict) or verdict_requested is True:
        return True
    return _requires_wake(message)


# ── 비밀 검사 ────────────────────────────────────────────────
def _check_secrets(text: str) -> None:
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("SECRET_IN_DELIVERY: 비밀이 포함된 메시지는 전달하지 않는다.")


# ── Codex 전달 ───────────────────────────────────────────────
def _project_mailbox(project: Path) -> Mailbox:
    """Use one runtime mailbox per repository while preserving the caller's source worktree separately."""
    from v7_harness.coord.hook_context import shared_desk
    root = shared_desk(Path(project)) / ".coord" / "mailbox"
    root.mkdir(parents=True, exist_ok=True)
    return Mailbox(root)


def _deliver_to_codex(
    message: str,
    thread: str,
    *,
    runner: Any = None,
    timeout: int = 60,
) -> DeliverResult:
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return DeliverResult(False, "codex", "CLI_NOT_FOUND", (), "")

    argv = (codex_bin, "queue", "--thread", thread, "--message", message)
    execute = runner or subprocess.run
    try:
        cp = execute(list(argv), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:{exc}", argv, "")

    if getattr(cp, "returncode", 1) != 0:
        stderr = getattr(cp, "stderr", "") or ""
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:rc={cp.returncode}", argv, stderr[:500])

    return DeliverResult(True, "codex", "SENT", argv, "")


# ── Claude 전달 ──────────────────────────────────────────────
@contextmanager
def _claude_turn(project_dir: Path | None, timeout: int):
    """Serialize messages through the one persisted Claude conversation, including across processes."""
    if project_dir is None:
        yield
        return
    lock = project_dir / ".coord" / "mailbox" / "delivery" / "claude-session.turn.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout + 5
    fd = None
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except PermissionError:
            # U53-F1: on Windows the previous holder's unlink leaves the lock delete-pending for a moment and
            # O_EXCL then raises PermissionError, not FileExistsError (1 of 30 eight-process runs). Wait, do not crash.
            time.sleep(CLAIM_SLEEP_S)
            continue
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > timeout + 30
            except OSError:
                stale = False
            if stale:
                try:
                    os.rename(lock, lock.with_name(f"{lock.name}.stale-{uuid.uuid4().hex}"))
                except OSError:
                    pass
            time.sleep(CLAIM_SLEEP_S)
    if fd is None:
        raise TimeoutError("CLAUDE_TURN_TIMEOUT")
    with os.fdopen(fd, "wb") as handle:
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _deliver_to_claude(
    message: str,
    *,
    project_dir: Path | None = None,
    runner: Any = None,
    timeout: int = 120,
    allowed_tools: tuple[str, ...] = ("Read",),
    session: str = "",
) -> DeliverResult:
    try:
        with _claude_turn(project_dir, timeout):
            return _deliver_to_claude_locked(
                message, project_dir=project_dir, runner=runner, timeout=timeout, allowed_tools=allowed_tools,
                session=session,
            )
    except TimeoutError as exc:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:{exc}", (), "")


def _deliver_to_claude_locked(
    message: str,
    *,
    project_dir: Path | None = None,
    runner: Any = None,
    timeout: int = 120,
    allowed_tools: tuple[str, ...] = ("Read",),
    session: str = "",
) -> DeliverResult:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return DeliverResult(False, "claude", "CLI_NOT_FOUND", (), "")

    session_path: Path | None = None
    session_id = ""
    resume = False
    window_cwd = ""
    if session:  # U115: a card window is an existing session; the default delivery session file is left alone
        from v7_harness.coord.windows import claude_session

        (session_id, window_cwd), resume = claude_session(session), True
    elif project_dir:
        session_path = project_dir / ".coord" / "mailbox" / "delivery" / "claude-session.json"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state = json.loads(session_path.read_text(encoding="utf-8"))
            session_id = str(state.get("session_id") or "")
            resume = bool(state.get("ready"))
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            state = {}
        if not session_id:
            session_id = str(uuid.uuid4())
            initial = (json.dumps({"session_id": session_id, "ready": False}, sort_keys=True) + "\n").encode("utf-8")
            try:
                fd = os.open(str(session_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                state = json.loads(session_path.read_text(encoding="utf-8"))
                session_id = str(state["session_id"])
                resume = bool(state.get("ready"))
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(initial)
                    handle.flush()
                    os.fsync(handle.fileno())

    argv_list = [claude_bin, "-p", message, "--output-format", "json"]
    if session_id:
        argv_list.extend(["--resume" if resume else "--session-id", session_id])
    for tool in allowed_tools:
        argv_list.extend(["--allowedTools", tool])

    execute = runner or subprocess.run
    # Claude emits UTF-8. Windows' locale is CP949 on this host, so text=True without an explicit encoding loses the
    # reply in subprocess' reader thread even when Claude exits successfully.
    kwargs: dict[str, Any] = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if project_dir:
        kwargs["cwd"] = str(project_dir)
    if window_cwd:  # U115 judge: resume where the window's transcript lives (it may have entered a worktree)
        kwargs["cwd"] = window_cwd

    rc = 1
    stdout = ""
    stderr = ""
    retry_argv = argv_list
    for attempt in range(2):
        run_argv = retry_argv if attempt == 1 else argv_list
        try:
            cp = execute(run_argv, **kwargs)
        except (subprocess.TimeoutExpired, OSError) as exc:
            if attempt == 0:
                if session_path and resume:
                    session_path.unlink(missing_ok=True)
                return DeliverResult(False, "claude", f"DELIVERY_FAILED:{exc}", tuple(argv_list), "")
            break
        rc = getattr(cp, "returncode", 1)
        stdout = getattr(cp, "stdout", "") or ""
        stderr = getattr(cp, "stderr", "") or ""
        if attempt == 1:
            argv_list = retry_argv
            if rc == 0 and resume:
                session_path = None
            break
        if rc != 0 and "already in use" in stderr.lower() and session_id and not session:
            fresh_id = str(uuid.uuid4())
            retry_argv = [
                "--session-id" if a == "--resume" else (fresh_id if a == session_id else a)
                for a in argv_list
            ]
            session_id = fresh_id
            continue
        break

    if rc != 0:
        if session_path and (resume or "already in use" in stderr.lower()):
            session_path.unlink(missing_ok=True)
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:rc={rc}", tuple(argv_list), stderr[:500])

    # Claude CLI JSON 응답에서 result 추출
    result_text = ""
    try:
        data = json.loads(stdout)
        if not isinstance(data, dict) or data.get("is_error") or data.get("type") == "error_max_budget_usd":
            return DeliverResult(False, "claude", "DELIVERY_FAILED:UNUSABLE_RESPONSE", tuple(argv_list), stdout[:500])
        result_text = data.get("result", stdout[:500])
    except (json.JSONDecodeError, AttributeError):
        result_text = stdout[:500]

    if session_path and session_id:
        temporary = session_path.with_suffix(f".tmp-{uuid.uuid4().hex}")
        temporary.write_text(json.dumps({"session_id": session_id, "ready": True}, sort_keys=True) + "\n",
                             encoding="utf-8")
        os.replace(temporary, session_path)
    reply = str(result_text)[:2000]
    try:
        _check_secrets(reply)
    except ValueError:
        return DeliverResult(False, "claude", "DELIVERY_FAILED:SECRET_IN_RESPONSE", tuple(argv_list), "")
    return DeliverResult(True, "claude", "SENT", tuple(argv_list), reply)


def _receipt_output(path: Path) -> str:
    """Return a previously persisted reply; malformed receipts fail closed to an empty reply."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("output") or "") if isinstance(data, dict) else ""


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Create one immutable receipt; concurrent attempts get separate names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _clear_owned_pending(path: Path, owner: str | None) -> None:
    """Remove only the direct-dispatch marker owned by this guard winner."""
    if not owner:
        return
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("owner") == owner:
            path.unlink(missing_ok=True)
    except (OSError, ValueError, AttributeError):
        pass


# ── 통합 전달기 ──────────────────────────────────────────────
# Why 300 s: a live dispatcher holds the guard at most for the Claude CLI timeout (120 s) plus receipt writes; 300 s
# gives 2.5x margin so a slow but live dispatcher is never taken for a crashed one.
GUARD_STALE_S = 300.0
# U83 (Codex REJECT of U49-G1R, 2026-09-29): the recovery lock is an OS byte-range lock on `<guard>.recover`, not an
# exclusively created file aged by mtime. The OS drops it when its holder exits or crashes, so nothing ever steals it by
# age: a holder paused for any length of time keeps it, and the file itself is never unlinked, so no caller can delete
# another holder's lock.
# 50 x 20 ms bounds the claim retry at about 1 s, well above the few ms a concurrent publish holds the file open.
CLAIM_TRIES = 50
CLAIM_SLEEP_S = 0.02
# Release waits for the recovery lock at most 5 s: recovery holds it for milliseconds, so 5 s only runs out when a
# recoverer is paused inside it; the guard is then left for stale recovery, which can delay but never double-dispatch.
RELEASE_WAIT_S = 5.0


def _payload(actor: str, message: str, digest: str, target: str | None, card: str = "",
             window: str | None = None, *, wake_class: str | None = None, verdict_requested: bool | None = None,
             verdict: str | None = None, delta: str | None = None, in_reply_to: str = "") -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    body = {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}
    if in_reply_to:  # U277: names the letter this one answers; written only when given (old bytes unchanged)
        body["in_reply_to"] = in_reply_to
    if card:  # U115: only a card letter carries these keys, so a letter without --card keeps today's bytes
        body.update(card=card, window=window)
    elif window and target != "antigravity":  # U214: an explicit native thread binds the letter to that receiver
        # (cause 1); U115 keys stay card-only, and Antigravity's headless auto-reply acks under its own id (relay_2d46a6ae).
        body["native_receiver"] = window
    # U141-A: the structured wake fields the watcher classifies. They are written only when given, so an untagged
    # letter keeps today's bytes and stays LEGACY.
    for key, value in (("wake_class", wake_class), ("verdict_requested", verdict_requested), ("verdict", verdict),
                       ("delta", delta)):
        if value is not None:
            body[key] = value
    return body


def _open_excl(path: Path) -> int | None:
    """Create path exclusively; None if it exists. On Windows a file being unlinked by its holder raises
    PermissionError (delete pending, seen 1 of 50 eight-process runs), so that case is retried, not raised."""
    for _ in range(CLAIM_TRIES):
        try:
            return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return None
        except PermissionError:
            time.sleep(CLAIM_SLEEP_S)
    return None


# U86: the OS lock helpers moved to stream.py, which now locks the same way (imported above).


@contextmanager
def _recover_lock(guard: Path, wait_s: float):
    """Yield True while holding the OS lock on `<guard>.recover`, or False if it was not taken within wait_s."""
    path = guard.with_name(guard.name + ".recover")
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        yield False
        return
    try:
        deadline = time.monotonic() + wait_s
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                yield False
                return
            time.sleep(CLAIM_SLEEP_S)
        try:
            yield True
        finally:
            try:
                _unlock(fd)
            except OSError:
                pass  # close below releases it anyway
    finally:
        os.close(fd)


def _acquire_guard(guard: Path, box: Mailbox, message_id: str, digest: str) -> int | None:
    """Take the per-message dispatch guard, recovering one left by a crashed dispatcher. None means IN_FLIGHT.

    Recovery runs under the OS recovery lock so the age check and the rename cannot interleave with another
    recoverer (otherwise one could rename a guard that another had just re-created). The stale guard is renamed,
    not deleted, and an attempt receipt records the recovery.
    """
    fd = _open_excl(guard)
    if fd is not None:
        return fd
    try:
        if time.time() - guard.stat().st_mtime < GUARD_STALE_S:
            return None
    except OSError:
        pass  # released since (or delete pending on Windows); the exclusive open below decides
    with _recover_lock(guard, 0.0) as held:
        if not held:
            return None  # another recoverer or releaser is working now; this caller's message is already published
        try:
            age = time.time() - guard.stat().st_mtime
        except OSError:
            age = None
        if age is not None:
            if age < GUARD_STALE_S:
                return None  # a live dispatcher re-created it between our checks
            stale = guard.with_name(f"{guard.name}.stale-{uuid.uuid4().hex}")
            os.rename(guard, stale)
            _write_receipt(box.root / "delivery" / "attempts" / f"{message_id}_{uuid.uuid4().hex}.json",
                           {"message_id": message_id, "digest": digest, "state": "GUARD_RECOVERED",
                            "stale_guard": str(stale), "age_s": round(age, 1), "timestamp_ns": time.time_ns()})
        return _open_excl(guard)


def _release_guard(guard: Path, owner: str) -> None:
    """Remove the dispatch guard only if this dispatcher still owns it, under the same lock recovery uses.

    U49-G1R (Codex REJECT of G1, 2026-09-27): an unconditional unlink by a dispatcher that outlived GUARD_STALE_S removed
    the new holder's guard, and G1's owner check alone still let a recovery land between the read and the unlink.
    Holding the recovery lock across compare and unlink makes release and recovery mutually exclusive, because recovery
    ages, renames and re-creates the guard only while holding that lock too.
    """
    with _recover_lock(guard, RELEASE_WAIT_S) as held:
        if not held:
            return  # left for stale recovery: a delay, never a second dispatcher
        data = None
        for _ in range(CLAIM_TRIES):  # a Windows sharing violation is transient; do not strand our own guard
            try:
                data = json.loads(guard.read_text(encoding="utf-8"))
                break
            except PermissionError:
                time.sleep(CLAIM_SLEEP_S)
            except (OSError, ValueError):
                return
        if isinstance(data, dict) and data.get("owner") == owner:
            guard.unlink(missing_ok=True)


def _dispatch_count(attempts: Path, message_id: str) -> int:
    """Count earlier dispatch attempts (DISPATCHED or FAILED) for one message; GUARD_RECOVERED receipts do not count.

    Called while holding the claim, so dispatchers of the same id are serialized and the count cannot race. A receipt
    that cannot be read yet (Windows delete-pending) or is not JSON is still counted: it can only be an attempt.
    U49-D2: valid JSON that is not an object (e.g. a list) is counted the same way instead of raising AttributeError.
    """
    count = 0
    for path in attempts.glob(f"{message_id}_*.json") if attempts.is_dir() else ():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        state = data.get("state") if isinstance(data, dict) else None
        if state != "GUARD_RECOVERED":
            count += 1
    return count


def _codex_sessions() -> Path:
    """U134-D: where Codex writes its rollouts; UAOS_CODEX_SESSIONS (presence.CODEX_SESSIONS_ENV) isolates tests."""
    from v7_harness.coord.presence import CODEX_SESSIONS_ENV
    return Path(os.environ.get(CODEX_SESSIONS_ENV) or (Path.home() / ".codex" / "sessions"))


META_LINE_MAX = 256 * 1024
UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _read_rollout_meta(path: Path) -> tuple[str, Path | None, str]:
    """Read session_id and canonical cwd from rollout file metadata.

    U134-R F1:
    - Bounded read (max 256 KiB bytes).
    - Requires type == 'session_meta' (rejects event_msg).
    - Every present id key (id, session_id) must be a non-empty string; at least one present; all equal.
    - Strict UUID format check and filename suffix check.
    - Returns (chosen_id, canonical_cwd, status).
    """
    try:
        with path.open("rb") as handle:
            raw_line = handle.readline(META_LINE_MAX + 1)
            if not raw_line or len(raw_line) > META_LINE_MAX:
                return "", None, "THREAD_UNVERIFIED"
            line = raw_line.decode("utf-8", errors="replace")
            data = json.loads(line)
    except (OSError, json.JSONDecodeError):
        return "", None, "THREAD_UNVERIFIED"
    if not isinstance(data, dict) or data.get("type") != "session_meta":
        return "", None, "THREAD_UNVERIFIED"
    payload = data.get("payload")
    if not isinstance(payload, dict):
        return "", None, "THREAD_UNVERIFIED"

    present_ids: list[str] = []
    for key in ("id", "session_id"):
        if key in payload:
            val = payload[key]
            if not isinstance(val, str) or not val.strip():
                return "", None, "THREAD_UNVERIFIED"
            present_ids.append(val.strip())

    if not present_ids:
        return "", None, "THREAD_UNVERIFIED"

    first = present_ids[0]
    if any(pid.lower() != first.lower() for pid in present_ids):
        return "", None, "THREAD_UNVERIFIED"

    chosen_id = first
    if not UUID_RE.fullmatch(chosen_id):
        return "", None, "THREAD_UNVERIFIED"
    if not path.name.lower().endswith(f"-{chosen_id.lower()}.jsonl"):
        return "", None, "THREAD_UNVERIFIED"
    if "cwd" in payload:
        cwd_val = payload["cwd"]
        if not isinstance(cwd_val, str) or not cwd_val.strip():
            return "", None, "THREAD_UNVERIFIED"
        cwd = Path(cwd_val).resolve()
    else:
        cwd = None
    return chosen_id, cwd, "OK"


def _registered_roots(project: Path) -> set[str]:
    """Return canonical checkouts belonging to this repository, including git worktrees.

    U134-R F1:
    - Resolves linked worktree back to main repository without subprocess.
    - Resolves <main>/.git/worktrees/*/gitdir and verifies back-pointers.
    - Normalizes paths with os.path.normcase(str(p)).
    """
    project_res = project.resolve()
    main_repo = project_res
    git_entry = project_res / ".git"

    if git_entry.is_file():
        try:
            content = git_entry.read_text(encoding="utf-8").strip()
            if content.startswith("gitdir:"):
                raw_target = content[7:].strip()
                gitdir_path = Path(raw_target)
                if not gitdir_path.is_absolute():
                    gitdir_path = (project_res / gitdir_path).resolve()
                else:
                    gitdir_path = gitdir_path.resolve()
                if "worktrees" in gitdir_path.parts:
                    p = gitdir_path
                    while p.name != ".git" and p.parent != p:
                        p = p.parent
                    if p.name == ".git":
                        main_repo = p.parent.resolve()
        except OSError:
            pass

    roots = {os.path.normcase(str(project_res)), os.path.normcase(str(main_repo))}
    worktrees_dir = main_repo / ".git" / "worktrees"
    if worktrees_dir.is_dir():
        try:
            for entry in worktrees_dir.iterdir():
                if entry.is_dir():
                    gitdir_file = entry / "gitdir"
                    if gitdir_file.is_file():
                        try:
                            target = gitdir_file.read_text(encoding="utf-8").strip()
                            tpath = Path(target)
                            if not tpath.is_absolute():
                                tpath = (entry / tpath).resolve()
                            else:
                                tpath = tpath.resolve()
                            wt_dir = tpath.parent if tpath.name == ".git" else tpath
                            wt_git = wt_dir / ".git"
                            if wt_git.is_file():
                                back_content = wt_git.read_text(encoding="utf-8").strip()
                                if back_content.startswith("gitdir:"):
                                    bpath = Path(back_content[7:].strip())
                                    if not bpath.is_absolute():
                                        bpath = (wt_dir / bpath).resolve()
                                    else:
                                        bpath = bpath.resolve()
                                    if os.path.normcase(str(bpath)) == os.path.normcase(str(entry.resolve())):
                                        roots.add(os.path.normcase(str(wt_dir.resolve())))
                            elif wt_dir.resolve() == main_repo.resolve():
                                roots.add(os.path.normcase(str(wt_dir.resolve())))
                        except OSError:
                            pass
        except OSError:
            pass

    return roots


# U147: text that a tool, not 윤겸스, puts into a Codex thread as a user turn: injected AGENTS.md, app context blocks
# (<...>), and UAOS relays and sentinel data (seen in the 2026-10-04 rollouts).
# U163 (relay_3ce52b3d): the wrappers _deliver_unlocked puts on a relayed letter are injected text too.
INJECTED_PREFIXES = ("# AGENTS.md", "<", "[UAOS relay", "[DATA]", "[안티그래비티에서 온 대화]", "[코덱스에서 온 대화]",
                     "[클로드에게서 온 대화]")


def last_human_input(path: Path) -> str:
    """U147: ISO timestamp of the last user turn 윤겸스 typed in a Codex rollout, '' when there is none.

    The newest-written rollout is not the user's window: a background Codex thread that answers relays is written on
    every letter, stays newest, and pulled every later letter away from the window 윤겸스 watched (2026-10-04,
    relay_54d2ee83 went to 01a1006f, not 01a102e7). The window a human last typed in is the one the user reads.
    """
    last = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"role":"user"' not in line and '"role": "user"' not in line:
                    continue  # cheap filter: four 1-4 MiB rollouts scanned in 0.05 s (2026-10-04)
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                payload = data.get("payload") if isinstance(data, dict) else None
                if not isinstance(payload, dict) or payload.get("role") != "user":
                    continue
                content = payload.get("content")
                text = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict)) \
                    if isinstance(content, list) else ""
                if text.strip() and not text.lstrip().startswith(INJECTED_PREFIXES):
                    last = str(data.get("timestamp") or last)
    except OSError:
        return ""
    return last


# U147-D: the guessed window is only a bootstrap. Any truncated candidate list starves the user's window: newest 12
# (relay_6dfa9184) and a 7-day window capped at 500 (relay_ef4ac44f) both lost it to newer relay-only threads, and a
# day cutoff drops a quiet desk. The guess therefore reads every rollout or none: above ROUTE_SCAN_MAX rollouts it
# fails closed and only the designated user desk routes. 226 rollouts existed on 2026-10-04, one first line each.
ROUTE_SCAN_MAX = 500


def _iso_epoch(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def verified_rollouts(desk: Path, sessions_dir: Path, exclude_threads: set[str] = ()) -> tuple[list[tuple[str, Path]], bool]:
    """U147-D: ((thread, rollout) of this project's verified Codex threads, newest-written first; overflow).

    overflow is True when more than ROUTE_SCAN_MAX rollouts exist; the list is then empty, never a truncated guess.
    """
    if not sessions_dir.is_dir():
        return [], False
    stamped = []
    for path in sessions_dir.glob("*/*/*/rollout-*.jsonl"):
        try:
            stamped.append((path.stat().st_mtime, path))
        except OSError:
            continue
    if len(stamped) > ROUTE_SCAN_MAX:
        return [], True
    reg_roots = _registered_roots(desk)
    verified: list[tuple[str, Path]] = []
    for _mtime, path in sorted(stamped, key=lambda item: item[0], reverse=True):
        chosen_id, cwd, status = _read_rollout_meta(path)
        if status == "OK" and chosen_id not in exclude_threads:
            if cwd and os.path.normcase(str(cwd.resolve())) in reg_roots:
                verified.append((chosen_id, path))
    return verified, False


def _newest_verified_thread(desk: Path, sessions_dir: Path, exclude_threads: set[str] = ()) -> str:
    """Bootstrap guess of the user's verified thread when no user desk is designated; '' above ROUTE_SCAN_MAX.

    U147: among verified threads, the one 윤겸스 typed in last wins; with no human turn anywhere, the newest-written.
    U147-R: a rollout's last human turn is never later than its write time, so the newest-first scan stops at the
    first rollout written before the best human turn found; with every rollout listed, that stop is exact.
    """
    verified, _overflow = verified_rollouts(desk, sessions_dir, exclude_threads)
    if not verified:
        return ""
    best_stamp, best_epoch, best_id = "", 0.0, verified[0][0]
    for chosen_id, path in verified:  # newest-written first, so a tie keeps the newest-written thread
        try:
            if best_stamp and path.stat().st_mtime < best_epoch:
                break
        except OSError:
            continue
        stamp = last_human_input(path)
        if stamp > best_stamp:  # ISO-8601 UTC strings of one format sort by time
            best_stamp, best_epoch, best_id = stamp, _iso_epoch(stamp), chosen_id
    return best_id


def _codex_thread(desk: Path, thread: str) -> tuple[str, dict[str, str], str]:
    """U134-D / U134-R F1: Resolve Codex thread with strict identity and workspace verification.

    Returns (chosen_thread, fallback_dict, status).
    Status is 'DISPATCH' on success, or 'THREAD_UNVERIFIED', 'THREAD_PROJECT_MISMATCH', 'NO_VERIFIED_THREAD',
    'USER_DESK_STALE' (U147-D).
    U147-D: with no usable explicit thread, the designated user desk routes; a designated desk that fails
    verification fails closed instead of falling back to a guess. Only an undesignated desk uses the bootstrap guess.
    """
    root = _codex_sessions()
    why = ""
    if thread and not UUID_RE.fullmatch(thread):
        why = "not_uuid"
    elif thread and not list(root.glob(f"*/*/*/rollout-*-{thread}.jsonl")):
        why = "no_rollout"
    elif thread:
        status = _verify_thread(desk, root, thread)
        return (thread, {}, status) if status == "DISPATCH" else ("", {}, status)

    desk_state, designated = user_desk_state(desk, "codex")
    if desk_state == "INVALID":
        return "", {"why": "user_desk_invalid"}, "USER_DESK_STALE"
    if designated:
        status = _verify_thread(desk, root, designated)
        if status != "DISPATCH":
            return "", {"designated": designated, "why": status}, "USER_DESK_STALE"
        return designated, ({"given": thread, "used": designated, "why": why} if why else {}), "DISPATCH"
    newest = _newest_verified_thread(desk, root)
    if newest:
        return newest, ({"given": thread, "used": newest, "why": why} if why else {}), "DISPATCH"
    return "", {}, "NO_VERIFIED_THREAD"


def _verify_thread(desk: Path, root: Path, thread: str) -> str:
    """U134-R F1 strict identity: a UUID whose rollout names itself and a cwd inside this project."""
    if not UUID_RE.fullmatch(thread):
        return "THREAD_UNVERIFIED"
    matched = list(root.glob(f"*/*/*/rollout-*-{thread}.jsonl"))
    if not matched:
        return "THREAD_UNVERIFIED"
    cid, cwd, status = _read_rollout_meta(matched[0])
    if status != "OK" or cid != thread:
        return "THREAD_UNVERIFIED"
    if not cwd or os.path.normcase(str(cwd.resolve())) not in _registered_roots(desk):
        return "THREAD_PROJECT_MISMATCH"
    return "DISPATCH"


# U147-D designated user desk, the window 윤겸스 types in, per tool:
# - registered: by the tool's UserPromptSubmit hook when the prompt is human-typed (not INJECTED_PREFIXES), so it
#   follows the user to a new window on their next prompt; `register_user_desk` is also callable directly.
# - stored: `.coord/presence/user_desk_<tool>.json`, one file per tool so two tools' hooks never overwrite each other;
#   written by temp file + os.replace, so a reader sees the old or the new record, never half of one.
# - verified at every delivery (`_verify_thread`); a stale desk (rollout gone, other project) fails closed as
#   USER_DESK_STALE and the letter stays in the mailbox until the next human prompt registers a live desk.
USER_DESK_TOOLS = ("codex", "claude", "antigravity")


def user_desk_path(project: Path, tool: str) -> Path:
    return Path(project) / ".coord" / "presence" / f"user_desk_{tool}.json"


def user_desk_state(project: Path, tool: str) -> tuple[str, str]:
    """U147-D: ("ABSENT", "") when no record exists, ("OK", thread), or ("INVALID", "") for a record that exists but
    cannot be read or holds no UUID. Only ABSENT allows the bootstrap guess (Codex relay_48fb8d38: a broken record
    must not silently hand a designated desk's letters to a guessed window)."""
    path = user_desk_path(project, tool)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "ABSENT", ""
    except (OSError, ValueError):
        return "INVALID", ""
    try:
        data = json.loads(text)
    except ValueError:
        return "INVALID", ""
    thread = data.get("thread") if isinstance(data, dict) else None
    if isinstance(thread, str) and UUID_RE.fullmatch(thread):
        return "OK", thread
    return "INVALID", ""


def read_user_desk(project: Path, tool: str) -> str:
    return user_desk_state(project, tool)[1]


# U176: Claude Code puts its own `<system-reminder>…</system-reminder>` blocks in front of what 윤겸스 typed (the
# first prompt of a desktop worktree session, 2026-10-10), and the "<" injected prefix then hid a real declaration.
# Only whole leading blocks are dropped (tag attributes allowed, Antigravity audit relay_6c7083d0); a prompt that is
# nothing but a reminder stays empty, so not human.
_HARNESS_NOTE_RE = re.compile(r"\A(?:\s*<system-reminder(?:\s[^>]*)?>.*?</system-reminder>)+\s*", re.S)


def typed_prompt(prompt: object) -> object:
    return _HARNESS_NOTE_RE.sub("", prompt) if isinstance(prompt, str) else prompt


def is_human_prompt(prompt: object) -> bool:
    prompt = typed_prompt(prompt)
    return isinstance(prompt, str) and bool(prompt.strip()) and not prompt.lstrip().startswith(INJECTED_PREFIXES)


def register_user_desk(project: Path, tool: str, thread: str, *, source: str) -> bool:
    if tool not in USER_DESK_TOOLS or not isinstance(thread, str) or not UUID_RE.fullmatch(thread):
        return False
    if read_user_desk(project, tool) == thread:
        return True  # every prompt in the same window would otherwise rewrite the record
    path = user_desk_path(project, tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(json.dumps({"thread": thread, "at": time.time(), "source": source}), encoding="utf-8")
    for _attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp, path)
            return True
        except PermissionError:
            time.sleep(0.05)
    temp.unlink(missing_ok=True)
    return False


def _queue_dir(project: Path, tool: str) -> Path:
    """U134: letters waiting for `tool` to turn ACTIVE live beside the mailbox's other delivery records."""
    return _project_mailbox(Path(project).resolve()).root / "delivery" / "queued" / tool


def _queue_until_active(project: Path, tool: str, *, message_id: str, digest: str, actor: str, message: str,
                        card: str, thread: str, verdict_requested: bool = False) -> DeliverResult:
    """U134-C (2026-10-03): a letter to a LIMITED/ABSENT codex/claude came back `mailbox_only` PUBLISHED with ok=true
    and nothing re-sent it when the tool returned (relay_18758c37 never reached Codex). It is now queued, and the
    tool's next ACTIVE heartbeat with dispatch (presence.mark -> dispatch_queued) sends it.
    U277 L1: a verdict request is marked on its queued record, so the stall scan counts it as a wait."""
    marker = _queue_dir(project, tool) / f"{message_id}.json"
    record = {"message_id": message_id, "actor": actor, "message": message, "card": card,
              "thread": thread, "attempts": 0, "digest": digest}
    if verdict_requested:
        record["verdict_requested"] = True
    try:
        _write_receipt(marker, record)
    except FileExistsError:
        pass  # the same letter sent again stays one queued letter
    return DeliverResult(False, tool, "QUEUED_UNTIL_ACTIVE", (), "", message_id, digest, str(marker))


def _park_failed(source_file: Path, message_id: str, queue_dir: Path) -> Path:
    """U134-F2: park a corrupt or exceeded-retries letter as .failed without overwriting existing evidence."""
    target = queue_dir / f"{message_id}.failed"
    # Decision: never overwrite existing .failed evidence; use unique hex suffix if default name is taken
    if target.exists():
        target = queue_dir / f"{message_id}.{uuid.uuid4().hex}.failed"
    os.replace(source_file, target)
    return target


def queued_letters(project: Path, tool: str) -> list[Path]:
    """U134-B: letters waiting for `tool`, oldest name first; a missing queue is empty (the hook's cheap check).
    U134-F2: collect letter ids from both <id>.json markers and orphan <id>.<hex>.taking files, each id once."""
    folder = _queue_dir(project, tool)
    if not folder.is_dir():
        return []
    ids: set[str] = set()
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.name.endswith(".json"):
            ids.add(p.stem)
        elif p.name.endswith(".taking"):
            # Decision: <id>.<hex>.taking -> extract <id> (first segment before the dot)
            ids.add(p.name.split(".")[0])
    # Decision: build list of marker paths so each id is processed once, in name order
    return [folder / f"{letter_id}.json" for letter_id in sorted(ids)]


def dispatch_queued(project: Path, tool: str, *, runner: Any = None) -> list[dict[str, str]]:
    """U134-B/F2: send each letter queued for `tool` once under a per-letter OS lock with scoped crash recovery.

    Documented risk: a crash after the remote send but before the accepted receipt can duplicate one send.

    A heartbeat takes each letter under a per-letter non-blocking OS lock (<id>.lock), held across the rename,
    send, and settle. A live owner keeps the lock even if paused, preventing stolen letters. If an orphan .taking
    exists under the lock, the previous owner is dead, so it is recovered along with any claimed mailbox entry.
    An unsettled send goes back to the queue without incrementing attempts if IN_FLIGHT, or increments attempts
    and parks as .failed after 3 tries.
    """
    # Reasons that end a queued letter's trip: sent, already acknowledged, or held for the interactive session.
    settled = ("DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY")
    # One try per hook kind (SessionStart, UserPromptSubmit, PostToolUse) before parking: a letter that keeps failing
    # (no thread, CLI error) must not fire `codex queue` on every heartbeat forever.
    # 3: max retries per hook kind before parking to failed
    tries = 3
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    folder = _queue_dir(project, tool)
    sent: list[dict[str, str]] = []

    for marker in queued_letters(project, tool):
        message_id = marker.stem
        lock_file = folder / f"{message_id}.lock"
        # Decision: per-letter OS lock. Open <message_id>.lock and take a non-blocking lock.
        # Decision: never unlink .lock file; the OS automatically releases locks on process exit/termination.
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        except OSError:
            continue

        locked = False
        try:
            if not _try_lock(fd):
                # Decision: busy lock means a live owner has it (even if paused); skip to next letter.
                continue
            locked = True

            # Decision: letter claim and orphan recovery under the per-letter lock.
            taking_files = sorted(folder.glob(f"{message_id}.*.taking"))
            is_orphan = False
            taking: Path
            if taking_files:
                # Decision: holding the lock while an orphan .taking exists proves its owner is dead. Adopt it.
                is_orphan = True
                # Judge fix (U134-F2a): adopt the oldest orphan only and delete nothing; the contract forbids deletion.
                taking = taking_files[0]
            elif marker.is_file():
                taking = marker.with_name(f"{message_id}.{uuid.uuid4().hex}.taking")
                try:
                    os.rename(marker, taking)
                except OSError:
                    continue
            else:
                # Neither taking nor marker exists; already settled or removed
                continue

            if is_orphan:
                # Decision: scoped mailbox recovery for THIS message id: if claimed and inbox is absent, move back to inbox.
                # Do not call box.recover_stale_claims or touch any other message id.
                claims = sorted(box.claimed_dir.glob(f"{message_id}_*.json"))
                if claims:
                    inbox_file = box.inbox_dir / f"{message_id}.json"
                    # Judge fix (U134-F2a): only move one claim back, never delete a claim (another holder may own it).
                    if not inbox_file.is_file():
                        os.replace(claims[0], inbox_file)
                # Decision: write an attempt receipt with state QUEUE_CLAIM_RECOVERED under delivery/attempts/
                attempts_dir = box.root / "delivery" / "attempts"
                attempts_dir.mkdir(parents=True, exist_ok=True)
                _write_receipt(
                    attempts_dir / f"{message_id}_{uuid.uuid4().hex}.json",
                    {
                        "message_id": message_id,
                        "state": "QUEUE_CLAIM_RECOVERED",
                        "timestamp_ns": time.time_ns(),
                    },
                )

            # Decision: read letter from taking file; handle corrupt markers without overwriting evidence
            try:
                letter = json.loads(taking.read_text(encoding="utf-8"))
                if not isinstance(letter, dict):
                    raise ValueError("letter is not a json object")
            except (OSError, ValueError):
                _park_failed(taking, message_id, folder)
                continue

            card = str(letter.get("card") or "")
            thread = str(letter.get("thread") or "")
            if card:
                from v7_harness.coord.windows import window_for
                thread = window_for(desk, card, tool) or thread  # U115: card's own window of the now-ACTIVE tool

            message = str(letter.get("message") or "")
            actor = str(letter.get("actor") or "")
            # Keep the published identity, including destination and legacy queued IDs.
            digest = str(letter.get("digest") or _digest(actor, message, card, ""))

            # Decision: acquire per-message dispatch guard following U83 age rule (_acquire_guard, GUARD_STALE_S)
            guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
            guard.parent.mkdir(parents=True, exist_ok=True)
            guard_fd = _acquire_guard(guard, box, message_id, digest)
            if guard_fd is None:
                # Decision: guard is still young held by another active/recent dispatcher -> IN_FLIGHT
                result = DeliverResult(False, tool, "IN_FLIGHT", (), "", message_id, digest)
            else:
                guard_owner = uuid.uuid4().hex
                with os.fdopen(guard_fd, "wb") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "message_id": message_id,
                                "digest": digest,
                                "actor": actor,
                                "message": message,
                                "target": tool,
                                "owner": guard_owner,
                            },
                            ensure_ascii=False,
                        ).encode("utf-8")
                    )
                    handle.flush()
                    os.fsync(handle.fileno())

                pending_owner = None
                if tool == "claude" and _requires_wake(message):
                    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
                    pending.parent.mkdir(parents=True, exist_ok=True)
                    pending.write_text(
                        json.dumps(
                            {
                                "message_id": message_id,
                                "target": "claude",
                                "state": "PENDING",
                                "owner": guard_owner,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    pending_owner = guard_owner

                try:
                    result = _deliver_unlocked(
                        project,
                        message=message,
                        actor=actor,
                        target=tool,
                        thread=thread,
                        runner=runner,
                        pending_owner=pending_owner,
                        card=card,
                        window="",
                        identity_digest=digest,
                    )
                finally:
                    _release_guard(guard, guard_owner)

            sent.append({"message_id": str(letter.get("message_id") or message_id), "reason": result.reason})

            # Decision: settle logic
            if result.reason in settled:
                taking.unlink(missing_ok=True)
                continue

            if result.reason == "IN_FLIGHT":
                # Decision: guard is still young; return letter to <message_id>.json without adding an attempt
                os.replace(taking, folder / f"{message_id}.json")
                continue

            # Decision: any other unsettled result adds one attempt and parks after tries (3) attempts
            letter["attempts"] = int(letter.get("attempts") or 0) + 1
            taking.write_text(json.dumps(letter, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            if letter["attempts"] < tries:
                os.replace(taking, folder / f"{message_id}.json")
            else:
                _park_failed(taking, message_id, folder)
        finally:
            if locked:
                try:
                    _unlock(fd)
                except OSError:
                    pass
            try:
                os.close(fd)
            except OSError:
                pass

    return sent


def _deliver_unlocked(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
    pending_owner: str | None = None,
    card: str = "",
    window: str = "",
    identity_digest: str | None = None,
    wants_turn: bool | None = None,
) -> DeliverResult:
    """메시지를 대상 도구에게 직접 전달한다.

    target: "codex" | "claude" | None (자동 판별).
    자동 판별 시 presence를 읽어 ACTIVE인 도구에게 보낸다.
    Codex ACTIVE면 Codex, 아니면 Claude에게 보낸다.

    불변식: 사용자에게 수동 릴레이를 요청하지 않는다.
    """
    _check_secrets(message)
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    # Stable id makes repeated calls with the same sender and bytes idempotent.
    digest = identity_digest or _digest(actor, message, card, window)
    message_id = "relay_" + digest[:32]
    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
    ack_file = box.ack_dir / f"{message_id}.json"
    if ack_file.is_file():
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(True, target or "auto", "ACKED", (), "", message_id, digest, str(ack_file))

    # U64 (2026-09-28): coord watch only returns to the shell process that launched it; it cannot start a new AI turn.
    # It may suppress an ACK-only/liveness delivery, but a real delta must use the direct Claude dispatch path.
    if target == "claude":
        from v7_harness.coord.watch import watcher_live, watcher_wakes
        # U117: a watcher that wakes its own session takes real deltas too; U64's headless turn stays for the rest.
        need_wake = _requires_wake(message) if wants_turn is None else wants_turn
        if watcher_live(desk, "claude") and (not need_wake or watcher_wakes(desk, "claude")):
            _clear_owned_pending(pending, pending_owner)
            pending.unlink(missing_ok=True)
            return DeliverResult(False, "claude", "QUEUED_INTERACTIVE", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))
        # U74-D: an explicit ACK_ONLY never spends a paid turn, even with no watcher (global relay rule). The letter
        # is already published; the next session reads it from the inbox.
        if _ACK_RE.search(message.upper()):
            return DeliverResult(False, "claude", "QUEUED_ACK_ONLY", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))

    accepted = box.root / "delivery" / "accepted" / f"{message_id}.json"
    if accepted.is_file():
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(False, target, "DISPATCHED", (), _receipt_output(accepted),
                             message_id, digest, str(accepted))

    # A same-id caller publishing outside the guard may hold the inbox file open for a moment, and Windows then
    # refuses the claim's rename. Retry briefly instead of reporting IN_FLIGHT with nobody dispatching.
    inbox_file = box.inbox_dir / f"{message_id}.json"
    claim = None
    for _ in range(CLAIM_TRIES):
        claim = box.claim(message_id, "dispatcher")
        if claim is not None or not inbox_file.is_file():
            break
        time.sleep(CLAIM_SLEEP_S)
    if claim is None:
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(False, target, "IN_FLIGHT", (), "", message_id, digest)

    result: DeliverResult
    try:
        # A contender may have checked before the first sender wrote this
        # receipt, then acquired the claim after the first sender returned it.
        if accepted.is_file():
            return DeliverResult(False, target, "DISPATCHED", (), _receipt_output(accepted),
                                 message_id, digest, str(accepted))
        # The claim serializes competing dispatchers. The original is returned
        # to inbox after the attempt; only recipient coord ack may settle it.
        envelope = f"[UAOS relay id={message_id} digest={digest}]\n{message}"
        if window:
            envelope += f"\nNative receiver {window}: after disposition, run coord ack --id {message_id} --consumer {window}."
        if target != "claude":
            envelope += (f"\nAfter processing, run coord ack --id {message_id} for this project. "
                         "The sender keeps this message in the inbox until ACK.")
        fallback: dict[str, str] = {}
        sent_thread = ""  # U147: the receipt names the Codex thread, so a misrouted letter is visible
        if target == "codex":
            if window:  # U115: the card's own Codex thread replaces the default thread
                thread = window
            chosen_thread, fallback, status = _codex_thread(desk, thread)
            if status != "DISPATCH":
                result = DeliverResult(False, "codex", status, (), "")
            else:
                result = _deliver_to_codex(envelope, chosen_thread, runner=runner)
                sent_thread = chosen_thread
                # Rule 6: retry once on rc != 0 with newest verified thread other than failed one
                # U147-D: a letter to the designated user desk is never re-sent to a guessed relay window.
                if not result.delivered and result.reason.startswith("DELIVERY_FAILED:rc=") \
                        and chosen_thread != read_user_desk(desk, "codex"):
                    alt_thread = _newest_verified_thread(desk, _codex_sessions(), exclude_threads={chosen_thread})
                    if alt_thread:
                        fallback = {"given": chosen_thread, "used": alt_thread, "why": "send_failed"}
                        result = _deliver_to_codex(envelope, alt_thread, runner=runner)
                        sent_thread = alt_thread
        elif target == "claude":
            prefix = "[안티그래비티에서 온 대화] " if actor.lower() in ("agy", "antigravity") else (
                "[코덱스에서 온 대화] " if actor.lower() == "codex" else "")
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner, session=window)
        else:
            result = DeliverResult(False, str(target), f"UNKNOWN_TARGET:{target}", (), "")

        attempts = box.root / "delivery" / "attempts"
        receipt = {"message_id": message_id, "digest": digest, "target": target,
                   "state": "DISPATCHED" if result.delivered else "FAILED", "reason": result.reason,
                   "attempt": _dispatch_count(attempts, message_id) + 1, "timestamp_ns": time.time_ns(),
                   "output": result.output, **({"thread_fallback": fallback} if fallback else {}),
                   **({"thread": sent_thread} if sent_thread else {})}
        attempt_path = attempts / f"{message_id}_{uuid.uuid4().hex}.json"
        _write_receipt(attempt_path, receipt)
        if result.delivered:
            try:
                _write_receipt(accepted, receipt)
            except FileExistsError:
                pass
            return DeliverResult(False, target, "DISPATCHED", result.command, result.output,
                                 message_id, digest, str(accepted))
        return DeliverResult(False, str(target), result.reason, result.command, result.output,
                             message_id, digest, str(attempt_path))
    finally:
        _clear_owned_pending(pending, pending_owner)
        try:
            box.nack(claim)
        except OSError:
            # A same-id publisher reading the claimed copy can block its unlink on Windows. The bytes are already in
            # the inbox or stay in claimed/ for recover_stale_claims, so nothing is lost; do not fail the dispatch.
            pass


_PR_URL_RE = re.compile(r"https?://\S+/pull/\d+")
_SHA_RE = re.compile(r"\b[0-9a-fA-F]{40}\b")


def _first(pattern: re.Pattern[str], text: str) -> str:
    match = pattern.search(text or "")
    return match.group(0) if match else ""


def _repo_url(root: Path) -> str:
    """The remote a request was made in (a binding field, U277). "" when git is unavailable."""
    try:
        done = subprocess.run(["git", "-C", str(root), "config", "--get", "remote.origin.url"], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def deliver(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
    card: str = "",
    wake_class: str | None = None,
    verdict_requested: bool | None = None,
    verdict: str | None = None,
    delta: str | None = None,
    subject: str = "",
    head: str = "",
    session: str = "",
    in_reply_to: str = "",
) -> DeliverResult:
    """U277 rev 2: a verdict request is registered durably before anything is published or dispatched.

    A registry failure is a refusal (REQUEST_TRACKING_FAILED): nothing is sent, so no letter waits unrecorded.
    The request's delivery fact (DISPATCHED or QUEUED) is written after the letter's own outcome.
    """
    from v7_harness.coord.requests import RequestError, mark_delivered, register

    root = Path(project).resolve()
    tracked: dict[str, str] = {}
    subject_val = subject or _first(_PR_URL_RE, message)
    head_val = (head or _first(_SHA_RE, message)).lower()
    session_val = session or os.environ.get("CLAUDE_SESSION_ID", "")

    def track(message_id: str, to: str) -> None:
        tracked["id"] = message_id
        register(root, request_id=message_id, requester=actor, target=to, card=card, subject=subject_val,
                 head=head_val, requester_session=session_val, repo=_repo_url(root))
        tracked["ok"] = "1"

    try:
        result = _deliver_impl(root, message=message, actor=actor, target=target, thread=thread, runner=runner,
                               card=card, wake_class=wake_class, verdict_requested=verdict_requested,
                               verdict=verdict, delta=delta, in_reply_to=in_reply_to,
                               _track=track if verdict_requested is True else None,
                               audit=verdict_requested is True)
    except RequestError as exc:
        return DeliverResult(False, target or "mailbox_only", exc.code, (), str(exc), tracked.get("id", ""), "")
    if tracked.get("ok"):
        delivery = "DISPATCHED" if result.reason in ("DISPATCHED", "SENT") else "QUEUED"
        try:
            mark_delivered(root, tracked["id"], delivery)
        except (RequestError, OSError, ValueError):
            pass  # the registry keeps PENDING_DELIVERY; reconcile reads the mailbox receipts later
    return result


def _deliver_impl(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
    card: str = "",
    wake_class: str | None = None,
    verdict_requested: bool | None = None,
    verdict: str | None = None,
    delta: str | None = None,
    in_reply_to: str = "",
    _track: Any = None,
    audit: bool = False,
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.

    On Windows, another publisher opening a claimed file can prevent NACK
    from unlinking it. This outer guard prevents same-id callers from touching
    mailbox files while the owner is publishing or dispatching.
    """
    _check_secrets(message)
    digest = _digest(actor, message)
    message_id = "relay_" + digest[:32]
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    requested_target = target
    queued_for = ""
    if target is None:
        from v7_harness.coord.presence import read as read_presence
        from v7_harness.coord.watch import watcher_live
        if read_presence(desk, "codex")["state"] == "ACTIVE":
            target = "codex"
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"
    # U113: a relay queued into a LIMITED tool's thread waits there and costs one paid turn per letter when it returns
    # (7 relays piled up in Codex's thread on 2026-10-01); its hooks show the inbox instead (desk delta, U103).
    elif target in ("codex", "claude"):
        from v7_harness.coord.presence import read as read_presence
        if read_presence(desk, target)["state"] in ("LIMITED", "ABSENT"):
            queued_for, target = target, None  # U134-C: queued below until the tool's next ACTIVE turn
    # U115: a card letter goes into the card's window of the resolved target (U114 record). A LIMITED/ABSENT target
    # was resolved to None above, so it gets no window and is queued without one (U113, U134-C).
    window = thread or None
    if card:
        from v7_harness.coord.windows import window_for
        window = window_for(desk, card, target or "")  # a bad card id raises before anything is published
    token = _unstructured_verdict(message, requested_target, wake_class, verdict_requested, verdict)
    if token:
        # U188 (Codex design verdict relay_61456b14): text never becomes authoritative and NOTICE never wakes, so the
        # contradiction fails visibly before any publish; the sender resends with the structured field.
        diag = (f"UNSTRUCTURED_VERDICT: the first line reads as verdict {token!r} but carries no wake field; resend "
                "with --verdict <PASS|REVISE|FAIL|APPROVE|PIVOT|REWORK> (or --wake-class ACTIONABLE --delta), or "
                "mark a status echo ACK_ONLY")
        return DeliverResult(False, target or "mailbox_only", "UNSTRUCTURED_VERDICT", (), diag, message_id, digest)
    explicit = {key: value for key, value in (("wake_class", wake_class), ("verdict_requested", verdict_requested),
                                              ("verdict", verdict), ("delta", delta)) if value is not None}
    if not explicit and requested_target and _requires_wake(message):
        # U141-B: an ordinary letter whose text asks for a turn becomes a structured ACTIONABLE envelope, so the
        # structured watcher (which never reads text) wakes its receiver. Explicit fields, even NOTICE, always win.
        first = next((line.strip() for line in message.splitlines() if line.strip()), "")
        wake_class, delta = "ACTIONABLE", first[:DELTA_LIMIT]
        explicit = {"wake_class": wake_class, "delta": delta}  # stored fields, so the id is v3 (see _digest)
    # U277: a reply names the letter it answers, so it is its own id even when its text repeats an earlier letter.
    id_fields = {**explicit, "in_reply_to": in_reply_to} if in_reply_to else explicit
    digest = _digest(actor, message, card, window, requested_target, id_fields)
    message_id = "relay_" + digest[:32]
    if explicit.get("wake_class") or explicit.get("verdict_requested") is True or explicit.get("verdict"):
        # U155 (C6 class): a letter that declares a wake intent with malformed fields (ACTIONABLE without delta, a
        # NOTICE asking for a verdict) used to publish an INVALID envelope that never wakes anyone. Refuse it before
        # any marker or publish, so the sender gets a non-OK result instead of a silent stall. Untagged, NOTICE,
        # ACK_ONLY and verdict_requested=False letters keep today's bytes (U141-B frozen test).
        from v7_harness.coord.watch import classify
        cls, diag = classify(_payload(actor, message, digest, requested_target, card, window, **explicit))
        if cls == "INVALID":
            return DeliverResult(False, target or "mailbox_only", "INVALID_INTENT", (), diag, message_id, digest)
    # U66: the intent marker exists before the inbox letter. A racing watcher waits instead of starting a second
    # paid turn; on failure `_deliver_unlocked` removes it and the same unseen letter becomes the fallback route.
    if _track is not None:
        # U277 rev 2: the request is recorded before the marker, the publish and any dispatch (a failure sends nothing).
        _track(message_id, requested_target or target or "")
    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
    wants_turn = _wants_wake(message, wake_class=explicit.get("wake_class"), verdict=explicit.get("verdict"),
                             verdict_requested=explicit.get("verdict_requested"))
    if target == "claude" and wants_turn and not pending.is_file():
        try:
            _write_receipt(pending, {"message_id": message_id, "target": "claude", "state": "PENDING"})
        except FileExistsError:
            pass
    # U48-D0 re-review (Claude, 2026-09-27): publish before the guard. A guard left by a crashed dispatcher used to
    # return IN_FLIGHT before any publish, so the message never reached the inbox. Publish is idempotent by id+bytes.
    box.publish(message_id, _payload(actor, message, digest, requested_target, card, window, wake_class=wake_class,
                                     verdict_requested=verdict_requested, verdict=verdict, delta=delta,
                                     in_reply_to=in_reply_to))
    # U169: one wake rule for the sound and the Antigravity auto-answer: an explicit class wins, else the text decides.
    wants_turn = explicit.get("wake_class") == "ACTIONABLE" or (explicit.get("wake_class") is None
                                                                and _requires_wake(message))
    if wants_turn:
        # U143: a letter that asks for a turn plays one real sound (coalesced in ring.py); a sound never fails a letter.
        from v7_harness.coord import ring as _ring
        try:
            _ring.ring(desk, reason=f"{message_id} {actor}->{requested_target or target or 'mailbox'}")
        except Exception:  # noqa: BLE001
            pass
    if target == "antigravity":
        from v7_harness.coord.watch import watcher_live, watcher_wakes
        if watcher_live(desk, "antigravity") and (not wants_turn or watcher_wakes(desk, "antigravity")):
            return DeliverResult(False, "antigravity", "QUEUED_INTERACTIVE", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))
        # U95-A: no CLI wakes Antigravity; its PreInvocation hook names the letter on its next turn (agy_line).
        # U118: a real delta stays unread until a user turn there; say so and name the headless route (user report).
        # U194: a structured verdict request asks Antigravity for a turn too (receipt relay_19f9c6aa). Narrowed to
        # this branch (Codex relay_5be83219): the U143 sound above keeps its rule; NOTICE/ACK_ONLY never ask.
        agy_turn = wants_turn or (explicit.get("verdict_requested") is True
                                  and explicit.get("wake_class") not in ("NOTICE", "ACK_ONLY"))
        unread = ("UNREAD until a user turn in Antigravity; for a verdict run `pilot review --reviewer agy` "
                  "(headless, no user)") if agy_turn else ""
        if unread and actor in ("claude", "codex") and os.environ.get("UAOS_AGY_AUTO", "1") != "0":
            # U120: a headless one-turn answer (U119 live: 27,989 tokens) is mailed back to the sender; a failure,
            # a loop tag or the daily cap keeps the U118 UNREAD route. UAOS_AGY_AUTO=0 opts out.
            from v7_harness.coord.agy_dispatch import dispatch
            # U199: a verdict request is the commit-gate audit; its answer is never held back by the daily cap
            row = dispatch(desk, message_id=message_id, actor=actor, message=message, runner=runner or subprocess.run,
                           card=card, audit=audit)
            detail = json.dumps(row, ensure_ascii=False)[:300] if row["state"] == "ANSWERED" else unread
            unread = f"AGY_{row['state']} {detail}"
        return DeliverResult(False, "antigravity", "PUBLISHED", (), unread, message_id, digest)
    if target is None and queued_for:
        return _queue_until_active(project, queued_for, message_id=message_id, digest=digest, actor=actor,
                                   message=message, card=card, thread=thread,
                                   verdict_requested=verdict_requested is True)
    if target is None:
        return DeliverResult(False, "mailbox_only", "PUBLISHED", (), "", message_id, digest)
    guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    fd = _acquire_guard(guard, box, message_id, digest)
    if fd is None:
        return DeliverResult(False, target or "mailbox_only", "IN_FLIGHT", (), "", message_id, digest)
    owner = uuid.uuid4().hex
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps({"message_id": message_id, "digest": digest, "actor": actor,
                                 "message": message, "target": target, "owner": owner},
                                ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    pending_owner = None
    if target == "claude" and _requires_wake(message):
        # The guard winner takes ownership even if another contender created the provisional marker. Guard losers
        # cannot remove it; this closes the last window where a watcher could start a second paid turn.
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps({"message_id": message_id, "target": "claude", "state": "PENDING",
                                       "owner": owner}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        pending_owner = owner
    try:
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner, pending_owner=pending_owner,
                                 card=card, window=window or "", identity_digest=digest, wants_turn=wants_turn)
    finally:
        _release_guard(guard, owner)


def agy_desktop_conversation(conversation: object) -> bool:
    if not isinstance(conversation, str) or not UUID_RE.fullmatch(conversation):
        return False
    home = Path(os.environ.get(AGY_APP_HOME_ENV) or (Path.home() / ".gemini" / "antigravity"))
    return (home / "conversations" / f"{conversation}.db").is_file() or (home / "brain" / conversation).is_dir()
===FILE: v7_harness/coord/watch.py===
"""U57: `coord watch` — block until a new mailbox letter for a tool arrives, at zero model tokens.

Why (2026-09-27/28): an interactive session wakes only on a user prompt. Letters between Claude sessions were held
by the app for the user's approval (sessions with different permission modes), one expired unseen, and the acting
conductor had to hand-write a shell loop over the inbox to be woken. The user then had to approve or copy messages.
This makes that loop a tested harness command: a session runs it in the background, and it exits when a letter for
its tool lands, so the session wakes without the user.

While a watch runs it keeps `.coord/presence/<tool>.watch.json` fresh. `coord deliver` reads that file: a live
watcher means an interactive session is listening, so the letter is left in the inbox for it (QUEUED_INTERACTIVE)
instead of starting a cold headless session that cannot see the conversation.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.presence import PRESENCE_DIR, TOOLS, replace_with_retry

# 2 s between inbox scans (U94, 2026-09-30): a letter waits at most one interval before the watch wakes; the
# hand-written loop of 2026-09-27 used 30 s. A scan lists the inbox and reads only letters it has not seen (U94-R1):
# re-reading all 464 desk letters took 132 ms a scan, so 2 s kept a watcher busy 6.6% of the time (15x the 30 s
# cost); the listing alone took 8.1 ms (0.4%). Never tokens either way.
DEFAULT_INTERVAL_S = 2.0
# 4 h per watch: the longest single wait seen on 2026-09-27 (Codex quota window). The session re-arms it after.
DEFAULT_TIMEOUT_S = 4 * 3600.0
# A watcher counts as live for three missed scans, and never less than 90 s, so one slow scan does not make
# `coord deliver` fall back to a cold session while the watcher is still running.
LIVE_SCANS = 3
LIVE_MIN_S = 90.0
# Longer than the 120 s Claude dispatch timeout plus receipt writes. A crashed dispatcher must not suppress the
# interactive fallback forever; after this bound the marker is evidence of failure, not an active dispatch.
PENDING_MAX_AGE_S = 300.0
# U179: 60 s between long-wait scans. A scan takes the stall lock, reads the schedule and the queued letters and
# writes three small state files, so it does not run on every 2 s inbox scan; 60 s bounds lateness to 3% of
# stall.MAX_WAIT_S (1800 s). Never tokens.
STALL_SCAN_S = 60.0
# U141-A: an empty O_EXCL placeholder younger than this is a claim being written (the full record follows within
# milliseconds), so it counts as EXISTS. An older empty one is a crashed claim: CORRUPT, kept, never a wake.
PLACEHOLDER_GRACE_S = 5.0

# U141-A wake policy (rev 4 f57b2186, Codex APPROVE relay_bcb089d1; rev 5 delta). Only these structured envelope
# fields decide a paid wake; the message text is never read, so a quoted marker cannot wake anyone.
WAKE_CLASSES = ("ACTIONABLE", "NOTICE")
VERDICTS = ("PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK")
STRUCTURED_FIELDS = ("wake_class", "verdict_requested", "verdict", "delta")
RECEIPT_KEYS = ("target", "message_id", "digest", "pid", "process_created", "created_at")


def watch_file(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.json"


def _beat(project: Path, tools: tuple[str, ...], token: str, interval_s: float, moment: float,
          wakes_session: bool = False, *, session: str = "", process_created: int | None = None) -> None:
    live_for = max(LIVE_SCANS * interval_s, LIVE_MIN_S)
    for tool in tools:
        target = watch_file(project, tool)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        # U277: the lease names its session and process identity, so a verdict request's stop hold can tell this
        # session's live watcher from a foreign one (watcher_wakes_for).
        tmp.write_text(json.dumps({"tool": tool, "token": token, "pid": os.getpid(),
                                   "expires_at": moment + live_for, "wakes_session": wakes_session,
                                   "session": session, "adapter": "claude-bg-task" if wakes_session else "",
                                   "process_created": process_created}),
                       encoding="utf-8")
        try:
            replace_with_retry(tmp, target)
        except PermissionError:
            # U60: a missed beat is not a missed letter. The file stays live for three scans, the next beat
            # rewrites it, and the inbox scan below runs either way.
            pass


def _clear(project: Path, tools: tuple[str, ...], token: str) -> None:
    """Remove only this watch's files; a newer watch for the same tool keeps its own."""
    for tool in tools:
        target = watch_file(project, tool)
        try:
            if json.loads(target.read_text(encoding="utf-8")).get("token") == token:
                target.unlink(missing_ok=True)
        except (OSError, ValueError, AttributeError):
            pass


def watcher_live(project: Path, tool: str, *, now: float | None = None) -> bool:
    moment = time.time() if now is None else now
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    expires_at = record.get("expires_at") if isinstance(record, dict) else None
    return isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > moment


def watcher_wakes(project: Path, tool: str) -> bool:
    """U117: a live watcher whose exit wakes its own session (a Claude Code background task) takes real deltas too."""
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return watcher_live(project, tool) and isinstance(record, dict) and record.get("wakes_session") is True


WAKE_ADAPTERS = ("claude-bg-task", "claude-async-rewake")


def watcher_wakes_for(project: Path, tool: str, session: str | None, *, now: float | None = None) -> bool:
    """U277 (docs 5.6): a live watcher that wakes its session, owned by a live process, for `session`.

    A lease of another session never satisfies the stop hold. An empty session on either side is not compared
    (no session to compare: the lease is accepted, as the stop gate's other checks are lenient on UNKNOWN)."""
    moment = time.time() if now is None else now
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(record, dict) or not watcher_live(project, tool, now=moment):
        return False
    if record.get("wakes_session") is not True or record.get("adapter") not in WAKE_ADAPTERS:
        return False
    pid, created = record.get("pid"), record.get("process_created")
    if not isinstance(pid, int) or isinstance(pid, bool) or created is None or process_identity(pid) != created:
        return False
    lease_session = str(record.get("session") or "")
    return not (session and lease_session and lease_session != session)


def _addressed(payload: Any, tools: tuple[str, ...]) -> bool:
    if not isinstance(payload, dict):
        return False
    return payload.get("requested_target") in tools or payload.get("to") in tools


def classify(payload: Any, migration: dict[str, Any] | None = None) -> tuple[str, str]:
    """U141-A: (ACTIONABLE | NOTICE | INVALID | LEGACY, diagnostic) from the structured fields only.

    Every field is validated before any row matches, so an early matching row cannot hide a contradictory field.
    """
    body = dict(payload) if isinstance(payload, dict) else {}
    if isinstance(migration, dict):
        # A digest-bound migration record overrides the four structured fields; the stored envelope is never rewritten.
        for key in STRUCTURED_FIELDS:
            if key in migration:
                body[key] = migration[key]
    present = [key for key in STRUCTURED_FIELDS if key in body]
    if not present:
        return "LEGACY", "no structured wake field"
    wake_class = body.get("wake_class")
    verdict = body.get("verdict")
    requested = body.get("verdict_requested")
    delta = body.get("delta")
    if "wake_class" in body and wake_class not in WAKE_CLASSES:
        return "INVALID", f"wake_class {wake_class!r} is not ACTIONABLE or NOTICE"
    if "verdict" in body and verdict not in VERDICTS:
        return "INVALID", f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}"
    if "verdict_requested" in body and not isinstance(requested, bool):
        return "INVALID", f"verdict_requested {requested!r} is not a bool"
    if "delta" in body and not (isinstance(delta, str) and delta.strip()):
        return "INVALID", "delta is empty"
    has_verdict = "verdict" in body
    if wake_class == "NOTICE":
        if has_verdict or requested is True:
            return "INVALID", "NOTICE carries a verdict or verdict_requested"
        return "NOTICE", ""
    if not (str(body.get("actor") or "").strip() and str(body.get("requested_target") or "").strip()):
        return "INVALID", "an actionable letter needs actor and requested_target"
    if wake_class == "ACTIONABLE":
        if "delta" in body:
            return "ACTIONABLE", ""
        return "INVALID", "ACTIONABLE without delta"
    if requested is True or has_verdict:
        return "ACTIONABLE", ""
    return "INVALID", "no policy row"


def migration_record(project: Path, message_id: str, digest: Any) -> dict[str, Any] | None:
    """U141-A: a legacy letter's wake fields, valid only while bound to that exact message id and digest."""
    path = Path(project) / ".coord" / "mailbox" / "migration" / f"{message_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict):
        return None
    if record.get("source_message_id") != message_id or record.get("source_digest") != digest or not digest:
        return None
    return record


def letter_digest(message_id: str, body: Any) -> str:
    """The receipt key: the envelope digest, or, for producers that write none (thrift, sentinel), the id's sha256."""
    digest = body.get("digest") if isinstance(body, dict) else None
    if isinstance(digest, str) and digest.strip():
        return digest
    return hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()


def _receipt_name(digest: Any) -> str:
    clean = "".join(ch for ch in str(digest or "") if ch.isalnum())
    if not clean:
        raise ValueError("a wake receipt needs a digest")
    return f"{clean}.json"


def pending_wake_path(project: Path, target: str, digest: Any) -> Path:
    watch_file(project, target)  # validates the tool name
    return Path(project) / PRESENCE_DIR / "pending_wake" / target / _receipt_name(digest)


def acked_wake_path(project: Path, target: str, digest: Any) -> Path:
    watch_file(project, target)
    return Path(project) / PRESENCE_DIR / "pending_wake" / target / "acked" / _receipt_name(digest)


def process_identity(pid: int) -> int | None:
    """U141-A: the creation time of a live process, so a reused PID never looks like the old owner. None if gone."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return None
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        kernel32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return None
        try:
            code = wintypes.DWORD()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) and code.value != still_active:
                return None  # an exited process whose handle is still held elsewhere
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return None
            return (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        try:
            os.kill(pid, 0)
        except OSError:
            return None
        return 0  # alive, but this platform has no /proc creation time; PID reuse cannot be told apart here
    # Field 22 (starttime) follows the ")" that closes the command name, which may itself hold spaces.
    fields = stat.rsplit(")", 1)[-1].split()
    try:
        return int(fields[19])
    except (IndexError, ValueError):
        return None


def _write_atomic(path: Path, record: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    replace_with_retry(tmp, path)


def _receipt_state(path: Path, clock: Callable[[], float]) -> str:
    """EXISTS for a full record or a fresh placeholder; CORRUPT for anything else (kept as evidence)."""
    try:
        raw = path.read_bytes()
        age = clock() - path.stat().st_mtime
    except FileNotFoundError:
        return "MISSING"
    except OSError:
        return "EXISTS"  # being replaced right now (Windows sharing violation): fail closed, no second wake
    if not raw:
        return "EXISTS" if age < PLACEHOLDER_GRACE_S else "CORRUPT"
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "CORRUPT"
    if not isinstance(record, dict) or any(key not in record for key in RECEIPT_KEYS):
        return "CORRUPT"
    return "EXISTS"


def claim_wake(project: Path, target: str, message_id: str, digest: Any, *,
               clock: Callable[[], float] | None = None) -> str:
    """U141-A: ACKED | CLAIMED | EXISTS | CORRUPT. Only CLAIMED may wake a session, so a letter wakes at most once."""
    clock = clock or time.time
    pending = pending_wake_path(project, target, digest)
    if acked_wake_path(project, target, digest).is_file():
        return "ACKED"
    pending.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(pending), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        state = _receipt_state(pending, clock)
        return "EXISTS" if state == "MISSING" else state
    os.close(fd)
    pid = os.getpid()
    _write_atomic(pending, {"target": target, "message_id": message_id, "digest": digest, "pid": pid,
                            "process_created": process_identity(pid), "created_at": clock()})
    return "CLAIMED"


def lock_file(project: Path, tool: str) -> Path:
    watch_file(project, tool)
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.lock.json"


def _lock_owner_live(path: Path) -> bool:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return False  # unreadable: treated as stale and replaced
    if not isinstance(record, dict):
        return False
    created = process_identity(record.get("pid"))
    return created is not None and created == record.get("process_created")


def _take_locks(project: Path, tools: tuple[str, ...], mine: dict[str, Any]) -> tuple[list[str], str | None]:
    taken: list[str] = []
    for tool in tools:
        path = lock_file(project, tool)
        path.parent.mkdir(parents=True, exist_ok=True)
        if _lock_owner_live(path):
            return taken, tool
        _write_atomic(path, mine)
        taken.append(tool)
    return taken, None


def _release_locks(project: Path, tools: list[str], mine: dict[str, Any]) -> None:
    """Remove only this watcher's locks; a replacement watcher keeps its own."""
    for tool in tools:
        path = lock_file(project, tool)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(record, dict) and record.get("pid") == mine["pid"] and \
                    record.get("process_created") == mine["process_created"] and record.get("token") == mine["token"]:
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            pass


def _stalled_wait(project: Path, tools: tuple[str, ...], clock: Callable[[], float]) -> dict[str, Any] | None:
    """U179: the first stalled wait one of `tools` has a part in and has not been woken for yet."""
    from v7_harness.coord import stall

    for tool in tools:
        try:
            result = stall.scan(project, tool, now=clock())
        except (OSError, ValueError):
            continue  # a locked or unreadable stall state: the next scan looks again, the watch goes on
        for entry in result["stalled"] + result["blocked"]:
            if tool not in (entry["author"], entry["waiting_on"], entry.get("owner")):
                continue
            # One receipt per wait instance: a step that waits again later has a new `since` and wakes again.
            key = f"stall:{entry['item']}:{entry['since']}"
            if claim_wake(project, tool, key, hashlib.sha256(key.encode("utf-8")).hexdigest(),
                          clock=clock) == "CLAIMED":
                return {"id": key, "reason": "STALLED_WAIT", "item": entry["item"], "kind": entry["kind"],
                        "waiting_on": entry["waiting_on"], "age_s": entry["age_s"], "owner": entry.get("owner"),
                        "requested_target": tool}
    return None


def _native_eligible(project, message_id, body, session, now):
    """Native listeners must reject stale and foreign work before consuming any claim."""
    from .stop_gate import _foreign, LETTER_FRESH_S
    from .continuity import _desk_matches
    if not isinstance(body, dict) or not _desk_matches(project, session):
        return False
    if body.get('requested_target') != 'claude' or body.get('delta') == 'ACK_ONLY':
        return False
    from . import windows as _windows
    unbound_card = (body.get('card') and not (body.get('native_receiver') or body.get('window'))
                    and _windows.window_for(project, str(body['card']), 'claude') is None)
    if not unbound_card and _foreign(project, 'claude', session, body):
        return False
    try:
        stamp = (project / '.coord/mailbox/inbox' / f'{message_id}.json').stat().st_mtime
        desk = json.loads((project / '.coord/presence/user_desk_claude.json').read_text(encoding='utf-8'))
        since = desk.get('at', now - LETTER_FRESH_S)
        return isinstance(since, (int, float)) and max(since, now - LETTER_FRESH_S) <= stamp <= now
    except (OSError, ValueError):
        return False


def _schedule_ready_wake(project: Path, tools: tuple[str, ...], clock: Callable[[], float]) -> dict[str, Any] | None:
    """U253: level-triggered wake when `.coord/master_schedule.json` has an unclaimed READY/ACTIVE phase for `tools`."""
    from .next_card import TERMINAL

    sched_path = Path(project) / ".coord" / "master_schedule.json"
    try:
        raw = json.loads(sched_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    phases = raw.get("phases") if isinstance(raw, dict) else None
    if not isinstance(phases, list):
        return None
    done_ids = {
        str(p.get("phase_id") or p.get("id") or "")
        for p in phases
        if isinstance(p, dict) and p.get("state") in TERMINAL
    }
    for p in phases:
        if not isinstance(p, dict):
            continue
        state = p.get("state")
        if state not in ("READY", "ACTIVE"):
            continue
        if p.get("blocker_kind") in ("SAFETY_GATE", "UNAPPROVED_REVIEW_DEPENDENCY"):
            continue
        owner = p.get("owner_tool") or p.get("owner")
        target = owner if owner in tools else (tools[0] if owner == "all" and tools else None)
        if not target:
            continue
        deps = p.get("depends_on") or []
        if isinstance(deps, list) and any(str(d) not in done_ids for d in deps):
            continue
        phase_id = str(p.get("phase_id") or p.get("id") or "").strip()
        if not phase_id:
            continue
        stamp = str(p.get("updated_at") or p.get("rerouted_at") or raw.get("updated_at") or state)
        sched_key = f"sched_{phase_id}"
        sched_digest = hashlib.sha256(f"u253-sched:{target}:{phase_id}:{state}:{stamp}".encode("utf-8")).hexdigest()
        if claim_wake(project, target, sched_key, sched_digest, clock=clock) == "CLAIMED":
            return {
                "id": sched_key,
                "kind": "SCHEDULE_READY",
                "actor": "scheduler",
                "requested_target": target,
                "card": phase_id,
                "wake_class": "ACTIONABLE",
            }
    return None


def _request_wake(project: Path, tools: tuple[str, ...], session: str | None, clock: Callable[[], float],
                  started_at: float) -> dict[str, Any] | None:
    """U277 rev 2 (docs 5.4): an exact answer to a verdict request this tool made wakes the session once. The registry
    CAS (claim_wake) makes one watcher the winner; a fuzzy hint wakes once and closes nothing. A registry error keeps
    the watch running: the next scan looks again."""
    from v7_harness.coord import requests

    try:
        transitions = requests.scan(project, now=clock())
        for row in requests.answered(project):
            if row.get("requester") not in tools:
                continue
            request_id = str(row["request_id"])
            if requests.claim_wake(project, request_id, session=session or "", now=clock(), started_at=started_at):
                return {"reason": "REQUEST_ANSWERED", "id": request_id, "request_id": request_id,
                        "outcome": row.get("outcome", ""), "event_id": row.get("answer_ref", ""),
                        "requested_target": row.get("requester")}
        for item in transitions:
            if item.get("type") != "HINT" or item.get("requester") not in tools:
                continue
            bound = str(item.get("requester_session") or "")
            if session and bound and bound != session:
                continue
            return {"reason": "REQUEST_HINT", "id": item["request_id"], "request_id": item["request_id"],
                    "event_id": item["event_id"], "requested_target": item.get("requester")}
    except (OSError, ValueError, requests.RequestError):
        return None
    return None


def watch(project: Path, tools: tuple[str, ...], *, timeout_s: float = DEFAULT_TIMEOUT_S,
          interval_s: float = DEFAULT_INTERVAL_S, clock: Callable[[], float] | None = None,
          sleep: Callable[[float], None] | None = None, wakes_session: bool = False,
          policy: str = "legacy", native_session: str | None = None,
          requester_session: str | None = None) -> dict[str, Any] | None:
    """Return the first letter addressed to one of `tools` that was not in the inbox when the watch began.

    Letters already waiting are what `coord inbox` shows at session start; the watch reports only new ones, so a
    re-armed watch never wakes the session twice for the same letter. None means the timeout passed.

    U141-A `policy="structured"` (the CLI default): one watcher per target (a live owner returns
    ALREADY_WATCHING), no start snapshot, and only an ACTIONABLE letter whose wake receipt this watcher CLAIMED wakes
    the session. The receipt, not the snapshot, keeps a re-armed watcher from waking twice.
    """
    if policy not in ("legacy", "structured"):
        raise ValueError(f"unknown watch policy: {policy}")
    clock = clock or time.time
    sleep = sleep or time.sleep  # looked up per call so tests and callers can patch time.sleep
    for tool in tools:
        watch_file(project, tool)  # validates the name before anything is written
    # U59: a project whose first letter has not arrived yet has no mailbox folder; waiting on it is still valid.
    mailbox_dir = Path(project) / ".coord" / "mailbox"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    box = Mailbox(mailbox_dir)
    structured = policy == "structured"
    token = uuid.uuid4().hex
    locks: list[str] = []
    mine = {"pid": os.getpid(), "process_created": process_identity(os.getpid()), "token": token}
    if structured and not native_session:
        locks, owned_by_other = _take_locks(project, tools, mine)
        if owned_by_other is not None:
            _release_locks(project, locks, mine)
            return {"state": "ALREADY_WATCHING", "tool": owned_by_other}
    seen = set() if structured else set(box.list_inbox())
    deadline = clock() + timeout_s
    next_stall_scan = deadline - timeout_s  # the first scan runs at once; no extra clock read (U117 test counts them)
    started_at = deadline - timeout_s  # the watch's start, without an extra clock read (see above)
    try:
        while True:
            if native_session:
                from .continuity import _desk_matches
                if not _desk_matches(Path(project), native_session):
                    return None
            _beat(project, tools, token, interval_s, clock(), wakes_session,
                  session=requester_session or "", process_created=mine["process_created"])
            if not native_session:
                # U277: every scan, not on the stall cadence; a request answered while this watch sleeps wakes it.
                woken = _request_wake(Path(project), tools, requester_session, clock, started_at)
                if woken is not None:
                    return woken
            # U94-R1: decide on the name first and read a letter's file only when its id is new to this watch.
            for message_id in box.list_inbox():
                if message_id in seen:
                    continue
                # U64-F: `coord deliver` already handed this letter to a Claude process (its accepted receipt
                # exists); waking the interactive session too would pay a second turn for the same letter.
                if (mailbox_dir / "delivery" / "accepted" / f"{message_id}.json").is_file():
                    seen.add(message_id)
                    continue
                # U66: the marker exists before a direct-dispatch letter is published. Do not mark it seen: if the
                # dispatch fails, the sender removes the marker and this same watcher becomes the fallback route.
                pending = mailbox_dir / "delivery" / "pending" / f"{message_id}.json"
                try:
                    pending_live = clock() - pending.stat().st_mtime <= PENDING_MAX_AGE_S
                except OSError:
                    pending_live = False
                if pending_live:
                    continue
                data = box.read_message(message_id)
                if data is None:
                    continue  # claimed meanwhile, or not readable yet: the next scan looks again, as peek() did
                seen.add(message_id)
                payload = data.get("payload")
                if native_session and not _native_eligible(Path(project), message_id, payload, native_session, clock()):
                    continue
                if _addressed(payload, tools):
                    body = payload if isinstance(payload, dict) else {}
                    found = {"id": message_id, "kind": body.get("kind"), "actor": body.get("actor"),
                             "requested_target": body.get("requested_target") or body.get("to")}
                    if not structured:
                        return found
                    target = found["requested_target"]
                    target = target if target in tools else tools[0]
                    cls, _diag = classify(body, migration_record(project, message_id, body.get("digest")))
                    if cls == "LEGACY" and wakes_session and str(body.get("actor") or "") not in ("", target):
                        from v7_harness.coord.deliver import _requires_wake
                        if _requires_wake(str(body.get("message") or "")):
                            cls = "ACTIONABLE"
                    if cls != "ACTIONABLE":
                        continue  # NOTICE, INVALID and LEGACY never wake; the hook shows them at zero tokens
                    digest = letter_digest(message_id, body)
                    if native_session:
                        if acked_wake_path(project, target, digest).is_file():
                            continue
                        digest = hashlib.sha256(f'native:{native_session}:{digest}'.encode()).hexdigest()
                    if claim_wake(project, target, message_id, digest,
                                  clock=clock) == "CLAIMED":
                        return {**found, "wake_class": cls}
            if structured and not native_session and clock() >= next_stall_scan:
                next_stall_scan = clock() + STALL_SCAN_S
                stalled = _stalled_wait(Path(project), tools, clock)
                if stalled is not None:
                    return stalled
            if structured and wakes_session and not native_session:
                sched_wake = _schedule_ready_wake(Path(project), tools, clock)
                if sched_wake is not None:
                    return sched_wake
            if clock() >= deadline:
                return None
            sleep(interval_s)
    finally:
        _clear(project, tools, token)
        _release_locks(project, locks, mine)
===FILE: v7_harness/coord/stop_gate.py===
"""U146-A: the end-of-turn gate and the push-grant check of the nonstop chain.

`gate` blocks a turn end once while the tool's own NEXT card is ready, then lets the stop through unless verified
progress happened (Antigravity audit relay_5d1e13d0 [HIGH]). `push_check` reads the user's standing push grant,
deny by default.

U146-B: the same gate is the Stop hook of Codex and Antigravity too (docs/75 §5), a LIMITED tool is not pushed into a
new card (R7), and a grant with `expires_at` stops counting once it passes.
"""

from __future__ import annotations

import datetime as _dt
import fnmatch
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from v7_harness import pilot_dirs
from v7_harness.coord import next_card

# Each block is a full-context paid turn, so one re-entry without progress, then fail closed (audit relay_5d1e13d0).
MAX_BLOCKS = 1
# Stage 0: Claude and Codex Stop hooks hold a turn with "block" (https://learn.chatgpt.com/docs/hooks); Antigravity's
# Stop hook re-enters its loop with "continue" (https://antigravity.google/docs/hooks).
HOLD_DECISION = {"claude": "block", "codex": "block", "antigravity": "continue"}
# R7: a tool whose desk says it has no budget left is not asked to start a new card.
NO_BUDGET_STATES = ("LIMITED",)
# U210: a letter counts as processed only once `coord ack` moves it out of the inbox. The inbox backlog that predates
# this rule (1885 items on 2026-10-18) is not news, so only letters younger than one day hold a stop.
LETTER_FRESH_S = 86400
# Ids named in one hold reason; the rest are counted.
LETTER_NAMES = 5


def hook_session(payload: Any) -> str | None:
    """The session that owns the claim: `session_id` (Claude, Codex) or `conversationId` (Antigravity)."""
    if not isinstance(payload, dict):
        return None
    for key in ("session_id", "conversationId"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:200]  # same bound as hook_context.hook_session
    return None


def should_gate(payload: Any) -> bool:
    """Antigravity reports `fullyIdle: false` while work is still pending; only a fully idle stop is held."""
    return not (isinstance(payload, dict) and payload.get("fullyIdle") is False)


def project_owns_gate(project: Path, tool: str) -> bool:
    """A project whose own Claude settings already run the gate (this repo since U146-A) keeps it; the global hook
    steps aside so one stop is gated once."""
    if tool != "claude":
        return False
    try:
        text = (Path(project) / ".claude" / "settings.json").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return "coord stop-gate" in text and "--from-hook" not in text


def progress_signature(project: Path) -> list:
    """Verified advancement only: a commit, a schedule status change, or a new pilot run.

    Ledger rows, results, `.coord/log` and `.coord/presence` are not progress: a pilot failing repeatedly writes them
    without advancing (the audit's spin case).
    """
    project = Path(project)
    try:
        done = subprocess.run(["git", "-C", str(project), "rev-parse", "HEAD"], capture_output=True, text=True,
                              timeout=10)
        head = done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        head = None
    schedule = next_card.schedule_path(project)
    schedule_mtime = schedule.stat().st_mtime if schedule.is_file() else None
    # U146a-R: runs live in every pilot dir (pilot_dirs.discover: .coord/pilot, .coord, .work/<x>), of this worktree and
    # of the main checkout; one summary.json per run, so a missing dir simply adds nothing.
    roots = {Path(d).resolve() for base in (project, next_card.coord_root(project)) for d in pilot_dirs.discover(base)}
    mtimes = [s.stat().st_mtime for root in sorted(roots) for s in (root / "runs").glob("*/summary.json")]
    return [head, schedule_mtime, max(mtimes) if mtimes else None, len(mtimes)]


def _foreign(root: Path, tool: str, session: str | None, body: dict) -> bool:
    from v7_harness.coord import windows

    window, card = body.get("native_receiver") or body.get("window"), body.get("card")
    if not window and not card:
        return False
    if not session:
        return False  # no session to compare: show the letter; the bound ACK guard keeps it from being erased
    if window and window != session:
        return True
    if not card:
        return False
    try:
        return windows.window_for(root, str(card), tool) != session
    except (OSError, ValueError, TypeError, AttributeError):
        return True


def pending_letters(project: Path, tool: str, now: float | None = None, session: str | None = None) -> list[str]:
    """U210: ids of fresh ACTIONABLE letters addressed to `tool` that are still in the inbox (not yet acked)."""
    from v7_harness.coord import desk_delta

    inbox = next_card.coord_root(Path(project)) / ".coord" / "mailbox" / "inbox"
    moment = time.time() if now is None else now
    found = []
    for path in sorted(inbox.glob("*.json")) if inbox.is_dir() else []:
        if path.name.startswith("evt_") or desk_delta.own_letter(path, tool):
            continue
        body = desk_delta._payload(path)
        target = desk_delta.canonical(str(body.get("requested_target") or body.get("to") or ""))
        try:
            fresh = moment - path.stat().st_mtime <= LETTER_FRESH_S
        except OSError:
            fresh = False
        if target == tool and body.get("wake_class") == "ACTIONABLE" and fresh and not _foreign(next_card.coord_root(Path(project)), tool, session, body):
            found.append(path.stem)
    return found


def letter_hold(project: Path, tool: str, now: float | None = None, session: str | None = None) -> dict[str, Any] | None:
    """U210: an unread letter is owed work even when the schedule names no card (relay_9f21437a receipt); each letter
    holds once, so a letter left unacked never spins the gate."""
    import hashlib

    letters = pending_letters(project, tool, now=now, session=session)
    scope = hashlib.sha256(session.encode("utf-8")).hexdigest()[:12] if session else "nosession"
    guard = Path(project) / ".coord" / "presence" / f"stop_gate_{tool}_letters_{scope}.json"
    try:
        held = json.loads(guard.read_text(encoding="utf-8")).get("held", [])
    except (OSError, ValueError, AttributeError):
        held = []
    new = [name for name in letters if name not in held]
    if not new:
        return None
    _write_atomic(guard, {"held": letters})
    more = f" (+{len(new) - LETTER_NAMES} more)" if len(new) > LETTER_NAMES else ""
    return {"decision": HOLD_DECISION.get(tool, "block"),
            "reason": f"Unread letter(s) for {tool}: {', '.join(new[:LETTER_NAMES])}{more}. Open each, act on it, "
                      "deliver the result, then `coord ack --id <full id>`"}


def _write_atomic(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _request_hold(project: Path, tool: str, session: str, now: float | None = None) -> dict[str, Any] | None:
    """U277 rev 2 (docs 5.6): hold a turn end while this session's verdict request is open. A live watcher of this
    session releases the hold. Each request blocks once; the next stop with no live watcher is let through and logged
    once as STOP_UNGUARDED (a visible fallback, never a silent loop). Any failure returns None, never a block."""
    import hashlib

    try:
        from v7_harness.coord import requests, stream, watch

        rows = requests.open_for(project, tool, session=session)
        if not rows:
            return None
        ids = [str(row["request_id"]) for row in rows]
        scope = hashlib.sha256(session.encode("utf-8")).hexdigest()[:12]
        guard_path = Path(project) / ".coord" / "presence" / f"stop_gate_request_{tool}_{scope}.json"
        try:
            state = json.loads(guard_path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                state = {}
        except (OSError, ValueError):
            state = {}
        entries = {rid: state[rid] if isinstance(state.get(rid), dict)
                   else {"blocks": 0, "lease_seen": False, "logged": False} for rid in ids}
        if watch.watcher_wakes_for(Path(project), tool, session, now=now):
            for entry in entries.values():
                entry["lease_seen"] = True  # a live watcher of this session: the next lapse starts a fresh count
            _write_atomic(guard_path, {**state, **entries})
            return None
        pending = []
        for rid, entry in entries.items():
            if entry["lease_seen"]:
                entry.update(blocks=0, lease_seen=False)
            if entry["blocks"] >= MAX_BLOCKS:
                if not entry["logged"]:
                    stream.append_event(Path(project), actor=tool, kind="BLOCKED", step="U277-STOP-UNGUARDED",
                                        summary=f"STOP_UNGUARDED request:{rid} open after {MAX_BLOCKS} block with no "
                                                f"live {tool} watcher; turn let through",
                                        refs=[f"request:{rid}"], evidence={})
                    entry["logged"] = True
                continue
            pending.append(rid)
        for rid in pending:
            entries[rid]["blocks"] += 1
        _write_atomic(guard_path, {**state, **entries})
        if not pending:
            return None
        return {"decision": HOLD_DECISION.get(tool, "block"),
                "reason": f"Open verdict request(s) {', '.join(pending[:LETTER_NAMES])}: keep "
                          f"`coord watch --target {tool} --wakes-session` running in the background, then take the "
                          "next ready card"}
    except Exception:  # noqa: BLE001 - a broken registry must not trap the turn; the next stop looks again
        return None


def gate(project: Path, tool: str, session: str | None = None, now: float | None = None) -> dict[str, Any] | None:
    project = Path(project)
    if not session:
        return None  # U146a-R: no session id, no claim and no block (UNKNOWN is no ground for acting)
    from v7_harness.coord import presence

    if presence.read(project, tool, now=now).get("state") in NO_BUDGET_STATES:
        return None  # R7: no claim and no paid re-entry for a tool without budget
    hold = letter_hold(project, tool, now=now, session=session)
    if hold is not None:
        return hold
    request_hold = _request_hold(project, tool, session, now)
    if request_hold is not None:
        return request_hold
    step = next_card.next_step(project, tool, claim=True, session=session, now=now)
    if step.get("state") != "NEXT":
        return None
    card = step["card"]
    guard_path = project / ".coord" / "presence" / f"stop_gate_{tool}.json"
    try:
        guard = json.loads(guard_path.read_text(encoding="utf-8"))
        if not isinstance(guard, dict):
            guard = {}
    except (OSError, ValueError):
        guard = {}
    progress = progress_signature(project)
    blocks = guard.get("blocks") if isinstance(guard.get("blocks"), int) else 0
    if guard.get("card") != card or guard.get("progress") != progress:
        blocks = 0
    if blocks >= MAX_BLOCKS:
        log = project / ".coord" / "log" / "stop_gate.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        row = {"kind": "BLOCKED", "tool": tool, "card": card, "blocks": blocks,
               "at": time.time() if now is None else now}
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return None
    _write_atomic(guard_path, {"card": card, "blocks": blocks + 1, "progress": progress})
    return {"decision": HOLD_DECISION.get(tool, "block"),
            "reason": f"NEXT {card} (owner {step.get('owner')}) is ready: start it now; human-list items go in the "
                      "final batched report"}


def _expiry(value: Any) -> float | None:
    """Epoch seconds of `expires_at`, or None when doubtful: a bool, a naive time (no offset) or any other text."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    try:
        moment = _dt.datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment.timestamp() if moment.tzinfo is not None else None


def push_check(project: Path, branch: str, force: bool = False) -> dict[str, str]:
    """R2 + U146a-R: ALLOW only a branch the grant on origin/main names. A working-tree edit or a local commit is
    agent-writable, so only the blob a human merged counts. Every missing or doubtful case is DENY."""
    root = next_card.coord_root(Path(project))
    try:
        done = subprocess.run(["git", "-C", str(root), "show", "refs/remotes/origin/main:.coord/grants/push.json"],
                              capture_output=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"decision": "DENY", "reason": f"git unavailable: {exc}"}
    if done.returncode != 0:
        return {"decision": "DENY", "reason": "no push grant committed on origin/main"}
    try:
        grant = json.loads(done.stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        return {"decision": "DENY", "reason": f"no readable push grant: {exc}"}
    if not isinstance(grant, dict) or grant.get("enabled") is not True:
        return {"decision": "DENY", "reason": "push grant not enabled"}
    if "expires_at" in grant:
        expires = _expiry(grant["expires_at"])
        if expires is None:
            return {"decision": "DENY", "reason": "push grant expires_at unreadable (ISO 8601 with offset, or epoch)"}
        if time.time() >= expires:
            return {"decision": "DENY", "reason": "push grant expired"}
    if force and grant.get("force") is not True:
        return {"decision": "DENY", "reason": "force push is never granted"}
    never = grant.get("never") if isinstance(grant.get("never"), list) else []
    if any(fnmatch.fnmatchcase(branch, str(pat)) for pat in never):
        return {"decision": "DENY", "reason": f"{branch} is in never"}
    branches = grant.get("branches") if isinstance(grant.get("branches"), list) else []
    if not any(fnmatch.fnmatchcase(branch, str(pat)) for pat in branches):
        return {"decision": "DENY", "reason": f"{branch} matches no granted pattern"}
    return {"decision": "ALLOW", "reason": f"{branch} matches the push grant"}
===FILE: v7_harness/coord/stall.py===
"""U166: waiting is a failure. A step that waits too long on one tool or on the user is rerouted by agreement.

윤겸스 (2026-10-05): Claude ended a turn with "Codex will re-review when it returns" while Antigravity could act, and
listed merges as user work while Antigravity could merge. Every tool's per-prompt hook (`--delta`, all 3 tools) runs
`scan`: it finds the waits on disk (queued verdict requests, waiting master-schedule phases that are not on the
Safety human-only list), and once one is older than
MAX_WAIT_S it names the tools that can do the step instead. The tool whose hook ran records its agreement; when every
ACTIVE tool has agreed (absent tools excluded), the reroute is written into `.coord/master_schedule.json`: a waiting
phase is reassigned in place as READY to the first capable tool, a waiting letter gets a new READY phase. Only then is
the owner told to act. Peers learn of a stall and its votes in their own hook output, which is how a
notice counts as delivered in UAOS. No model is called: reading a few small files costs no paid tokens.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import ingress
from .merge_route import MERGERS
from .presence import TOOLS

# Half the Claude main-session cache lifetime (1 h, global rules): a reroute starts before a resumed waiting session
# pays a full cache rebuild, and a normal review round trip (minutes) never trips it.
MAX_WAIT_S = 1800
# U203: a ballot open for two vote windows (a vote expires after MAX_WAIT_S) without every ACTIVE tool is held
# by an idle tool, not a deciding one; its missing vote no longer holds the reroute (Raft-style election timeout).
QUORUM_TIMEOUT_S = 2 * MAX_WAIT_S
# Who can do each kind of step, in order of preference. merge: 윤겸스's order (merge_route.MERGERS). verdict: Codex
# conducts, Antigravity is the independent judge when it is away. letter: any peer that can read and act on it.
# implement: Claude is the default implementer (global rules), then Antigravity, then Codex.
CAPABILITY = {
    "merge": MERGERS,
    "verdict": ("codex", "antigravity"),
    "implement": ("claude", "antigravity", "codex"),
}
WAIT_STATES = ("HUMAN", "REVIEW", "BLOCKED")
# How long an adoption notice stays visible after its wait is gone: the Claude/Codex usage window is 5 hours (global
# rules), so a tool that was paused by its limit still hears of the reroute at its first prompt back.
NOTICE_KEEP_S = 6 * 3600
# The Safety human-only list (global rules): a phase that names one of these stays with 윤겸스 and is never rerouted,
# even when it also says "merge" (Antigravity design audit relay_45a03503, defect 1). Matching is deliberately broad:
# a false hit only leaves a step with the user, a miss would hand a human decision to a tool.
HUMAN_ONLY_RE = re.compile(
    r"delet|deploy|publish|public post|store submission|spend|payment|billing|money|purchase|account|credential|"
    r"secret|password|permission|system setting|push|삭제|배포|게시|공개|지출|결제|구매|계정|자격|비밀|권한|시스템 설정|푸시",
    re.IGNORECASE)
STATE_DIR = Path(".coord") / "stall"
SCHEDULE = Path(".coord") / "master_schedule.json"
QUEUED = Path(".coord") / "mailbox" / "delivery" / "queued"
# U214: a dispatched letter waits in INBOX until `coord ack` moves it to ACK; deliver stamps the dispatch moment once
# in the ACCEPTED receipt; dispatched waits count only from the WATERMARK written at the first scan.
INBOX = Path(".coord") / "mailbox" / "inbox"
ACK = Path(".coord") / "mailbox" / "ack"
ACCEPTED = Path(".coord") / "mailbox" / "delivery" / "accepted"
WATERMARK = STATE_DIR / "watermark.json"
TERMINAL = ("DONE", "CANCELLED")
AGY_REPLY = re.compile(r"\[agy-auto\] re ([A-Za-z0-9_]+)")


def _item_id(item: str) -> str:
    return "STALL-" + hashlib.sha256(item.encode("utf-8")).hexdigest()[:8]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _letter_waits(project: Path, schedule: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    found = []
    root = project / QUEUED
    answered = _answered(project, _watermark(project, time.time()))
    ended = {str(p.get("phase_id")) for p in (schedule if isinstance(schedule, dict) else {}).get("phases") or []
             if isinstance(p, dict) and p.get("state") in TERMINAL}
    for target_dir in sorted(p for p in root.glob("*") if p.is_dir()):
        target = target_dir.name
        for letter in sorted(target_dir.glob("*.json")):
            try:
                payload = json.loads(letter.read_text(encoding="utf-8"))
                since = letter.stat().st_mtime
            except (OSError, ValueError):
                continue
            if not isinstance(payload, dict):
                continue
            # Only a letter that asks for a verdict is a step someone waits on; a status note or ACK is not
            # (relay_45a03503, defect 1), and U120 already uses this token as the wake word.
            # U277 L1: the queued record carries the structured flag; the token stays for letters sent before it.
            if payload.get("verdict_requested") is not True and "VERDICT_REQUESTED=YES" not in str(payload.get("message", "")):
                continue
            body = _payload(project / INBOX / letter.name) or payload
            if ((project / ACK / letter.name).exists() or letter.stem in answered
                    or str(body.get("card", "")) in ended):
                continue
            found.append({"item": f"letter:{target}:{letter.stem}", "kind": "verdict", "waiting_on": target,
                          "author": str(payload.get("actor", "")), "since": since, "pr": ""})
    found.extend(_request_waits(project, ended, {item["item"].rsplit(":", 1)[-1] for item in found}))
    return found


def _request_waits(project: Path, ended: set[str], known: set[str]) -> list[dict[str, Any]]:
    """U277 H2: a verdict request whose letter was DISPATCHED and is still OPEN in the registry is a wait, whichever
    route carried it. A request already counted through its queued letter (`known`) is not counted twice."""
    from . import requests

    found = []
    for row in requests.dispatched_open(project):
        request_id = str(row.get("request_id") or "")
        if request_id in known or str(row.get("card") or "") in ended:
            continue
        found.append({"item": f"request:{row.get('target')}:{request_id}", "kind": "verdict",
                      "waiting_on": str(row.get("target") or ""), "author": str(row.get("requester") or ""),
                      "since": float(row.get("created_at") or 0), "pr": ""})
    return found


def _watermark(project: Path, moment: float) -> float:
    """U214: the explicit start of dispatched waits, written once at the first scan, so the inbox history before it
    never bursts into reroutes (Antigravity CE1). An unreadable or malformed watermark counts no letter at all."""
    path = project / WATERMARK
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("since")
    except FileNotFoundError:
        _write_json(path, {"since": moment})
        return moment
    except (OSError, ValueError, AttributeError):
        return float("inf")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else float("inf")


def _payload(path: Path) -> dict[str, Any] | None:
    """U214: the payload of one mailbox letter; None when it is unreadable or has no payload object."""
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    body = record.get("payload") if isinstance(record, dict) else None
    return body if isinstance(body, dict) else None


def _reply_to(body: dict[str, Any]) -> str:
    """U214: the letter id a reply answers: payload `in_reply_to`, the same key in a JSON message, or `[agy-auto] re`."""
    value, message = body.get("in_reply_to"), str(body.get("message", ""))
    if not value and message.lstrip().startswith("{"):
        try:
            inner = json.loads(message)
        except ValueError:
            inner = None
        value = inner.get("in_reply_to") if isinstance(inner, dict) else None
    if not value and (match := AGY_REPLY.match(message)):
        value = match.group(1)
    return value if isinstance(value, str) else ""


def _dispatched_at(project: Path, message_id: str) -> float | None:
    """U214: the dispatch moment deliver wrote once in the accepted receipt; a file mtime moves on rewrite or copy."""
    try:
        record = json.loads((project / ACCEPTED / f"{message_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    stamp = record.get("timestamp_ns") if isinstance(record, dict) else None
    ok = (isinstance(stamp, int) and not isinstance(stamp, bool) and stamp > 0
          and record.get("state", "DISPATCHED") == "DISPATCHED")
    return stamp / 1e9 if ok else None


def _answered(project: Path, mark: float) -> set[str]:
    """U214: ids answered by any reply written since the watermark, read or not yet read (inbox and ack)."""
    found = set()
    for folder in (INBOX, ACK):
        for path in (project / folder).glob("*.json"):
            try:
                fresh = path.stat().st_mtime >= mark
            except OSError:
                continue
            body = _payload(path) if fresh else None
            if body is not None:
                found.add(_reply_to(body))
    return found


def _inbox_waits(project: Path, schedule: dict[str, Any] | None, moment: float) -> list[dict[str, Any]]:
    """U214: deliver dispatches at once, so a sent verdict request waits in the inbox until it is acked, answered
    (in_reply_to) or its card's phase is terminal; only letters dispatched after the watermark count."""
    from .desk_delta import canonical

    mark = _watermark(project, moment)
    ended = {str(p.get("phase_id")) for p in (schedule or {}).get("phases") or []
             if isinstance(p, dict) and p.get("state") in TERMINAL}
    answered, found = _answered(project, mark), []
    for path in sorted((project / INBOX).glob("*.json")):
        body, since = _payload(path), _dispatched_at(project, path.stem)
        if (path.name.startswith("evt_") or body is None or since is None or since < mark
                or path.stem in answered or (project / ACK / path.name).exists()):
            continue
        asked = body.get("verdict_requested") is True or "VERDICT_REQUESTED=YES" in str(body.get("message", ""))
        target = canonical(str(body.get("requested_target") or body.get("to") or ""))
        if body.get("wake_class") == "ACTIONABLE" and asked and target and str(body.get("card", "")) not in ended:
            found.append({"item": f"letter:{target}:{path.stem}", "kind": "verdict", "waiting_on": target,
                          "author": str(body.get("actor", "")), "since": since, "pr": ""})
    return found


def _phase_waits(schedule: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for phase in schedule.get("phases") or []:
        if not isinstance(phase, dict) or not phase.get("phase_id"):
            continue
        state, waiting_on = str(phase.get("state", "")), str(phase.get("waiting_on", ""))
        if state not in WAIT_STATES:
            continue
        if phase.get("blocker_kind") in ("SAFETY_GATE", "SCOPE_DECISION", "HUMAN_AUTH"):
            continue
        if phase.get("implementation_go") is False or phase.get("actuator_verdict") == "STOP_NO_IMPLEMENTATION_GO":
            continue
        text = f"{phase['phase_id']} {phase.get('human', '')} {phase.get('note', '')}".lower()
        if state == "HUMAN" and HUMAN_ONLY_RE.search(text):
            continue
        if "merge" in text:
            kind = "merge"
        elif "verdict" in waiting_on.lower() or state == "REVIEW":
            kind = "verdict"
        else:
            kind = "implement"
        on = waiting_on.split("-")[0] if waiting_on else ("human" if state == "HUMAN" else "unknown")
        found.append({"item": f"phase:{phase['phase_id']}", "kind": kind, "waiting_on": on,
                      "author": str(phase.get("owner_tool", "")), "since": None, "pr": str(phase.get("pr", "")),
                      "declared": _declared(phase.get("waiting_since"))})
    return found


def _declared(value: Any) -> float | None:
    """A phase's own `waiting_since` (epoch seconds or ISO 8601), if it has one."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        from datetime import datetime

        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return None
    return None


def route(wait: dict[str, Any], desk: dict[str, dict[str, Any]]) -> list[str]:
    """Capable ACTIVE tools other than the one waited on; a verdict never goes to its own author."""
    out = []
    for tool in CAPABILITY[wait["kind"]]:
        if tool == wait["waiting_on"] or (desk.get(tool) or {}).get("state") != "ACTIVE":
            continue
        if wait["kind"] == "verdict" and tool == wait["author"]:
            continue
        out.append(tool)
    return out


def action(wait: dict[str, Any], owner: str) -> str:
    if wait["kind"] == "merge":
        pr = wait["pr"].lstrip("#") or "<pr>"
        return (f"uaos coord merge --pr {pr} --head <sha> --verdict <judge relay> "
                f"(merger order {'/'.join(MERGERS)})")
    if wait["kind"] == "verdict":
        return f"{owner} gives the independent verdict (pilot review/judge --reviewer {owner})"
    return f"{owner} takes the step"


def scan(project: Path, tool: str | None, *, now: float | None = None,
         desk: dict[str, dict[str, Any]] | None = None, max_wait_s: int = MAX_WAIT_S) -> dict[str, Any]:
    from .next_card import coord_root
    from .stream import _exclusive

    # One schedule and one stall state for every worktree, kept in the main checkout (U146-A R5).
    project = coord_root(Path(project))
    moment = time.time() if now is None else now
    if desk is None:
        from .presence import read_all

        desk = read_all(project, now=moment)
    present = sorted(t for t in TOOLS if (desk.get(t) or {}).get("state") == "ACTIVE")
    state_dir = project / STATE_DIR
    result: dict[str, Any] = {"stalled": [], "adopted": [], "blocked": [], "error": None}
    with _exclusive(state_dir / "stall.lock"):
        try:
            schedule = _read_json(project / SCHEDULE, {"phases": []})
            if not isinstance(schedule, dict):
                raise ValueError("schedule is not an object")
        except (OSError, ValueError) as exc:
            result["error"] = f"schedule {type(exc).__name__}"
            schedule = None
        seen = _read_json(state_dir / "seen.json", {})
        votes = _read_json(state_dir / "votes.json", {})
        adopted = _read_json(state_dir / "adopted.json", {})
        if not all(isinstance(x, dict) for x in (seen, votes, adopted)):
            result["error"] = "stall state corrupt"
            return result
        letters = {w["item"]: w for w in _inbox_waits(project, schedule, moment) + _letter_waits(project, schedule)}
        waits = list(letters.values()) + (_phase_waits(schedule) if schedule is not None else [])
        live = {w["item"] for w in waits}
        seen = {k: v for k, v in seen.items() if k in live}
        # A phase has waited at least since the schedule file was last written: it was already in its waiting state
        # then, because the file has not changed since. So the first scan of an old wait sees its real age (Codex
        # judge U166-APPLY4, finding 1); a declared `waiting_since` is used when it is earlier still.
        try:
            written = (project / SCHEDULE).stat().st_mtime
        except OSError:
            written = moment
        for wait in waits:
            if wait["since"] is None:
                first = min(float(seen.get(wait["item"], moment)), written, wait.pop("declared", None) or moment)
                wait["since"] = seen[wait["item"]] = first
        changed_schedule = False
        result["ingress"] = []
        for wait in waits:
            age = moment - float(wait["since"])
            done = adopted.get(wait["item"])
            # U215: no ingress 10 s after dispatch probes the receiver; a LIMITED one is replanned now, not at 30 min.
            record = desk.get(wait["waiting_on"]) or {}
            if (decision := ingress.decide(wait, record, moment)) != "WAIT":
                result["ingress"].append({"item": wait["item"], "decision": decision})
            # An adoption covers only the wait instance it was made for; a phase that waits again later is a new
            # instance with a new start and is rerouted again (Codex judge U166-APPLY4, finding 2).
            if age < ingress.limit(wait, record, moment, max_wait_s) or (
                    isinstance(done, dict) and done.get("since") == wait["since"]):
                continue
            owners = route(wait, desk)
            entry = {"item": wait["item"], "kind": wait["kind"], "waiting_on": wait["waiting_on"],
                     "age_s": int(age), "route": owners, "author": wait["author"], "since": wait["since"]}
            if not owners:
                result["blocked"].append(entry)
                continue
            # A vote holds only for this wait instance and this owner, and only while fresh: a vote cast for an
            # earlier instance, another route, or older than the wait limit is dropped (relay_45a03503, defect 4).
            # Absent tools are not counted because presence expires a silent heartbeat to UNKNOWN (presence.py), so
            # a crashed tool leaves the quorum by itself (defect 3). With one ACTIVE tool, that tool is the conductor
            # under the global authority order, so its own agreement suffices.
            ballot = votes.get(wait["item"])
            if (not isinstance(ballot, dict) or ballot.get("owner") != owners[0]
                    or ballot.get("since") != wait["since"] or not isinstance(ballot.get("by"), dict)):
                ballot = {"owner": owners[0], "since": wait["since"], "by": {}}
            ballot.setdefault("opened", moment)  # U203: when this wait instance first had a ballot
            ballot["by"] = {t: ts for t, ts in ballot["by"].items()
                            if isinstance(ts, (int, float)) and moment - ts < max_wait_s}
            if tool:  # U203: the sentinel scans without a vote of its own
                ballot["by"][tool] = moment
            votes[wait["item"]] = ballot
            voters = sorted(ballot["by"])
            entry.update({"owner": owners[0], "action": action(wait, owners[0]), "voters": voters,
                          "present": present})
            result["stalled"].append(entry)
            timed_out = moment - float(ballot["opened"]) >= QUORUM_TIMEOUT_S
            if schedule is not None and present and (set(present) <= set(voters) or timed_out):
                note = "U166 reroute: waiting is a failure"
                original = next((p for p in schedule.get("phases") or [] if isinstance(p, dict)
                                 and wait["item"] == f"phase:{p.get('phase_id')}"), None)
                if original is not None:
                    # Reassign the waiting phase itself, so its dependents stay linked and the tool that was waited
                    # on cannot take the same step again when it returns (Codex judge U166-APPLY3, finding 2).
                    original["rerouted_from"] = {k: original.get(k) for k in
                                                 ("owner_tool", "owner_session", "state", "waiting_on")}
                    original.pop("waiting_on", None)
                    # U203: the old owner's session would bind the transition wake to a thread the new owner
                    # cannot ack
                    original.pop("owner_session", None)
                    original.update({"state": "READY", "owner_tool": owners[0], "action": entry["action"],
                                     "agreed_by": present, "note": note})
                    phase_id = str(original["phase_id"])
                else:
                    phase_id = _item_id(wait["item"])
                    schedule.setdefault("phases", []).append(
                        {"phase_id": phase_id, "state": "READY", "owner_tool": owners[0], "depends_on": [],
                         "source": wait["item"], "kind": wait["kind"], "action": entry["action"],
                         "agreed_by": present, "note": note})
                adopted[wait["item"]] = {"phase_id": phase_id, "owner": owners[0], "at": moment,
                                         "since": wait["since"]}
                result["adopted"].append({"phase_id": phase_id, "source": wait["item"], "owner_tool": owners[0],
                                          "agreed_by": present})
                changed_schedule = True
        if changed_schedule:
            _write_json(project / SCHEDULE, schedule)
        votes = {k: v for k, v in votes.items() if k in live}
        # An adoption is kept while its wait is still on disk, or for NOTICE_KEEP_S after it, so every tool hears of
        # it at its next prompt (a reassigned phase stops being a wait at once).
        adopted = {k: v for k, v in adopted.items() if isinstance(v, dict)
                   and (k in live or moment - float(v.get("at", 0)) < NOTICE_KEEP_S)}
        fresh = {p["source"] for p in result["adopted"]}
        result["settled"] = [{"item": k, "phase_id": v["phase_id"], "owner": v["owner"]}
                             for k, v in sorted(adopted.items()) if k not in fresh]
        _write_json(state_dir / "seen.json", seen)
        _write_json(state_dir / "votes.json", votes)
        _write_json(state_dir / "adopted.json", adopted)
    return result


def hook_lines(project: Path, tool: str, *, now: float | None = None) -> str:
    """The per-prompt hook text: one line per stalled step, shown only when it changed since this tool last saw it."""
    result = scan(project, tool, now=now)
    lines = []
    # Only an agreed reroute tells a tool to act (Codex judge U166-APPLY3, finding 1); before that it is a proposal
    # that this prompt has just agreed to.
    for entry in result["stalled"]:
        if entry["item"] in {p["source"] for p in result["adopted"]}:
            continue
        lines.append(f"WAIT IS FAILURE (U166): {entry['item']} waited {entry['age_s'] // 60} min on "
                     f"{entry['waiting_on']}; proposed reroute → {entry['owner']}: {entry['action']} "
                     f"(agreed {len(entry['voters'])}/{len(entry['present'])} present; adopted when all agree)")
    for phase in result["adopted"]:
        you = " — you take it now" if phase["owner_tool"] == tool else ""
        lines.append(f"ADOPTED (U166): {phase['source']} → {phase['owner_tool']} as {phase['phase_id']} on the "
                     f"master schedule, agreed by {','.join(phase['agreed_by'])}{you}")
    for entry in result.get("settled", []):
        you = " — you take it now" if entry["owner"] == tool else ""
        lines.append(f"REROUTED (U166): {entry['item']} → {entry['owner']} as {entry['phase_id']} on the master "
                     f"schedule (see uaos coord next){you}")
    for entry in result["blocked"]:
        lines.append(f"WAIT IS FAILURE (U166): {entry['item']} waited {entry['age_s'] // 60} min on "
                     f"{entry['waiting_on']} and no ACTIVE tool can take it: log BLOCKED and take the next card")
    text = "\n".join(lines)
    from .next_card import coord_root

    marker = coord_root(Path(project)) / STATE_DIR / f"shown_{tool}.txt"
    try:
        if text and marker.read_text(encoding="utf-8") == text:
            return ""
    except OSError:
        pass
    if text:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(text, encoding="utf-8")
    return text
===FILE: tests/test_u277_request_wake.py===
"""U277 rev 2 (H1+H2): a verdict request is durable, an exact answer wakes its requester once, a fuzzy hint never closes
a request, the turn end is held while a request is open, and a dispatched request counts as a stall wait.

Receipt (2026-10-27, CLAUDE-WAKE-GAP-PR249): a verdict request returned DISPATCHED, the answer came back as a
`coord log --kind BLOCKED` row, and the requester never woke. These tests use real temp project folders, the real
stream writer (`stream.append_event`) and real watcher processes; only the clock is passed in where a test needs it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v7_harness.coord import stream  # noqa: E402

SHA = "09e49ee355605ddd83bc9c0aaaa9d3de77530b77"
PR = "https://github.com/o/r/pull/249"


def _project() -> tuple[tempfile.TemporaryDirectory, Path]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / ".coord").mkdir()
    (root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
    return tmp, root


def _register(root: Path, request_id: str, *, session: str = "sA", now: float | None = None) -> dict:
    from v7_harness.coord import requests

    row = requests.register(root, request_id=request_id, requester="claude", target="codex", card="U275",
                            subject=PR, head=SHA, requester_session=session, now=now)
    requests.mark_delivered(root, request_id, "DISPATCHED")
    return row


def _answer(root: Path, request_id: str, *, actor: str = "codex", kind: str = "BLOCKED",
            outcome: str = "BLOCKED") -> None:
    stream.append_event(root, actor=actor, kind=kind, step="U277-TEST", summary="answer",
                        refs=[f"request:{request_id}"], evidence={"outcome": outcome} if outcome else {})


def _lease(root: Path, session: str, *, expires_in: float = 60.0, pid: int | None = None) -> None:
    from v7_harness.coord import watch

    pid = os.getpid() if pid is None else pid
    target = watch.watch_file(root, "claude")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"tool": "claude", "token": "t", "pid": pid,
                                  "process_created": watch.process_identity(pid),
                                  "expires_at": time.time() + expires_in, "wakes_session": True,
                                  "session": session, "adapter": "claude-bg-task"}), encoding="utf-8")


class RegistryTests(unittest.TestCase):
    def test_register_is_idempotent_and_conflicting_binding_is_refused(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            now = time.time()
            first = requests.register(root, request_id="relay_r1", requester="claude", target="codex", card="U275",
                                      subject=PR, head=SHA, requester_session="sA", now=now)
            again = requests.register(root, request_id="relay_r1", requester="claude", target="codex", card="U275",
                                      subject=PR, head=SHA, requester_session="sA", now=now + 50)
            self.assertEqual(first["rev"], again["rev"])
            with self.assertRaises(requests.RequestError) as cm:
                requests.register(root, request_id="relay_r1", requester="claude", target="codex", card="U275",
                                  subject=PR, head="1" * 40, requester_session="sA", now=now)
            self.assertEqual(cm.exception.code, "REQUEST_ID_CONFLICT")

    def test_exact_answer_moves_only_its_request(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_a")
            _register(root, "relay_b")
            _answer(root, "relay_a", outcome="REVISE")
            requests.scan(root)
            self.assertEqual(requests.get(root, "relay_a")["state"], "ANSWER_OBSERVED")
            self.assertEqual(requests.get(root, "relay_a")["outcome"], "REVISE")
            self.assertEqual(requests.get(root, "relay_b")["state"], "OPEN")

    def test_note_and_wrong_actor_never_answer(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_n")
            _answer(root, "relay_n", actor="antigravity")
            _answer(root, "relay_n", kind="NOTE", outcome="")
            requests.scan(root)
            self.assertEqual(requests.get(root, "relay_n")["state"], "OPEN")

    def test_pending_delivery_reconciles_from_accepted_receipt(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            requests.register(root, request_id="relay_p", requester="claude", target="codex", card="U275",
                              subject=PR, head=SHA, requester_session="sA")
            accepted = root / ".coord" / "mailbox" / "delivery" / "accepted"
            accepted.mkdir(parents=True)
            (accepted / "relay_p.json").write_text("{}", encoding="utf-8")
            requests.reconcile(root)
            row = requests.get(root, "relay_p")
            self.assertEqual((row["state"], row["delivery"]), ("OPEN", "DISPATCHED"))

    def test_registry_failure_refuses_deliver_and_sends_nothing(self) -> None:
        from v7_harness.coord import deliver

        tmp, root = _project()
        with tmp:
            (root / ".coord" / "requests").write_text("not a directory", encoding="utf-8")
            calls: list[tuple] = []

            def runner(*args, **kwargs):
                calls.append(args)
                raise AssertionError("dispatch must not run when the request cannot be recorded")

            result = deliver.deliver(root, message="please judge U275 PR249", actor="claude", target="codex",
                                     card="U275", verdict_requested=True, runner=runner)
            self.assertFalse(result.delivered)
            self.assertEqual(result.reason, "REQUEST_TRACKING_FAILED")
            self.assertEqual(calls, [])
            inbox = root / ".coord" / "mailbox" / "inbox"
            self.assertFalse(inbox.exists() and any(inbox.glob("*.json")))


class WakeTests(unittest.TestCase):
    def test_claim_has_one_winner_across_real_processes(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_mp")
            _answer(root, "relay_mp")
            requests.scan(root)
            # Each child records its start before the shared "go" file, so every claim is later than every start.
            code = ("import json,sys,time;from pathlib import Path;root=Path(sys.argv[1]);started=time.time();"
                    "(root/('ready_'+sys.argv[2])).write_text('1');"
                    "go=root/'go'\nwhile not go.exists():\n    time.sleep(0.01)\n"
                    "sys.path.insert(0,sys.argv[3]);from v7_harness.coord import requests;"
                    "print(json.dumps(requests.claim_wake(root,'relay_mp',session='sA',started_at=started)))")
            procs = [subprocess.Popen([sys.executable, "-c", code, str(root), str(i), str(ROOT)],
                                      stdout=subprocess.PIPE, text=True) for i in range(4)]
            deadline = time.time() + 60
            while time.time() < deadline and sum((root / f"ready_{i}").exists() for i in range(4)) < 4:
                time.sleep(0.02)
            (root / "go").write_text("1")
            outs = [json.loads(proc.communicate(timeout=60)[0].strip().splitlines()[-1]) for proc in procs]
            self.assertEqual(outs.count(True), 1, outs)
            self.assertEqual(requests.get(root, "relay_mp")["state"], "WAKE_PENDING")

    def test_ack_is_session_bound_and_idempotent(self) -> None:
        from v7_harness.coord import requests

        tmp, root = _project()
        with tmp:
            _register(root, "relay_k")
            _answer(root, "relay_k")
            requests.scan(root)
            self.assertTrue(requests.claim_wake(root, "relay_k", session="sA"))
            with self.assertRaises(requests.RequestError) as cm:
                requests.ack(root, "relay_k", session="sB")
            self.assertEqual(cm.exception.code, "ACK_SESSION_MISMATCH")
            self.assertEqual(requests.ack(root, "relay_k", session="sA"), "ACKED")
            self.assertEqual(requests.ack(root, "relay_k", session="sA"), "ALREADY")
            self.assertEqual(requests.open_for(root, "claude", session="sA"), [])

    def test_fuzzy_hint_wakes_once_and_keeps_request_open(self) -> None:
        from v7_harness.coord import requests, watch

        tmp, root = _project()
        with tmp:
            _register(root, "relay_h", now=time.time() - 5)
            stream.append_event(root, actor="codex", kind="BLOCKED", step="U275",
                                summary="PR249 missing check; head 09e49ee REVISE", refs=[], evidence={})
            first = watch.watch(root, ("claude",), timeout_s=3, interval_s=0.2, wakes_session=True,
                                requester_session="sA")
            self.assertEqual((first or {}).get("reason"), "REQUEST_HINT")
            self.assertEqual(requests.get(root, "relay_h")["state"], "OPEN")
            second = watch.watch(root, ("claude",), timeout_s=1.0, interval_s=0.2, wakes_session=True,
                                 requester_session="sA")
            self.assertTrue(second is None or second.get("reason") not in ("REQUEST_HINT", "REQUEST_ANSWERED"))


class StopHoldTests(unittest.TestCase):
    def test_hold_blocks_once_releases_on_live_watcher_and_logs_fallback(self) -> None:
        from v7_harness.coord import stop_gate

        tmp, root = _project()
        with tmp:
            _register(root, "relay_s")
            first = stop_gate.gate(root, "claude", session="sA")
            self.assertEqual((first or {}).get("decision"), "block")
            self.assertIn("relay_s", first.get("reason", ""))
            _lease(root, "sA")
            self.assertIsNone(stop_gate.gate(root, "claude", session="sA"))
            _lease(root, "sA", expires_in=-5)
            self.assertEqual((stop_gate.gate(root, "claude", session="sA") or {}).get("decision"), "block")
            for _ in range(5):
                if stop_gate.gate(root, "claude", session="sA") is None:
                    break
            self.assertIsNone(stop_gate.gate(root, "claude", session="sA"))
            events = stream.read_events(root)
            self.assertTrue(any("STOP_UNGUARDED" in e.get("summary", "") and "request:relay_s" in e.get("refs", [])
                                for e in events), events)

    def test_foreign_session_lease_does_not_release_the_hold(self) -> None:
        from v7_harness.coord import stop_gate

        tmp, root = _project()
        with tmp:
            _register(root, "relay_f")
            _lease(root, "sB")
            self.assertEqual((stop_gate.gate(root, "claude", session="sA") or {}).get("decision"), "block")

    def test_registry_error_never_blocks(self) -> None:
        from v7_harness.coord import stop_gate

        tmp, root = _project()
        with tmp:
            (root / ".coord" / "requests").write_text("not a directory", encoding="utf-8")
            self.assertIsNone(stop_gate._request_hold(root, "claude", "sA"))


class StallTests(unittest.TestCase):
    def test_dispatched_open_request_is_a_stall_wait(self) -> None:
        from v7_harness.coord import stall

        tmp, root = _project()
        with tmp:
            _register(root, "relay_t")
            waits = stall._letter_waits(root)
            self.assertTrue(any(w["item"] == "request:codex:relay_t" for w in waits), waits)


if __name__ == "__main__":
    unittest.main()
===END===
