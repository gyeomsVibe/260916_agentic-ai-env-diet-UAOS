"""U326 card-session fabric: schema constants and refusal types (M1 skeleton)."""
from __future__ import annotations
import math
import re

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
    """Production config plus injected external ports (judge amendment V2); git/store/lock land in later slices."""
    def __init__(self, spec, external):
        self.spec = dict(spec)
        self.clock = external["clock"]
        self.quota = external["quota"]
        self.native = external["native"]
        self.mailbox = external["mailbox"]


def build_ports(spec, *, external):
    """Picklable production spec plus explicit external doubles -> Ports."""
    return Ports(spec, external)


def prepare(project, card, tool, parent, *, source_head, reviewed_ref, max_tokens, max_wall_s,
            permissions="INHERITED", ports):
    """Inputs, then quota admission, both before any native call; lease and workspace are not built yet."""
    check_inputs(card, tool, permissions, max_tokens, max_wall_s)
    admit(ports.quota.read(tool), ports.clock.wall())
    raise NotImplementedError("U326-M1: lease and workspace slices have not landed")


class NativeRejected(Exception):
    """The native side refused the call; it is known to have had no effect."""
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def admit(reading, now):
    """PORTS v1 QuotaPort order, first failure wins; freshness is the owning policy's, never a constant."""
    if type(now) not in (int, float) or not math.isfinite(now):
        raise FabricRefusal("CLOCK_INVALID", "clock.wall() must be a finite number")
    if not isinstance(reading, dict) or any(key not in reading for key in _READING):
        raise FabricRefusal("ADMISSION_MALFORMED", "quota reading is not an object with every key")
    for key, kind in _READING.items():
        value = reading[key]
        if (type(value) not in (int, float)) if kind is float else (type(value) is not kind):
            raise FabricRefusal("ADMISSION_MALFORMED", f"{key} has the wrong type")
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
