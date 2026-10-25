"""U229: durable metadata-only invocation receipts and evidence-only review.

The journal grants no approval and stores no prompts or raw provider diagnostics.
Provider execution is parked: atomic process-tree containment was not proven.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import time
import uuid

CALLERS = ("codex", "claude", "antigravity")
HAIKU = "claude-haiku-5-5"
LOCAL_MODEL = "qwen2.5-coder:7b"
DEFAULT_DB = Path.home() / ".uaos" / "usage" / "invocations.sqlite3"
SECRET = re.compile(r"(?:sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{20,}|Bearer\s+\S{20,})")
SCHEMA = """CREATE TABLE IF NOT EXISTS attempts (
 id TEXT PRIMARY KEY, caller TEXT NOT NULL, project TEXT NOT NULL,
 work_id TEXT NOT NULL, purpose TEXT NOT NULL, model TEXT NOT NULL,
 input_sha256 TEXT NOT NULL, started_at REAL NOT NULL, finished_at REAL,
 wall_time_s REAL, outcome TEXT NOT NULL, error_class TEXT,
 input_tokens INTEGER, output_tokens INTEGER, acceptance TEXT NOT NULL,
 metadata TEXT NOT NULL DEFAULT '{}')"""


class InvocationError(ValueError):
    """Invalid/unbounded request or an unavailable durable receipt."""




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




def _review_rows(db, window):
    if type(window) is not int or not 1 <= window <= 1000:
        raise InvocationError("INVALID_REVIEW_WINDOW")
    with _connect(db) as con:
        rows = con.execute("SELECT * FROM attempts ORDER BY started_at DESC,id LIMIT ?", (window,)).fetchall()
    return [dict(row) for row in reversed(rows)]




def _proposal(rows):
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()
    return {"schema": "uaos-invocation-review-v1", "fingerprint": fingerprint,
            "attempts": len(rows), "outcomes": dict(Counter(row["outcome"] for row in rows)),
            "models": dict(Counter(row["model"] for row in rows)),
            "errors": dict(Counter(row["error_class"] for row in rows if row["error_class"])),
            "token_unknown_attempts": sum(row["input_tokens"] is None or row["output_tokens"] is None for row in rows),
            "acceptance": "UNVERIFIED", "quota_saving": "UNMEASURED", "automatic_adoption": False,
            "auto_adopt": False,
            "next_action": "REVIEW_FIXED_ACCEPTANCE_AND_CAUSES_BEFORE_ROUTING_OR_POLICY_CHANGE"}




def review(db=None, output=None, *, window=100):
    proposal = _proposal(_review_rows(db, window))
    selected = Path(output) if output else Path(db or DEFAULT_DB).parent / "invocation-reviews"
    directory = selected.parent if selected.suffix.lower() == ".json" else selected
    directory.mkdir(parents=True, exist_ok=True)
    target = selected if selected.suffix.lower() == ".json" else directory / (proposal["fingerprint"] + ".json")
    try:
        with target.open("x", encoding="utf-8") as handle:
            json.dump(proposal, handle, sort_keys=True, indent=2)
    except FileExistsError:
        if json.loads(target.read_text(encoding="utf-8")) != proposal:
            raise InvocationError("REVIEW_FINGERPRINT_COLLISION")
    return {**proposal, "artifact": str(target)}




def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("run", "pair", "review"))
    parser.add_argument("--input", type=Path, help="JSON request file; raw prompts are never journalled")
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path, help="Review artifact directory")
    parser.add_argument("--window", type=int, default=100)
    return parser




def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        if args.action == "review":
            result = review(args.db, args.output, window=args.window)
        else:
            raise InvocationError("EXECUTOR_PARKED_UNVERIFIED_TREE_CONTAINMENT")
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(json.dumps({"outcome": "FAILED", "error_class": _exception(exc)}))
        return 1




def evaluate_roi_metrics(db=None, *, window=100):
    rows = _review_rows(db, window)
    total = len(rows)
    succeeded = sum(row["outcome"] == "SUCCEEDED" for row in rows)
    local_calls = sum(row["model"] == LOCAL_MODEL for row in rows)
    paid_calls = total - local_calls
    return {
        "schema": "uaos-rsi-roi-v1",
        "window_attempts": total,
        "succeeded_attempts": succeeded,
        "first_pass_yield": (succeeded / total) if total else 0.0,
        "local_calls": local_calls,
        "paid_calls": paid_calls,
        "local_offload_ratio": (local_calls / total) if total else 0.0,
        "quota_saving": "UNMEASURED",
        "auto_adopt": False,
    }


if __name__ == "__main__":
    raise SystemExit(main())
