"""S5: participation mode (TRIO / DUO / SOLO / HALT) decided before any card is dispatched.

Contract: .work/sustain_20261107/S5_contract.md (revision 3, after Codex audits relay_19bd9932 and relay_cf934922).

Why: on 2026-11-07 Codex was ACTIVE but weekly-RED (79%), Antigravity was ACTIVE with no quota reading, and only
Claude had admitted quota. Presence alone (conductor/route_authority) said "three tools", so lanes went to tools that
could not pay for the work. Here a tool executes only when it is ACTIVE *and* S1's quota producer admits paid work for
the pool it dispatches on; an ACTIVE tool without admission may judge keypoints only under a quota reservation;
UNKNOWN never counts.
"""
from __future__ import annotations

import json
import math
import os
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from . import presence

TOOLS = ("codex", "claude", "antigravity")
SNAPSHOT = Path(".coord") / "participation.json"
READERS = Path(".coord") / "participation.readers"
# 900 s = S1's max age for a 5h-window reading: a decision may not live longer than the freshest input it rests on.
TTL_S = 900
# The lock is held only for milliseconds (read/write one JSON file, add one reader token); 10 s means a stuck holder.
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0
# A reader token covers one gate-then-send; deliver's longest bound is a 120 s turn + 5 s (deliver.py), so a writer
# waits up to 300 s for in-flight sends, and only a token older than 600 s (no live send lasts that long) is dead.
READER_WAIT_S = 300.0
READER_STALE_S = 600.0

EXECUTOR, JUDGE_ONLY, OFFLINE, UNKNOWN = "EXECUTOR", "JUDGE_ONLY", "OFFLINE", "UNKNOWN"
MODES = {3: "TRIO", 2: "DUO", 1: "SOLO", 0: "HALT"}

# Lane owner / judge preference; reasons in the contract (behaviour item 3).
LANE_PREFS: dict[str, dict[str, tuple[str, ...]]] = {
    "IMPL_CODE": {"owner": ("antigravity", "claude", "codex"), "judge": ("claude", "antigravity", "codex")},
    "VERIFY_AUDIT": {"owner": ("claude", "antigravity", "codex"), "judge": ("codex", "antigravity", "claude")},
    "ARCH_DESIGN": {"owner": ("claude", "codex", "antigravity"), "judge": ("codex", "antigravity", "claude")},
    "MERGE_RELEASE": {"owner": ("antigravity", "codex", "claude"), "judge": ("claude", "codex", "antigravity")},
    "RECOVERY_OPS": {"owner": ("claude", "antigravity", "codex"), "judge": ("antigravity", "codex", "claude")},
}
# Windows of one measured account in S1's producer shape (antigravity has one cockpit pool window).
ACCOUNT_WINDOWS = {"codex": ("five_hour", "seven_day"), "claude": ("five_hour", "seven_day"),
                   "antigravity": ("selected_pool",)}


def classify(state: Any, admitted: Any) -> str:
    """Role of one tool. Only an exact `True` admission makes an executor (a truthy non-bool is not a verdict)."""
    state = str(state or "").upper()
    if state in ("LIMITED", "ABSENT"):
        return OFFLINE
    if state != "ACTIVE":
        return UNKNOWN
    return EXECUTOR if admitted is True else JUDGE_ONLY


def _finite(value: Any) -> float | None:
    """A finite real number, else None (rev 3: NaN and +-inf are not expiries)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _epoch(value: Any) -> float | None:
    number = _finite(value)
    if number is not None:
        return number
    if isinstance(value, str) and value:
        try:
            return _finite(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            return None
    return None


def window_expiry(window: Any) -> float | None:
    """When one S1 window stops admitting: min(observed_at + max_age_s, resets_at). None when not derivable."""
    if not isinstance(window, dict):
        return None
    observed, max_age = _epoch(window.get("observed_at")), _finite(window.get("max_age_s"))
    if observed is None or max_age is None:
        return None
    bounds = [observed + max_age]
    reset = _epoch(window.get("resets_at"))
    if reset is not None:
        bounds.append(reset)
    return min(bounds)


def account_expiry(tool: str, account: Any) -> float | None:
    """Rev 3 (relay_cf934922 item 2): expiry from the windows S1 really emits, never an `expires_at` key."""
    if not isinstance(account, dict):
        return None
    ends = [window_expiry(account.get(k)) for k in ACCOUNT_WINDOWS.get(tool, ())]
    return None if not ends or any(e is None for e in ends) else min(ends)


def _producer_admissions(accounts: dict[str, Any], pools: dict[str, str] | None) -> dict[str, bool]:
    """S1's own producer decides (`apply_measured_quota(..., dispatch_pools=)`): POOL_UNBOUND, an old signature
    without `dispatch_pools`, or any error fails closed."""
    from .quota_sources import apply_measured_quota
    engines: dict[str, dict[str, Any]] = {t: {} for t in TOOLS}
    apply_measured_quota(engines, accounts, {}, dispatch_pools=dict(pools or {}))
    return {t: (engines[t].get("subscription_plan") or {}).get("quota_admit_paid") is True for t in TOOLS}


def admissions(accounts: Any, admit: Any = None, *, pools: dict[str, str] | None = None) -> dict[str, bool]:
    """Per-tool paid admission. Default: S1's producer with the dispatch pools; a test may inject `admit(tool,
    account) -> bool`. Anything but an exact True, and any admitted account whose expiry is not derivable, fails
    closed."""
    out = {t: False for t in TOOLS}
    if not isinstance(accounts, dict):
        return out
    try:
        raw = ({t: admit(t, accounts.get(t)) for t in TOOLS if accounts.get(t) is not None} if callable(admit)
               else _producer_admissions(accounts, pools))
    except Exception:
        return out
    for tool in TOOLS:
        out[tool] = raw.get(tool) is True and account_expiry(tool, accounts.get(tool)) is not None
    return out


def decide(states: dict[str, Any], admitted: dict[str, Any]) -> dict[str, Any]:
    roles = {t: classify((states or {}).get(t), (admitted or {}).get(t)) for t in TOOLS}
    executors = [t for t in TOOLS if roles[t] == EXECUTOR]
    judges = [t for t in TOOLS if roles[t] in (EXECUTOR, JUDGE_ONLY)]
    mode = MODES[len(executors)]
    lanes: dict[str, dict[str, Any]] = {}
    for lane, prefs in LANE_PREFS.items():
        owner = next((t for t in prefs["owner"] if roles[t] == EXECUTOR), None)
        if owner is None:
            lanes[lane] = {"owner": None, "judge": None, "verdict": "HALTED"}
            continue
        # A non-owner executor judges live; a JUDGE_ONLY tool spends a RED/unknown account, so keypoints only and
        # only under a quota reservation (gate_dispatch).
        judge = next((t for t in prefs["judge"] if t != owner and roles[t] == EXECUTOR), None)
        verdict = "LIVE"
        if judge is None:
            judge = next((t for t in prefs["judge"] if t != owner and roles[t] == JUDGE_ONLY), None)
            verdict = "KEYPOINT_ONLY" if judge else "DEFERRED_TO_RETURNING"
        lanes[lane] = {"owner": owner, "judge": judge, "verdict": verdict}
    return {"mode": mode, "roles": roles, "executors": executors, "judges": judges, "lanes": lanes,
            "self_approval": False}


def decide_with_expiry(states: dict[str, Any], admitted: dict[str, Any], *, now: float,
                       input_expiries: Iterable[Any] = ()) -> dict[str, Any]:
    """The decision expires at the earliest of its own TTL and every finite input expiry it rests on."""
    decision = decide(states, admitted)
    decision["decided_at"] = float(now)
    decision["expires_at"] = min([float(now) + TTL_S, *[e for e in map(_finite, input_expiries) if e is not None]])
    return decision


@contextmanager
def _lock(project: Path, timeout_s: float = LOCK_TIMEOUT_S):
    target = Path(project) / SNAPSHOT
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = target.with_name(target.name + ".lock")
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            os.close(os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE_S:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise TimeoutError(f"participation lock busy: {lock}")
            time.sleep(0.01)
    try:
        yield
    finally:
        try:
            lock.unlink(missing_ok=True)
        except OSError:
            pass


def _live_readers(project: Path) -> list[Path]:
    folder = Path(project) / READERS
    live = []
    for token in (folder.iterdir() if folder.is_dir() else ()):
        try:
            if time.time() - token.stat().st_mtime > READER_STALE_S:
                token.unlink(missing_ok=True)
            else:
                live.append(token)
        except OSError:
            continue
    return live


@contextmanager
def dispatch_guard(project: Path):
    """Rev 3 (relay_cf934922 item 4): a reader token, added under the lock, covers one gate-then-send. A snapshot
    writer holds the lock (so no new dispatch can start) and waits for every token before it writes, so a
    revocation never lands between a passed gate and its send."""
    folder = Path(project) / READERS
    with _lock(project):
        folder.mkdir(parents=True, exist_ok=True)
        token = folder / f"{os.getpid()}-{uuid.uuid4().hex}"
        token.write_text(str(time.time()), encoding="utf-8")
    try:
        yield
    finally:
        try:
            token.unlink(missing_ok=True)
        except OSError:
            pass


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write(project: Path, decision: dict[str, Any]) -> dict[str, Any]:
    """Serialized write that waits for in-flight dispatches and never replaces a snapshot decided later; returns the
    snapshot that stands."""
    target = Path(project) / SNAPSHOT
    with _lock(project):
        deadline = time.monotonic() + READER_WAIT_S
        lock = target.with_name(target.name + ".lock")
        while _live_readers(project):
            if time.monotonic() > deadline:
                raise TimeoutError("participation snapshot: in-flight dispatches did not finish")
            # Rev 4 (Codex judge U322-apply2): a live holder refreshes the lock's mtime while it waits for readers,
            # so LOCK_STALE_S (60 s) only ever frees the lock of a dead holder, never one still waiting up to 300 s.
            try:
                os.utime(lock)
            except OSError:
                pass
            time.sleep(0.01)
        current = _read(target)
        newer = _finite((current or {}).get("decided_at"))
        if newer is not None and newer > float(decision["decided_at"]):
            return current  # type: ignore[return-value]
        tmp = target.with_name(f"{target.name}.{os.getpid()}.{time.time_ns()}.tmp")
        tmp.write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding="utf-8")
        presence.replace_with_retry(tmp, target)
    return decision


def snapshot(project: Path, *, home: Path | None = None, now: float | None = None, admit: Any = None,
             pools: dict[str, str] | None = None, write_file: bool = True,
             accounts: Any = None) -> dict[str, Any]:
    """Read desk presence and local quota files (zero paid tokens), decide, and write `.coord/participation.json`.
    `accounts` replaces the local quota read (tests feed S1-shaped readings)."""
    moment = time.time() if now is None else float(now)
    desk = presence.read_all(Path(project), now=moment)
    states = {t: (desk.get(t) or {}).get("state", "UNKNOWN") for t in TOOLS}
    if accounts is None:
        try:
            from .quota_sources import measured_accounts
            accounts = measured_accounts(Path(home) if home else Path.home(), moment)
        except Exception:
            accounts = None
    admitted = admissions(accounts, admit, pools=pools)
    expiries: list[Any] = [_epoch((desk.get(t) or {}).get("expires_at")) for t in TOOLS if states[t] == "ACTIVE"]
    expiries += [account_expiry(t, (accounts or {}).get(t)) for t in TOOLS if admitted[t]]
    decision = decide_with_expiry(states, admitted, now=moment, input_expiries=expiries)
    return write(Path(project), decision) if write_file else decision


def gate_dispatch(project: Path, tool: str, *, purpose: str = "execute", keypoint: bool = False,
                  reservation: Any = None, reservation_ok: Callable[[str, Any], Any] | None = None,
                  now: float | None = None) -> dict[str, Any]:
    """Fail-closed dispatch check against the boot snapshot: no snapshot, an unreadable one, a non-finite expiry or
    `now >= expires_at` all refuse. A JUDGE_ONLY keypoint verdict needs a reservation that `reservation_ok` (S2's
    atomic reservation check) confirms with an exact True (rev 3, relay_cf934922 item 1)."""
    path = Path(project) / SNAPSHOT
    if not path.exists():
        return {"allowed": False, "reason": "NO_SNAPSHOT"}
    data = _read(path)
    if not data or not isinstance(data.get("roles"), dict):
        return {"allowed": False, "reason": "SNAPSHOT_UNREADABLE"}
    moment = time.time() if now is None else float(now)
    expires = _finite(data.get("expires_at"))
    if expires is None or moment >= expires:
        return {"allowed": False, "reason": "SNAPSHOT_EXPIRED"}
    role = data["roles"].get(tool, UNKNOWN)
    if role == EXECUTOR:
        return {"allowed": True, "reason": EXECUTOR}
    if purpose == "judge" and role == JUDGE_ONLY:
        if not keypoint:
            return {"allowed": False, "reason": "PAID_JUDGE_ONLY"}
        try:
            reserved = reservation is not None and callable(reservation_ok) and \
                reservation_ok(tool, reservation) is True
        except Exception:
            reserved = False
        if reserved:
            return {"allowed": True, "reason": "JUDGE_ONLY_KEYPOINT_RESERVED"}
        return {"allowed": False, "reason": "NO_RESERVATION"}
    return {"allowed": False, "reason": f"ROLE_{role}"}
