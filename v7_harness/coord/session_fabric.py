"""U326 card-session fabric: schema constants and refusal types (M1 skeleton)."""
from __future__ import annotations
import math
import re
import copy
import hashlib
import json
import os
import socket
import subprocess
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

SCHEMA = "uaos/u326/card_session.v1.1"
TOOLS = ("codex", "claude", "antigravity")

PERMISSIONS = ("INHERITED", "PLAN_READONLY")  # the only values schema v1.1 allows; anything else is weaker


_CARD = re.compile(r"U[0-9]{2,4}(-[A-Z0-9]{1,8})?")  # schema v1.1 card pattern; also blocks path traversal


ADAPTER_VERSION = "u326-m1"  # names the M1 offline adapter; live adapters bump it when they land


NATIVE_KIND = {"codex": "codex_thread", "claude": "claude_desktop_session", "antigravity": "agy_conversation"}


CODES = frozenset((  # PORTS v1 (77d016dd) section 3 CODES; the enum is frozen, so no TOOL_INVALID/INPUT_INVALID
    "PARENT_UNBOUND", "CAPS_INVALID", "ADMISSION_MALFORMED", "ADMISSION_FUTURE_READING", "ADMISSION_STALE_QUOTA",
    "ADMISSION_RESET_UNOBSERVED", "ADMISSION_REFUSED", "PERMISSION_WEAKER_THAN_INHERITED",
    "LEASE_HELD", "DUPLICATE_OPEN", "CAP_GLOBAL", "CAP_TOOL", "CAP_LOCK_TIMEOUT",
    "SOURCE_DIRTY_OR_STALE", "WORKTREE_FAILED", "WORKSPACE_UNCLEAN", "PARENT_SNAPSHOT_CHANGED",
    "PATH_ESCAPE", "PATH_TOO_LONG", "BRANCH_INVALID", "ILLEGAL_STATE", "STALE_RECORD", "CORRUPT_RECORD",
    "CLOCK_INVALID", "RESUME_BUSY", "RESUME_MISSING", "EFFECT_UNKNOWN_PENDING", "AUTHOR_IS_JUDGE",
    "RELEASE_LIVE_WRITER"))


_READING = {"tool": str, "pool": str, "window": str, "observed_wall": float, "freshness_s": float,
            "reset_status": str, "admit_paid": bool, "evidence": str}  # PORTS v1 QuotaReading keys and types


MAX_PATH_CHARS = 200  # PORTS v1 s4: 60 chars stay under Windows MAX_PATH 260 for nested repo files


LOCK_WAIT_S = 10.0  # PORTS v1 s3 LockPort bound: longer than any count-and-create section, short enough to surface


ERROR_MAX = 2000  # schema v1.1 turns[].error maxLength


_BRANCH = re.compile(r"(codex|claude|antigravity)/U[0-9]{2,4}(-[a-z0-9]{1,40})?")  # PORTS v1 s4 branch rule


_DESK = re.compile(r"[A-Za-z0-9_-]{1,64}")  # path-safe desk ids (amendment V2 parent_binding)


_SECRETS = (  # mirrors v7_harness.coord.mailbox.SECRET_PATTERNS (production redactor); stdlib-only copy
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}"), re.compile(r"ghp_[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]{20,}"),
    re.compile(r"(?:api[_-]?key|secret|token|password|credential)[\"']?\s*[:=]\s*[\"']?[a-zA-Z0-9_\-]{16,}", re.I))


PARENT_KEYS = ("desk_id", "desk_tool", "project_root", "owner", "lane")


EXCLUDE = (".work/wt/", ".coord/fabric/")  # the fabric's own roots never enter the parent snapshot


_TERMINAL = {"completed": "COMPLETED", "failed": "FAILED", "interrupted": "INTERRUPTED"}


class FabricRefusal(Exception):
    def __init__(self, code: str, detail: str = "", evidence: dict | None = None):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail
        self.evidence = dict(evidence) if evidence else ({"detail": detail} if detail else {})

class NativeBusy(Exception):
    """The native session is mid-turn."""

class NativeMissing(Exception):
    """The native session no longer exists."""

class NativeTransportLost(Exception):
    """The native start call lost its transport; the outcome is unknown."""


def check_inputs(card, tool, permissions, max_tokens, max_wall_s):
    """Schema checks on caller inputs; every refusal happens before any port is touched."""
    if tool not in TOOLS or not isinstance(card, str) or not _CARD.fullmatch(card):
        raise FabricRefusal("BRANCH_INVALID", "card or tool outside schema v1.1")
    if permissions not in PERMISSIONS:
        raise FabricRefusal("PERMISSION_WEAKER_THAN_INHERITED", str(permissions))
    if type(max_tokens) is not int or max_tokens < 1:
        raise FabricRefusal("CAPS_INVALID", "max_tokens must be an int >= 1")
    if type(max_wall_s) not in (int, float) or not math.isfinite(max_wall_s) or max_wall_s <= 0:
        raise FabricRefusal("CAPS_INVALID", "max_wall_s must be a finite number > 0")
    return {"max_tokens": max_tokens, "max_wall_s": float(max_wall_s)}


def build_record(*, card, card_uuid, tool, parent, workspace, open_key, journal, lease, caps, permissions, now):
    """Assemble a PREPARED schema-v1.1 record from measured values; never invents ids, hashes or leases."""
    if type(now) not in (int, float) or not math.isfinite(now):
        raise FabricRefusal("CLOCK_INVALID", "record time must be a finite number")
    def unknown():
        return {"state": "UNKNOWN", "evidence": None, "probe_kind": None, "probed_wall": None}
    return {"schema": SCHEMA, "card": card, "card_uuid": card_uuid, "tool": tool,
            "adapter": tool, "adapter_version": ADAPTER_VERSION, "parent": dict(parent),
            "workspace": {**workspace, "parent_snapshot": dict(workspace["parent_snapshot"])},
            "state": "PREPARED", "idempotency": {"open_key": open_key, "journal": journal},
            "native": {"kind": NATIVE_KIND[tool], "native_id": None, "cli_id": None,
                       "desktop_id": None, "id_mapping": "UNMAPPED"},
            "turns": [], "result": None,
            "visibility": {"native_sidebar": unknown(), "native_nesting": unknown()},
            "created_at": float(now), "updated_at": float(now), "rev": 0,
            "permissions": permissions, "caps": dict(caps), "lease": dict(lease)}


class Ports:
    """Production config plus injected external ports (judge amendment V2); Git, Store, Lock and redactor are real."""
    def __init__(self, spec, external):
        self.spec = dict(spec)
        self.clock = external["clock"]
        self.quota = external["quota"]
        self.native = external["native"]
        self.mailbox = external["mailbox"]
        self.git = Git()
        self.store = Store(spec["project"])
        self.lock = Lock(spec["project"], spec["caps"])
        self.caps = dict(spec["caps"])


def build_ports(spec, *, external):
    """Picklable production spec plus explicit external doubles -> Ports."""
    return Ports(spec, external)


def prepare(project, card, tool, parent, *, source_head, reviewed_ref, max_tokens, max_wall_s,
            permissions="INHERITED", ports):
    """Inputs, admission, parent binding and path rules before any effect; then lease, slot and clean workspace."""
    caps = check_inputs(card, tool, permissions, max_tokens, max_wall_s)
    admit(ports.quota.read(tool), ports.clock.wall(), tool)
    bound = _bind_parent(project, parent, ports)
    path, branch = _workspace_target(project, card, tool)
    if ports.git.rev_parse(project, reviewed_ref) != source_head:
        raise FabricRefusal("SOURCE_DIRTY_OR_STALE", f"{reviewed_ref} is not {source_head}")
    now = _wall(ports)
    lease = ports.lock.acquire_open(card, tool, {"pid": os.getpid(), "host": socket.gethostname()}, now)
    slot = None
    try:
        slot = ports.lock.acquire_slot(tool, lease["lease_id"])
        before = ports.git.parent_snapshot(project, EXCLUDE)
        ports.git.add_worktree(project, path, branch, source_head)
        state, manifest = ports.git.worktree_state(path), ports.git.head_manifest(project, source_head)
        after = ports.git.parent_snapshot(project, EXCLUDE)
        if state["head"] != source_head or not state["clean"] or state["manifest"] != manifest:
            raise FabricRefusal("WORKSPACE_UNCLEAN", str(path))
        if before != after:
            raise FabricRefusal("PARENT_SNAPSHOT_CHANGED", str(path))
        card_uuid = str(uuid.uuid4())
        workspace = {"path": str(path), "branch": branch, "source_head": source_head,
                     "source_manifest_sha256": manifest, "cleanup": "MANUAL_DRY_RUN_ONLY",
                     "reviewed_ref": reviewed_ref, "parent_snapshot": after}
        record = build_record(card=card, card_uuid=card_uuid, tool=tool, parent=bound, workspace=workspace,
                              open_key=_sha(f"{card_uuid}|{tool}|start|0".encode()),
                              journal=f"journal/{card}__{tool}", lease=lease, caps=caps,
                              permissions=permissions, now=now)
        ports.store.write_record(record)
    except FabricRefusal:  # known pre-native failure: free capacity; a partial worktree stays for manual cleanup
        ports.lock.drop_fresh_lease(card, tool, slot)
        raise
    return record


class NativeRejected(Exception):
    """The native side refused the call; it is known to have had no effect."""
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def admit(reading, now, tool=None):
    """PORTS v1 QuotaPort order, first failure wins; freshness is the owning policy's, never a constant."""
    if type(now) not in (int, float) or not math.isfinite(now):
        raise FabricRefusal("CLOCK_INVALID", "clock.wall() must be a finite number")
    if not isinstance(reading, dict) or any(key not in reading for key in _READING):
        raise FabricRefusal("ADMISSION_MALFORMED", "quota reading is not an object with every key")
    for key, kind in _READING.items():
        value = reading[key]
        if (type(value) not in (int, float)) if kind is float else (type(value) is not kind):
            raise FabricRefusal("ADMISSION_MALFORMED", f"{key} has the wrong type")
    if (tool is not None and reading["tool"] != tool) or not reading["pool"] or not reading["window"]:
        raise FabricRefusal("ADMISSION_MALFORMED", "reading is not for the requested account/pool/window")
    observed, fresh = reading["observed_wall"], reading["freshness_s"]
    if not math.isfinite(observed) or not math.isfinite(fresh) or fresh <= 0:
        raise FabricRefusal("ADMISSION_MALFORMED", "observed_wall/freshness_s must be finite, freshness_s > 0")
    if observed > now:
        raise FabricRefusal("ADMISSION_FUTURE_READING", f"observed_wall {observed} > now {now}")
    if now - observed > fresh:
        raise FabricRefusal("ADMISSION_STALE_QUOTA", f"age {now - observed} > freshness_s {fresh}")
    if reading["reset_status"] != "OBSERVED":
        raise FabricRefusal("ADMISSION_RESET_UNOBSERVED", reading["reset_status"])
    if reading["admit_paid"] is not True:
        raise FabricRefusal("ADMISSION_REFUSED", reading["evidence"])
    return dict(reading)


def redact(text):
    """RedactorPort: idempotent; every persisted string passes through it before bytes are written."""
    for pattern in _SECRETS:
        text = pattern.sub("[redacted]", text)
    return text


def _redact_all(value):
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: _redact_all(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_all(v) for v in value]
    return value


def _sha(data):
    return hashlib.sha256(data).hexdigest()


@contextmanager
def _mutex(path, wait_s=LOCK_WAIT_S):
    """O_EXCL mutex file with a bounded wait; Windows reports a delete-pending file as PermissionError."""
    deadline = time.monotonic() + wait_s
    while True:
        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except (FileExistsError, PermissionError):
            if time.monotonic() > deadline:
                raise FabricRefusal("CAP_LOCK_TIMEOUT", str(path))
            time.sleep(0.01)
    try:
        yield
    finally:
        os.unlink(path)


class Git:
    """GitPort (real): shells out to git with --no-optional-locks so the parent index is never refreshed."""

    def _run(self, cwd, *args):
        return subprocess.run(["git", "--no-optional-locks", "-C", str(cwd), *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    def rev_parse(self, project, ref):
        out = self._run(project, "rev-parse", "--verify", "--quiet", ref + "^{commit}")
        sha = out.stdout.decode("ascii", "replace").strip()
        if out.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise FabricRefusal("SOURCE_DIRTY_OR_STALE", f"unknown ref {ref}")
        return sha

    def _z(self, cwd, *args):
        return [x for x in self._run(cwd, *args).stdout.split(b"\0") if x]

    def head_manifest(self, project, sha):
        entries = self._z(project, "ls-tree", "-r", "-z", "--full-tree", sha)
        return _sha(b"\0".join(sorted(entries, key=lambda e: e.split(b"\t", 1)[-1])))

    def parent_snapshot(self, project, exclude):
        keep = lambda path: not any(path.startswith(x.encode()) for x in exclude)
        def files(paths):
            rows = []
            for path in sorted(p for p in paths if keep(p)):
                full = Path(project) / os.fsdecode(path)
                rows.append(path + b"\0" + (_sha(full.read_bytes()).encode() if full.is_file() else b"DELETED"))
            return _sha(b"\n".join(rows))
        staged = _sha(b"\0".join(e for e in self._z(project, "ls-files", "-s", "-z") if keep(e.split(b"\t", 1)[-1])))
        unstaged = files(self._z(project, "diff", "--name-only", "-z"))
        untracked = files(self._z(project, "ls-files", "-o", "--exclude-standard", "-z"))
        return {"staged": staged, "unstaged": unstaged, "untracked": untracked,
                "combined": _sha((staged + unstaged + untracked).encode())}

    def add_worktree(self, project, path, branch, sha):
        out = self._run(project, "worktree", "add", "-b", branch, str(path), sha)
        if out.returncode:
            raise FabricRefusal("WORKTREE_FAILED", redact(out.stderr.decode("utf-8", "replace"))[:ERROR_MAX])

    def worktree_state(self, path):
        head = self.rev_parse(path, "HEAD")
        status = self._run(path, "status", "--porcelain=v1", "-uall")
        return {"head": head, "clean": status.returncode == 0 and not status.stdout.strip(),
                "manifest": self.head_manifest(path, head)}


class Store:
    """StorePort (real): records, journal and parent bindings under <project>/.coord/fabric/."""

    def __init__(self, project):
        self.root = Path(project) / ".coord" / "fabric"

    def read_parent(self, desk_id):
        if not isinstance(desk_id, str) or not _DESK.fullmatch(desk_id):
            return None
        try:
            data = json.loads((self.root / "parents" / f"{desk_id}.json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError:
            raise FabricRefusal("CORRUPT_RECORD", f"parent {desk_id}")
        return data if isinstance(data, dict) else None

    def _path(self, card, tool):
        return self.root / "records" / f"{card}__{tool}.json"

    def read_record(self, card, tool):
        try:
            data = json.loads(self._path(card, tool).read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except ValueError:
            raise FabricRefusal("CORRUPT_RECORD", f"{card}__{tool} is not JSON")
        if not isinstance(data, dict) or data.get("schema") != SCHEMA or type(data.get("rev")) is not int:
            raise FabricRefusal("CORRUPT_RECORD", f"{card}__{tool} is not schema v1.1")
        return data

    def write_record(self, record):
        """tmp + fsync + os.replace under the record lock; rev 0 only creates, rev n needs stored rev n-1."""
        path = self._path(record["card"], record["tool"])
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(_redact_all(record), allow_nan=False, sort_keys=True).encode("utf-8")
        with _mutex(path.with_name(path.name + ".lock")):
            stored = self.read_record(record["card"], record["tool"])
            if record["rev"] == 0 and stored is not None:
                raise FabricRefusal("STALE_RECORD", f"a record already exists at rev {stored['rev']}")
            if record["rev"] > 0 and (stored is None or stored["rev"] != record["rev"] - 1):
                raise FabricRefusal("STALE_RECORD", f"stored rev is not {record['rev'] - 1}")
            tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
            with open(tmp, "xb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)

    def append_intent(self, card, tool, kind, payload):
        """One O_EXCL file per entry, fsynced; concurrent appends to one file lose lines on Windows."""
        folder = self.root / "journal" / f"{card}__{tool}"
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{time.monotonic_ns():020d}_{os.getpid()}_{kind}.json"
        fd = os.open(folder / name, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
        with os.fdopen(fd, "wb") as f:
            f.write(json.dumps(_redact_all({"kind": kind, **payload}), allow_nan=False).encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        return name

    def list_intents(self, card, tool):
        folder = self.root / "journal" / f"{card}__{tool}"
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("*.json"))]


class Lock:
    """LockPort (real): O_EXCL open leases and cap slots; no automatic reclaim of any held slot or lease."""
    def __init__(self, project, caps):
        self.root = Path(project) / ".coord" / "fabric" / "locks"
        self.caps = dict(caps)

    def acquire_open(self, card, tool, owner, now):
        self.root.mkdir(parents=True, exist_ok=True)
        lease = {"lease_id": _sha(f"{card}|{tool}|{owner['pid']}|{owner['host']}|{uuid.uuid4().hex}".encode()),
                 "owner_pid": owner["pid"], "owner_host": owner["host"], "acquired_wall": float(now)}
        try:
            fd = os.open(self.root / f"open_{card}__{tool}.lease", os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise FabricRefusal("LEASE_HELD", f"{card}__{tool}")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(lease, f)
            f.flush()
            os.fsync(f.fileno())
        return lease

    def drop_fresh_lease(self, card, tool, slot=None):
        """Only prepare calls this, for the lease (and slot) it took itself, after a known pre-native failure."""
        if slot is not None:
            with _mutex(self.root / "caps.lock"):
                os.unlink(self.root / "slots" / slot)
        os.unlink(self.root / f"open_{card}__{tool}.lease")

    def acquire_slot(self, tool, lease_id):
        slots = self.root / "slots"
        slots.mkdir(parents=True, exist_ok=True)
        with _mutex(self.root / "caps.lock"):
            held = [p.name.split("__", 1)[0] for p in slots.glob("*.slot")]
            if len(held) >= self.caps["global"]:
                raise FabricRefusal("CAP_GLOBAL", f"{len(held)} slots held")
            if held.count(tool) >= self.caps[tool]:
                raise FabricRefusal("CAP_TOOL", f"{held.count(tool)} {tool} slots held")
            (slots / f"{tool}__{lease_id}.slot").write_text(lease_id, encoding="utf-8")
        return f"{tool}__{lease_id}.slot"


def _wall(ports):
    now = ports.clock.wall()
    if type(now) not in (int, float) or not math.isfinite(now):
        raise FabricRefusal("CLOCK_INVALID", "clock.wall() must be a finite number")
    return float(now)


def _bind_parent(project, parent, ports):
    """Amendment V2: the supplied parent must equal the independently registered binding for its desk."""
    bound = ports.store.read_parent(parent.get("desk_id")) if isinstance(parent, dict) else None
    if bound is None or any(bound.get(k) != parent.get(k) for k in PARENT_KEYS) \
            or os.path.normcase(os.path.abspath(project)) != os.path.normcase(os.path.abspath(bound["project_root"])):
        raise FabricRefusal("PARENT_UNBOUND", "parent does not match its registered binding")
    return {**{k: bound[k] for k in PARENT_KEYS}, "handoff": None}


def _workspace_target(project, card, tool):
    """PORTS v1 s4 path rules, all before any git or native call."""
    root = Path(os.path.abspath(Path(project) / ".work" / "wt"))
    path = Path(os.path.abspath(root / f"{card}-{tool}"))
    if root not in path.parents:
        raise FabricRefusal("PATH_ESCAPE", str(path))
    if len(str(path)) > MAX_PATH_CHARS:
        raise FabricRefusal("PATH_TOO_LONG", f"{len(str(path))} > {MAX_PATH_CHARS}")
    head, _, tail = card.partition("-")
    branch = f"{tool}/{head}" + (f"-{tail.lower()}" if tail else "")
    if not _BRANCH.fullmatch(branch):
        raise FabricRefusal("BRANCH_INVALID", branch)
    return path, branch


def _load(record, ports, allowed):
    """Re-read the stored record; the caller's rev must match and its state must allow the call."""
    stored = ports.store.read_record(record["card"], record["tool"])
    if stored is None or stored["rev"] != record["rev"]:
        raise FabricRefusal("STALE_RECORD", f"caller rev {record['rev']}")
    if stored["state"] not in allowed:
        raise FabricRefusal("ILLEGAL_STATE", stored["state"])
    return copy.deepcopy(stored)


def _save(rec, ports, **changes):
    rec = _redact_all({**rec, **changes, "rev": rec["rev"] + 1, "updated_at": _wall(ports)})
    ports.store.write_record(rec)
    return rec


def start(record, manual_text, *, ports):
    """PORTS v1 s5: S1 intent, S2 STARTING, S3 native.start with caps, S4 RUNNING with native ids."""
    rec = _load(record, ports, ("PREPARED",))
    key = rec["idempotency"]["open_key"]
    ports.store.append_intent(rec["card"], rec["tool"], "start", {"key": key})
    rec = _save(rec, ports, state="STARTING")
    began = _wall(ports)
    try:
        ids = ports.native[rec["tool"]].start(workspace=rec["workspace"]["path"], title=f"{rec['card']} {rec['tool']}",
                                              manual_text=manual_text, permissions=rec["permissions"],
                                              idempotency_key=key, caps=dict(rec["caps"]))
    except NativeTransportLost:
        return _save(rec, ports, state="EFFECT_UNKNOWN")
    except NativeRejected:
        return _save(rec, ports, state="FAILED")
    turn = {"turn_key": _sha(f"{key}|turn|0".encode()), "native_turn_id": ids.get("turn_id"), "status": "SENT",
            "terminal_event": None, "started_at": began, "ended_at": None, "tokens": None, "error": None}
    native = {**rec["native"], **{k: ids.get(k) for k in ("native_id", "cli_id", "desktop_id")}}
    return _save(rec, ports, state="RUNNING", native=native, turns=[*rec["turns"], turn])


def await_turn(record, turn_key, *, ports, time_cap_s):
    """Only a native terminal event ends a turn; None (deadline) or an unknown status is EFFECT_UNKNOWN."""
    rec = _load(record, ports, ("RUNNING",))
    if type(time_cap_s) not in (int, float) or not math.isfinite(time_cap_s) or time_cap_s <= 0:
        raise FabricRefusal("CAPS_INVALID", "time_cap_s must be a finite number > 0")
    turns = [dict(t) for t in rec["turns"]]
    turn = next((t for t in turns if t["turn_key"] == turn_key), None)
    if turn is None:
        raise FabricRefusal("ILLEGAL_STATE", "unknown turn_key")
    mono = ports.clock.mono()
    if type(mono) not in (int, float) or not math.isfinite(mono):
        raise FabricRefusal("CLOCK_INVALID", "clock.mono() must be a finite number")
    out = ports.native[rec["tool"]].await_terminal(rec["native"]["native_id"], turn["native_turn_id"],
                                                   deadline_mono=mono + time_cap_s)
    status = _TERMINAL.get(out.get("status")) if isinstance(out, dict) else None
    if status is None:
        turn["status"] = "EFFECT_UNKNOWN"
        return _save(rec, ports, state="EFFECT_UNKNOWN", turns=turns)
    tokens, error = out.get("tokens"), out.get("error")
    turn.update(status=status, terminal_event=redact(str(out.get("event")))[:ERROR_MAX], ended_at=_wall(ports),
                tokens=tokens if type(tokens) is int and tokens >= 0 else None,
                error=None if error is None else redact(str(error))[:ERROR_MAX])
    return _save(rec, ports, state="WAITING" if status == "COMPLETED" else "FAILED", turns=turns)
