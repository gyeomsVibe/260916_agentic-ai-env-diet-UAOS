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


_HEX64 = "[0-9a-f]{64}"  # schema v1.1 sha256 / lease id / key pattern


_UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"  # card_uuid format uuid, str(uuid4()) form


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
    card_uuid, slot = str(uuid.uuid4()), None
    workspace = {"path": str(path), "branch": branch, "source_head": source_head, "source_manifest_sha256": None,
                 "cleanup": "MANUAL_DRY_RUN_ONLY", "reviewed_ref": reviewed_ref, "parent_snapshot": {}}
    fields = dict(card=card, card_uuid=card_uuid, tool=tool, parent=bound, workspace=workspace,
                  open_key=_sha(f"{card_uuid}|{tool}|start|0".encode()), journal=f"journal/{card}__{tool}",
                  lease=lease, caps=caps, permissions=permissions, now=now)
    try:
        slot = ports.lock.acquire_slot(tool, lease["lease_id"])
        before = ports.git.parent_snapshot(project, EXCLUDE)
        manifest = ports.git.head_manifest(project, source_head)  # measured before any worktree effect
        workspace.update(parent_snapshot=before, source_manifest_sha256=manifest)
        ports.git.add_worktree(project, path, branch, source_head)
        state = ports.git.worktree_state(path)
        after = ports.git.parent_snapshot(project, EXCLUDE)
        if state["head"] != source_head or not state["clean"] or state["manifest"] != manifest:
            raise FabricRefusal("WORKSPACE_UNCLEAN", str(path))
        if before != after:
            raise FabricRefusal("PARENT_SNAPSHOT_CHANGED", str(path))
        record = build_record(**fields)
        ports.store.write_record(record)
    except FabricRefusal as refusal:  # known pre-native failure: durable FAILED evidence, capacity freed even on OSError
        try:
            _record_failure(ports, fields, refusal.code)
        finally:
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
        """cwd must itself be a repository or worktree root: discovery never climbs into an enclosing repository."""
        env = dict(os.environ, GIT_CEILING_DIRECTORIES=os.path.dirname(os.path.realpath(cwd)))
        return subprocess.run(["git", "--no-optional-locks", "-C", str(cwd), *args],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)

    def rev_parse(self, project, ref):
        """--end-of-options: a caller ref that starts with '-' is read as a revision, never as a git option"""
        out = self._run(project, "rev-parse", "--verify", "--quiet", "--end-of-options", ref + "^{commit}")
        sha = out.stdout.decode("ascii", "replace").strip()
        if out.returncode or not re.fullmatch(r"[0-9a-f]{40}", sha):
            raise FabricRefusal("SOURCE_DIRTY_OR_STALE", f"unknown ref {ref}")
        return sha

    def _z(self, cwd, *args):
        out = self._run(cwd, *args)
        if out.returncode:
            raise FabricRefusal("SOURCE_DIRTY_OR_STALE", redact(out.stderr.decode("utf-8", "replace"))[:ERROR_MAX])
        return [x for x in out.stdout.split(b"\0") if x]

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
        if not _V11(data) or data["card"] != card or data["tool"] != tool:
            raise FabricRefusal("CORRUPT_RECORD", f"{card}__{tool} is not a schema v1.1 record for this card and tool")
        return data

    def write_record(self, record):
        """tmp + fsync + os.replace under the record lock; rev 0 only creates, rev n needs stored rev n-1."""
        if not _V11(record) or _redact_all(record) != record:
            raise FabricRefusal("CORRUPT_RECORD", "not a schema v1.1 record, or secret-shaped text (refused, never rewritten)")
        path = self._path(record["card"], record["tool"])
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(record, allow_nan=False, sort_keys=True).encode("utf-8")
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

    def append_intent(self, card, tool, kind, payload, once=False):
        """One O_EXCL file per entry, fsynced, under the journal mutex; once=True reuses an entry of this kind and key."""
        folder = self.root / "journal" / f"{card}__{tool}"
        folder.mkdir(parents=True, exist_ok=True)
        with _mutex(folder.with_name(folder.name + ".lock")):
            if once and any(i.get("kind") == kind and i.get("key") == payload.get("key")
                            for i in self.list_intents(card, tool)):
                return None
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
    if any(_redact_all(bound[k]) != bound[k] for k in PARENT_KEYS):
        raise FabricRefusal("PARENT_UNBOUND", "a parent identifier holds secret-shaped text; refused, not rewritten")
    return {**{k: bound[k] for k in PARENT_KEYS}, "handoff": None}


def _workspace_target(project, card, tool):
    """PORTS v1 s4 path rules, all before any git or native call; links and junctions are resolved first."""
    root = Path(os.path.abspath(Path(project) / ".work" / "wt"))
    path = Path(os.path.abspath(root / f"{card}-{tool}"))
    real_project, real_root = Path(os.path.realpath(project)), Path(os.path.realpath(root))
    if root not in path.parents or real_project not in real_root.parents \
            or real_root not in Path(os.path.realpath(path)).parents:
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
    rec = {**rec, **changes, "rev": rec["rev"] + 1, "updated_at": _wall(ports)}
    ports.store.write_record(rec)
    return rec


def start(record, manual_text, *, ports):
    """PORTS v1 s5: S1 intent (once per open key, survives a crash), S2 STARTING, S3 native.start, S4 RUNNING."""
    rec = _load(record, ports, ("PREPARED",))
    key = rec["idempotency"]["open_key"]
    ports.store.append_intent(rec["card"], rec["tool"], "start", {"key": key}, once=True)
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


def _record_failure(ports, fields, code):
    """Known pre-native failure: always a durable prepare_failed intent (manifest null while unmeasured, never
    invented), then a FAILED rev-0 record when the fields are schema-valid; an existing record is never overwritten."""
    ports.store.append_intent(fields["card"], fields["tool"], "prepare_failed",
                              {"state": "FAILED", "failure_code": code, "card_uuid": fields["card_uuid"],
                               "source_manifest_sha256": fields["workspace"]["source_manifest_sha256"]})
    try:
        record = build_record(**fields)
        record["state"] = "FAILED"
        ports.store.write_record(record)
    except FabricRefusal:
        pass


def _text(minimum=0, pattern=None, maximum=None):
    """schema v1.1 string: a str of minimum..maximum chars that fully matches pattern when one is given"""
    return lambda v: (isinstance(v, str) and len(v) >= minimum and (maximum is None or len(v) <= maximum)
                      and (pattern is None or re.fullmatch(pattern, v) is not None))


def _number(low=None, exclusive=False):
    """schema v1.1 number: int or float but never bool, finite, and at or above (or above) low when given"""
    return lambda v: (type(v) in (int, float) and math.isfinite(v)
                      and (low is None or (v > low if exclusive else v >= low)))


def _integer(low):
    """schema v1.1 integer with a minimum: bool is not an integer here"""
    return lambda v: type(v) is int and v >= low


def _enum(*values):
    """schema v1.1 enum/const: equal value of the same type, so True never matches 1"""
    return lambda v: any(type(v) is type(x) and v == x for x in values)


def _nullable(check):
    return lambda v: v is None or check(v)


def _closed(fields, optional=()):
    """schema v1.1 object, additionalProperties false: no unknown key, every non-optional key, each value valid"""
    return lambda v: (isinstance(v, dict) and set(v) <= set(fields) and set(fields) - set(optional) <= set(v)
                      and all(fields[k](v[k]) for k in v))


def _v11_workspace():
    """schema v1.1 parent, workspace and idempotency (card_session_v1_1.schema.json 882e9e77)"""
    lanes = ("IMPL_CODE", "VERIFY_AUDIT", "ARCH_DESIGN", "MERGE_RELEASE", "RECOVERY_OPS")
    handoff = lambda v: v is None or (isinstance(v, dict) and {"from_desk", "to_desk", "at", "receipt"} <= set(v))
    snapshot = _closed({k: _text(pattern=_HEX64) for k in ("staged", "unstaged", "untracked", "combined")})
    return {"parent": _closed({"desk_id": _text(1), "desk_tool": _enum(*TOOLS), "project_root": _text(),
                               "owner": _text(), "lane": _enum(*lanes), "handoff": handoff}, optional=("handoff",)),
            "workspace": _closed({"path": _text(), "branch": _text(pattern=r"[a-z]+/U[0-9]{2,4}[-a-z0-9]*"),
                                  "source_head": _text(pattern="[0-9a-f]{40}"),
                                  "source_manifest_sha256": _text(pattern=_HEX64),
                                  "cleanup": _enum("MANUAL_DRY_RUN_ONLY"), "reviewed_ref": _text(1),
                                  "parent_snapshot": snapshot}),
            # the schema text leaves idempotency open; it is closed here as fail-closed (Codex probe idempotency_extra_key)
            "idempotency": _closed({"open_key": _text(pattern=_HEX64), "journal": _text()})}


def _v11_native():
    """schema v1.1 native, visibility, caps and lease"""
    probe = _closed({"state": _enum("OBSERVED", "UNKNOWN", "UNSUPPORTED"), "evidence": _nullable(_text()),
                     "probe_kind": _enum("live", "fake", None), "probed_wall": _nullable(_number())})
    return {"native": _closed({"kind": _enum(*NATIVE_KIND.values()), "native_id": _nullable(_text()),
                               "cli_id": _nullable(_text()), "desktop_id": _nullable(_text()),
                               "id_mapping": _enum("SAME", "MAPPED_OBSERVED", "UNMAPPED")}),
            "visibility": _closed({"native_sidebar": probe, "native_nesting": probe}),
            "caps": _closed({"max_tokens": _integer(1), "max_wall_s": _number(0, exclusive=True)}),
            "lease": _closed({"lease_id": _text(pattern=_HEX64), "owner_pid": _integer(1), "owner_host": _text(1),
                              "acquired_wall": _number()})}


def _v11_turns_result():
    """schema v1.1 turns[] items and result (with its judgment)"""
    turn = _closed({"turn_key": _text(pattern=_HEX64), "native_turn_id": _nullable(_text()),
                    "status": _enum("SENT", "COMPLETED", "FAILED", "INTERRUPTED", "EFFECT_UNKNOWN"),
                    "terminal_event": _nullable(_text()), "started_at": _number(), "ended_at": _nullable(_number()),
                    "tokens": _nullable(_integer(0)), "error": _nullable(_text(maximum=ERROR_MAX))})
    judgment = _closed({"judge_tool": _enum(*TOOLS), "verdict": _enum("PASS", "REVISE", "FAIL"),
                        "evidence": _text(1), "judged_at": _number()})
    result = _closed({"result_id": _text(pattern=_HEX64), "author_tool": _enum(*TOOLS), "receipt_id": _text(1),
                      "status": _enum("QUEUED", "DELIVERED", "READ", "ACKED"), "status_at": _number(),
                      "delivered_to": _text(1), "judgment": _nullable(judgment)})
    return {"turns": lambda v: isinstance(v, list) and all(turn(t) for t in v), "result": _nullable(result)}


def _v11_record():
    """the whole schema v1.1 record; every required key, no unknown key at any level"""
    states = ("PREPARED", "STARTING", "RUNNING", "WAITING", "COMPLETED", "FAILED", "EFFECT_UNKNOWN")
    return _closed({"schema": _enum(SCHEMA), "card": _text(pattern=_CARD.pattern), "card_uuid": _text(pattern=_UUID),
                    "tool": _enum(*TOOLS), "adapter": _text(), "adapter_version": _text(1), "state": _enum(*states),
                    "permissions": _enum(*PERMISSIONS), "created_at": _number(), "updated_at": _number(),
                    "rev": _integer(0), **_v11_workspace(), **_v11_native(), **_v11_turns_result()})


def _V11(record):
    """read_record and write_record both refuse anything this rejects; the checks are rebuilt per call (cheap)"""
    return _v11_record()(record)


def tree(project, desk_id, *, ports):
    """Stored card sessions under one parent desk, read-only: never probes, never mutates rev (amendment V2)."""
    if not isinstance(desk_id, str) or not _DESK.fullmatch(desk_id):
        return []
    store, rows = Store(project), []  # the named project's store; ports is kept for the pinned signature (D3)
    for path in sorted((store.root / "records").glob("*__*.json")):
        card, _, tool = path.stem.rpartition("__")
        record = store.read_record(card, tool)  # a corrupt record refuses (CORRUPT_RECORD), never skipped
        if record is None or record["parent"]["desk_id"] != desk_id:
            continue
        seen = {record["visibility"][k]["state"] for k in ("native_sidebar", "native_nesting")}
        rows.append({"card": card, "tool": tool, "card_uuid": record["card_uuid"], "state": record["state"],
                     "native_id": record["native"]["native_id"], "rev": record["rev"],
                     "native_visibility": seen.pop() if len(seen) == 1 else "UNKNOWN"})
    return rows
