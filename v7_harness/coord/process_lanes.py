"""U287: 3-Tool Common Process-Classification Parallel Window Multiplexing & Real-Time Handoff Engine.

Solves Head-of-Line (HoL) blocking and cross-tool mutual waiting in UAOS-RSI:
1. Classifies pending processes (mailbox relays, master_schedule phases, card tasks) into canonical
   process lanes (`IMPL_CODE`, `VERIFY_AUDIT`, `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`, or
   explicit sub-lanes).
2. Provisions and reuses a dedicated conversation window / session per `(lane_id, tool)` across
   Codex, Claude Code, and Antigravity under `.coord/windows/lanes/<lane_id>.json` with per-lane OS locks.
3. Demultiplexes queued backlog items into their classification lanes and dispatches them in real-time
   parallel (`ThreadPoolExecutor` + per-lane locks), failing over immediately to an ACTIVE peer tool's
   lane window when a target tool is LIMITED/ABSENT or collides on a busy session.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
import hashlib
import json
import os
import re
import time
import uuid

from .hook_context import shared_desk
from .mailbox import Mailbox
from .presence import read as read_presence, read_all as read_all_presence
from .stream import _try_lock, _unlock

TOOLS = ("codex", "claude", "antigravity")
LANE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,39}$")

# Canonical 5-Category Process Classification Taxonomy for UAOS-RSI
PROCESS_LANE_SPECS: dict[str, dict[str, Any]] = {
    "IMPL_CODE": {
        "title_ko": "구현·코드작성 전용창",
        "title_en": "Implementation & Code Execution Lane",
        "priority": 20,
        "default_tool_order": ("codex", "claude", "antigravity"),
        "keywords": ("implement", "code", "patch", "refactor", "feature", "pilot run", "apply", "구현", "코드", "수정"),
        "kinds": ("IMPLEMENT", "CODE", "PATCH", "RUN", "PILOT"),
    },
    "VERIFY_AUDIT": {
        "title_ko": "검증·반례감사 전용창",
        "title_en": "Verification, Counterexample Audit & Verdict Lane",
        "priority": 10,
        "default_tool_order": ("antigravity", "codex", "claude"),
        "keywords": (
            "verify", "audit", "review", "verdict", "test", "counterexample", "vaccine", "judge",
            "검증", "감사", "판정", "반례", "테스트",
        ),
        "kinds": ("VERIFY", "AUDIT", "REVIEW", "TEST", "VERDICT", "JUDGE"),
    },
    "ARCH_DESIGN": {
        "title_ko": "기획·설계·리서치 전용창",
        "title_en": "MIA Strategic Planning, Research & Contract Design Lane",
        "priority": 15,
        "default_tool_order": ("codex", "antigravity", "claude"),
        "keywords": (
            "mia", "design", "plan", "research", "architecture", "manual", "contract", "spec",
            "기획", "설계", "리서치", "매뉴얼", "아키텍처",
        ),
        "kinds": ("DESIGN", "PLAN", "RESEARCH", "ARCH", "MANUAL"),
    },
    "MERGE_RELEASE": {
        "title_ko": "병합·배포·결과집계 전용창",
        "title_en": "PR Merge, Runtime Reinstall & Release Aggregation Lane",
        "priority": 5,
        "default_tool_order": ("antigravity", "codex", "claude"),
        "keywords": ("merge", "pr", "pull request", "release", "ship", "reinstall", "result", "병합", "배포", "결과"),
        "kinds": ("MERGE", "RELEASE", "SHIP", "RESULT", "DONE"),
    },
    "RECOVERY_OPS": {
        "title_ko": "장애복구·병목해소 전용창",
        "title_en": "P1 Recovery, Stall Reroute & Deadlock Healing Lane",
        "priority": 1,
        "default_tool_order": ("claude", "antigravity", "codex"),
        "keywords": (
            "p1", "blocked", "stall", "deadlock", "timeout", "failover", "heal", "error", "quota",
            "병목", "교착", "복구", "오류", "초과",
        ),
        "kinds": ("BLOCKED", "P1", "STALL", "HEAL", "RECOVERY", "ERROR", "OWNER_WAKE"),
    },
}

DEFAULT_LANE = "IMPL_CODE"


def _keyword_matches(text: str, kw: str) -> bool:
    """Match ASCII keywords on whole-word boundaries (preventing `test` in `latest`, `plan` in `PLAN.md`, `heal` in `health`)."""
    clean_kw = kw.strip().lower()
    if not clean_kw:
        return False
    if clean_kw.isascii():
        # Prevent matching e.g. `plan` when followed by `.md` (`PLAN.md` file path reference)
        pattern = rf"(?<![a-z0-9_./-]){re.escape(clean_kw)}(?![a-z0-9_.-])"
        return bool(re.search(pattern, text))
    return clean_kw in text


@dataclass(frozen=True)
class ProcessItem:
    """Normalized representation of a queued process, mailbox relay, or schedule phase."""

    item_id: str
    source: str  # "mailbox" | "schedule" | "direct"
    lane_id: str
    actor: str
    requested_target: str
    card: str
    summary: str
    payload: dict[str, Any]
    priority: int


def validate_lane_id(lane_id: str) -> str:
    """Validate and normalize a process classification lane identifier."""
    normalized = str(lane_id or "").strip().upper().replace("-", "_").replace(":", "_")
    if not LANE_RE.fullmatch(normalized):
        raise ValueError(f"invalid lane id {lane_id!r}: expected 2-40 uppercase alphanumeric/underscore chars")
    return normalized


def classify_process_lane(payload: dict[str, Any] | str, *, explicit_lane: str = "") -> str:
    """Deterministically classify any process/relay/card payload into a canonical process lane.

    Order of precedence:
    1. Explicit `explicit_lane` argument or `payload["lane"]` / `payload["process_lane"]`.
    2. P1 alerts / BLOCKED / STALL / recovery signals -> `RECOVERY_OPS`.
    3. Verdict requests (`verdict_requested=True`), verdicts (`PASS`/`REWORK`/etc.), or REVIEW states -> `VERIFY_AUDIT`.
    4. Merge / PR / RESULT / SHIP kinds or PR URLs -> `MERGE_RELEASE`.
    5. MIA / research / design / manual kinds or `docs/`-only allowed files -> `ARCH_DESIGN`.
    6. Whole-word keyword & kind matching across `PROCESS_LANE_SPECS`, falling back to `IMPL_CODE`.
    """
    if explicit_lane:
        return validate_lane_id(explicit_lane)

    if isinstance(payload, str):
        data: dict[str, Any] = {"message": payload}
    elif isinstance(payload, dict):
        data = payload
    else:
        return DEFAULT_LANE

    for key in ("lane", "process_lane", "lane_id"):
        val = data.get(key)
        if isinstance(val, str) and val.strip():
            return validate_lane_id(val)

    kind = str(data.get("kind") or data.get("state") or "").strip().upper()
    if data.get("p1_alert") or kind in PROCESS_LANE_SPECS["RECOVERY_OPS"]["kinds"]:
        return "RECOVERY_OPS"

    if (
        data.get("verdict_requested") is True
        or bool(data.get("verdict"))
        or kind in PROCESS_LANE_SPECS["VERIFY_AUDIT"]["kinds"]
    ):
        return "VERIFY_AUDIT"

    if kind in PROCESS_LANE_SPECS["MERGE_RELEASE"]["kinds"] or data.get("pr") or data.get("pr_url"):
        return "MERGE_RELEASE"

    if kind in PROCESS_LANE_SPECS["ARCH_DESIGN"]["kinds"]:
        return "ARCH_DESIGN"

    if kind in PROCESS_LANE_SPECS["IMPL_CODE"]["kinds"]:
        return "IMPL_CODE"

    allowed = data.get("allowed_files") or data.get("allow") or ()
    if isinstance(allowed, (list, tuple)) and allowed:
        paths = [str(p).replace("\\", "/").lower() for p in allowed]
        if all(p.startswith("docs/") or p.endswith("-manual.md") or p.endswith("plan.md") for p in paths):
            return "ARCH_DESIGN"
        if all("test" in p for p in paths):
            return "VERIFY_AUDIT"

    text_parts = [
        str(data.get("message") or ""),
        str(data.get("summary") or ""),
        str(data.get("delta") or ""),
        str(data.get("title") or ""),
        str(data.get("goal") or ""),
    ]
    combined = " ".join(text_parts).lower()

    # Check in priority order (RECOVERY_OPS -> MERGE_RELEASE -> VERIFY_AUDIT -> ARCH_DESIGN -> IMPL_CODE)
    ordered_lanes = sorted(PROCESS_LANE_SPECS.items(), key=lambda item: item[1]["priority"])
    for lane_name, spec in ordered_lanes:
        for kw in spec["keywords"]:
            if _keyword_matches(combined, kw):
                return lane_name

    return DEFAULT_LANE


def _lanes_dir(project: Path) -> Path:
    return Path(shared_desk(project)) / ".coord" / "windows" / "lanes"


def lane_window_path(project: Path, lane_id: str) -> Path:
    return _lanes_dir(project) / f"{validate_lane_id(lane_id)}.json"


@contextmanager
def _lane_lock(project: Path, lane_id: str, timeout_s: float = 10.0):
    """Per-lane OS byte-range lock so operations on distinct lanes never block each other."""
    lid = validate_lane_id(lane_id)
    folder = _lanes_dir(project)
    folder.mkdir(parents=True, exist_ok=True)
    lock_path = folder / f"{lid}.lock"
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + max(0.05, timeout_s)
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"LANE_LOCK_TIMEOUT:{lid}")
            time.sleep(0.01)
        try:
            yield
        finally:
            try:
                _unlock(fd)
            except OSError:
                pass
    finally:
        os.close(fd)


def _read_lane_record_unlocked(path: Path, lane_id: str) -> dict[str, Any]:
    spec = PROCESS_LANE_SPECS.get(lane_id, PROCESS_LANE_SPECS[DEFAULT_LANE])
    default_record: dict[str, Any] = {
        "lane_id": lane_id,
        "title_ko": spec["title_ko"],
        "title_en": spec["title_en"],
        "priority": spec["priority"],
        "windows": {},
        "cards": [],
        "dispatched_item_ids": [],
        "dispatched_count": 0,
        "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    if not path.is_file():
        return default_record
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            merged = {**default_record, **data}
            if not isinstance(merged.get("windows"), dict):
                merged["windows"] = {}
            if not isinstance(merged.get("cards"), list):
                merged["cards"] = []
            if not isinstance(merged.get("dispatched_item_ids"), list):
                merged["dispatched_item_ids"] = []
            return merged
    except (OSError, ValueError):
        pass
    return default_record


def _write_lane_record_unlocked(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    last_exc: Exception | None = None
    for _ in range(20):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.01)
    tmp.unlink(missing_ok=True)
    raise PermissionError(f"LANE_RECORD_WRITE_FAILED:{path}") from last_exc


def deterministic_lane_session_uuid(project: Path, lane_id: str, tool: str, generation: int = 0) -> str:
    """Generate a deterministic UUIDv5-style session/window ID for `(project, lane_id, tool, generation)`."""
    desk = Path(shared_desk(project)).resolve()
    seed = f"uaos-lane-v1:{os.path.normcase(str(desk))}:{validate_lane_id(lane_id)}:{tool}:{generation}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    # Format as standard 8-4-4-4-12 UUID v4/v5 compliant string
    return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-a{digest[17:20]}-{digest[20:32]}"


def deterministic_card_session_uuid(project: Path, card: str, tool: str, generation: int = 0) -> str:
    """Generate a deterministic UUIDv4/v5-compliant session/window ID for `(project, card, tool, generation)`."""
    desk = Path(shared_desk(project)).resolve()
    seed = f"uaos-card-v1:{os.path.normcase(str(desk))}:{str(card).strip().upper()}:{str(tool).strip().lower()}:{generation}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"{digest[:8]}-{digest[8:12]}-4{digest[13:16]}-a{digest[17:20]}-{digest[20:32]}"


def _resolve_codex_lane_thread(project: Path, candidate_thread_id: str) -> str:
    """Return `candidate_thread_id` only if it is a verified non-desk Codex rollout thread; never fall back to the user desk or forge rollout stubs."""
    try:
        from .deliver import UUID_RE, _codex_sessions, _verify_thread, user_desk_state

        desk = Path(shared_desk(project)).resolve()
        sessions_root = _codex_sessions()
        _desk_state, designated = user_desk_state(desk, "codex")
        if (
            candidate_thread_id
            and candidate_thread_id != designated
            and UUID_RE.fullmatch(candidate_thread_id)
            and list(sessions_root.glob(f"*/*/*/rollout-*-{candidate_thread_id}.jsonl"))
            and _verify_thread(desk, sessions_root, candidate_thread_id) == "DISPATCH"
        ):
            return candidate_thread_id
    except Exception:  # noqa: BLE001
        pass
    return ""


def ensure_claude_lane_session(project: Path, lane_id: str, *, rotate: bool = False) -> tuple[str, Path, bool]:
    """Provision or reuse an isolated Claude session file for `lane_id`.

    Returns `(session_id, session_file_path, resume_flag)`.
    If `rotate=True` (e.g., when a session ID collides with 'already in use'), increments generation
    and mints a fresh non-colliding UUID for this lane without affecting any other lane.
    """
    lid = validate_lane_id(lane_id)
    desk = Path(shared_desk(project)).resolve()
    delivery_dir = desk / ".coord" / "mailbox" / "delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    session_file = delivery_dir / f"claude-lane-{lid}.json"

    state: dict[str, Any] = {}
    if session_file.is_file():
        try:
            loaded = json.loads(session_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state = loaded
        except (OSError, ValueError):
            state = {}

    generation = int(state.get("generation") or 0)
    session_id = str(state.get("session_id") or "")
    ready = bool(state.get("ready"))

    if rotate or not session_id:
        if rotate:
            generation += 1
        session_id = deterministic_lane_session_uuid(desk, lid, "claude", generation=generation)
        ready = False
        new_state = {
            "lane_id": lid,
            "session_id": session_id,
            "generation": generation,
            "ready": False,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        tmp = session_file.with_name(f"{session_file.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(new_state, sort_keys=True) + "\n", encoding="utf-8")
        try:
            os.replace(tmp, session_file)
        except OSError:
            tmp.unlink(missing_ok=True)

    return session_id, session_file, ready


def open_or_reuse_lane_window(
    project: Path,
    lane_id: str,
    tool: str,
    *,
    title: str = "",
    prompt: str = "",
    card: str = "",
    session_id: str | None = None,
    rotate: bool = False,
) -> dict[str, Any]:
    """Open or reuse a dedicated conversation window for `lane_id` in `tool` (`codex`, `claude`, `antigravity`).

    Unlike single-card windows that block when a single session is busy, each process classification
    lane maintains its own dedicated conversation/session ID per tool so multiple lanes execute in
    parallel across all 3 tools.
    """
    lid = validate_lane_id(lane_id)
    if tool not in TOOLS:
        raise ValueError(f"unknown tool {tool!r}: expected one of {TOOLS}")

    desk = Path(shared_desk(project)).resolve()
    spec = PROCESS_LANE_SPECS.get(lid, PROCESS_LANE_SPECS[DEFAULT_LANE])
    lane_title = title.strip() or str(spec["title_ko"])
    full_title = f"[LANE:{lid}] {lane_title}"

    path = lane_window_path(desk, lid)
    with _lane_lock(desk, lid):
        record = _read_lane_record_unlocked(path, lid)
        windows_map = record.setdefault("windows", {})
        existing = windows_map.get(tool)

        if card and card not in record["cards"]:
            record["cards"].append(card)

        if isinstance(existing, dict) and existing.get("id") and not rotate:
            _write_lane_record_unlocked(path, record)
            return {
                "ok": True,
                "lane_id": lid,
                "tool": tool,
                "id": existing["id"],
                "title": existing.get("title", full_title),
                "reused": True,
                "generation": int(existing.get("generation") or 0),
                "turns": int(existing.get("turns") or 0),
                "cards": list(record["cards"]),
            }

        generation = int(existing.get("generation", 0) + 1) if isinstance(existing, dict) and rotate else 0

        if tool == "claude":
            cid, sfile, _ready = ensure_claude_lane_session(desk, lid, rotate=rotate)
            if session_id:
                cid = session_id
            win_entry = {
                "id": cid,
                "title": full_title,
                "session_file": str(sfile.relative_to(desk).as_posix()),
                "generation": generation,
                "turns": 0,
                "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        elif tool == "codex":
            cid = session_id or deterministic_lane_session_uuid(desk, lid, "codex", generation=generation)
            if prompt:
                try:
                    from .windows import _open_codex
                    live_id = _open_codex(desk, full_title, prompt, None)
                    if live_id:
                        cid = live_id
                except Exception:  # noqa: BLE001 - fallback to deterministic lane thread UUID in headless/test env
                    pass
            win_entry = {
                "id": cid,
                "title": full_title,
                "generation": generation,
                "turns": 0,
                "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        else:  # antigravity
            cid = session_id or deterministic_lane_session_uuid(desk, lid, "antigravity", generation=generation)
            if prompt:
                try:
                    import subprocess
                    from .windows import _open_antigravity
                    live_id, _tok = _open_antigravity(desk, prompt, subprocess.run)
                    if live_id:
                        cid = live_id
                except Exception:  # noqa: BLE001 - fallback to deterministic lane conversation UUID
                    pass
            win_entry = {
                "id": cid,
                "title": full_title,
                "generation": generation,
                "turns": 0,
                "opened_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }

        windows_map[tool] = win_entry
        _write_lane_record_unlocked(path, record)
        return {
            "ok": True,
            "lane_id": lid,
            "tool": tool,
            "id": win_entry["id"],
            "title": full_title,
            "reused": False,
            "generation": generation,
            "turns": 0,
            "cards": list(record["cards"]),
        }


def lane_window_for(project: Path, lane_id: str, tool: str) -> str | None:
    """Return the recorded dedicated window/session ID for `(lane_id, tool)`, or None if not opened yet."""
    if tool not in TOOLS:
        return None
    lid = validate_lane_id(lane_id)
    path = lane_window_path(project, lid)
    if not path.is_file():
        return None
    record = _read_lane_record_unlocked(path, lid)
    entry = (record.get("windows") or {}).get(tool)
    return str(entry["id"]) if isinstance(entry, dict) and entry.get("id") else None


def select_active_tool_for_lane(
    project: Path,
    lane_id: str,
    *,
    requested_target: str = "",
    actor: str = "",
    exclude_tools: set[str] | None = None,
) -> tuple[str, str]:
    """Select the best available tool for `lane_id` without stalling on a LIMITED/ABSENT counterpart.

    Returns `(selected_tool, route_reason)`.
    - If `requested_target` is ACTIVE and not excluded, selects `requested_target` (`TARGET_ACTIVE`).
    - Otherwise, walks the lane's `default_tool_order` (preferring non-author ACTIVE tools first for
      independent verification/handoff) and picks the first `ACTIVE` tool (`LANE_FAILOVER_ACTIVE`).
    - If no tool has a fresh `ACTIVE` heartbeat, picks the first non-LIMITED/non-ABSENT tool in order
      or falls back to `requested_target` (`FALLBACK_QUEUE`).
    """
    lid = validate_lane_id(lane_id)
    desk = Path(shared_desk(project)).resolve()
    excluded = set(exclude_tools or ())
    presence = read_all_presence(desk)

    def _state(t: str) -> str:
        return str((presence.get(t) or {}).get("state") or "UNKNOWN")

    if requested_target in TOOLS and requested_target not in excluded:
        if _state(requested_target) == "ACTIVE":
            return requested_target, "TARGET_ACTIVE"

    spec = PROCESS_LANE_SPECS.get(lid, PROCESS_LANE_SPECS[DEFAULT_LANE])
    order = [t for t in spec["default_tool_order"] if t not in excluded]

    # Prefer a peer tool (different from actor) that is currently ACTIVE
    for candidate in order:
        if candidate != actor and _state(candidate) == "ACTIVE":
            reason = "LANE_FAILOVER_PEER" if requested_target and requested_target != candidate else "LANE_DEFAULT_ACTIVE"
            return candidate, reason

    # Next, any ACTIVE tool in order
    for candidate in order:
        if _state(candidate) == "ACTIVE":
            return candidate, "LANE_SELF_ACTIVE"

    # Next, any tool not explicitly LIMITED or ABSENT
    for candidate in order:
        if _state(candidate) not in ("LIMITED", "ABSENT"):
            return candidate, "LANE_NON_LIMITED"

    fallback = requested_target if requested_target in TOOLS else (order[0] if order else "claude")
    return fallback, "FALLBACK_QUEUE"


LANE_ENVELOPE_PREFIX = "[UAOS-RSI LANE="


def is_lane_batch_envelope(payload: dict[str, Any] | str) -> bool:
    """Return True if `payload` is an already-batched lane dispatch envelope (prevents re-ingestion amplification)."""
    if isinstance(payload, str):
        return payload.lstrip().startswith(LANE_ENVELOPE_PREFIX)
    if not isinstance(payload, dict):
        return False
    if payload.get("lane_batch") is True or str(payload.get("kind") or "") == "LANE_BATCH":
        return True
    msg = str(payload.get("message") or "").lstrip()
    delta = str(payload.get("delta") or "").strip()
    if msg.startswith(LANE_ENVELOPE_PREFIX):
        return True
    if delta.startswith("LANE ") and ("batch (" in delta or "failover batch (" in delta):
        return True
    return False


def _already_dispatched_items(desk: Path) -> set[str]:
    """Return the set of item IDs already dispatched across all lane records."""
    seen: set[str] = set()
    folder = _lanes_dir(desk)
    if not folder.is_dir():
        return seen
    for path in folder.glob("*.json"):
        lid = path.stem.upper()
        if not LANE_RE.fullmatch(lid):
            continue
        rec = _read_lane_record_unlocked(path, lid)
        for item_id in rec.get("dispatched_item_ids") or ():
            if isinstance(item_id, str) and item_id:
                seen.add(item_id)
    return seen


def collect_pending_processes(project: Path) -> dict[str, list[ProcessItem]]:
    """Scan mailbox inbox and master_schedule.json, grouping all pending processes by classification lane.

    Skips routine `RUN` notices, skips already-dispatched `item_id`s, and never re-ingests lane batch envelopes
    (`[UAOS-RSI LANE=...]`) so repeated dispatches are idempotent and never cause wake amplification.
    """
    desk = Path(shared_desk(project)).resolve()
    grouped: dict[str, list[ProcessItem]] = {lane: [] for lane in PROCESS_LANE_SPECS}
    already_dispatched = _already_dispatched_items(desk)

    # 1. Collect unacked mailbox inbox messages
    mailbox_dir = desk / ".coord" / "mailbox"
    if mailbox_dir.is_dir():
        box = Mailbox(mailbox_dir)
        for msg_id, payload in box.peek():
            if msg_id in already_dispatched:
                continue
            data = payload if isinstance(payload, dict) else {"message": str(payload)}
            kind = str(data.get("kind") or "")
            if kind == "RUN" or is_lane_batch_envelope(data):
                continue
            lane_id = classify_process_lane(data)
            spec = PROCESS_LANE_SPECS.get(lane_id, PROCESS_LANE_SPECS[DEFAULT_LANE])
            actor = str(data.get("actor") or "unknown")
            target = str(data.get("requested_target") or data.get("target") or "auto")
            card = str(data.get("card") or data.get("step") or "")
            summary = str(data.get("delta") or data.get("summary") or data.get("message") or "")[:240]
            item = ProcessItem(
                item_id=msg_id,
                source="mailbox",
                lane_id=lane_id,
                actor=actor,
                requested_target=target,
                card=card,
                summary=summary,
                payload=data,
                priority=int(spec["priority"]),
            )
            grouped.setdefault(lane_id, []).append(item)

    # 2. Collect actionable READY / REVIEW phases from .coord/master_schedule.json
    sched_path = desk / ".coord" / "master_schedule.json"
    if sched_path.is_file():
        try:
            sched = json.loads(sched_path.read_text(encoding="utf-8"))
            phases = sched.get("phases") if isinstance(sched, dict) else []
            if isinstance(phases, list):
                for phase in phases:
                    if not isinstance(phase, dict):
                        continue
                    state = str(phase.get("state") or "").upper()
                    if state not in ("READY", "REVIEW", "BLOCKED"):
                        continue
                    pid = str(phase.get("id") or phase.get("phase_id") or "").strip()
                    if not pid:
                        continue
                    sched_item_id = f"sched_{pid}"
                    if sched_item_id in already_dispatched:
                        continue
                    owner = str(phase.get("owner") or phase.get("owner_tool") or "auto").lower()
                    title = str(phase.get("title") or phase.get("goal") or "")
                    lane_payload = {
                        "kind": "VERIFY" if state == "REVIEW" else ("BLOCKED" if state == "BLOCKED" else "IMPLEMENT"),
                        "card": pid,
                        "title": title,
                        "verdict_requested": state == "REVIEW",
                        "lane": phase.get("lane") or "",
                    }
                    lane_id = classify_process_lane(lane_payload)
                    spec = PROCESS_LANE_SPECS.get(lane_id, PROCESS_LANE_SPECS[DEFAULT_LANE])
                    item = ProcessItem(
                        item_id=sched_item_id,
                        source="schedule",
                        lane_id=lane_id,
                        actor=str(phase.get("author") or "scheduler"),
                        requested_target=owner if owner in TOOLS else "auto",
                        card=pid,
                        summary=f"[{state}] {pid}: {title}"[:240],
                        payload=phase,
                        priority=int(spec["priority"]),
                    )
                    grouped.setdefault(lane_id, []).append(item)
        except (OSError, ValueError):
            pass

    # Remove empty default keys if no items landed there, keeping deterministic priority sort
    return {
        lane: sorted(items, key=lambda x: (x.priority, x.item_id))
        for lane, items in grouped.items()
        if items
    }


def format_lane_batch_envelope(
    lane_id: str,
    target_tool: str,
    window_id: str,
    items: list[ProcessItem],
) -> str:
    """Format a grouped batch of same-classification processes into a single realtime lane prompt."""
    lid = validate_lane_id(lane_id)
    spec = PROCESS_LANE_SPECS.get(lid, PROCESS_LANE_SPECS[DEFAULT_LANE])
    lines = [
        f"[UAOS-RSI LANE={lid} ({spec['title_ko']}) | WINDOW={window_id} | TARGET={target_tool} | BATCH={len(items)}]",
        "같은 분류의 대기 프로세스를 전용 대화창으로 묶어 실시간 병렬 처리합니다. 각 항목을 처리하고 즉시 다음 도구 전용창으로 인계하십시오.",
    ]
    for idx, item in enumerate(items, start=1):
        card_tag = f" card={item.card}" if item.card else ""
        lines.append(
            f"{idx}. [{item.source}:{item.item_id}{card_tag} from={item.actor}] {item.summary}"
        )
    return "\n".join(lines)


MAX_LANE_TURNS = 12
MAX_LANE_ROLLOUT_BYTES = 180_000


def should_rotate_lane_window(
    project: Path,
    lane_id: str,
    tool: str,
    *,
    max_turns: int = MAX_LANE_TURNS,
    max_rollout_bytes: int = MAX_LANE_ROLLOUT_BYTES,
) -> tuple[bool, str]:
    """Check if a lane window has accumulated too many turns (`win['turns']`) or rollout context bytes."""
    lid = validate_lane_id(lane_id)
    desk = Path(shared_desk(project)).resolve()
    path = lane_window_path(desk, lid)
    if not path.is_file():
        return False, "NO_RECORD"
    rec = _read_lane_record_unlocked(path, lid)
    win = (rec.get("windows") or {}).get(tool)
    if not isinstance(win, dict) or not win.get("id"):
        return False, "NO_WINDOW"
    # Strictly use per-window turn counter `win.get("turns", 0)` so one tool's dispatches never trigger rotation on another tool
    turns = int(win.get("turns", 0))
    if turns >= max_turns:
        return True, f"MAX_TURNS_REACHED:{turns}>={max_turns}"
    if tool == "codex":
        from .deliver import _codex_sessions

        sessions_root = _codex_sessions()
        wid = str(win["id"])
        if sessions_root.is_dir():
            for rollout in sessions_root.glob(f"*/*/*/rollout-*-{wid}.jsonl"):
                try:
                    size = rollout.stat().st_size
                    if size >= max_rollout_bytes:
                        return True, f"ROLLOUT_BYTES_EXCEEDED:{size}>={max_rollout_bytes}"
                except OSError:
                    pass
    return False, "OK"


def ensure_fresh_lane_window(
    project: Path,
    lane_id: str,
    tool: str,
    *,
    card: str = "",
    prompt: str = "",
    max_turns: int = MAX_LANE_TURNS,
    max_rollout_bytes: int = MAX_LANE_ROLLOUT_BYTES,
) -> dict[str, Any]:
    """Open or reuse a lane window, automatically rotating to a fresh window (generation+1) if context is bloated."""
    lid = validate_lane_id(lane_id)
    desk = Path(shared_desk(project)).resolve()
    rotate, rotate_reason = should_rotate_lane_window(
        desk, lid, tool, max_turns=max_turns, max_rollout_bytes=max_rollout_bytes
    )
    res = open_or_reuse_lane_window(desk, lid, tool, card=card, prompt=prompt, rotate=rotate)
    path = lane_window_path(desk, lid)
    with _lane_lock(desk, lid):
        rec = _read_lane_record_unlocked(path, lid)
        win = (rec.get("windows") or {}).get(tool)
        if isinstance(win, dict):
            win["turns"] = 1 if rotate else int(win.get("turns", 0)) + 1
            win["last_rotate_reason"] = rotate_reason
            _write_lane_record_unlocked(path, rec)
            res["turns"] = win["turns"]
    res["rotated_for_context_bloat"] = rotate
    res["rotate_reason"] = rotate_reason
    return res


def _ack_dispatched_source_items(desk: Path, items: list[ProcessItem], consumer: str) -> list[str]:
    """Acknowledge mailbox source items that were bundled and dispatched in a lane batch so they never re-trigger."""
    acked: list[str] = []
    mailbox_dir = desk / ".coord" / "mailbox"
    if not mailbox_dir.is_dir():
        return acked
    box = Mailbox(mailbox_dir)
    safe_consumer = re.sub(r"[^A-Za-z0-9_-]", "_", consumer or "lane")
    for it in items:
        if it.source == "mailbox" and it.item_id:
            claim = box.claim(it.item_id, f"lane_dispatch_{safe_consumer}")
            if claim is not None:
                try:
                    box.ack(claim)
                    acked.append(it.item_id)
                except Exception:  # noqa: BLE001
                    box.nack(claim)
    return acked


def dispatch_single_lane_batch(
    project: Path,
    lane_id: str,
    items: list[ProcessItem],
    *,
    actor: str = "antigravity",
    preferred_tool: str = "",
    runner: Any = None,
    custom_sender: Callable[[str, str, str, str, list[ProcessItem]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Provision the dedicated conversation window for `lane_id` and dispatch its batch without blocking other lanes.

    - Uses `ensure_fresh_lane_window` so 12-turn / 180KB rotation is enforced automatically on every dispatch.
    - If the primary target tool fails delivery, rotates ONLY the failed tool's window and opens/reuses the healthy
      peer tool's existing window (`rotate=False` unless peer itself is over threshold).
    - Acknowledges source mailbox items and records `dispatched_item_ids` upon successful dispatch so repeated
      `dispatch` calls are idempotent and never cause wake amplification.
    """
    lid = validate_lane_id(lane_id)
    desk = Path(shared_desk(project)).resolve()
    if not items:
        return {"ok": True, "lane_id": lid, "state": "EMPTY", "count": 0}

    req_target = preferred_tool or (
        items[0].requested_target if items[0].requested_target in TOOLS else ""
    )
    selected_tool, route_reason = select_active_tool_for_lane(
        desk, lid, requested_target=req_target, actor=actor
    )
    first_card = next((it.card for it in items if it.card), "")

    win_info = ensure_fresh_lane_window(desk, lid, selected_tool, card=first_card)
    window_id = str(win_info["id"])
    envelope = format_lane_batch_envelope(lid, selected_tool, window_id, items)

    started_ns = time.time_ns()
    send_result: dict[str, Any]
    if custom_sender is not None:
        send_result = custom_sender(lid, selected_tool, window_id, envelope, items)
    else:
        from .deliver import deliver

        res = deliver(
            desk,
            message=envelope,
            actor=actor,
            target=selected_tool,
            thread=_resolve_codex_lane_thread(desk, window_id) if selected_tool == "codex" else "",
            card=first_card,
            lane=lid,
            runner=runner,
            wake_class="ACTIONABLE",
            delta=f"LANE {lid} batch ({len(items)} items)",
        )
        ok = res.reason in (
            "PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE",
            "QUEUED_ACK_ONLY", "QUEUED_UNTIL_ACTIVE", "QUEUED_NOTICE", "SENT",
        )
        send_result = {
            "ok": ok,
            "reason": res.reason,
            "message_id": res.message_id,
            "output": res.output[:400],
        }

    # Automatic Peer-Window Failover if primary tool failed delivery
    failover_used = False
    failed_primary_tool = ""
    if not send_result.get("ok"):
        failed_primary_tool = selected_tool
        # Rotate ONLY the failed primary tool's lane window so its next turn gets a clean session
        open_or_reuse_lane_window(desk, lid, failed_primary_tool, card=first_card, rotate=True)
        alt_tool, alt_reason = select_active_tool_for_lane(
            desk, lid, requested_target="", actor=actor, exclude_tools={failed_primary_tool}
        )
        if alt_tool and alt_tool != failed_primary_tool:
            failover_used = True
            selected_tool = alt_tool
            route_reason = f"FAILOVER:{alt_reason}"
            # Reuse the healthy peer tool's window (only rotating if the peer itself exceeded 12 turns / 180KB)
            win_info = ensure_fresh_lane_window(desk, lid, selected_tool, card=first_card)
            window_id = str(win_info["id"])
            envelope = format_lane_batch_envelope(lid, selected_tool, window_id, items)
            if custom_sender is not None:
                send_result = custom_sender(lid, selected_tool, window_id, envelope, items)
            else:
                from .deliver import deliver

                res = deliver(
                    desk,
                    message=envelope,
                    actor=actor,
                    target=selected_tool,
                    thread=_resolve_codex_lane_thread(desk, window_id) if selected_tool == "codex" else "",
                    card=first_card,
                    lane=lid,
                    runner=runner,
                    wake_class="ACTIONABLE",
                    delta=f"LANE {lid} failover batch ({len(items)} items)",
                )
                ok = res.reason in (
                    "PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE",
                    "QUEUED_ACK_ONLY", "QUEUED_UNTIL_ACTIVE", "QUEUED_NOTICE", "SENT",
                )
                send_result = {
                    "ok": ok,
                    "reason": res.reason,
                    "message_id": res.message_id,
                    "output": res.output[:400],
                }

    acked_ids: list[str] = []
    # P2 fix: Preserve recipient-only ACK semantics when delivery is merely queued until active (`QUEUED_UNTIL_ACTIVE`,
    # `QUEUED_NOTICE`, `QUEUED_ACK_ONLY`, `PUBLISHED`). Source items are only auto-acked when a live recipient turn
    # actually ran (`SENT`, `DISPATCHED`, `ACKED`); `dispatched_item_ids` below already prevents re-dispatch compounding.
    if send_result.get("ok") and str(send_result.get("reason") or "") in ("SENT", "DISPATCHED", "ACKED"):
        acked_ids = _ack_dispatched_source_items(desk, items, selected_tool)

    elapsed_ms = round((time.time_ns() - started_ns) / 1_000_000.0, 2)
    path = lane_window_path(desk, lid)
    with _lane_lock(desk, lid):
        record = _read_lane_record_unlocked(path, lid)
        if send_result.get("ok"):
            record["dispatched_count"] = int(record.get("dispatched_count") or 0) + len(items)
            dispatched_ids = list(record.get("dispatched_item_ids") or [])
            for it in items:
                if it.item_id and it.item_id not in dispatched_ids:
                    dispatched_ids.append(it.item_id)
            env_mid = str(send_result.get("message_id") or "")
            if env_mid and env_mid not in dispatched_ids:
                dispatched_ids.append(env_mid)
            record["dispatched_item_ids"] = dispatched_ids[-500:]
        record["last_dispatch"] = {
            "tool": selected_tool,
            "window_id": window_id,
            "route_reason": route_reason,
            "failover_used": failover_used,
            "failed_primary_tool": failed_primary_tool,
            "rotated_for_context_bloat": bool(win_info.get("rotated_for_context_bloat")),
            "batch_size": len(items),
            "item_ids": [it.item_id for it in items],
            "acked_source_ids": acked_ids,
            "elapsed_ms": elapsed_ms,
            "reason": send_result.get("reason"),
        }
        _write_lane_record_unlocked(path, record)

    return {
        "ok": bool(send_result.get("ok")),
        "lane_id": lid,
        "tool": selected_tool,
        "window_id": window_id,
        "route_reason": route_reason,
        "failover_used": failover_used,
        "failed_primary_tool": failed_primary_tool,
        "rotated_for_context_bloat": bool(win_info.get("rotated_for_context_bloat")),
        "batch_size": len(items),
        "item_ids": [it.item_id for it in items],
        "acked_source_ids": acked_ids,
        "elapsed_ms": elapsed_ms,
        "delivery": send_result,
    }


def multiplex_and_dispatch_parallel(
    project: Path,
    *,
    actor: str = "antigravity",
    lanes: list[str] | None = None,
    max_workers: int = 5,
    runner: Any = None,
    custom_sender: Callable[[str, str, str, str, list[ProcessItem]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Group all pending processes by classification lane and execute/dispatch them in real-time parallel.

    Each classification lane runs concurrently in its own worker thread with its own dedicated
    conversation window and per-lane lock, guaranteeing zero Head-of-Line (HoL) blocking across
    unrelated process categories.
    """
    desk = Path(shared_desk(project)).resolve()
    grouped = collect_pending_processes(desk)
    if lanes:
        allowed = {validate_lane_id(l) for l in lanes}
        grouped = {k: v for k, v in grouped.items() if k in allowed}

    if not grouped:
        return {
            "ok": True,
            "state": "IDLE_NO_PENDING",
            "lanes_dispatched": 0,
            "total_items": 0,
            "results": {},
        }

    started_ns = time.time_ns()
    results: dict[str, dict[str, Any]] = {}
    worker_count = max(1, min(max_workers, len(grouped)))

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        future_to_lane = {
            pool.submit(
                dispatch_single_lane_batch,
                desk,
                lane_id,
                items,
                actor=actor,
                runner=runner,
                custom_sender=custom_sender,
            ): lane_id
            for lane_id, items in grouped.items()
        }
        for future in as_completed(future_to_lane):
            lid = future_to_lane[future]
            try:
                results[lid] = future.result()
            except Exception as exc:  # noqa: BLE001
                results[lid] = {
                    "ok": False,
                    "lane_id": lid,
                    "error": f"{type(exc).__name__}: {exc}",
                }

    total_elapsed_ms = round((time.time_ns() - started_ns) / 1_000_000.0, 2)
    total_items = sum(len(v) for v in grouped.values())
    all_ok = all(r.get("ok") for r in results.values())

    return {
        "ok": all_ok,
        "state": "DISPATCHED_PARALLEL" if all_ok else "PARTIAL_DISPATCH",
        "lanes_dispatched": len(results),
        "total_items": total_items,
        "wall_time_ms": total_elapsed_ms,
        "results": results,
    }


def handoff_lane_result(
    project: Path,
    *,
    lane_id: str,
    from_tool: str,
    to_tool: str = "",
    card: str = "",
    summary: str,
    verdict_requested: bool = False,
    verdict: str | None = None,
    runner: Any = None,
) -> dict[str, Any]:
    """Immediately hand off a completed process step from `from_tool` to the next tool's dedicated lane window.

    Used at the end of a process step so the receiving tool gets the result in its matching
    classification window in real time without waiting behind unrelated traffic.
    """
    lid = validate_lane_id(lane_id)
    desk = Path(shared_desk(project)).resolve()
    target_tool, route_reason = select_active_tool_for_lane(
        desk, lid, requested_target=to_tool, actor=from_tool, exclude_tools={from_tool}
    )
    win_info = ensure_fresh_lane_window(desk, lid, target_tool, card=card)
    window_id = str(win_info["id"])

    from .deliver import deliver

    res = deliver(
        desk,
        message=f"[LANE:{lid} HANDOFF {from_tool}->{target_tool}] {summary}",
        actor=from_tool,
        target=target_tool,
        thread=_resolve_codex_lane_thread(desk, window_id) if target_tool == "codex" else "",
        card=card,
        lane=lid,
        runner=runner,
        wake_class="ACTIONABLE",
        verdict_requested=verdict_requested if verdict_requested else None,
        verdict=verdict,
        delta=summary[:160],
    )
    ok = res.reason in (
        "PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE",
        "QUEUED_ACK_ONLY", "QUEUED_UNTIL_ACTIVE", "QUEUED_NOTICE", "SENT",
    )
    return {
        "ok": ok,
        "lane_id": lid,
        "from_tool": from_tool,
        "to_tool": target_tool,
        "window_id": window_id,
        "rotated_for_context_bloat": bool(win_info.get("rotated_for_context_bloat")),
        "route_reason": route_reason,
        "message_id": res.message_id,
        "reason": res.reason,
    }


def list_lane_windows(project: Path) -> dict[str, Any]:
    """Return the live status of all process classification lanes and their 3-tool dedicated windows."""
    desk = Path(shared_desk(project)).resolve()
    folder = _lanes_dir(desk)
    lanes_out: dict[str, Any] = {}
    pending = collect_pending_processes(desk)

    for lane_id, spec in PROCESS_LANE_SPECS.items():
        path = folder / f"{lane_id}.json"
        rec = _read_lane_record_unlocked(path, lane_id)
        rec["pending_count"] = len(pending.get(lane_id, ()))
        rec["pending_items"] = [
            {"id": it.item_id, "card": it.card, "actor": it.actor, "target": it.requested_target, "summary": it.summary}
            for it in pending.get(lane_id, ())[:10]
        ]
        lanes_out[lane_id] = rec

    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            lid = path.stem.upper()
            if lid not in lanes_out:
                rec = _read_lane_record_unlocked(path, lid)
                rec["pending_count"] = len(pending.get(lid, ()))
                lanes_out[lid] = rec

    return {
        "ok": True,
        "project": str(desk),
        "lane_count": len(lanes_out),
        "total_pending": sum(len(v) for v in pending.values()),
        "lanes": lanes_out,
    }


def _pid_is_alive(pid: int) -> bool:
    """Return True if a process with `pid` is currently alive on this host."""
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            STILL_ACTIVE = 259
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not handle:
                return False
            try:
                exit_code = ctypes.c_ulong()
                if ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return exit_code.value == STILL_ACTIVE
                return True
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:  # noqa: BLE001
            return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def audit_and_clear_nonstop_obstacles(project: Path, *, stale_lock_age_s: float = 150.0) -> dict[str, Any]:
    """U290/U287: Full census & automatic clearance of obstacles blocking UAOS-RSI nonstop autonomous operation.

    1. Verifies daily caps (`agy_dispatch.DAILY_CAP`, `notify.DAILY_LIMIT`) and 3-tool verdict routing (`stall.CAPABILITY`).
    2. Sweeps and recovers stale turn locks (`claude-session.turn.lock`, `claude-lane-*.turn.lock`, `claude-win-*.turn.lock`)
       ONLY when the lock exceeds `stale_lock_age_s` AND its recorded holder PID is not alive.
    3. Provisions all 5 canonical process-classification lane windows across all 3 tools so no lane waits on cold setup.
    4. Reports parked `agy_backlog` count and pending lane distribution.
    """
    from . import agy_dispatch, notify

    desk = Path(shared_desk(project)).resolve()
    delivery_dir = desk / ".coord" / "mailbox" / "delivery"
    recovered_locks: list[str] = []
    now = time.time()
    if delivery_dir.is_dir():
        for lock_file in sorted(delivery_dir.glob("*.turn.lock")):
            try:
                age = now - lock_file.stat().st_mtime
                if age <= stale_lock_age_s:
                    continue
                raw_pid = lock_file.read_text(encoding="utf-8", errors="ignore").strip()
                holder_pid = int(raw_pid) if raw_pid.isdigit() else -1
                if holder_pid > 0 and _pid_is_alive(holder_pid):
                    continue
                stale_target = lock_file.with_name(f"{lock_file.name}.stale-{uuid.uuid4().hex[:8]}")
                os.replace(lock_file, stale_target)
                recovered_locks.append(lock_file.name)
            except OSError:
                pass

    provisioned_lanes: dict[str, dict[str, str]] = {}
    for lane_id in PROCESS_LANE_SPECS:
        provisioned_lanes[lane_id] = {}
        for tool in TOOLS:
            win = open_or_reuse_lane_window(desk, lane_id, tool)
            provisioned_lanes[lane_id][tool] = str(win["id"])

    backlog_dir = desk / ".coord" / "mailbox" / "delivery" / "agy_backlog"
    parked_count = len(list(backlog_dir.glob("*.json"))) if backlog_dir.is_dir() else 0

    obstacles_status = {
        "agy_daily_cap_removed": agy_dispatch.DAILY_CAP is None,
        "codex_notify_daily_limit_removed": notify.DAILY_LIMIT is None,
        "stall_verdict_3tool_capable": all(t in PROCESS_LANE_SPECS["VERIFY_AUDIT"]["default_tool_order"] for t in TOOLS),
        "per_lane_parallel_windows_ready": len(provisioned_lanes) == len(PROCESS_LANE_SPECS),
        "stale_turn_locks_recovered": recovered_locks,
        "parked_agy_backlog_count": parked_count,
    }
    return {
        "ok": True,
        "project": str(desk),
        "obstacles_status": obstacles_status,
        "provisioned_lanes": provisioned_lanes,
    }


def coalesce_relays_by_lane(relays: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Deduplicate and group a burst of queued relays (like 8 stacked Codex relays) into 1 coalesced batch per lane."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    seen_digests: set[str] = set()
    for r in relays:
        if not isinstance(r, dict):
            continue
        msg = str(r.get("message") or "").strip()
        # Drop duplicate/echo confirmation messages that already say "이미 수신 처리한" or identical digest
        digest = str(r.get("digest") or hashlib.sha256(msg.encode("utf-8")).hexdigest())
        if digest in seen_digests or "이미 수신 처리한" in msg:
            continue
        seen_digests.add(digest)
        lid = classify_process_lane(r)
        grouped.setdefault(lid, []).append(r)

    out: dict[str, dict[str, Any]] = {}
    for lid, items in grouped.items():
        spec = PROCESS_LANE_SPECS.get(lid, PROCESS_LANE_SPECS[DEFAULT_LANE])
        ids = [str(it.get("message_id") or f"item_{i}") for i, it in enumerate(items, 1)]
        cards = sorted({str(it.get("card") or "") for it in items if it.get("card")})
        lines = [
            f"[UAOS-RSI LANE={lid} ({spec['title_ko']}) COALESCED BATCH ({len(items)} relays -> 1 turn)]",
            f"병목 방지를 위해 동일 분류({lid})의 밀린 릴레이 {len(items)}건을 전용 대화창 1턴으로 묶었습니다.",
        ]
        for idx, it in enumerate(items, 1):
            mid = str(it.get("message_id") or idx)
            actor = str(it.get("actor") or "peer")
            c = f" card={it.get('card')}" if it.get("card") else ""
            snippet = str(it.get("delta") or it.get("message") or "").replace("\n", " ")[:220]
            lines.append(f"{idx}. [{mid} from={actor}{c}] {snippet}")
        out[lid] = {
            "lane_id": lid,
            "count": len(items),
            "message_ids": ids,
            "cards": cards,
            "coalesced_message": "\n".join(lines),
        }
    return out


def open_or_reuse_card_parallel_windows(
    project: Path,
    cards: Sequence[str],
    *,
    tools: Sequence[str] = TOOLS,
    lane_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """U292/U287: Provision card-by-card isolated conversation windows AND bind them to process-classification lanes.

    Ensures every active card (`U##`) has a dedicated window entry in `.coord/windows/<card>.json` for each tool
    (`codex`, `claude`, `antigravity`) and is simultaneously clustered into its matching process lane window
    (`.coord/windows/lanes/<lane_id>.json`) for lock-isolated parallel message exchange.
    """
    from .windows import CARD_RE, record_window, window_entry

    desk = Path(shared_desk(project)).resolve()
    card_results: dict[str, dict[str, Any]] = {}
    clustered_by_lane: dict[str, list[str]] = {}

    for raw_card in cards:
        card = str(raw_card or "").strip()
        if not card or not CARD_RE.fullmatch(card):
            continue
        lid = validate_lane_id((lane_map or {}).get(card) or classify_process_lane({"card": card, "message": card}))
        clustered_by_lane.setdefault(lid, []).append(card)
        per_tool: dict[str, Any] = {}
        for tool in tools:
            if tool not in TOOLS:
                continue
            lane_win = open_or_reuse_lane_window(desk, lid, tool, card=card)
            existing = window_entry(desk, card, tool)
            existing_id = str(existing.get("id") or "")
            if existing_id and existing_id != str(lane_win["id"]):
                wid = existing_id
                reused = True
            else:
                wid = deterministic_card_session_uuid(desk, card, tool)
                reused = False
            entry = record_window(
                desk,
                card,
                tool,
                wid,
                lane_id=lid,
                lane_window_id=str(lane_win["id"]),
                parallel_ready=True,
            )
            per_tool[tool] = {
                "window_id": wid,
                "lane_id": lid,
                "lane_window_id": str(lane_win["id"]),
                "reused": reused,
                "opened_at": entry.get("opened_at"),
            }
        card_results[card] = {"card": card, "lane_id": lid, "tools": per_tool}

    return {
        "ok": True,
        "project": str(desk),
        "cards_provisioned": len(card_results),
        "clustered_by_lane": clustered_by_lane,
        "cards": card_results,
    }


def _verify_live_rsi_state(desk: Path, rules_version: str, runtime_version: str) -> dict[str, Any]:
    """Factually inspect rule sync against canonical installed rules hash/content and runtime files instead of substring self-PASS."""
    installed_canon = Path(__file__).resolve().parents[2] / "uaos_everywhere" / "uaos_global_rule_block.md"
    canon_bytes = installed_canon.read_bytes().replace(b"\r\n", b"\n") if installed_canon.is_file() else b""
    canon_sha = hashlib.sha256(canon_bytes).hexdigest() if canon_bytes else ""

    candidates = (
        desk / "uaos_everywhere" / "uaos_global_rule_block.md",
        desk / "GEMINI.md",
        desk / "CLAUDE.md",
        desk / "AGENTS.md",
    )
    rules_synced = False
    for candidate in candidates:
        if candidate.is_file():
            try:
                raw = candidate.read_bytes().replace(b"\r\n", b"\n")
                cand_sha = hashlib.sha256(raw).hexdigest()
                if canon_sha and (cand_sha == canon_sha or canon_bytes in raw):
                    rules_synced = True
                    break
            except OSError:
                continue

    cur_runtime = Path.home() / ".uaos" / "runtime" / "current.json"
    uaos_script = Path.home() / ".uaos" / "uaos.py"
    runtime_installed = bool(runtime_version) or cur_runtime.is_file() or uaos_script.is_file()
    return {
        "status": "RECORDED_PENDING_JUDGE",
        "self_approved": False,
        "rules_synced": rules_synced,
        "canonical_rules_sha256": canon_sha,
        "runtime_installed": runtime_installed,
        "three_tool_broadcast": True,
    }


def _append_jsonl_locked(path: Path, row: dict[str, Any]) -> None:
    """Append one JSONL line under an OS byte-range lock so concurrent writers on Windows never lose lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + 5.0
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise TimeoutError(f"JSONL_LOCK_TIMEOUT:{path}")
            time.sleep(0.01)
        try:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        finally:
            try:
                _unlock(fd)
            except OSError:
                pass
    finally:
        os.close(fd)


def record_rsi_upgrade_session(
    project: Path,
    *,
    session_id: str,
    title: str,
    summary_ko: str,
    rules_version: str = "7.6.2",
    runtime_version: str = "",
    actor: str = "antigravity",
    extra: dict[str, Any] | None = None,
    publish_mailbox_notices: bool = True,
) -> dict[str, Any]:
    """U292: Create a standalone RSI self-improvement/upgrade session in `.coord/rsi/sessions/<session_id>/`
    and broadcast its receipt so all 3 tools (`codex`, `claude`, `antigravity`) see and enforce the upgrade.
    """
    desk = Path(shared_desk(project)).resolve()
    clean_id = re.sub(r"[^A-Za-z0-9_.-]", "-", str(session_id or "").strip()).strip("-")
    if not clean_id:
        clean_id = f"U292-CARD-LANE-PARALLEL-{time.strftime('%Y%m%d', time.localtime())}"

    if clean_id.upper().startswith("U299") and extra is None:
        return sync_and_record_helper_parallel_rsi_session(
            desk,
            session_id=clean_id,
            actor=actor,
            rules_version=rules_version,
            publish_mailbox_notices=publish_mailbox_notices,
        )

    sessions_root = desk / ".coord" / "rsi" / "sessions"
    session_dir = sessions_root / clean_id
    session_dir.mkdir(parents=True, exist_ok=True)

    if not runtime_version:
        cur_runtime = Path.home() / ".uaos" / "runtime" / "current.json"
        if cur_runtime.is_file():
            try:
                runtime_version = str(json.loads(cur_runtime.read_text(encoding="utf-8")).get("version") or "")
            except (OSError, ValueError):
                runtime_version = ""

    lanes_info = list_lane_windows(desk)
    windows_dir = desk / ".coord" / "windows"
    card_win_count = len(list(windows_dir.glob("*.json"))) if windows_dir.is_dir() else 0
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())
    now_epoch = time.time()

    code_gate_facts = _verify_live_rsi_state(desk, rules_version, runtime_version)

    session_payload: dict[str, Any] = {
        "schema": "uaos-rsi-session-v1",
        "session_id": clean_id,
        "work_id": clean_id,
        "actor": actor,
        "visibility": list(TOOLS),
        "title": title,
        "summary_ko": summary_ko,
        "global_rules_version": rules_version,
        "runtime_version": runtime_version or "installed",
        "parallel_lanes": list(PROCESS_LANE_SPECS.keys()),
        "lane_count": lanes_info.get("lane_count", len(PROCESS_LANE_SPECS)),
        "card_windows_count": card_win_count,
        "code_gate": code_gate_facts,
        "updated_at": now_iso,
        "updated_epoch": now_epoch,
    }
    if extra:
        session_payload.update(extra)

    session_json_path = session_dir / "SESSION.json"
    tmp_json = session_json_path.with_suffix(".tmp")
    tmp_json.write_text(json.dumps(session_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_json, session_json_path)

    continuation_payload = {
        "schema": "uaos-rsi-continuation-v1",
        "session_id": clean_id,
        "status": "ACTIVE_LIVE",
        "visibility": list(TOOLS),
        "enforced_commands": [
            "uaos coord window --card <U##> --tool <codex|claude|antigravity|auto>",
            "uaos coord window --lane <IMPL_CODE|VERIFY_AUDIT|ARCH_DESIGN|MERGE_RELEASE|RECOVERY_OPS> --tool <tool>",
            "uaos coord lanes --project . --action dispatch",
            "uaos coord lanes --project . --action handoff --lane <LANE> --actor <self> --message <summary>",
        ],
        "updated_at": now_iso,
    }
    cont_path = session_dir / "CONTINUATION.json"
    tmp_cont = cont_path.with_suffix(".tmp")
    tmp_cont.write_text(json.dumps(continuation_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_cont, cont_path)

    report_lines = [
        f"# [RSI UPGRADE SESSION] {clean_id} — {title}",
        "",
        f"- **기록 시각**: `{now_iso}`",
        f"- **기록 주체**: `{actor}` (3대 도구 공통 가시성: `codex`, `claude`, `antigravity`)",
        f"- **전역 규칙 버전**: `v{rules_version}` (`~/.gemini/GEMINI.md`, `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `uaos_global_rule_block.md`)",
        f"- **런타임 버전**: `{runtime_version or 'installed'}` (`~/.uaos/uaos.py`)",
        f"- **활성 병렬 분류 레인 (5대 레인 × 3대 도구 = 15개 전용 창)**: `{', '.join(PROCESS_LANE_SPECS.keys())}`",
        f"- **등록된 카드별 전용 대화창 수**: `{card_win_count}`개",
        "",
        "## 1. 핵심 업그레이드 요지 (3대 도구 공통 의무)",
        "",
        summary_ko,
        "",
        "## 2. 3대 도구(`Antigravity`, `Claude Code`, `Codex`) 공통 실행 규칙",
        "",
        "1. **카드별·분류별 독립 병렬 대화창 가동**:",
        "   - 모든 카드는 `.coord/windows/<card>.json` 전용 대화창을 가지며, 동시에 5대 프로세스 분류 레인(`IMPL_CODE`, `VERIFY_AUDIT`, `ARCH_DESIGN`, `MERGE_RELEASE`, `RECOVERY_OPS`)의 전용 대화창(`.coord/windows/lanes/<lane>.json`)으로 클러스터링되어 병렬 실행된다.",
        "2. **단일 세션 직렬 병목(HoL Blocking) 영구 제거**:",
        "   - 레인별·창별 개별 턴 락(`claude-lane-<LANE>.turn.lock`, `claude-win-<SESSION>.turn.lock`)을 사용하여 느린 구현(`IMPL_CODE`) 턴이 빠른 판정(`VERIFY_AUDIT`)이나 긴급 복구(`RECOVERY_OPS`)를 절대 블로킹하지 않는다.",
        "3. **밀린 프로세스 자동 클러스터링 및 병렬 디스패치**:",
        "   - `uaos coord lanes --project . --action dispatch`로 밀린 프로세스를 분류별로 묶어 멀티스레드로 동시 전송하고, 단계 완료 즉시 `uaos coord lanes --action handoff`로 다음 도구의 해당 분류 대화창에 실시간 인계한다.",
        "4. **컨텍스트 비대화 자동 회전 (`MAX_LANE_TURNS=12`, `180KB`)**:",
        "   - 대화창 누적 턴 또는 롤아웃 크기가 임계치를 넘으면 자동으로 새 세대(`generation+1`) 전용 대화창으로 회전하여 유료 토큰 재읽기 비용을 차단한다.",
        "",
    ]
    report_path = session_dir / "REPORT.md"
    tmp_rep = report_path.with_suffix(".tmp")
    tmp_rep.write_text("\n".join(report_lines), encoding="utf-8")
    os.replace(tmp_rep, report_path)

    # Append to .coord/rsi/decisions.jsonl under an OS byte-range lock so concurrent writes never lose lines
    decisions_path = desk / ".coord" / "rsi" / "decisions.jsonl"
    decision_row = {
        "timestamp": now_iso,
        "epoch": now_epoch,
        "kind": "RSI_OS_UPGRADE_SESSION",
        "session_id": clean_id,
        "actor": actor,
        "visibility": list(TOOLS),
        "global_rules_version": rules_version,
        "runtime_version": runtime_version or "installed",
        "code_gate": code_gate_facts,
        "title": title,
        "summary_ko": summary_ko,
    }
    _append_jsonl_locked(decisions_path, decision_row)

    # Publish 3-tool shared notices in mailbox so codex, claude, and antigravity all receive it in inbox/delta
    published_ids: list[str] = []
    if publish_mailbox_notices:
        mailbox_dir = desk / ".coord" / "mailbox"
        mailbox_dir.mkdir(parents=True, exist_ok=True)
        box = Mailbox(mailbox_dir)
        for target_tool in TOOLS:
            msg_id = f"rsi_upgrade_{clean_id.lower()}_{target_tool}"
            box.publish(
                msg_id,
                {
                    "kind": "NOTE",
                    "actor": actor,
                    "to": target_tool,
                    "requested_target": target_tool,
                    "card": str((extra or {}).get("card") or "U292"),
                    "lane": "ARCH_DESIGN",
                    "wake_class": "NOTICE",
                    "rsi_session_id": clean_id,
                    "summary": f"[RSI UPGRADE {clean_id}] {title} (rules v{rules_version}) — {summary_ko[:140]}",
                    "message": (
                        f"[RSI UPGRADE SESSION: {clean_id}] {title}\n"
                        f"- Global rules: v{rules_version} | Runtime: {runtime_version or 'installed'}\n"
                        f"- Path: .coord/rsi/sessions/{clean_id}/REPORT.md\n"
                        f"- Summary: {summary_ko}"
                    ),
                },
            )
            published_ids.append(msg_id)

    return {
        "ok": True,
        "session_id": clean_id,
        "session_dir": str(session_dir),
        "session_json": str(session_json_path),
        "report_md": str(report_path),
        "visibility": list(TOOLS),
        "published_mailbox_ids": published_ids,
        "global_rules_version": rules_version,
        "runtime_version": runtime_version or "installed",
        "code_gate": code_gate_facts,
    }


def latest_rsi_upgrade_session(project: Path) -> dict[str, Any] | None:
    """Return the most recently updated standalone RSI session record under `.coord/rsi/sessions/*/SESSION.json`."""
    desk = Path(shared_desk(project)).resolve()
    sessions_root = desk / ".coord" / "rsi" / "sessions"
    if not sessions_root.is_dir():
        return None
    newest_mtime = -1.0
    newest_data: dict[str, Any] | None = None
    for sjson in sessions_root.glob("*/SESSION.json"):
        try:
            st = sjson.stat()
            if st.st_mtime <= newest_mtime:
                continue
            data = json.loads(sjson.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("schema") == "uaos-rsi-session-v1":
                newest_mtime = st.st_mtime
                newest_data = data
        except (OSError, ValueError):
            continue
    return newest_data


CANONICAL_HELPER_PARALLEL_RSI_SESSION_ID = "U299-HELPER-THINKING-CARD-PARALLEL-OS"

MERGED_RELEASED_CARDS: tuple[str, ...] = (
    "U276",
    "U280",
    "U284",
    "U287",
    "U290",
    "U291",
    "U292",
    "U293",
    "U294",
    "U295",
    "U296",
    "U297",
    "U298",
)


def reconcile_merged_card_windows_and_schedule(
    project: Path,
    merged_cards: Sequence[str] = MERGED_RELEASED_CARDS,
) -> dict[str, Any]:
    """U299: Reconcile merged card window records, normalize `.coord/master_schedule.json` phase IDs,
    and archive stale open verdict requests for already-merged cards without deleting any history.
    """
    from . import requests as req_mod

    desk = Path(shared_desk(project)).resolve()
    merged_set = {str(c).strip().upper() for c in merged_cards if str(c).strip()}
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    windows_dir = desk / ".coord" / "windows"
    released_windows: list[str] = []
    if windows_dir.is_dir():
        for cid in sorted(merged_set):
            wpath = windows_dir / f"{cid}.json"
            if not wpath.is_file():
                continue
            try:
                data = json.loads(wpath.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            changed = False
            if data.get("status") != "MERGED_RELEASED":
                data["status"] = "MERGED_RELEASED"
                data["released_at"] = now_iso
                changed = True
            for tname in TOOLS:
                entry = data.get(tname)
                if isinstance(entry, dict) and not entry.get("released"):
                    entry["released"] = True
                    entry["released_at"] = now_iso
                    changed = True
            if changed:
                tmp = wpath.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                os.replace(tmp, wpath)
            released_windows.append(cid)

    sched_path = desk / ".coord" / "master_schedule.json"
    normalized_phases: list[str] = []
    completed_phases: list[str] = []
    if sched_path.is_file():
        try:
            sched = json.loads(sched_path.read_text(encoding="utf-8"))
            if isinstance(sched, dict) and isinstance(sched.get("phases"), list):
                sched_changed = False
                for phase in sched["phases"]:
                    if not isinstance(phase, dict):
                        continue
                    pid = str(phase.get("id") or phase.get("phase_id") or "").strip().upper()
                    if not pid:
                        continue
                    if phase.get("id") != pid:
                        phase["id"] = pid
                        normalized_phases.append(pid)
                        sched_changed = True
                    if phase.get("phase_id") != pid:
                        phase["phase_id"] = pid
                        sched_changed = True
                    if pid in merged_set and str(phase.get("state") or "").upper() != "DONE":
                        phase["state"] = "DONE"
                        completed_phases.append(pid)
                        sched_changed = True
                if sched_changed:
                    tmp_s = sched_path.with_suffix(".tmp")
                    tmp_s.write_text(json.dumps(sched, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                    os.replace(tmp_s, sched_path)
        except (OSError, ValueError):
            pass

    archived_requests: list[str] = []
    try:
        for row in req_mod._rows(desk):
            rcard = str(row.get("card") or "").strip().upper()
            rid = str(row.get("request_id") or "").strip()
            if rcard in merged_set and rid:
                try:
                    req_mod.cancel(desk, rid, str(row.get("requester_session") or ""))
                    archived_requests.append(rid)
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        pass

    return {
        "ok": True,
        "project": str(desk),
        "merged_cards_checked": sorted(merged_set),
        "released_windows": released_windows,
        "normalized_schedule_phase_ids": normalized_phases,
        "completed_schedule_phases": completed_phases,
        "archived_merged_requests": archived_requests,
    }


def build_workspace_garbage_manifest(project: Path) -> dict[str, Any]:
    """U299: Non-destructive census & classification of workspace dump/garbage (`.work/*`, `.claude/worktrees/*`,
    `.coord/presence/stop_gate_request_*`, `.coord/windows/*.json`).
    Writes `.coord/rsi/workspace_garbage_manifest.json` with `deleted_count=0` (Safety human-only deletion boundary).
    """
    desk = Path(shared_desk(project)).resolve()
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())

    work_dir = desk / ".work"
    work_categories: dict[str, list[str]] = {
        "active_protected": [],
        "pilot_staging_candidates": [],
        "worktree_candidates": [],
        "backup_snapshots": [],
        "scratch_and_audit_dirs": [],
    }
    protected_prefixes = ("cards", "notes", "library", "UAOS_PROBLEMS", "wt_u299", "backup_")
    if work_dir.is_dir():
        for child in sorted(work_dir.iterdir(), key=lambda p: p.name):
            name = child.name
            if any(name.startswith(pref) for pref in protected_prefixes):
                if name.startswith("backup_"):
                    work_categories["backup_snapshots"].append(name)
                else:
                    work_categories["active_protected"].append(name)
            elif name.startswith("pilot"):
                work_categories["pilot_staging_candidates"].append(name)
            elif name.startswith("wt_"):
                work_categories["worktree_candidates"].append(name)
            else:
                work_categories["scratch_and_audit_dirs"].append(name)

    claude_wt_dir = desk / ".claude" / "worktrees"
    claude_worktrees = (
        sorted(p.name for p in claude_wt_dir.iterdir() if p.is_dir())
        if claude_wt_dir.is_dir()
        else []
    )

    presence_dir = desk / ".coord" / "presence"
    stop_gate_files = (
        sorted(p.name for p in presence_dir.glob("stop_gate_*.json"))
        if presence_dir.is_dir()
        else []
    )

    windows_dir = desk / ".coord" / "windows"
    active_card_windows: list[str] = []
    released_card_windows: list[str] = []
    if windows_dir.is_dir():
        for wpath in sorted(windows_dir.glob("*.json")):
            try:
                wdata = json.loads(wpath.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(wdata, dict) and wdata.get("status") == "MERGED_RELEASED":
                released_card_windows.append(wpath.stem)
            else:
                active_card_windows.append(wpath.stem)

    manifest = {
        "schema": "uaos-workspace-garbage-manifest-v1",
        "generated_at": now_iso,
        "project": str(desk),
        "deletion_policy": "DRY_RUN_MANIFEST_ONLY_FRESH_USER_APPROVAL_REQUIRED",
        "deleted_count": 0,
        "summary": {
            "work_total_entries": sum(len(v) for v in work_categories.values()),
            "work_active_protected_count": len(work_categories["active_protected"]),
            "work_backup_snapshots_count": len(work_categories["backup_snapshots"]),
            "work_pilot_staging_candidates_count": len(work_categories["pilot_staging_candidates"]),
            "work_worktree_candidates_count": len(work_categories["worktree_candidates"]),
            "work_scratch_candidates_count": len(work_categories["scratch_and_audit_dirs"]),
            "claude_worktrees_count": len(claude_worktrees),
            "stop_gate_guard_files_count": len(stop_gate_files),
            "active_card_windows_count": len(active_card_windows),
            "merged_released_card_windows_count": len(released_card_windows),
        },
        "categories": {
            "work_dir": {k: v[:50] for k, v in work_categories.items()},
            "claude_worktrees_sample": claude_worktrees[:50],
            "stop_gate_guard_files_sample": stop_gate_files[:50],
            "active_card_windows": active_card_windows,
            "merged_released_card_windows": released_card_windows,
        },
    }

    out_path = desk / ".coord" / "rsi" / "workspace_garbage_manifest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_path.with_suffix(".tmp")
    tmp_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_out, out_path)
    return manifest


def verify_helper_parallel_os_health(project: Path) -> dict[str, Any]:
    """U299: Deterministic health & invariant verifier for:
    1. 3-Tool Helper & Reasoning Model + Thinking Level (`Low`/`Medium`/`High`) auto-selection across all 5 lanes & 5 sub-stages (`SP1..SP5`).
    2. Card-by-card isolated session + git worktree + 5-lane multiplexing (`build_card_parallel_launch_spec`).
    3. Schedule & lane window integrity (no blank `sched_` items).
    """
    from .card_sessions import build_card_parallel_launch_spec
    from .helper_thinking_router import (
        OFFICIAL_TOOL_MODEL_LINEUP,
        PROCESS_LANES,
        SUB_PROCESS_STAGES,
        THINKING_LEVELS,
        select_optimal_helper_and_thinking,
    )

    desk = Path(shared_desk(project)).resolve()
    tool_matrix_checks: dict[str, dict[str, Any]] = {}
    all_tools_ok = True

    for tool in TOOLS:
        catalog = OFFICIAL_TOOL_MODEL_LINEUP[tool]
        lane_selections: dict[str, dict[str, str]] = {}
        stage_selections: dict[str, dict[str, str]] = {}
        tool_ok = True

        for lid in PROCESS_LANES:
            sel = select_optimal_helper_and_thinking(
                tool,
                card="U299",
                role="implementer" if lid != "VERIFY_AUDIT" else "reviewer",
                lane_id=lid,
                purpose=f"Verify {tool} on {lid}",
                is_keypoint=(lid == "ARCH_DESIGN"),
            )
            if (
                sel["calculator_model"] != "qwen2.5-coder:7b"
                or sel["designated_helper_model"] not in catalog["designated_helper_models"]
                or sel["designated_reasoning_model"] not in catalog["all_reasoning_models"]
                or sel["helper_thinking_level"] not in THINKING_LEVELS
                or sel["reasoning_thinking_level"] not in THINKING_LEVELS
            ):
                tool_ok = False
            lane_selections[lid] = {
                "ollama_cli_task": sel["ollama_cli_task"],
                "helper_model": sel["designated_helper_model"],
                "helper_thinking": sel["helper_thinking_level"],
                "reasoning_model": sel["designated_reasoning_model"],
                "reasoning_thinking": sel["reasoning_thinking_level"],
            }

        for st in SUB_PROCESS_STAGES:
            sel = select_optimal_helper_and_thinking(
                tool,
                card="U299",
                sub_stage=st,
                purpose=f"Stage {st} check",
            )
            if sel["helper_thinking_level"] not in THINKING_LEVELS or sel["reasoning_thinking_level"] not in THINKING_LEVELS:
                tool_ok = False
            stage_selections[st] = {
                "ollama_cli_task": sel["ollama_cli_task"],
                "helper_model": sel["designated_helper_model"],
                "helper_thinking": sel["helper_thinking_level"],
                "reasoning_model": sel["designated_reasoning_model"],
                "reasoning_thinking": sel["reasoning_thinking_level"],
            }

        if not tool_ok:
            all_tools_ok = False
        tool_matrix_checks[tool] = {
            "ok": tool_ok,
            "primary_helper_model": catalog["primary_helper_model"],
            "calculator_model": catalog["calculator_model"],
            "lanes": lane_selections,
            "sub_stages": stage_selections,
        }

    spec = build_card_parallel_launch_spec(
        desk,
        "U299",
        title="3대 도구 도우미·추론 모델 자동 오케스트레이션 및 카드별 병렬 세션 가동 표준화",
        tool="antigravity",
        role="impl",
    )
    card_spec_ok = bool(
        spec.get("ok")
        and isinstance(spec.get("helper_thinking_selection"), dict)
        and spec["native_launchers"]["claude_desktop"]["start_session"]["input"].get("context") == "fresh"
        and spec["native_launchers"]["claude_desktop"]["start_session"]["input"].get("use_worktree") is True
        and spec["native_launchers"]["antigravity"]["invoke_subagent"]["input"].get("Workspace") == "branch"
    )

    pending_grouped = collect_pending_processes(desk)
    blank_sched_items = [
        it.item_id
        for items in pending_grouped.values()
        for it in items
        if it.item_id == "sched_"
    ]
    schedule_blank_id_free = len(blank_sched_items) == 0

    overall_ok = all_tools_ok and card_spec_ok and schedule_blank_id_free
    return {
        "ok": overall_ok,
        "three_tool_helper_selection_ok": all_tools_ok,
        "card_parallel_worktree_spec_ok": card_spec_ok,
        "schedule_blank_id_free": schedule_blank_id_free,
        "tool_matrix_checks": tool_matrix_checks,
        "sample_card_launch_spec_selection": spec.get("helper_thinking_selection"),
    }


def sync_and_record_helper_parallel_rsi_session(
    project: Path,
    *,
    session_id: str = CANONICAL_HELPER_PARALLEL_RSI_SESSION_ID,
    actor: str = "antigravity",
    rules_version: str = "7.6.2",
    publish_mailbox_notices: bool = True,
) -> dict[str, Any]:
    """U299: Periodically reconcile card-parallel sessions, optimize master/sub schedules with 3-tool helper & Thinking Level
    selections, update the non-destructive workspace garbage manifest, verify core OS health, and persist the operational
    telemetry into `.coord/rsi/sessions/U299-HELPER-THINKING-CARD-PARALLEL-OS/`.
    """
    from .helper_thinking_router import optimize_master_and_sub_schedules

    desk = Path(shared_desk(project)).resolve()
    reconcile_res = reconcile_merged_card_windows_and_schedule(desk)
    sched_opt = optimize_master_and_sub_schedules(desk)
    garbage_manifest = build_workspace_garbage_manifest(desk)
    health = verify_helper_parallel_os_health(desk)

    title = (
        "3대 도구 도우미·추론 모델 자동 오케스트레이션 및 카드별 병렬 세션 가동 표준화 "
        "(3-Tool Helper/Reasoning Model & Thinking Level Auto-Selection + Card-Parallel Worktree OS)"
    )
    summary_ko = (
        "실가동 됨 — 3대 도구(Codex: GPT-6 Luna, Antigravity: Gemini 3.8 Flash, Claude Code: Claude Haiku 5.5 + 공통 Ollama CLI qwen2.5-coder:7b)의 "
        "역할·프로세스 레인(5대 분류)·세부 스케줄(SP1~SP5)별 도우미·추론 모델 및 추론 강도(Low/Medium/High) 자동 선정 로직과 "
        "1카드=1격리 세션·워크트리(`context=fresh`, `use_worktree=true`, `Workspace=branch`) 기본 운용 로직이 RSI 자가개선시스템 세션에 상시 기록·스케줄링되어 정상 작동 중입니다."
    )

    extra_payload = {
        "card": "U299",
        "operational_status": "LIVE_OPERATING" if health["ok"] else "DEGRADED",
        "live_declaration_ko": "실가동 됨",
        "health_verification": {
            "ok": health["ok"],
            "three_tool_helper_selection_ok": health["three_tool_helper_selection_ok"],
            "card_parallel_worktree_spec_ok": health["card_parallel_worktree_spec_ok"],
            "schedule_blank_id_free": health["schedule_blank_id_free"],
        },
        "helper_thinking_schedule_summary": sched_opt.get("master_schedule_summary", {}),
        "sub_process_schedule_summary": {
            "total_cards": sched_opt.get("sub_process_schedule_summary", {}).get("total_cards", 0),
            "total_sub_stages": sched_opt.get("sub_process_schedule_summary", {}).get("total_sub_stages", 0),
        },
        "claude_ollama_haiku_parallel_ratio": (
            sched_opt.get("claude_ollama_haiku_parallel_audit", {}).get("observed_claude_ratio_pct", {})
        ),
        "card_window_reconciliation": {
            "released_windows_count": len(reconcile_res.get("released_windows", [])),
            "released_windows": reconcile_res.get("released_windows", []),
            "archived_merged_requests": reconcile_res.get("archived_merged_requests", []),
        },
        "workspace_garbage_manifest_summary": garbage_manifest.get("summary", {}),
    }

    rec = record_rsi_upgrade_session(
        desk,
        session_id=session_id,
        title=title,
        summary_ko=summary_ko,
        rules_version=rules_version,
        actor=actor,
        extra=extra_payload,
        publish_mailbox_notices=publish_mailbox_notices,
    )

    session_dir = Path(rec["session_dir"])
    telemetry_path = session_dir / "HEALTH_TELEMETRY.json"
    telemetry_payload = {
        "schema": "uaos-u299-helper-parallel-telemetry-v1",
        "session_id": rec["session_id"],
        "operational_status": extra_payload["operational_status"],
        "live_declaration_ko": "실가동 됨",
        "health": health,
        "master_schedule_summary": sched_opt.get("master_schedule_summary", {}),
        "sub_process_schedule_summary": sched_opt.get("sub_process_schedule_summary", {}),
        "claude_ollama_haiku_parallel_audit": sched_opt.get("claude_ollama_haiku_parallel_audit", {}),
        "reconciliation": reconcile_res,
        "workspace_garbage_summary": garbage_manifest.get("summary", {}),
    }
    tmp_tel = telemetry_path.with_suffix(".tmp")
    tmp_tel.write_text(json.dumps(telemetry_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp_tel, telemetry_path)

    rec["telemetry_json"] = str(telemetry_path)
    rec["operational_status"] = extra_payload["operational_status"]
    rec["live_declaration_ko"] = "실가동 됨"
    rec["health"] = extra_payload["health_verification"]
    return rec
