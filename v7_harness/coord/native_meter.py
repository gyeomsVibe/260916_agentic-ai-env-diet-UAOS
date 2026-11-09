"""U313: sanitized native quota observations and bounded pool admission; no token estimates."""
import argparse
import hashlib
import json
import math
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from pathlib import Path

def _number(value, name='number'):
    if isinstance(value, bool):
        raise ValueError(name)
    if not isinstance(value, (int, float)):
        raise ValueError(name)
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise ValueError(name) from None
    if not math.isfinite(number):
        raise ValueError(name)
    return number

def _dict(value, name):
    if not isinstance(value, dict):
        raise ValueError(name)
    return value

def _identity(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value):
        raise ValueError(name)
    return value

def _epoch(value, name):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError(name)
            return dt.timestamp()
        except (ValueError, OverflowError):
            raise ValueError(name) from None
    return _number(value, name)

def _percent(value, fraction=False):
    number = _number(value, "quota")
    if not 0 <= number <= (1 if fraction else 100):
        raise ValueError("quota_range")
    return number * 100 if fraction else number

def _bucket(bucket):
    endings = (("-five-hour", "5h"), ("-weekly", "7d"), ("-5h", "5h"), ("-7d", "7d"))
    for ending, window in endings:
        if bucket.endswith(ending):
            pool = bucket[:-len(ending)]
            return ("claude_gpt" if pool == "3p" else pool), window
    return bucket, "unknown"

def _native_windows(tool, payload):
    if tool == "antigravity":
        quota = _dict(payload.get("quota", {}), "quota")
        return [(*_bucket(_identity(key, "bucket")), _dict(row, "bucket"), True) for key, row in quota.items()]
    limits = _dict(payload.get("rate_limits", {}), "rate_limits")
    names = (("primary", "5h"), ("secondary", "7d")) if tool == "codex" else (("five_hour", "5h"), ("seven_day", "7d"))
    return [(tool, window, _dict(limits[name], "window"), False) for name, window in names if name in limits]

def _model(payload):
    model = payload.get("model")
    model = model if isinstance(model, dict) else {}
    return {key: str(model[key])[:200] for key in ("id", "display_name", "effort") if isinstance(model.get(key), str)}

def _counters(payload):
    usage = payload.get("usage")
    if usage is None:
        context = payload.get("context_window") or {}
        usage = context.get("current_usage") if isinstance(context, dict) else None
    if usage is None:
        return {}
    usage = _dict(usage, "usage")
    allowed = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_input_tokens", "thinking_tokens", "reasoning_tokens", "total_tokens")
    counters = {k: _number(usage[k], "counter") for k in allowed if k in usage}
    if any(v < 0 or not v.is_integer() for v in counters.values()):
        raise ValueError("counter")
    return {k: int(v) for k, v in counters.items()}

def _quota_row(tool, pool, window, native, fraction):
    if fraction:
        raw = native.get("remaining_fraction")
        remaining = None if raw is None else _percent(raw, fraction=True)
        reset = native.get("reset_time")
    else:
        raw = native.get("used_percent" if tool == "codex" else "used_percentage")
        remaining = None if raw is None else 100 - _percent(raw)
        reset = native.get("resets_at")
    if "remaining_amount" in native:
        _number(native["remaining_amount"], "remaining_amount")
    return {"pool": pool, "window": window, "remaining_pct": remaining, "reset_at": _epoch(reset, "reset"),
            "raw_quota": None if raw is None else str(raw), "raw_unit": "remaining_fraction" if fraction else "used_percent",
            "disabled": native.get("disabled") is True}

def normalize(tool, payload, *, account, observed_at=None, received_at=None):
    if tool not in ("codex", "claude", "antigravity"):
        raise ValueError("tool")
    payload = _dict(payload, "payload")
    account = _identity(account, "account")
    observed = _epoch(observed_at, "observed_at")
    received = _epoch(time.time() if received_at is None else received_at, "received_at")
    if observed is not None and observed > received:
        raise ValueError("future_observation")
    model, counters = _model(payload), _counters(payload)
    rows = [_quota_row(tool, pool, window, native, fraction) for pool, window, native, fraction in _native_windows(tool, payload)]
    for row in rows:
        row.update(tool=tool, account=account, observed_at=observed, received_at=received, model=model, counters=counters,
                   observation_basis="caller_bound_source_time" if observed is not None else "MISSING_SOURCE_TIME",
                   precision_basis="numeric_representation; provider accuracy UNKNOWN")
    return rows

def _schema(con):
    con.execute("CREATE TABLE IF NOT EXISTS observations(id INTEGER PRIMARY KEY, fingerprint TEXT UNIQUE NOT NULL, tool TEXT, account TEXT, pool TEXT, window TEXT, observed REAL, data TEXT NOT NULL)")
    con.execute("CREATE INDEX IF NOT EXISTS meter_scope ON observations(tool,account,pool,window,observed,id)")
    con.execute("CREATE TABLE IF NOT EXISTS jobs(work_id TEXT PRIMARY KEY, tool TEXT, account TEXT, pool TEXT, started REAL, finished REAL, requested REAL NOT NULL, before_data TEXT NOT NULL, result TEXT)")

def _dump(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False)

def _insert(con, row):
    identity = {k: v for k, v in row.items() if k != "received_at"}
    fingerprint = hashlib.sha256(_dump(identity).encode()).hexdigest()
    cursor = con.execute("INSERT OR IGNORE INTO observations(fingerprint,tool,account,pool,window,observed,data) VALUES(?,?,?,?,?,?,?)",
                         (fingerprint, row["tool"], row["account"], row["pool"], row["window"], row["observed_at"], _dump(row)))
    return cursor.rowcount

def _latest(con, tool, account, pool):
    rows = {}
    for window in ("5h", "7d"):
        value = con.execute("SELECT data FROM observations WHERE tool=? AND account=? AND pool=? AND window=? ORDER BY observed DESC,id DESC LIMIT 1", (tool, account, pool, window)).fetchone()
        if value:
            rows[window] = json.loads(value[0])
    return rows

def _fresh(rows, now, max_age_s):
    if set(rows) != {"5h", "7d"}:
        return "MISSING_WINDOW"
    for row in rows.values():
        observed = row["observed_at"]
        if observed is None:
            return "MISSING_SOURCE_TIME"
        if observed > now or row["received_at"] > now:
            return "FUTURE_OBSERVATION"
        if now - observed > max_age_s:
            return "STALE_OBSERVATION"
        if row["reset_at"] is None or row["reset_at"] <= now:
            return "RESET_ELAPSED_OR_UNKNOWN"
        if row["disabled"] or row["remaining_pct"] is None:
            return "UNAVAILABLE_QUOTA"
    return None

def _budget(now, max_age_s, requested_points=0, reserve_points=0):
    values = [_number(v, name) for v, name in ((now, "now"), (max_age_s, "max_age_s"), (requested_points, "requested_points"), (reserve_points, "reserve_points"))]
    if values[1] <= 0 or not 0 <= values[2] <= 100 or not 0 <= values[3] <= 100:
        raise ValueError("budget_range")
    return values

def _route(con, tool, account, pool, now, age, requested, reserve):
    rows = _latest(con, tool, account, pool)
    reason = _fresh(rows, now, age)
    if reason:
        return {"action": "BLOCKED", "reason": reason}
    active = con.execute("SELECT COALESCE(SUM(requested),0) FROM jobs WHERE tool=? AND account=? AND pool=? AND result IS NULL", (tool, account, pool)).fetchone()[0]
    if requested <= 0 or any(row["remaining_pct"] < requested + reserve + active for row in rows.values()):
        return {"action": "BLOCKED", "reason": "INSUFFICIENT_QUOTA"}
    return {"action": "ALLOW_BOUNDED", "requested_points": requested, "reserve_points": reserve, "active_reserved_points": active,
            "remaining_pct": {w: row["remaining_pct"] for w, row in rows.items()}, "attribution": "POOL_INTERVAL"}

def _begin(con, work_id, tool, account, pool, now, age, requested=0):
    _identity(work_id, "work_id")
    prior = con.execute("SELECT tool,account,pool,before_data FROM jobs WHERE work_id=?", (work_id,)).fetchone()
    if prior:
        return {"ok": False, "reason": "WORK_ID_EXISTS"}
    rows = _latest(con, tool, account, pool)
    reason = _fresh(rows, now, age)
    if reason:
        return {"ok": False, "reason": reason}
    con.execute("INSERT INTO jobs(work_id,tool,account,pool,started,requested,before_data) VALUES(?,?,?,?,?,?,?)", (work_id, tool, account, pool, now, requested, _dump(rows)))
    return {"ok": True, "work_id": work_id, "attribution": "POOL_INTERVAL"}

def _delta(before, after):
    delta, bounds = {}, {}
    for window, first in before.items():
        last = after[window]
        if first["reset_at"] != last["reset_at"]:
            return None, None, "RESET_CHANGED"
        if last["observed_at"] <= first["observed_at"]:
            return None, None, "MISSING_AFTER_OBSERVATION"
        value = first["remaining_pct"] - last["remaining_pct"]
        if value < 0:
            return None, None, "QUOTA_INCREASE_WITHOUT_RESET"
        delta[window] = value
        widths = [float(Decimal(10) ** Decimal(r["raw_quota"]).as_tuple().exponent) * (100 if r["raw_unit"] == "remaining_fraction" else 1) for r in (first, last)]
        bounds[window] = {"lower": max(0, value - sum(widths) / 2), "upper": value + sum(widths) / 2, "basis": "numeric_rounding_assumption_not_provider_accuracy"}
    return delta, bounds, None

def _receipt(con, job, after, now):
    work_id, tool, account, pool, started, before_text = job
    before = json.loads(before_text)
    if any(row["observed_at"] <= started or row["observed_at"] > now for row in after.values()):
        return {"ok": False, "reason": "MISSING_AFTER_OBSERVATION", "attribution": "POOL_INTERVAL"}
    delta, bounds, reason = _delta(before, after)
    if reason:
        return {"ok": False, "reason": reason, "attribution": "POOL_INTERVAL"}
    overlaps = [r[0] for r in con.execute("SELECT work_id FROM jobs WHERE tool=? AND account=? AND pool=? AND work_id<>? AND started<=? AND (finished IS NULL OR finished>=?)", (tool, account, pool, work_id, now, started))]
    return {"ok": True, "work_id": work_id, "attribution": "POOL_INTERVAL", "delta_pct_points": delta,
            "inference_bounds_pct_points": bounds, "concurrent_work_ids": overlaps, "task_cost": "UNMEASURED",
            "before": before, "after": after}

class _Txn:

    pass

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.con = sqlite3.connect(self.path, timeout=2, isolation_level=None)
        try:
            self.con.execute("BEGIN IMMEDIATE")
        except sqlite3.Error:
            self.con.close()
            raise
        return self.con

    def __exit__(self, kind, error, traceback):
        try:
            self.con.execute("ROLLBACK" if kind else "COMMIT")
        finally:
            self.con.close()

class MeterStore:

    pass

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as con:
            _schema(con)

    def _transaction(self):
        return _Txn(self.path)

    def ingest(self, tool, payload, *, account, observed_at=None, received_at=None):
        rows = normalize(tool, payload, account=account, observed_at=observed_at, received_at=received_at)
        with self._transaction() as con:
            return sum(_insert(con, row) for row in rows)

    def observations(self):
        with self._transaction() as con:
            return [json.loads(r[0]) for r in con.execute("SELECT data FROM observations ORDER BY id")]

    def route(self, tool, account, pool, *, now, max_age_s, requested_points, reserve_points):
        values = _budget(now, max_age_s, requested_points, reserve_points)
        for value, name in ((tool, "tool"), (account, "account"), (pool, "pool")):
            _identity(value, name)
        with self._transaction() as con:
            return _route(con, tool, account, pool, *values)

    def begin(self, work_id, tool, account, pool, *, now, max_age_s):
        now, age, _, _ = _budget(now, max_age_s)
        with self._transaction() as con:
            return _begin(con, work_id, tool, account, pool, now, age)

    def end(self, work_id, *, now, max_age_s):
        now, age, _, _ = _budget(now, max_age_s)
        with self._transaction() as con:
            prior = con.execute("SELECT result FROM jobs WHERE work_id=?", (work_id,)).fetchone()
            if prior is None:
                return {"ok": False, "reason": "MISSING_BEGIN"}
            if prior[0] is not None:
                return json.loads(prior[0])
            job = con.execute("SELECT work_id,tool,account,pool,started,before_data FROM jobs WHERE work_id=?", (work_id,)).fetchone()
            after = _latest(con, job[1], job[2], job[3])
            reason = _fresh(after, now, age)
            receipt = {"ok": False, "reason": reason} if reason else _receipt(con, job, after, now)
            if receipt["ok"]:
                con.execute("UPDATE jobs SET result=?,finished=? WHERE work_id=?", (_dump(receipt), now, work_id))
            return receipt

    def _admit(self, work_id, tool, account, pool, now, age, requested, reserve):
        with self._transaction() as con:
            route = _route(con, tool, account, pool, now, age, requested, reserve)
            if route["action"] != "ALLOW_BOUNDED":
                return {"ok": False, "admission": route}
            begun = _begin(con, work_id, tool, account, pool, now, age, requested)
            return {**begun, "admission": route}

    def run_bounded(self, work_id, tool, account, pool, operation, *, now, after_now=None, max_age_s, requested_points, reserve_points):
        values = _budget(now, max_age_s, requested_points, reserve_points)
        if after_now is not None and _number(after_now, "after_now") < values[0]:
            raise ValueError("after_now_before_begin")
        admission = self._admit(work_id, tool, account, pool, *values)
        if not admission["ok"]:
            return admission
        try:
            value = operation()
        except Exception as error:
            return {"ok": False, "reason": "OPERATION_FAILED", "error_type": type(error).__name__, "work_id": work_id}
        receipt = self.end(work_id, now=time.time() if after_now is None else after_now, max_age_s=max_age_s)
        return {"ok": True, "operation_executed": True, "measurement_status": "PAIRED" if receipt["ok"] else "UNMEASURED",
                "value": value, "receipt": receipt, "admission": admission["admission"]}

def add_parser(subparsers):
    parser = subparsers.add_parser("meter", help="U313: sanitized native quota ingest and bounded operating guard")
    parser.add_argument("action", choices=("ingest", "observations", "begin", "end", "route", "run"))
    parser.add_argument("--tool", choices=("codex", "claude", "antigravity"))
    parser.add_argument("--account")
    parser.add_argument("--pool")
    parser.add_argument("--work-id")
    parser.add_argument("--db", default=str(Path.home() / ".uaos/usage/native_meter.sqlite3"))
    for flag in ("observed-at", "received-at", "now", "after-now", "max-age-s", "requested-points", "reserve-points"):
        parser.add_argument("--" + flag, type=float)
    parser.add_argument("--command", nargs=argparse.REMAINDER)
    parser.set_defaults(func=cli_main)

def _command(command):
    if not command:
        raise ValueError("command")

    def invoke():
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        return {"returncode": result.returncode}
    return invoke

def _cli_result(store, args):
    now = time.time() if args.now is None else args.now
    if args.action == "ingest":
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        return {"ok": True, "inserted": store.ingest(args.tool, payload, account=args.account, observed_at=args.observed_at, received_at=args.received_at)}
    if args.action == "observations":
        return {"observations": store.observations()}
    if args.action == "end":
        return store.end(args.work_id, now=now, max_age_s=args.max_age_s)
    scope = (args.tool, args.account, args.pool)
    if args.action == "begin":
        return store.begin(args.work_id, *scope, now=now, max_age_s=args.max_age_s)
    budget = dict(now=now, max_age_s=args.max_age_s, requested_points=args.requested_points, reserve_points=args.reserve_points)
    if args.action == "route":
        return store.route(*scope, **budget)
    return store.run_bounded(args.work_id, *scope, _command(args.command), after_now=args.after_now, **budget)

def cli_main(args):
    try:
        result = _cli_result(MeterStore(args.db), args)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return 0 if result.get("ok", result.get("action") != "BLOCKED") else 2
    except (ValueError, TypeError, OSError, sqlite3.Error):
        print(json.dumps({"ok": False, "reason": "INVALID_OR_UNAVAILABLE_NATIVE_METER"}))
        return 2

# U313 bounded append anchor
