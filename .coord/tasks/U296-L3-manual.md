```contract
work_id: U296-L3
worker: apply
goal: U296 session-addressed letters, STOP_UNGUARDED noise dedupe, async agy deliver
inputs:
- v7_harness/coord/watch.py sha256=34d77ba888fbd3260b1fb469331e1bc07dd7bd9d002b714b982172dbb94d93ac
- v7_harness/coord/sentinel.py sha256=994470ca262652de639044545c6b7648a367b47c94cc8b6e3ad85806c2deaa9e
- v7_harness/coord/deliver.py sha256=68c9091b4449a03f46ed5eb33e0a2860b5938a850465ade13011a7f5dab07437
- v7_harness/coord/agy_dispatch.py sha256=dad4c67ee66b8e0b4169bd7ec4b6ddef684d177893136dfbcf70525f2aefa9dc
- v7_harness/cli.py sha256=950246a4b96b3cc44074eeb6e5435a4ccfb1ad5933ca9ba7d1baea1c142828fb
allow:
- v7_harness/coord/watch.py
- v7_harness/coord/sentinel.py
- v7_harness/coord/deliver.py
- v7_harness/coord/agy_dispatch.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u296_mailbox_bottlenecks
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 180
remote_budget_tokens: 0
apply_after: U296-L1
paid_after: U296-L1b
paid_reason: local PROMPT_TOO_LARGE on cli.py
```

## Instructions for the worker

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH


def watch_file(project: Path, tool: str) -> Path:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.json"
=======


def session_key(session: str) -> str:
    """U296: a stable short file-name key for a session id (the id itself may hold characters a file name rejects)."""
    return hashlib.sha256(session.encode("utf-8")).hexdigest()[:12]


def watch_file(project: Path, tool: str, session: str = "") -> Path:
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool}")
    # U296: a named session gets its own lease file; no session keeps the per-tool singleton bytes and name.
    stem = f"{tool}.{session_key(session)}" if session else tool
    return Path(project) / PRESENCE_DIR / f"{stem}.watch.json"


def _watch_records(project: Path, tool: str) -> list[dict[str, Any]]:
    """U296: every lease record of `tool`: the singleton plus one per named session."""
    base = watch_file(project, tool)
    records = []
    for path in [base, *sorted(base.parent.glob(f"{tool}.*.watch.json"))]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict):
            records.append(record)
    return records
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
    live_for = max(LIVE_SCANS * interval_s, LIVE_MIN_S)
    for tool in tools:
        target = watch_file(project, tool)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
=======
    live_for = max(LIVE_SCANS * interval_s, LIVE_MIN_S)
    for tool in tools:
        target = watch_file(project, tool, session)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH


def _clear(project: Path, tools: tuple[str, ...], token: str) -> None:
    """Remove only this watch's files; a newer watch for the same tool keeps its own."""
    for tool in tools:
        target = watch_file(project, tool)
        try:
            if json.loads(target.read_text(encoding="utf-8")).get("token") == token:
=======


def _clear(project: Path, tools: tuple[str, ...], token: str, session: str = "") -> None:
    """Remove only this watch's files; a newer watch for the same tool keeps its own."""
    for tool in tools:
        target = watch_file(project, tool, session)
        try:
            if json.loads(target.read_text(encoding="utf-8")).get("token") == token:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
def watcher_live(project: Path, tool: str, *, now: float | None = None) -> bool:
    moment = time.time() if now is None else now
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    expires_at = record.get("expires_at") if isinstance(record, dict) else None
    return isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > moment
=======
def watcher_live(project: Path, tool: str, *, now: float | None = None) -> bool:
    moment = time.time() if now is None else now
    return any(_record_live(record, moment) for record in _watch_records(project, tool))


def _record_live(record: dict[str, Any], moment: float) -> bool:
    expires_at = record.get("expires_at")
    return isinstance(expires_at, (int, float)) and not isinstance(expires_at, bool) and expires_at > moment
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
def watcher_wakes(project: Path, tool: str) -> bool:
    """U117: a live watcher whose exit wakes its own session (a Claude Code background task) takes real deltas too."""
    try:
        record = json.loads(watch_file(project, tool).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return watcher_live(project, tool) and isinstance(record, dict) and record.get("wakes_session") is True
=======
def watcher_wakes(project: Path, tool: str) -> bool:
    """U117: a live watcher whose exit wakes its own session (a Claude Code background task) takes real deltas too."""
    moment = time.time()
    return any(_record_live(record, moment) and record.get("wakes_session") is True
               for record in _watch_records(project, tool))
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
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
=======
    (no session to compare: the lease is accepted, as the stop gate's other checks are lenient on UNKNOWN)."""
    moment = time.time() if now is None else now
    for record in _watch_records(project, tool):  # U296: one lease per session; any matching live one satisfies
        if not _record_live(record, moment):
            continue
        if record.get("wakes_session") is not True or record.get("adapter") not in WAKE_ADAPTERS:
            continue
        pid, created = record.get("pid"), record.get("process_created")
        if not isinstance(pid, int) or isinstance(pid, bool) or created is None or process_identity(pid) != created:
            continue
        lease_session = str(record.get("session") or "")
        if not (session and lease_session and lease_session != session):
            return True
    return False
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH


def lock_file(project: Path, tool: str) -> Path:
    watch_file(project, tool)
    return Path(project) / PRESENCE_DIR / f"{tool}.watch.lock.json"
=======


def lock_file(project: Path, tool: str, session: str = "") -> Path:
    watch_file(project, tool)
    stem = f"{tool}.{session_key(session)}" if session else tool  # U296: one lock per (tool, session)
    return Path(project) / PRESENCE_DIR / f"{stem}.watch.lock.json"
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
    preempt = bool(mine.get("wakes_session"))
    for tool in tools:
        path = lock_file(project, tool)
        path.parent.mkdir(parents=True, exist_ok=True)
        if _lock_owner_live(path, preempt_non_waking=preempt):
=======
    preempt = bool(mine.get("wakes_session"))
    for tool in tools:
        path = lock_file(project, tool, str(mine.get("session") or ""))
        path.parent.mkdir(parents=True, exist_ok=True)
        if _lock_owner_live(path, preempt_non_waking=preempt):
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
    """Remove only this watcher's locks; a replacement watcher keeps its own."""
    for tool in tools:
        path = lock_file(project, tool)
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
=======
    """Remove only this watcher's locks; a replacement watcher keeps its own."""
    for tool in tools:
        path = lock_file(project, tool, str(mine.get("session") or ""))
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH


def _owns_all_locks(project: Path, locks: list[str], token: str) -> bool:
    """U291: False as soon as any lock file was preempted by another watcher token or removed."""
    for locked_tool in locks:
        try:
            cur_lock = json.loads(lock_file(project, locked_tool).read_text(encoding="utf-8"))
            if not isinstance(cur_lock, dict) or cur_lock.get("token") not in (None, token):
                return False
=======


def _owns_all_locks(project: Path, locks: list[str], token: str, session: str = "") -> bool:
    """U291: False as soon as any lock file was preempted by another watcher token or removed."""
    for locked_tool in locks:
        try:
            cur_lock = json.loads(lock_file(project, locked_tool, session).read_text(encoding="utf-8"))
            if not isinstance(cur_lock, dict) or cur_lock.get("token") not in (None, token):
                return False
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH


def _native_eligible(project, message_id, body, session, now):
    """Native listeners must reject stale and foreign work before consuming any claim."""
=======


def main_desk_session(project: Path) -> str:
    """U296: the user's main Claude desk (topmost `[YYMMDD-N]` window), '' when no desk record exists."""
    try:
        record = json.loads((Path(project) / PRESENCE_DIR / "user_desk_claude.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(record.get("thread") or "") if isinstance(record, dict) else ""


def _session_eligible(project: Path, tool: str, body: dict[str, Any], session: str) -> bool:
    """U296 (B6): may the watcher of `session` take this letter? A letter naming a session or a card window goes only
    to that session; an unaddressed letter goes to the main desk, so a child card session never takes it. With no
    desk record the unaddressed letter stays open to any session (UNKNOWN is no ground to refuse it)."""
    from .stop_gate import _foreign

    if body.get("native_receiver") or body.get("window") or body.get("card"):
        return not _foreign(Path(project), tool, session, body)
    desk = main_desk_session(project)
    return not desk or desk == session


def _native_eligible(project, message_id, body, session, now):
    """Native listeners must reject stale and foreign work before consuming any claim."""
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
    mine = {"pid": os.getpid(), "process_created": process_identity(os.getpid()), "token": token,
            "wakes_session": bool(wakes_session)}
    if structured and not native_session:
        locks, owned_by_other = _take_locks(project, tools, mine)
=======
    mine = {"pid": os.getpid(), "process_created": process_identity(os.getpid()), "token": token,
            "wakes_session": bool(wakes_session)}
    own_session = str(requester_session or "") if structured and not native_session else ""
    if own_session:
        mine["session"] = own_session  # U296: the lock and lease are per (tool, session), not per tool
    if structured and not native_session:
        locks, owned_by_other = _take_locks(project, tools, mine)
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
    try:
        while True:
            if locks and not _owns_all_locks(project, locks, token):
                return None  # Preempted by a newer session watcher; exit without stealing wake claims
            if native_session:
=======
    try:
        while True:
            if locks and not _owns_all_locks(project, locks, token, own_session):
                return None  # Preempted by a newer session watcher; exit without stealing wake claims
            if native_session:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
            now = clock()  # one read serves the beat and the request scan (U117 test counts clock reads)
            _beat(project, tools, token, interval_s, now, wakes_session,
                  session=requester_session or "", process_created=mine["process_created"])
            if not native_session:
                # U277: every scan, not on the stall cadence; a request answered while this watch sleeps wakes it.
=======
            now = clock()  # one read serves the beat and the request scan (U117 test counts clock reads)
            _beat(project, tools, token, interval_s, now, wakes_session,
                  session=own_session, process_created=mine["process_created"])
            if not native_session:
                # U277: every scan, not on the stall cadence; a request answered while this watch sleeps wakes it.
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
                    found = {"id": message_id, "kind": body.get("kind"), "actor": body.get("actor"),
                             "requested_target": body.get("requested_target") or body.get("to")}
                    if locks and not _owns_all_locks(project, locks, token):
                        return None
                    if not structured:
=======
                    found = {"id": message_id, "kind": body.get("kind"), "actor": body.get("actor"),
                             "requested_target": body.get("requested_target") or body.get("to")}
                    if locks and not _owns_all_locks(project, locks, token, own_session):
                        return None
                    if not structured:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
                    target = found["requested_target"]
                    target = target if target in tools else tools[0]
                    cls, _diag = classify(body, migration_record(project, message_id, body.get("digest")))
                    if cls == "LEGACY" and wakes_session and str(body.get("actor") or "") not in ("", target):
=======
                    target = found["requested_target"]
                    target = target if target in tools else tools[0]
                    if own_session and not _session_eligible(Path(project), target, body, own_session):
                        continue  # U296: addressed to another session, or to the main desk; never this watcher's wake
                    cls, _diag = classify(body, migration_record(project, message_id, body.get("digest")))
                    if cls == "LEGACY" and wakes_session and str(body.get("actor") or "") not in ("", target):
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
                            continue
                        digest = hashlib.sha256(f'native:{native_session}:{digest}'.encode()).hexdigest()
                    if locks and not _owns_all_locks(project, locks, token):
                        return None  # Re-check lock ownership immediately before claim_wake so a preempted watcher never claims
                    if claim_wake(project, target, message_id, digest,
=======
                            continue
                        digest = hashlib.sha256(f'native:{native_session}:{digest}'.encode()).hexdigest()
                    if locks and not _owns_all_locks(project, locks, token, own_session):
                        return None  # Re-check lock ownership immediately before claim_wake so a preempted watcher never claims
                    if claim_wake(project, target, message_id, digest,
>>>>>>> REPLACE

===EDIT: v7_harness/coord/watch.py===
<<<<<<< SEARCH
            sleep(interval_s)
    finally:
        _clear(project, tools, token)
        _release_locks(project, locks, mine)
=======
            sleep(interval_s)
    finally:
        _clear(project, tools, token, own_session)
        _release_locks(project, locks, mine)
>>>>>>> REPLACE
===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH


def run_sentinel_cycle(
    project_root: Path,
=======


STOP_UNGUARDED_STEP = "U277-STOP-UNGUARDED"


def stop_unguarded_request(payload: dict[str, Any]) -> str | None:
    """U296 (B5): the request id of a STOP_UNGUARDED event, None for any other payload."""
    if payload.get("kind") != "BLOCKED" or payload.get("step") != STOP_UNGUARDED_STEP:
        return None
    for ref in payload.get("refs") or ():
        if isinstance(ref, str) and ref.startswith("request:"):
            return ref[len("request:"):]
    return ""


def stop_unguarded_is_noise(project_root: Path, request_id: str) -> bool:
    """U296 (B5): a STOP_UNGUARDED event matters only while its request is still open and belongs to the main desk.
    A child card session ending a turn, an answered or cancelled request, and an unknown request are noise: they
    neither wake nor block the main desk. Any read failure keeps the event (a wake too many beats a lost alert)."""
    from . import requests
    from .watch import main_desk_session

    try:
        row = requests.get(project_root, request_id) if request_id else None
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(row, dict) or row.get("state") not in requests.OPEN_STATES:
        return True
    bound = str(row.get("requester_session") or "")
    desk = main_desk_session(project_root)
    return bool(bound and desk and bound != desk)


def run_sentinel_cycle(
    project_root: Path,
>>>>>>> REPLACE

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
    passed = _last_pass_by_step(project_root)
    p1_superseded: list[str] = []
    # Read only. Claiming to look hid each message from real consumers for the length of the check.
    for msg_id, payload in box.peek():
=======
    passed = _last_pass_by_step(project_root)
    p1_superseded: list[str] = []
    unguarded_seen: set[str] = set()
    # Read only. Claiming to look hid each message from real consumers for the length of the check.
    for msg_id, payload in box.peek():
>>>>>>> REPLACE

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
            p1_superseded.append(str(payload.get("step")))
            continue
        if payload.get("kind") == "BLOCKED" or payload.get("is_p1"):
            p1_reasons.append(f"BLOCKED_TASK: {payload.get('step')}")
=======
            p1_superseded.append(str(payload.get("step")))
            continue
        unguarded = stop_unguarded_request(payload)
        if unguarded is not None:
            # U296 (B5): one event per open main-desk request; the fingerprint sees the request set, not event ids.
            if unguarded in unguarded_seen or stop_unguarded_is_noise(project_root, unguarded):
                continue
            unguarded_seen.add(unguarded)
            p1_reasons.append(f"STOP_UNGUARDED: request {unguarded}")
            p1_events.append({"kind": "stop_unguarded", "request_id": unguarded})
            continue
        if payload.get("kind") == "BLOCKED" or payload.get("is_p1"):
            p1_reasons.append(f"BLOCKED_TASK: {payload.get('step')}")
>>>>>>> REPLACE

===EDIT: v7_harness/coord/sentinel.py===
<<<<<<< SEARCH
        event_fingerprint = hashlib.sha256(canonical).hexdigest()
        wake_id = f"wake_{event_fingerprint[:24]}"
        # has_message also sees a wake that someone has claimed but not yet acked, so it is not sent twice.
        if not box.has_message(wake_id):
            box.publish(
                message_id=wake_id,
=======
        event_fingerprint = hashlib.sha256(canonical).hexdigest()
        wake_id = f"wake_{event_fingerprint[:24]}"
        # U296 (B5): a set of only STOP_UNGUARDED items wakes once per distinct set, even after the wake was acked.
        only_unguarded = all(event.get("kind") == "stop_unguarded" for event in p1_events)
        unguarded_state = Path(project_root) / ".coord" / "presence" / "sentinel_stop_unguarded.json"
        try:
            last_set = json.loads(unguarded_state.read_text(encoding="utf-8")).get("fingerprint")
        except (OSError, ValueError, AttributeError):
            last_set = None
        unchanged_set = only_unguarded and last_set == event_fingerprint
        # has_message also sees a wake that someone has claimed but not yet acked, so it is not sent twice.
        if not unchanged_set and not box.has_message(wake_id):
            if only_unguarded:
                from .watch import _write_atomic
                unguarded_state.parent.mkdir(parents=True, exist_ok=True)
                _write_atomic(unguarded_state, {"fingerprint": event_fingerprint})
            box.publish(
                message_id=wake_id,
>>>>>>> REPLACE
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    session: str = "",
    in_reply_to: str = "",
) -> DeliverResult:
    """U277 rev 2: a verdict request is registered durably before anything is published or dispatched.
=======
    session: str = "",
    in_reply_to: str = "",
    agy_wait: bool = True,
) -> DeliverResult:
    """U277 rev 2: a verdict request is registered durably before anything is published or dispatched.
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
                               verdict=verdict, delta=delta, in_reply_to=in_reply_to,
                               _track=track if verdict_requested is True else None,
                               audit=verdict_requested is True)
    except RequestError as exc:
        return DeliverResult(False, target or "mailbox_only", exc.code, (), str(exc), tracked.get("id", ""), "")
=======
                               verdict=verdict, delta=delta, in_reply_to=in_reply_to,
                               _track=track if verdict_requested is True else None,
                               audit=verdict_requested is True, agy_wait=agy_wait)
    except RequestError as exc:
        return DeliverResult(False, target or "mailbox_only", exc.code, (), str(exc), tracked.get("id", ""), "")
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    _track: Any = None,
    audit: bool = False,
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.
=======
    _track: Any = None,
    audit: bool = False,
    agy_wait: bool = True,
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
            # U120: a headless one-turn answer (U119 live: 27,989 tokens) is mailed back to the sender; a failure,
            # a loop tag or the daily cap keeps the U118 UNREAD route. UAOS_AGY_AUTO=0 opts out.
            from v7_harness.coord.agy_dispatch import dispatch
            # U199: a verdict request is the commit-gate audit; its answer is never held back by the daily cap
            row = dispatch(desk, message_id=message_id, actor=actor, message=message, runner=runner or subprocess.run,
=======
            # U120: a headless one-turn answer (U119 live: 27,989 tokens) is mailed back to the sender; a failure,
            # a loop tag or the daily cap keeps the U118 UNREAD route. UAOS_AGY_AUTO=0 opts out.
            from v7_harness.coord.agy_dispatch import dispatch, dispatch_detached
            if not agy_wait and runner is None:
                # U296 (B11): the CLI returns right after PUBLISHED; the answer arrives later as a normal letter.
                # An injected runner (tests) stays synchronous: a detached process cannot call it.
                started = dispatch_detached(desk, message_id=message_id, actor=actor, message=message, card=card,
                                            audit=audit)
                if started:
                    return DeliverResult(False, "antigravity", "PUBLISHED", (),
                                         f"AGY_DETACHED answer arrives as a letter (id {message_id})", message_id, digest)
            # U199: a verdict request is the commit-gate audit; its answer is never held back by the daily cap
            row = dispatch(desk, message_id=message_id, actor=actor, message=message, runner=runner or subprocess.run,
>>>>>>> REPLACE
===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
            kept.append(message_id)
    return kept
=======
            kept.append(message_id)
    return kept


SPOOL_CODE = ("import sys; from pathlib import Path; from v7_harness.coord.agy_dispatch import _run_spool; "
              "raise SystemExit(_run_spool(Path(sys.argv[1])))")


def dispatch_detached(project: Path, *, message_id: str, actor: str, message: str, card: str = "",
                      audit: bool = False) -> bool:
    """U296 (B11): run `dispatch` in a detached child so `coord deliver` returns right after PUBLISHED.

    The child owns the request through dispatch()'s own lock and replay record, so a second start is REQUEST_BUSY or
    ALREADY_ANSWERED, never a second paid call. The answer is mailed as a normal letter. False means the child could
    not start; the caller then falls back to the synchronous call."""
    from v7_harness.coord.presence import _spawn_detached

    spool = Path(project) / ".coord" / "mailbox" / "delivery" / "agy_spool" / f"{message_id}.json"
    try:
        spool.parent.mkdir(parents=True, exist_ok=True)
        spool.write_text(json.dumps({"project": str(project), "message_id": message_id, "actor": actor,
                                     "message": message, "card": card, "audit": audit}, ensure_ascii=False),
                         encoding="utf-8")
        # The one reviewed detached-spawn helper (U54 audit): a fixed code constant plus the spool path as argv.
        _spawn_detached(SPOOL_CODE, str(spool))
    except OSError:
        return False
    return True


def _run_spool(spool: Path) -> int:
    try:
        job = json.loads(spool.read_text(encoding="utf-8"))
        spool.unlink(missing_ok=True)
        dispatch(Path(job["project"]), message_id=job["message_id"], actor=job["actor"], message=job["message"],
                 card=job.get("card", ""), audit=bool(job.get("audit")))
    except (OSError, ValueError, KeyError):
        return 1
    return 0
>>>>>>> REPLACE
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                                 choices=["PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK"])
    p_coord_deliver.add_argument("--delta", default=None, help="U141-A: what changed; an ACTIONABLE letter needs one")
    p_coord_deliver.set_defaults(func=cmd_coord_deliver)
=======
                                 choices=["PASS", "REVISE", "FAIL", "APPROVE", "PIVOT", "REWORK"])
    p_coord_deliver.add_argument("--delta", default=None, help="U141-A: what changed; an ACTIONABLE letter needs one")
    p_coord_deliver.add_argument("--session", default="",
                                 help="U296: address the letter to one receiver session (same as --thread)")
    p_coord_deliver.add_argument("--wait", action="store_true",
                                 help="U296: wait for the Antigravity auto-answer (old behavior); default returns "
                                      "after PUBLISHED and the answer arrives as a letter")
    p_coord_deliver.set_defaults(func=cmd_coord_deliver)
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    # U141-A: structured (default) wakes only on an ACTIONABLE letter, once per letter, one watcher per target.
    p_coord_watch.add_argument("--policy", default="structured", choices=["structured", "legacy"])
    p_coord_watch.set_defaults(func=cmd_coord_watch)
    p_coord_listen = p_coord_subs.add_parser("listen", help="Fast Claude startup bootstrap; native Stop asyncRewake listener")
=======
    # U141-A: structured (default) wakes only on an ACTIONABLE letter, once per letter, one watcher per target.
    p_coord_watch.add_argument("--policy", default="structured", choices=["structured", "legacy"])
    p_coord_watch.add_argument("--session", default="",
                               help="U296: this session's id; one watcher per (target, session), and it takes only "
                                    "letters naming it (the main desk also takes unaddressed ones)")
    p_coord_watch.set_defaults(func=cmd_coord_watch)
    p_coord_listen = p_coord_subs.add_parser("listen", help="Fast Claude startup bootstrap; native Stop asyncRewake listener")
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH

    result = deliver(Path(args.project), message=args.message, actor=args.actor,
                     target=args.target, thread=args.thread, card=args.card,
                     wake_class=getattr(args, "wake_class", None),
                     verdict_requested=getattr(args, "verdict_requested", None),
                     verdict=getattr(args, "verdict", None), delta=getattr(args, "delta", None))
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    # U74-D: QUEUED_ACK_ONLY is an ACK_ONLY letter left in the inbox without a paid turn; also not a failure.
=======

    result = deliver(Path(args.project), message=args.message, actor=args.actor,
                     target=args.target, thread=args.thread or getattr(args, "session", ""), card=args.card,
                     wake_class=getattr(args, "wake_class", None),
                     verdict_requested=getattr(args, "verdict_requested", None),
                     verdict=getattr(args, "verdict", None), delta=getattr(args, "delta", None),
                     **({"agy_wait": bool(args.wait)} if hasattr(args, "wait") else {}))
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    # U74-D: QUEUED_ACK_ONLY is an ACK_ONLY letter left in the inbox without a paid turn; also not a failure.
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval,
                  wakes_session=args.wakes_session, policy=getattr(args, "policy", "structured"))
    if found is not None and found.get("state") == "ALREADY_WATCHING":
        # U141-A: one watcher per target; a second one exits instead of waking the session a second time.
=======

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval,
                  wakes_session=args.wakes_session, policy=getattr(args, "policy", "structured"),
                  requester_session=getattr(args, "session", None) or None)
    if found is not None and found.get("state") == "ALREADY_WATCHING":
        # U141-A: one watcher per target; a second one exits instead of waking the session a second time.
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
