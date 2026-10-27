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
