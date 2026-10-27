# U229B2-L2 (judge claude, deputy for LIMITED codex; Codex re-review owed): invocation journal write path

Card manual: `.coord/tasks/U229B2-card-manual.md`. Slice 2 of `v7_harness/invocation.py`: the write path
(`_label`, `_integer`, `_connect`, `_open`, `start_attempt`, `_metadata`, `finish_attempt`, `tracked_call`,
`_exception`), added as whole new top-level functions after `InvocationError`. L3 adds the review path and `main`.

```contract
work_id: U229B2-L2
worker: local
goal: add the durable metadata-only journal write path (start_attempt, finish_attempt, tracked_call) to v7_harness/invocation.py
inputs:
- v7_harness/invocation.py sha256=691545ae8fd7cfe0e7af91638cda2890eeae8d4d7dcb8c52814c0b2bd064b915
- tests/test_u229_independent_invocation.py sha256=e755fafb36ca36a071835f67ab52e259eaf40563d8ad38e84cfdf2f8f7e1201c
allow:
- v7_harness/invocation.py
context_allow:
- tests/test_u229_independent_invocation.py
acceptance: python -m unittest tests.test_u229_independent_invocation.Journal.test_all_callers_start_and_terminal_are_committed tests.test_u229_independent_invocation.Journal.test_unknown_usage_and_raw_prompt_are_not_fabricated tests.test_u229_independent_invocation.Journal.test_invalid_identity_and_unwritable_journal_fail_before_provider tests.test_u229_independent_invocation.Journal.test_four_actual_processes_do_not_drop_attempts
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Exact edits: nine whole new top-level functions, verbatim, in this order

```python
def _label(value, maximum=160):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise InvocationError("INVALID_METADATA_LABEL")
    if SECRET.search(value) or any(ord(c) < 32 for c in value):
        raise InvocationError("PRIVATE_OR_CONTROL_METADATA")
    return value


def _integer(value):
    if value is not None and (type(value) is not int or value < 0):
        raise InvocationError("INVALID_TOKEN_COUNT")
    return value


@contextmanager
def _connect(db=None):
    path = Path(db or DEFAULT_DB).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = _open(path)
    try:
        with con:
            yield con
    finally:
        con.close()


def _open(path):
    deadline = time.monotonic() + 15
    while True:
        con = sqlite3.connect(str(path), timeout=15)
        try:
            con.execute("PRAGMA busy_timeout=15000")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA synchronous=FULL")
            con.execute(SCHEMA)
            con.row_factory = sqlite3.Row
            return con
        except sqlite3.OperationalError as exc:
            con.close()
            if exc.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED) or time.monotonic() >= deadline:
                raise
            time.sleep(.01)


def start_attempt(*, caller, project, work_id, purpose, model, input_sha256, db=None):
    if caller not in (*CALLERS, "unknown"):
        raise InvocationError("INVALID_CALLER")
    if not isinstance(project, (str, Path)):
        raise InvocationError("INVALID_PROJECT")
    path = Path(project).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise InvocationError("PROJECT_MUST_BE_EXISTING_ABSOLUTE_DIRECTORY")
    if not isinstance(input_sha256, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", input_sha256):
        raise InvocationError("INVALID_INPUT_SHA256")
    values = [_label(x) for x in (work_id, purpose, model)]
    attempt_id = uuid.uuid4().hex
    with _connect(db) as con:
        con.execute("INSERT INTO attempts(id,caller,project,work_id,purpose,model,input_sha256,"
                    "started_at,outcome,acceptance) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (attempt_id, caller, str(path.resolve()), *values,
                     input_sha256.lower(), time.time(), "STARTED", "UNVERIFIED"))
    return attempt_id


def _metadata(values):
    allowed = {"exit_code", "stderr_bytes", "output_bytes", "output_sha256", "provider",
               "cost_usd", "cache_read_input_tokens", "cache_creation_input_tokens"}
    if set(values) - allowed:
        raise InvocationError("UNSUPPORTED_METADATA_FIELDS")
    payload = json.dumps(values, sort_keys=True, allow_nan=False)
    if len(payload) > 2048 or SECRET.search(payload):
        raise InvocationError("INVALID_OR_PRIVATE_METADATA")
    return payload


def finish_attempt(attempt_id, *, outcome, error_class=None, input_tokens=None,
                   output_tokens=None, db=None, **metadata):
    outcome = _label(outcome, 40)
    if outcome == "STARTED" or not re.fullmatch(r"[A-Z_]+", outcome):
        raise InvocationError("INVALID_TERMINAL_OUTCOME")
    if error_class is not None and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", error_class):
        raise InvocationError("INVALID_ERROR_CLASS")
    error_class = error_class.upper() if error_class else None
    counts = (_integer(input_tokens), _integer(output_tokens))
    payload, now = _metadata(metadata), time.time()
    with _connect(db) as con:
        row = con.execute("SELECT outcome,started_at FROM attempts WHERE id=?", (attempt_id,)).fetchone()
        if row is None:
            raise InvocationError("UNKNOWN_ATTEMPT")
        if row["outcome"] != "STARTED":
            return
        con.execute("UPDATE attempts SET finished_at=?,wall_time_s=?,outcome=?,error_class=?,"
                    "input_tokens=?,output_tokens=?,metadata=? WHERE id=? AND outcome='STARTED'",
                    (now, max(0.0, now-row["started_at"]), outcome, error_class, *counts, payload, attempt_id))


@contextmanager
def tracked_call(*, caller, project, work_id, purpose, model, input_sha256, db=None):
    attempt_id = start_attempt(caller=caller, project=project, work_id=work_id, purpose=purpose,
                               model=model, input_sha256=input_sha256, db=db)
    result = {"outcome": "FAILED", "error_class": "UNFINISHED_CALL"}
    try:
        yield result
    except BaseException as exc:
        result.update(outcome="FAILED", error_class=_exception(exc))
        raise
    finally:
        finish_attempt(attempt_id, db=db, **result)


def _exception(exc):
    if isinstance(exc, (subprocess.TimeoutExpired, TimeoutError)) or isinstance(getattr(exc, "reason", None), TimeoutError):
        return "TIMEOUT"
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return "PARSE_ERROR"
    if isinstance(exc, InvocationError) and re.fullmatch(r"[A-Z0-9_]{1,64}", str(exc)):
        return str(exc)
    return "PROCESS_ERROR" if isinstance(exc, OSError) else "CALL_EXCEPTION"
```

## Output

- Reply with one ===EDIT: v7_harness/invocation.py=== block holding the nine whole top-level functions above in a
  ```python fence, copied character for character. No explanations. Do not claim success; the acceptance command
  decides.
