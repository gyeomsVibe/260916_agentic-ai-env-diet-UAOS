"""U337-P1: Option C zero-LLM autonomous companion auto-attach kernel.

Receipt: every new primary card needed a hand-pasted prompt per peer window, and a single silent judge stalled a
verdict for 30 minutes (contract `.work/notes/command_tower_261122/U337_P1_AUTO_ATTACH_CONTRACT_261122.md`).
This kernel only keeps deterministic state under `.coord/auto_attach/`: the prompt hook enqueues, `reconcile_once`
admits, claims and calls a caller-supplied adapter, and the verdict plane routes non-author judges with SLAs.
It calls no model, starts no process and never closes or steals a session on time alone.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator

TOOLS: tuple[str, ...] = ("codex", "claude", "antigravity")
# A pool observation older than one 5-minute quota refresh window is not evidence of free capacity.
POOL_MAX_AGE_S: float = 300.0
# One companion window per peer for up to three concurrent primaries (one per tool); more waits in the FIFO queue.
MAX_OPEN_COMPANIONS: int = 3
# Two consecutive provider errors trip the breaker; 120 s covers a typical provider 429 retry-after window.
CB_TRIP_FAILURES: int = 2
CB_COOLDOWN_S: float = 120.0
# A judge that cannot ACK within 15 s is not watching; 60 s bounds a verdict before a second judge is hedged in.
ACK_SLA_S: float = 15.0
VERDICT_SLA_S: float = 60.0
# A claim's TTL is recorded for audit only; an alive owner PID always wins over an elapsed TTL.
CLAIM_TTL_S: float = 300.0
# Lock waits longer than 30 s mean a wedged holder; the caller fails closed instead of hanging the hook.
LOCK_TIMEOUT_S: float = 30.0
# os.replace on Windows fails while another process reads the target; 50 retries x 20 ms bound that to 1 s.
REPLACE_RETRIES: int = 50
REPLACE_SLEEP_S: float = 0.02
# When every judge is exhausted and no reset time is known, re-check after one pool freshness window.
EXHAUSTED_RETRY_S: float = POOL_MAX_AGE_S

ACTIVE_CARD_STATES = ("PENDING", "WAITING", "PAUSED")
TERMINAL_CARD_STATES = ("DONE", "STOPPED")
IN_FLIGHT_CLAIMS = ("CLAIMED", "ADAPTER_STARTED")
# States that occupy a peer slot: open, in flight, or an unresolved external effect.
SLOT_CLAIMS = ("CLAIMED", "ADAPTER_STARTED", "VERIFIED_OPEN", "UNKNOWN_EFFECT", "NO_VERIFIED_SESSION")
# States after which generation g+1 may be claimed without risking a duplicate window.
RETRYABLE_CLAIMS = ("CRASHED_BEFORE_EFFECT", "CONFIRMED_ABSENT", "ABORTED_BEFORE_LAUNCH")
OPEN_VERDICT_STATES = ("AWAITING_ACK", "ACKED", "TIED_HEDGED", "EXHAUSTED_WAIT_RESET")
VERDICTS = ("PASS", "FAIL", "REVISE", "HOLD")
EXECUTOR = "EXECUTOR"
JUDGE_ROLES = ("EXECUTOR", "JUDGE_ONLY")
KNOWN_MODES = ("TRIO", "DUO", "SOLO")

_NOISE_PREFIXES = ("ack_only", "[ack_only", "relay:", "[relay", "<system-reminder")
_WORK_WORDS = ("implement", "fix", "add", "modify", "refactor", "write", "create", "update", "build", "remove",
               "rename", "test", "구현", "수정", "추가", "고쳐", "만들", "작성", "리팩", "삭제", "변경")
_EXTS = ("py", "md", "json", "jsonl", "js", "ts", "tsx", "jsx", "toml", "yaml", "yml", "txt", "ps1", "sh", "cfg",
         "ini", "html", "css")
_PATH_RE = re.compile(r"(?<![\w/.\\-])((?:[\w.-]+[/\\])*[\w-]+\.(?:" + "|".join(_EXTS) + r"))(?![\w/\\])",
                      re.IGNORECASE)


# -----------------------------------------------------------------------------
# 1. Identity, paths, lock and atomic JSON
# -----------------------------------------------------------------------------
def project_id(project: Path) -> str:
    """Deterministic id of the resolved project path (case-folded on Windows), so equal card ids never collide."""
    canon = os.path.normcase(str(Path(project).resolve()))
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()[:16]


def _coord_dir(project: Path) -> Path:
    return Path(project) / ".coord" / "auto_attach"


def _now(now: float | None) -> float:
    return time.time() if now is None else float(now)


def _read_json(path: Path, default: Any = None) -> Any:
    for _ in range(REPLACE_RETRIES):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return default
        except PermissionError:
            time.sleep(REPLACE_SLEEP_S)
        except ValueError:
            return default
    return default


def _write_json(path: Path, doc: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    for attempt in range(REPLACE_RETRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == REPLACE_RETRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_SLEEP_S)


@contextmanager
def _lock(project: Path) -> Iterator[None]:
    """One cross-process lock for all kernel state; held only for short read-modify-write sections.

    The OS releases it when the holder dies, so a crashed helper never wedges the next reconcile.
    Adapters, hooks and close callbacks always run outside it.
    """
    path = _coord_dir(project) / "locks" / "auto_attach.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    try:
        if sys.platform == "win32":
            import msvcrt

            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"auto_attach lock busy: {path}")
                    time.sleep(0.005)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _pid_alive(pid: int) -> bool:
    if not pid or pid <= 0:
        return False
    if pid == os.getpid():
        return True
    if sys.platform == "win32":  # os.kill(pid, 0) on Windows sends a console event, so query the exit code instead
        import ctypes
        from ctypes import wintypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        k32.GetExitCodeProcess.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD))
        k32.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = k32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = wintypes.DWORD()
            ok = k32.GetExitCodeProcess(handle, ctypes.byref(code))
            return bool(ok) and code.value == 259  # STILL_ACTIVE
        finally:
            k32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _safe(name: str) -> str:
    if not name or not re.fullmatch(r"[\w.-]+", name) or name in (".", ".."):
        raise ValueError(f"unsafe id: {name!r}")
    return name


def _ts(value: Any) -> float | None:
    """Epoch seconds from a number or an ISO-8601 string; None when absent or unreadable."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


# -----------------------------------------------------------------------------
# 2. Queue, cards and the prompt hook
# -----------------------------------------------------------------------------
def _queue_path(project: Path) -> Path:
    return _coord_dir(project) / "queue.json"


def _index_path(project: Path) -> Path:
    return _coord_dir(project) / "index.json"


def _card_path(project: Path, card_id: str) -> Path:
    return _coord_dir(project) / "cards" / f"{_safe(card_id)}.json"


def read_queue(project: Path) -> list[dict[str, Any]]:
    doc = _read_json(_queue_path(project), [])
    return doc if isinstance(doc, list) else []


def read_card(project: Path, card_id: str) -> dict[str, Any] | None:
    doc = _read_json(_card_path(project, card_id))
    return doc if isinstance(doc, dict) else None


def _peers_for(owner: str) -> list[str]:
    if owner not in TOOLS:
        raise ValueError(f"unknown tool: {owner!r}")
    return [t for t in TOOLS if t != owner]


def _extract_files(prompt: str) -> list[str]:
    seen: list[str] = []
    for match in _PATH_RE.findall(prompt or ""):
        norm = match.replace("\\", "/")
        if norm not in seen:
            seen.append(norm)
    return seen


def _classify_prompt(prompt: str) -> str:
    """'' for a work prompt, else the skip reason. Deterministic; no model is asked."""
    text = (prompt or "").strip()
    if not text:
        return "EMPTY_PROMPT"
    lowered = text.lower()
    if lowered.startswith(_NOISE_PREFIXES):
        return "RELAY_NOISE"
    if _extract_files(text):
        return ""
    for word in _WORK_WORDS:
        if word.isascii():
            if re.search(rf"(?<![a-z0-9_]){re.escape(word)}", lowered):
                return ""
        elif word in text:
            return ""
    return "NOT_WORK_PROMPT"


# U367: the safe Standard profile a card gets when triage itself fails (the contract's middle tier, never Fast).
_MIA_FALLBACK: dict[str, Any] = {
    "tier": "MIA-Standard", "steps": 6, "thinking_level": "Medium",
    "card_slots": ["Research", "MIA", "Execute", "Verify"], "escalated": False,
    "escalation_reason": "triage_exception_fallback", "reasons": ["fallback_to_standard"],
    "invariants": ["author!=judge", "fixed_acceptance_exit_0", "backup_before_overwrite", "safety_7_human_only"],
    "token_savings": "UNMEASURED"}


def _triage_card_prompt(prompt: str, files: list[str]) -> dict[str, Any]:
    """U367: zero-token MIA tier for a card (mia_triage reads no file, calls no model); never raises into the hook."""
    try:
        from .mia_triage import classify_mia_tier
        return classify_mia_tier(prompt, paths=files)
    except Exception:  # the prompt hook must stay alive; Standard keeps every invariant
        return dict(_MIA_FALLBACK, file_count=len(files) if files else None)


def _sync_queue_state(queue: list[dict[str, Any]], card: dict[str, Any]) -> None:
    for item in queue:
        if item.get("card_id") == card["card_id"]:
            item["state"] = card["state"]
            item["blocked_by"] = card.get("blocked_by")
            item["files"] = list(card.get("files", []))
            if "mia_tier" in card:
                item["mia_tier"] = card["mia_tier"]


def _overlap_blocker(queue: list[dict[str, Any]], cards: dict[str, dict[str, Any]], card_id: str,
                     files: list[str]) -> str | None:
    """First earlier active (not WAITING) card in FIFO order that touches one of `files`."""
    wanted = set(files)
    if not wanted:
        return None
    for item in queue:
        other = item.get("card_id")
        if other == card_id:
            continue
        card = cards.get(other) or {}
        if card.get("state") not in ("PENDING", "PAUSED"):
            continue
        if wanted & set(card.get("files", [])):
            return other
    return None


def _load_cards(project: Path, queue: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in queue:
        cid = item.get("card_id")
        if cid and cid not in out:
            card = read_card(project, cid)
            if card:
                out[cid] = card
    return out


def enqueue_from_prompt(project: Path, tool: str, prompt: str, *, session: str = "", event_id: str = "",
                        explicit_card: str = "", now: float | None = None) -> dict[str, Any]:
    """Atomic FIFO append of a primary card; replays and same-session follow-ups reuse the card (no duplicate)."""
    t = _now(now)
    peers = _peers_for(tool)
    files = _extract_files(prompt)
    with _lock(project):
        queue = read_queue(project)
        index = _read_json(_index_path(project), {}) or {}
        events = index.setdefault("events", {})
        sessions = index.setdefault("sessions", {})
        event_key = f"{tool}:{event_id}" if event_id else ""
        if event_key and event_key in events:
            card = read_card(project, events[event_key]) or {}
            return {"ok": True, "action": "DUPLICATE", "duplicate": True, "reused": False,
                    "card_id": events[event_key], "state": card.get("state"), "blocked_by": card.get("blocked_by"),
                    "mia_tier": card.get("mia_tier"), "mia_profile": card.get("mia_profile")}
        cards = _load_cards(project, queue)
        session_key = f"{tool}:{session}" if session else ""
        reuse_id = explicit_card or (sessions.get(session_key) if session_key else None)
        existing = cards.get(reuse_id) if reuse_id else None
        if existing and existing.get("state") in ACTIVE_CARD_STATES and existing.get("owner") == tool:
            merged = list(existing.get("files", []))
            merged += [f for f in files if f not in merged]
            existing["files"] = merged
            existing["updated_at"] = t
            existing["mia_profile"] = _triage_card_prompt(existing.get("prompt", ""), merged)
            existing["mia_tier"] = existing["mia_profile"]["tier"]
            _write_json(_card_path(project, existing["card_id"]), existing)
            _sync_queue_state(queue, existing)
            if event_key:
                events[event_key] = existing["card_id"]
            _write_json(_queue_path(project), queue)
            _write_json(_index_path(project), index)
            return {"ok": True, "action": "REUSED", "duplicate": False, "reused": True,
                    "card_id": existing["card_id"], "state": existing["state"],
                    "blocked_by": existing.get("blocked_by"), "peers": existing["peers"], "files": merged,
                    "mia_tier": existing["mia_tier"], "mia_profile": existing["mia_profile"]}
        if existing and explicit_card:
            return {"ok": False, "action": "CARD_ID_TAKEN", "duplicate": False, "reused": False,
                    "card_id": existing["card_id"], "state": existing.get("state"),
                    "blocked_by": existing.get("blocked_by")}
        index["seq"] = int(index.get("seq", 0)) + 1
        card_id = _safe(explicit_card) if explicit_card else f"AA-{int(t)}-{index['seq']}"
        blocker = _overlap_blocker(queue, cards, card_id, files)
        state = "WAITING" if blocker else "PENDING"
        mia_profile = _triage_card_prompt(prompt, files)
        mia_tier = mia_profile["tier"]
        card = {"card_id": card_id, "owner": tool, "prompt": prompt, "session": session, "peers": peers,
                "state": state, "reason": "FILE_OVERLAP" if blocker else "", "blocked_by": blocker,
                "files": files, "mia_tier": mia_tier, "mia_profile": mia_profile, "enqueued_at": t,
                "updated_at": t, "project_id": project_id(project)}
        _write_json(_card_path(project, card_id), card)
        queue.append({"card_id": card_id, "owner": tool, "prompt": prompt, "session": session,
                      "event_id": event_id, "peers": peers, "state": state, "blocked_by": blocker,
                      "enqueued_at": t, "files": files, "mia_tier": mia_tier})
        if event_key:
            events[event_key] = card_id
        if session_key:
            sessions[session_key] = card_id
        _write_json(_queue_path(project), queue)
        _write_json(_index_path(project), index)
    return {"ok": True, "action": "ENQUEUED", "duplicate": False, "reused": False, "card_id": card_id,
            "state": state, "blocked_by": blocker, "peers": peers, "files": files, "mia_tier": mia_tier,
            "mia_profile": mia_profile}


def _companion_session_owner(project: Path, tool: str, session: str) -> str | None:
    if not session:
        return None
    for path in sorted((_coord_dir(project) / "claims").glob(f"*.{tool}.g*.json")):
        claim = _read_json(path) or {}
        if claim.get("peer") == tool and claim.get("verified_session_id") == session and \
                claim.get("state") == "VERIFIED_OPEN":
            return f"{claim.get('card_id')}.{tool}"
    return None


def _audit(project: Path, doc: dict[str, Any]) -> Path:
    path = _coord_dir(project) / "audit" / f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}.json"
    _write_json(path, doc)
    return path


def hook_on_prompt(project: Path, tool: str, prompt: str, *, session: str = "", event_id: str = "",
                   now: float | None = None, _enqueue_fn: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Prompt hook: read and enqueue only. Never launches anything; a failure leaves an auditable receipt."""
    if os.environ.get("UAOS_WORKER"):
        return {"ok": True, "action": "SKIPPED", "skipped": "UAOS_WORKER"}
    if os.environ.get("UAOS_AUTO_ATTACH", "").strip() == "0":
        return {"ok": True, "action": "SKIPPED", "skipped": "AUTO_ATTACH_DISABLED"}
    reason = _classify_prompt(prompt)
    if reason:
        return {"ok": True, "action": "SKIPPED", "skipped": reason}
    try:
        companion = _companion_session_owner(project, tool, session)
        if companion:
            return {"ok": True, "action": "SKIPPED", "skipped": "COMPANION_WINDOW_NO_RECURSION",
                    "companion_id": companion}
        enqueue = _enqueue_fn or enqueue_from_prompt
        return enqueue(project, tool, prompt, session=session, event_id=event_id, now=now)
    except Exception as exc:  # the optional hook must never kill the caller or fall through to a paid route
        doc = {"state": "BLOCKED_HOOK_ERROR", "tool": tool, "session": session, "event_id": event_id,
               "error": f"{type(exc).__name__}: {exc}", "at": _now(now), "prompt_sha256":
               hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()}
        try:
            audit_file = str(_audit(project, doc))
        except Exception as audit_exc:  # still report, never raise into the caller
            audit_file = ""
            doc["audit_error"] = f"{type(audit_exc).__name__}: {audit_exc}"
        return {"ok": False, "state": "BLOCKED_HOOK_ERROR", "error": doc["error"], "audit_file": audit_file}


def _set_card_state(project: Path, card_id: str, state: str, reason: str, now: float | None,
                    **extra: Any) -> dict[str, Any]:
    with _lock(project):
        card = read_card(project, card_id)
        if not card:
            return {"ok": False, "reason": "CARD_NOT_FOUND", "card_id": card_id}
        if card.get("state") in TERMINAL_CARD_STATES:
            return {"ok": False, "reason": f"CARD_{card['state']}", "card_id": card_id, "state": card["state"]}
        card.update(state=state, reason=reason, updated_at=_now(now), **extra)
        _write_json(_card_path(project, card_id), card)
        queue = read_queue(project)
        _sync_queue_state(queue, card)
        _write_json(_queue_path(project), queue)
    return {"ok": True, "card_id": card_id, "state": state, "owner": card.get("owner")}


def pause_card(project: Path, card_id: str, *, reason: str = "user_paused", now: float | None = None) -> dict[str, Any]:
    return _set_card_state(project, card_id, "PAUSED", reason, now)


def stop_card(project: Path, card_id: str, *, reason: str = "user_stop", now: float | None = None) -> dict[str, Any]:
    return _set_card_state(project, card_id, "STOPPED", reason, now)


# -----------------------------------------------------------------------------
# 3. Admission, pool freshness and circuit breaker
# -----------------------------------------------------------------------------
def _participation(project: Path) -> dict[str, Any] | None:
    doc = _read_json(Path(project) / ".coord" / "participation.json")
    return doc if isinstance(doc, dict) else None


def _presence(project: Path, tool: str) -> dict[str, Any]:
    doc = _read_json(Path(project) / ".coord" / "presence" / f"{tool}.json")
    return doc if isinstance(doc, dict) else {}


def _presence_active(project: Path, tool: str, t: float) -> bool:
    doc = _presence(project, tool)
    expires = _ts(doc.get("expires_at"))
    return str(doc.get("state", "")).upper() == "ACTIVE" and (expires is None or expires > t)


def _snapshot_reason(project: Path, tool: str, t: float, roles: tuple[str, ...]) -> str:
    snap = _participation(project)
    if not snap or str(snap.get("mode", "")).upper() == "HALT":
        return "ADMISSION_HALT"
    expires = _ts(snap.get("expires_at"))
    if expires is None:
        return "ADMISSION_UNKNOWN"
    if expires <= t:
        return "ADMISSION_EXPIRED"
    if str(snap.get("mode", "")).upper() not in KNOWN_MODES:
        return "ADMISSION_UNKNOWN"
    role = str((snap.get("roles") or {}).get(tool, "UNKNOWN")).upper()
    if role not in roles:
        if role == "JUDGE_ONLY":
            return "ADMISSION_JUDGE_ONLY"
        if role == "UNKNOWN":
            return "ADMISSION_UNKNOWN"
        return f"ADMISSION_ROLE_{re.sub(r'[^A-Z_]', '', role) or 'UNKNOWN'}"
    if not _presence_active(project, tool, t):
        return "PRESENCE_NOT_ACTIVE"
    return ""


def evaluate_admission(project: Path, tool: str, *, now: float | None = None, sandbox: str = "") -> dict[str, Any]:
    """Launch authority for `tool`: fail closed on a missing, HALT, expired or unknown snapshot, a non-EXECUTOR
    role, non-ACTIVE presence, or a read-only sandbox."""
    reason = _snapshot_reason(project, tool, _now(now), (EXECUTOR,))
    if not reason and str(sandbox).strip().lower() in ("read-only", "readonly", "read_only"):
        reason = "READ_ONLY_SANDBOX"
    return {"admitted": not reason, "reason": reason or "OK", "tool": tool}


def _pool_reason(project: Path, tool: str, t: float) -> str:
    doc = _read_json(_coord_dir(project) / "pools" / f"{tool}.json")
    if not isinstance(doc, dict) or str(doc.get("state", "")).upper() != "FRESH":
        return "POOL_STALE_OR_UNKNOWN"
    observed = _ts(doc.get("observed_at"))
    expires = _ts(doc.get("expires_at"))
    if observed is None or t - observed > POOL_MAX_AGE_S or (expires is not None and expires <= t):
        return "POOL_STALE_OR_UNKNOWN"
    return ""


def _circuit_path(project: Path, tool: str) -> Path:
    return _coord_dir(project) / "circuit" / f"{_safe(tool)}.json"


def _circuit_view(doc: dict[str, Any], tool: str, t: float) -> dict[str, Any]:
    view = {"tool": tool, "state": "CLOSED", "consecutive_failures": 0, "open_until": None,
            "last_failure_at": None}
    view.update(doc or {})
    if view["state"] == "OPEN" and view.get("open_until") is not None and t >= float(view["open_until"]):
        view["state"] = "HALF_OPEN"
    return view


def get_circuit_state(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    return _circuit_view(_read_json(_circuit_path(project, tool), {}) or {}, tool, _now(now))


def record_peer_failure(project: Path, tool: str, error: str = "PROVIDER_ERROR", *,
                        now: float | None = None) -> dict[str, Any]:
    """Count a provider failure; CB_TRIP_FAILURES in a row (or one in HALF_OPEN) opens the breaker."""
    t = _now(now)
    with _lock(project):
        view = _circuit_view(_read_json(_circuit_path(project, tool), {}) or {}, tool, t)
        failures = int(view.get("consecutive_failures", 0)) + 1
        doc = {"tool": tool, "consecutive_failures": failures, "last_failure_at": t, "last_error": str(error),
               "state": "CLOSED", "open_until": None}
        if failures >= CB_TRIP_FAILURES or view["state"] == "HALF_OPEN":
            doc.update(state="OPEN", open_until=t + CB_COOLDOWN_S)
        _write_json(_circuit_path(project, tool), doc)
    return dict(doc)


def record_peer_success(project: Path, tool: str, *, now: float | None = None) -> dict[str, Any]:
    t = _now(now)
    doc = {"tool": tool, "state": "CLOSED", "consecutive_failures": 0, "open_until": None, "last_success_at": t,
           "last_failure_at": None}
    with _lock(project):
        old = _read_json(_circuit_path(project, tool), {}) or {}
        doc["last_failure_at"] = old.get("last_failure_at")
        _write_json(_circuit_path(project, tool), doc)
    return dict(doc)


# -----------------------------------------------------------------------------
# 4. Generational claims
# -----------------------------------------------------------------------------
def _claim_path(project: Path, card_id: str, peer: str, generation: int) -> Path:
    return _coord_dir(project) / "claims" / f"{_safe(card_id)}.{_safe(peer)}.g{int(generation)}.json"


def read_claim(project: Path, card_id: str, peer: str, generation: int) -> dict[str, Any] | None:
    doc = _read_json(_claim_path(project, card_id, peer, generation))
    return doc if isinstance(doc, dict) else None


def _claims_for(project: Path, card_id: str, peer: str) -> list[dict[str, Any]]:
    out = []
    prefix = f"{_safe(card_id)}.{_safe(peer)}.g"
    for path in (_coord_dir(project) / "claims").glob(f"{prefix}*.json"):
        gen = path.name[len(prefix):-len(".json")]
        if gen.isdigit():
            doc = _read_json(path)
            if isinstance(doc, dict):
                out.append(doc)
    return sorted(out, key=lambda c: int(c.get("generation", 0)))


def _latest_claim(project: Path, card_id: str, peer: str) -> dict[str, Any] | None:
    claims = _claims_for(project, card_id, peer)
    return claims[-1] if claims else None


def _claim_locked(project: Path, card_id: str, peer: str, generation: int, t: float) -> dict[str, Any]:
    path = _claim_path(project, card_id, peer, generation)
    if path.exists():
        return {"claimed": False, "reason": "GENERATION_TAKEN", "generation": generation,
                "state": (read_claim(project, card_id, peer, generation) or {}).get("state")}
    for prior in _claims_for(project, card_id, peer):
        if int(prior.get("generation", 0)) < generation and prior.get("state") not in RETRYABLE_CLAIMS:
            return {"claimed": False, "reason": "PRIOR_GENERATION_ACTIVE", "generation": generation,
                    "prior_generation": prior.get("generation"), "state": prior.get("state")}
    doc = {"card_id": card_id, "peer": peer, "generation": int(generation), "pid": os.getpid(),
           "claimed_at": t, "ttl_expires_at": t + CLAIM_TTL_S, "state": "CLAIMED", "verified_session_id": "",
           "project_id": project_id(project), "history": [{"state": "CLAIMED", "at": t}]}
    _write_json(path, doc)
    return {"claimed": True, "generation": generation, "state": "CLAIMED", "claim": doc}


def claim_generation(project: Path, card_id: str, peer: str, generation: int, *,
                     now: float | None = None) -> dict[str, Any]:
    """Atomic single-winner claim of generation g for one companion window (cross-process)."""
    with _lock(project):
        return _claim_locked(project, card_id, peer, int(generation), _now(now))


def _update_claim(project: Path, claim: dict[str, Any], state: str, t: float, **extra: Any) -> dict[str, Any]:
    claim = dict(claim)
    claim.update(state=state, **extra)
    claim.setdefault("history", []).append({"state": state, "at": t})
    _write_json(_claim_path(project, claim["card_id"], claim["peer"], int(claim["generation"])), claim)
    return claim


def record_trusted_receipt(project: Path, card_id: str, peer: str, generation: int, *, source: str,
                           verified_session_id: str = "", verified_absent: bool = False,
                           now: float | None = None) -> dict[str, Any]:
    """Resolve an UNKNOWN_EFFECT / NO_VERIFIED_SESSION barrier with external proof: a session that exists
    (converges to VERIFIED_OPEN, no relaunch) or proof of absence (CONFIRMED_ABSENT unlocks g+1)."""
    t = _now(now)
    if not str(source).strip():
        raise ValueError("trusted receipt needs a source")
    if bool(verified_session_id) == bool(verified_absent):
        raise ValueError("give exactly one of verified_session_id or verified_absent")
    with _lock(project):
        claim = read_claim(project, card_id, peer, generation)
        if not claim:
            return {"ok": False, "reason": "CLAIM_NOT_FOUND", "state": None}
        if claim.get("state") not in ("UNKNOWN_EFFECT", "NO_VERIFIED_SESSION"):
            return {"ok": False, "reason": "NOT_AWAITING_RECEIPT", "state": claim.get("state")}
        receipt = {"card_id": card_id, "peer": peer, "generation": int(generation), "source": source,
                   "verified_session_id": verified_session_id, "verified_absent": bool(verified_absent),
                   "prior_state": claim.get("state"), "at": t}
        _write_json(_coord_dir(project) / "receipts" / f"{_safe(card_id)}.{_safe(peer)}.g{int(generation)}.json",
                    receipt)
        if verified_session_id:
            claim = _update_claim(project, claim, "VERIFIED_OPEN", t, verified_session_id=verified_session_id,
                                  receipt_source=source)
        else:
            claim = _update_claim(project, claim, "CONFIRMED_ABSENT", t, receipt_source=source)
    return {"ok": True, "state": claim["state"], "generation": int(generation)}


def _write_verified_session_for_test(project: Path, card_id: str, tool: str, session_id: str) -> None:
    """Test helper: record companion `<card>.<tool>` as an already verified open session."""
    suffix = f".{tool}"
    card = card_id[:-len(suffix)] if card_id.endswith(suffix) else card_id
    with _lock(project):
        latest = _latest_claim(project, card, tool)
        gen = int(latest["generation"]) + 1 if latest else 1
        t = time.time()
        _write_json(_claim_path(project, card, tool, gen),
                    {"card_id": card, "peer": tool, "generation": gen, "pid": 0, "claimed_at": t,
                     "ttl_expires_at": t + CLAIM_TTL_S, "state": "VERIFIED_OPEN", "verified_session_id": session_id,
                     "project_id": project_id(project), "history": [{"state": "VERIFIED_OPEN", "at": t}]})


# -----------------------------------------------------------------------------
# 5. Reconciliation
# -----------------------------------------------------------------------------
def _open_slots(project: Path, peer: str, cards: dict[str, dict[str, Any]]) -> int:
    count = 0
    for path in (_coord_dir(project) / "claims").glob(f"*.{_safe(peer)}.g*.json"):
        claim = _read_json(path) or {}
        if claim.get("peer") != peer or claim.get("state") not in SLOT_CLAIMS:
            continue
        card = cards.get(claim.get("card_id")) or read_card(project, claim.get("card_id", "")) or {}
        if card.get("state") in TERMINAL_CARD_STATES:
            continue
        latest = _latest_claim(project, claim["card_id"], peer)
        if latest and int(latest.get("generation", 0)) == int(claim.get("generation", 0)):
            count += 1
    return count


def _resolve_existing(project: Path, card_id: str, peer: str, t: float) -> tuple[dict[str, Any] | None, int]:
    """Under the lock: settle the latest claim. Returns (blocking result or None, next generation to claim)."""
    latest = _latest_claim(project, card_id, peer)
    if not latest:
        return None, 1
    gen = int(latest.get("generation", 1))
    state = latest.get("state")
    if state in IN_FLIGHT_CLAIMS:
        if _pid_alive(int(latest.get("pid") or 0)):
            return {"status": state, "reason": "HELD_BY_SLOW_OWNER", "generation": gen}, gen + 1
        if state == "CLAIMED":
            _update_claim(project, latest, "CRASHED_BEFORE_EFFECT", t)
            return None, gen + 1
        _update_claim(project, latest, "UNKNOWN_EFFECT", t)
        return {"status": "UNKNOWN_EFFECT", "reason": "RETRY_BLOCKED_UNKNOWN_EFFECT", "generation": gen}, gen + 1
    if state == "VERIFIED_OPEN":
        return {"status": "VERIFIED_OPEN", "reason": "ALREADY_VERIFIED_OPEN", "generation": gen,
                "session_id": latest.get("verified_session_id", "")}, gen + 1
    if state == "UNKNOWN_EFFECT":
        return {"status": "UNKNOWN_EFFECT", "reason": "RETRY_BLOCKED_UNKNOWN_EFFECT", "generation": gen}, gen + 1
    if state == "NO_VERIFIED_SESSION":
        return {"status": "NO_VERIFIED_SESSION", "reason": "RETRY_BLOCKED_NO_VERIFIED_SESSION",
                "generation": gen}, gen + 1
    if state == "CLOSED":
        return {"status": "CLOSED", "reason": "COMPANION_CLOSED", "generation": gen}, gen + 1
    return None, gen + 1


def _claude_exact_session(project: Path) -> str:
    doc = _read_json(Path(project) / ".coord" / "presence" / "user_desk_claude.json")
    if not isinstance(doc, dict):
        return ""
    return str(doc.get("thread") or doc.get("session_id") or "")


def _claude_notice(project: Path, card: dict[str, Any], t: float) -> Path:
    companion_id = f"{card['card_id']}.claude"
    path = _coord_dir(project) / "claude_notices" / f"{companion_id}.json"
    _write_json(path, {"status": "DURABLE_NON_WAKING_NOTICE", "card_id": card["card_id"],
                       "companion_id": companion_id, "owner": card.get("owner"), "created_at": t,
                       "launch_spec": {"method": "mcp__ccd_session__start_session", "card_id": card["card_id"],
                                       "companion_id": companion_id, "context": "fresh", "use_worktree": True,
                                       "files": card.get("files", []), "prompt": card.get("prompt", "")}})
    return path


def _attach_peer(project: Path, card: dict[str, Any], peer: str, *, adapters: dict[str, Any], sandbox: str,
                 claude_watcher_check: Callable[[Path, str], bool] | None,
                 pre_launch_hook: Callable[..., Any] | None, t: float) -> dict[str, Any]:
    card_id = card["card_id"]
    companion_id = f"{card_id}.{peer}"
    with _lock(project):
        blocked, gen = _resolve_existing(project, card_id, peer, t)
    if blocked:
        return blocked
    admission = evaluate_admission(project, peer, now=t, sandbox=sandbox)
    if not admission["admitted"]:
        return {"status": "NOT_ADMITTED", "reason": admission["reason"]}
    if get_circuit_state(project, peer, now=t)["state"] == "OPEN":
        return {"status": "NOT_ADMITTED", "reason": "CIRCUIT_OPEN"}
    pool = _pool_reason(project, peer, t)
    if pool:
        return {"status": "NOT_ADMITTED", "reason": pool}
    adapter = (adapters or {}).get(peer)
    if adapter is None:
        return {"status": "NOT_ADMITTED", "reason": "NO_ADAPTER"}
    exact_session = ""
    if peer == "claude":
        exact_session = _claude_exact_session(project)
        watched = bool(exact_session) and claude_watcher_check is not None and \
            bool(claude_watcher_check(project, exact_session))
        if not watched:
            notice = _claude_notice(project, card, t)
            return {"status": "DURABLE_NON_WAKING_NOTICE", "reason": "CLAUDE_NO_EXACT_WATCHER",
                    "notice_file": str(notice)}
    with _lock(project):
        blocked, gen = _resolve_existing(project, card_id, peer, t)
        if blocked:
            return blocked
        if _open_slots(project, peer, {}) >= MAX_OPEN_COMPANIONS:
            return {"status": "QUEUED", "reason": "POOL_AT_CAPACITY"}
        claim = _claim_locked(project, card_id, peer, gen, t)
    if not claim["claimed"]:
        return {"status": "QUEUED", "reason": claim["reason"], "generation": gen}
    if pre_launch_hook is not None:
        pre_launch_hook(project, card_id, peer, gen)
    with _lock(project):
        current = read_card(project, card_id) or {}
        live = read_claim(project, card_id, peer, gen) or claim["claim"]
        if current.get("state") != "PENDING":  # paused, stopped, finished (DONE) or missing during the hook
            reason = f"CARD_{current.get('state', 'MISSING')}"
            _update_claim(project, live, "ABORTED_BEFORE_LAUNCH", t, abort_reason=reason)
            return {"status": "ABORTED_BEFORE_LAUNCH", "reason": reason, "generation": gen}
        _update_claim(project, live, "ADAPTER_STARTED", t)
    kwargs = {"project": Path(project), "project_id": project_id(project), "card_id": card_id, "peer": peer,
              "generation": gen, "companion_id": companion_id, "owner": card.get("owner"),
              "prompt": card.get("prompt", ""), "files": list(card.get("files", [])),
              "exact_session": exact_session}
    try:
        result = adapter(**kwargs)
    except Exception as exc:  # ambiguous: the adapter may have opened a window before failing
        with _lock(project):
            live = read_claim(project, card_id, peer, gen) or {}
            if live.get("state") == "ADAPTER_STARTED":
                _update_claim(project, live, "UNKNOWN_EFFECT", t, error=f"{type(exc).__name__}: {exc}")
        record_peer_failure(project, peer, f"{type(exc).__name__}", now=t)
        return {"status": "UNKNOWN_EFFECT", "reason": "ADAPTER_ERROR_UNKNOWN_EFFECT", "generation": gen}
    result = result if isinstance(result, dict) else {}
    session_id = str(result.get("session_id") or "")
    with _lock(project):
        live = read_claim(project, card_id, peer, gen) or {}
        if live.get("state") != "ADAPTER_STARTED":
            return {"status": live.get("state"), "reason": "CLAIM_CHANGED_DURING_LAUNCH", "generation": gen}
        if result.get("verified") is True and session_id:
            _update_claim(project, live, "VERIFIED_OPEN", t, verified_session_id=session_id)
            outcome = {"status": "VERIFIED_OPEN", "reason": "LAUNCHED", "generation": gen, "session_id": session_id}
        elif result.get("verified") is False:
            _update_claim(project, live, "NO_VERIFIED_SESSION", t, verified_session_id="")
            outcome = {"status": "NO_VERIFIED_SESSION", "reason": "NO_VERIFIED_SESSION", "generation": gen}
        else:
            _update_claim(project, live, "UNKNOWN_EFFECT", t, adapter_outcome=str(result.get("outcome", "")))
            outcome = {"status": "UNKNOWN_EFFECT", "reason": "ADAPTER_OUTCOME_UNKNOWN", "generation": gen}
    if outcome["status"] == "VERIFIED_OPEN":
        record_peer_success(project, peer, now=t)
    return outcome


def _unblock_waiting(project: Path) -> list[str]:
    """Under the lock: WAITING cards whose blockers are gone move to PENDING, in FIFO order."""
    queue = read_queue(project)
    cards = _load_cards(project, queue)
    unblocked = []
    for item in queue:
        card = cards.get(item.get("card_id"))
        if not card or card.get("state") != "WAITING":
            continue
        blocker = _overlap_blocker(queue, cards, card["card_id"], card.get("files", []))
        if blocker:
            card["blocked_by"] = blocker
        else:
            card.update(state="PENDING", blocked_by=None, reason="")
            unblocked.append(card["card_id"])
        _write_json(_card_path(project, card["card_id"]), card)
        _sync_queue_state(queue, card)
    if unblocked:
        _write_json(_queue_path(project), queue)
    return unblocked


def reconcile_once(project: Path, *, adapters: dict[str, Any] | None = None, sandbox: str = "",
                   claude_watcher_check: Callable[[Path, str], bool] | None = None,
                   pre_launch_hook: Callable[..., Any] | None = None, now: float | None = None) -> dict[str, Any]:
    """One deterministic pass (0 paid tokens) over the FIFO queue. Never closes or steals on TTL alone."""
    t = _now(now)
    with _lock(project):
        unblocked = _unblock_waiting(project)
        queue = read_queue(project)
    peers: dict[str, dict[str, Any]] = {}
    skipped: dict[str, str] = {}
    for item in queue:
        card_id = item.get("card_id", "")
        card = read_card(project, card_id)
        if not card:
            skipped[card_id] = "CARD_MISSING"
            continue
        state = card.get("state")
        if state != "PENDING":
            skipped[card_id] = {"PAUSED": "CARD_PAUSED", "STOPPED": "CARD_STOPPED", "DONE": "CARD_DONE",
                                "WAITING": "WAITING_FILE_OVERLAP"}.get(state, f"CARD_{state}")
            continue
        for peer in card.get("peers", []):
            peers[f"{card_id}.{peer}"] = _attach_peer(
                project, card, peer, adapters=adapters or {}, sandbox=sandbox,
                claude_watcher_check=claude_watcher_check, pre_launch_hook=pre_launch_hook, t=t)
    # Closing a session needs finish_card's trusted close callback; this pass never closes one on its own.
    return {"ok": True, "project_id": project_id(project), "peers": peers, "skipped_cards": skipped,
            "unblocked": unblocked, "orphans_closed": []}


def finish_card(project: Path, card_id: str, tool: str, outcome: str = "merged", *,
                close_adapter: Callable[..., Any] | None = None, now: float | None = None) -> dict[str, Any]:
    """Owner closes its card: verified companions are closed through `close_adapter`, WAITING cards unblock."""
    t = _now(now)
    card = read_card(project, card_id)
    if not card:
        return {"ok": False, "status": "CARD_NOT_FOUND", "card_id": card_id}
    if card.get("owner") != tool:
        return {"ok": False, "status": "NOT_OWNER", "card_id": card_id, "owner": card.get("owner")}
    closed, close_pending = [], []
    for peer in card.get("peers", []):
        claim = _latest_claim(project, card_id, peer)
        if not claim or claim.get("state") != "VERIFIED_OPEN":
            continue
        companion_id = f"{card_id}.{peer}"
        if close_adapter is None:
            close_pending.append(companion_id)
            continue
        try:
            res = close_adapter(project=Path(project), card_id=card_id, peer=peer, companion_id=companion_id,
                                session_id=claim.get("verified_session_id", ""), outcome=outcome)
        except Exception as exc:  # keep the session recorded open; a human or a later finish closes it
            res = {"closed": False, "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(res, dict) and res.get("closed") is True:
            with _lock(project):
                live = read_claim(project, card_id, peer, int(claim["generation"])) or claim
                _update_claim(project, live, "CLOSED", t, close_outcome=outcome)
            closed.append(companion_id)
        else:
            close_pending.append(companion_id)
    with _lock(project):
        card = read_card(project, card_id) or card
        card.update(state="DONE", reason=str(outcome), outcome=str(outcome), updated_at=t, blocked_by=None)
        _write_json(_card_path(project, card_id), card)
        queue = read_queue(project)
        _sync_queue_state(queue, card)
        _write_json(_queue_path(project), queue)
        unblocked = _unblock_waiting(project)
    return {"ok": True, "status": "DONE", "card_id": card_id, "closed": closed, "close_pending": close_pending,
            "unblocked": unblocked}


# -----------------------------------------------------------------------------
# 6. Verdict federation (author != judge, SLAs, hedging)
# -----------------------------------------------------------------------------
def _verdict_path(project: Path, req_id: str) -> Path:
    return _coord_dir(project) / "verdicts" / f"{_safe(req_id)}.json"


def read_verdict_request(project: Path, req_id: str) -> dict[str, Any] | None:
    doc = _read_json(_verdict_path(project, req_id))
    return doc if isinstance(doc, dict) else None


def _judge_skip_reason(project: Path, tool: str, t: float) -> str:
    if get_circuit_state(project, tool, now=t)["state"] == "OPEN":
        return "CIRCUIT_OPEN"
    return _snapshot_reason(project, tool, t, JUDGE_ROLES)


def _wake_time(project: Path, tools: list[str], t: float) -> float:
    """Earliest known reset among `tools` (presence expiry or breaker open_until), else one retry window."""
    times = []
    for tool in tools:
        pres = _presence(project, tool)
        if str(pres.get("state", "")).upper() != "ACTIVE":
            exp = _ts(pres.get("reset_at")) or _ts(pres.get("expires_at"))
            if exp is not None and exp > t:
                times.append(exp)
        circuit = get_circuit_state(project, tool, now=t)
        if circuit["state"] == "OPEN" and circuit.get("open_until"):
            times.append(float(circuit["open_until"]))
    return min(times) if times else t + EXHAUSTED_RETRY_S


def select_verdict_judge(project: Path, *, author: str, keypoint_codex_only: bool = False, is_keypoint: bool = False,
                         exclude: list[str] | tuple[str, ...] = (), now: float | None = None) -> dict[str, Any]:
    """Pick a non-author judge. Non-keypoint work prefers Claude/Antigravity cross-approval so Codex stays free
    for its exclusive keypoints (U257); a Codex keypoint fails closed when Codex cannot judge."""
    t = _now(now)
    keypoint = bool(keypoint_codex_only or is_keypoint)
    skipped: dict[str, str] = {}
    if keypoint:
        if "codex" in exclude:  # Codex already holds or tried this keypoint; never hedge Codex against itself
            return {"judge": None, "reason": "KEYPOINT_CODEX_EXCLUDED", "skipped": {"codex": "EXCLUDED"},
                    "next_wake_at": _wake_time(project, ["codex"], t)}
        if author == "codex":
            return {"judge": None, "reason": "KEYPOINT_AUTHOR_IS_CODEX", "skipped": {"codex": "AUTHOR"},
                    "next_wake_at": None}
        reason = _judge_skip_reason(project, "codex", t)
        if reason:
            return {"judge": None, "reason": "KEYPOINT_NEEDS_CODEX", "skipped": {"codex": reason},
                    "next_wake_at": _wake_time(project, ["codex"], t)}
        return {"judge": "codex", "reason": "OK", "skipped": {}, "next_wake_at": None}
    order = [tool for tool in TOOLS if tool != "codex"] + ["codex"]
    candidates = [tool for tool in order if tool != author and tool not in exclude]
    for tool in candidates:
        reason = _judge_skip_reason(project, tool, t)
        if reason:
            skipped[tool] = reason
    for tool in candidates:
        if tool not in skipped:
            return {"judge": tool, "reason": "OK", "skipped": skipped, "next_wake_at": None}
    return {"judge": None, "reason": "NO_ELIGIBLE_JUDGE", "skipped": skipped,
            "next_wake_at": _wake_time(project, [tool for tool in TOOLS if tool != author], t)}


def create_verdict_request(project: Path, *, card_id: str, author: str, req_id: str, preferred_judge: str = "",
                           keypoint_codex_only: bool = False, now: float | None = None) -> dict[str, Any]:
    t = _now(now)
    if author not in TOOLS:
        raise ValueError(f"unknown author: {author!r}")
    with _lock(project):
        existing = read_verdict_request(project, req_id)
        if existing:
            return existing
        judge = None
        if preferred_judge and preferred_judge != author and preferred_judge in TOOLS and not keypoint_codex_only \
                and not _judge_skip_reason(project, preferred_judge, t):
            judge = preferred_judge
        pick = {"judge": judge, "reason": "PREFERRED", "next_wake_at": None} if judge else \
            select_verdict_judge(project, author=author, keypoint_codex_only=keypoint_codex_only, now=t)
        judge = pick["judge"]
        doc = {"req_id": req_id, "card_id": card_id, "author": author, "keypoint_codex_only": bool(keypoint_codex_only),
               "created_at": t, "current_judge": judge, "assigned_judge": judge,
               "tried_tools": [judge] if judge else [], "hops": 0, "hedged_judges": [],
               "state": "AWAITING_ACK" if judge else "EXHAUSTED_WAIT_RESET",
               "ack_deadline": t + ACK_SLA_S, "verdict_deadline": t + VERDICT_SLA_S,
               "next_wake_at": pick.get("next_wake_at"), "select_reason": pick.get("reason"),
               "verdict": None, "evidence": "", "winner": None, "cancelled": []}
        _write_json(_verdict_path(project, req_id), doc)
    return doc


def ack_verdict_request(project: Path, req_id: str, judge: str, *, now: float | None = None) -> dict[str, Any]:
    t = _now(now)
    with _lock(project):
        doc = read_verdict_request(project, req_id)
        if not doc:
            return {"ok": False, "reason": "REQUEST_NOT_FOUND"}
        if judge != doc.get("current_judge") or doc.get("state") != "AWAITING_ACK":
            return {"ok": False, "reason": "NOT_CURRENT_JUDGE_OR_STATE", "state": doc.get("state")}
        doc.update(state="ACKED", acked_at=t, acked_by=judge)
        _write_json(_verdict_path(project, req_id), doc)
    return {"ok": True, **doc}


def submit_verdict(project: Path, req_id: str, *, judge: str, verdict: str, evidence: str = "",
                   now: float | None = None) -> dict[str, Any]:
    """First valid verdict commits atomically; a racing hedged judge gets CANCELLED_SUPERSEDED."""
    t = _now(now)
    value = str(verdict).strip().upper()
    if value not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    with _lock(project):
        doc = read_verdict_request(project, req_id)
        if not doc:
            return {"won": False, "status": "REQUEST_NOT_FOUND"}
        if judge == doc.get("author"):
            raise PermissionError("author cannot judge its own work (author != judge)")
        allowed = {doc.get("current_judge")} | set(doc.get("hedged_judges") or [])
        if judge not in allowed:
            raise PermissionError(f"{judge} is not an assigned judge of {req_id}")
        if doc.get("state") == "VERDICT_COMMITTED":
            doc.setdefault("cancelled", []).append({"judge": judge, "verdict": value, "at": t})
            _write_json(_verdict_path(project, req_id), doc)
            return {"won": False, "status": "CANCELLED_SUPERSEDED", "winner": doc.get("winner")}
        if doc.get("state") not in OPEN_VERDICT_STATES:
            return {"won": False, "status": doc.get("state")}
        doc.update(state="VERDICT_COMMITTED", verdict=value, evidence=evidence, winner=judge, committed_at=t)
        _write_json(_verdict_path(project, req_id), doc)
    return {"won": True, "status": "VERDICT_COMMITTED", "winner": judge, "verdict": value}


def reconcile_verdict_requests(project: Path, *, answered_ids: set[str] | None = None,
                               now: float | None = None) -> dict[str, Any]:
    """SLA pass: un-ACKed requests fail over once per untried judge (never back), late verdicts get a hedged
    second judge, answered or finished-card requests close as CLOSED_CONVERGED."""
    t = _now(now)
    answered = set(answered_ids or ())
    out: dict[str, list[Any]] = {"rerouted": [], "hedged": [], "exhausted": [], "converged": [], "open_waits": []}
    with _lock(project):
        for path in sorted((_coord_dir(project) / "verdicts").glob("*.json")):
            doc = _read_json(path)
            if not isinstance(doc, dict) or doc.get("state") not in OPEN_VERDICT_STATES:
                continue
            req_id = doc["req_id"]
            card = read_card(project, str(doc.get("card_id", ""))) if re.fullmatch(r"[\w.-]+", str(
                doc.get("card_id", ""))) else None
            if req_id in answered or (card and card.get("state") in TERMINAL_CARD_STATES):
                doc.update(state="CLOSED_CONVERGED", closed_at=t)
                out["converged"].append(req_id)
            elif doc["state"] == "EXHAUSTED_WAIT_RESET":
                if doc.get("next_wake_at") is not None and t >= float(doc["next_wake_at"]):
                    pick = select_verdict_judge(project, author=doc["author"],
                                                keypoint_codex_only=doc.get("keypoint_codex_only", False), now=t)
                    if pick["judge"]:
                        doc.setdefault("rounds", []).append(list(doc.get("tried_tools", [])))
                        doc.update(state="AWAITING_ACK", current_judge=pick["judge"], tried_tools=[pick["judge"]],
                                   ack_deadline=t + ACK_SLA_S, verdict_deadline=t + VERDICT_SLA_S,
                                   next_wake_at=None)
                        out["rerouted"].append({"req_id": req_id, "from": None, "to": pick["judge"]})
                    else:
                        doc["next_wake_at"] = pick["next_wake_at"]
            elif doc["state"] == "AWAITING_ACK" and t > float(doc.get("ack_deadline", t)):
                pick = select_verdict_judge(project, author=doc["author"],
                                            keypoint_codex_only=doc.get("keypoint_codex_only", False),
                                            exclude=doc.get("tried_tools", []), now=t)
                if pick["judge"] and pick["judge"] not in doc.get("tried_tools", []):
                    out["rerouted"].append({"req_id": req_id, "from": doc.get("current_judge"), "to": pick["judge"]})
                    doc["tried_tools"] = list(doc.get("tried_tools", [])) + [pick["judge"]]
                    doc.update(current_judge=pick["judge"], hops=int(doc.get("hops", 0)) + 1,
                               ack_deadline=t + ACK_SLA_S, verdict_deadline=t + VERDICT_SLA_S)
                else:
                    wake = pick.get("next_wake_at")
                    doc.update(state="EXHAUSTED_WAIT_RESET",
                               next_wake_at=wake if wake is not None and wake > t else t + EXHAUSTED_RETRY_S)
                    out["exhausted"].append(req_id)
            elif doc["state"] == "ACKED" and t > float(doc.get("verdict_deadline", t)):
                pick = select_verdict_judge(project, author=doc["author"],
                                            keypoint_codex_only=doc.get("keypoint_codex_only", False),
                                            exclude=[doc.get("current_judge")], now=t)
                if pick["judge"] and pick["judge"] != doc.get("current_judge"):
                    doc.update(state="TIED_HEDGED", hedged_judges=[doc.get("current_judge"), pick["judge"]],
                               hedged_at=t)
                    out["hedged"].append({"req_id": req_id, "judges": doc["hedged_judges"]})
            _write_json(path, doc)
            if doc["state"] in OPEN_VERDICT_STATES:
                out["open_waits"].append(req_id)
    return out
