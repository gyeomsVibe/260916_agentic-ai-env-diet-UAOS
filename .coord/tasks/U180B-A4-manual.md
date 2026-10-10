```contract
work_id: U180B-A4
worker: apply
apply_after: U180B-L1
goal: Data-only atomic shared project registry library
inputs:
- v7_harness/coord/__init__.py sha256=6dbd2b49c3d0ae8e454109aa365c8dd9e5c89e565ca351666725c5690d7d20f6
allow:
- v7_harness/coord/projects.py
context_allow:
- v7_harness/coord/__init__.py
acceptance: python D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.claude/worktrees/new-user-chat-channel-ac139c/.work/wt_u180b/.work/U180B_accept.py && python D:/D_Workspace_NB/-agentic-ai-workspace/260916_agentic-ai-env-diet/.claude/worktrees/new-user-chat-channel-ac139c/.work/wt_u180b/.work/U180B_counterexamples.py
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 90
remote_budget_tokens: 0
```

## Instructions for the worker

# U180B nonexecuting project registry calculator contract

Generate ONE NEW file v7_harness/coord/projects.py. Source is a clean main worktree. Do not read huge files, invoke tools/workers/network, edit tests/settings/other files, or install. No paid escalation. Output ONE ===FILE block for the allowed file only. Example format: header ===FILE: path=== then the complete file body. No code fences or commentary. One operation, 90s, remote0. Judge Codex; no approval by worker.

This is a DATA_ONLY library, not boot supervision, not authorization, not adapter wiring. Independent Stage4 Go exists only for this library. Input __init__.py is just a small pinned repository anchor; no changes to it.

Public APIs:
load(registry_path)->dictionary {schema:1,generation:nonnegative integer,projects:list}; missing file returns empty initial state, but malformed/inconsistent data raises ValueError and preserves bytes.
enroll(registry_path, project_root, *, tool, session, event_id, parent_id=None, timeout_s=5)->project entry dictionary.

Entry fields EXACTLY id,root,parent_id,events. id = SHA256 of os.path.normcase(str(Path(project_root).resolve())) UTF-8. root stores that normalized resolved path. Directory must already exist. tools only codex/claude/antigravity; session is full UUID; event_id nonempty string length<=200. Event fields EXACTLY tool,session,event_id. Event key is (project_id,tool,session,event_id); same event id in another project is distinct. Same key same bytes is no-op (file bytes and generation unchanged). Existing root parent_id cannot be silently changed. New event adds to its project and increments generation once. No authority/conductor/status or prompt text in entry/events.

Parent: nested new root must name an already registered nearest real ancestor via parent_id. Reject nested root without parent, invalid/non-ancestor/self parent, duplicate ids, cycles, id/root mismatch and malformed event records in load as well as enroll. Top-level roots have parent_id None. Data validation must not scan folders or open project files.

Concurrency: use existing v7_harness.coord.stream._try_lock(fd)->bool and _unlock(fd) OS lock helpers. Stable separate registry_path+'.lock' file, open O_CREAT|O_RDWR, never unlink lock file. Deadline time.monotonic; validate timeout finite positive. Lock encompasses read/validate/update + tempfile in SAME directory with unique uuid + UTF8 JSON canonical serialization + flush/fsync + os.replace. No O_APPEND. Do not replace before holding lock. Release lock+fd in finally. Missing registry.parent can be mkdir(parents=True,exist_ok=True); registry data remains untouched on validation error/timeout. Writers real8processes must lose no records. Readers see whole validated snapshots, never partial bytes. Retry bounded Windows PermissionError only within monotonic deadline; otherwise propagate visibly, no empty-success fallback.

Fixed acceptance .work/U180B_accept.py in this same worktree is judge-owned and frozen before your run: nine tests including 3 roots x3tools/nine receipts, replay/parent conflict, corrupt preservation, nested parent, invalid args, real8process writers, lock timeout/re-acquire, wrong-schema JSON, registry isolation. Run command from staging: python .work/U180B_accept.py. These imports select staged module through cwd. Do not branch on tests or process names.

Forbidden: file edits beyond projects.py; deleting data; auto-registration/scanning; daemon/CLI/sentinel/presence changes; auth/permission changes; model/network calls; Git; tests/evaluator changes; authority decisions. Stop on mismatched pinned input or inability to produce one file. Produce complete maintainable Python with intent comments for locking and identity choices. Rollback: unapproved candidate stays isolated, source remains unchanged.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
===FILE: v7_harness/coord/projects.py===
"""Data-only project enrollment: identities and receipts never confer authority."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

from .stream import _try_lock, _unlock

TOOLS = frozenset(("codex", "claude", "antigravity"))
SESSION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
RETRY_S = 0.01  # bounded OS-lock/Windows-sharing retry, not a paid poll


def _root(value):
    return os.path.normcase(str(Path(value).resolve()))


def _identity(root):
    return hashlib.sha256(root.encode("utf-8")).hexdigest()


def _ancestor(parent, child):
    return Path(parent) in Path(child).parents


def _event(tool, session, event_id):
    if tool not in TOOLS or not isinstance(session, str) or not SESSION.fullmatch(session):
        raise ValueError("INVALID_ADAPTER_EVENT")
    if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 200:
        raise ValueError("INVALID_EVENT_ID")
    return {"tool": tool, "session": session, "event_id": event_id}


def _validate(data):
    if not isinstance(data, dict) or set(data) != {"schema", "generation", "projects"}:
        raise ValueError("REGISTRY_SCHEMA")
    if type(data["schema"]) is not int or data["schema"] != 1 or type(data["generation"]) is not int or data["generation"] < 0:
        raise ValueError("REGISTRY_VERSION")
    if not isinstance(data["projects"], list):
        raise ValueError("REGISTRY_PROJECTS")
    by_id = {}
    for entry in data["projects"]:
        if not isinstance(entry, dict) or set(entry) != {"id", "root", "parent_id", "events"}:
            raise ValueError("REGISTRY_ENTRY")
        root = entry["root"]
        if not isinstance(root, str) or not root or root != _root(root) or entry["id"] != _identity(root):
            raise ValueError("REGISTRY_IDENTITY")
        if entry["id"] in by_id or not isinstance(entry["events"], list):
            raise ValueError("REGISTRY_DUPLICATE")
        seen = set()
        for event in entry["events"]:
            if not isinstance(event, dict) or set(event) != {"tool", "session", "event_id"}:
                raise ValueError("REGISTRY_EVENT")
            _event(event["tool"], event["session"], event["event_id"])
            key = (event["tool"], event["session"], event["event_id"])
            if key in seen:
                raise ValueError("REGISTRY_EVENT_REPLAY")
            seen.add(key)
        by_id[entry["id"]] = entry
    for entry in by_id.values():
        ancestors = [p for p in by_id.values() if _ancestor(p["root"], entry["root"])]
        nearest = max(ancestors, key=lambda p: len(Path(p["root"]).parts)) if ancestors else None
        expected = nearest["id"] if nearest else None
        if entry["parent_id"] != expected:
            raise ValueError("REGISTRY_PARENT")
    return data


def load(registry_path):
    """Missing is initial state; invalid bytes are preserved, never treated as empty."""
    try:
        text = Path(registry_path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schema": 1, "generation": 0, "projects": []}
    try:
        return _validate(json.loads(text))
    except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("REGISTRY_CORRUPT") from exc


def enroll(registry_path, project_root, *, tool, session, event_id, parent_id=None, timeout_s=5):
    """One OS lock protects the complete read/validate/update/persist transaction."""
    if not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
        raise ValueError("INVALID_TIMEOUT")
    event = _event(tool, session, event_id)
    root = _root(project_root)
    if not Path(root).is_dir():
        raise ValueError("PROJECT_MISSING")
    path = Path(registry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout_s
    fd = os.open(str(path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    locked = False
    temporary = None
    try:
        while not (locked := _try_lock(fd)):
            if time.monotonic() >= deadline:
                raise TimeoutError("REGISTRY_LOCK_TIMEOUT")
            time.sleep(min(RETRY_S, max(0, deadline - time.monotonic())))
        data = load(path)
        project_id = _identity(root)
        entry = next((p for p in data["projects"] if p["id"] == project_id), None)
        if entry is not None:
            if entry["parent_id"] != parent_id:
                raise ValueError("PROJECT_PARENT_CHANGED")
            if event in entry["events"]:
                return entry  # identical replay has identical bytes and generation
        else:
            entry = {"id": project_id, "root": root, "parent_id": parent_id, "events": []}
            data["projects"].append(entry)
        entry["events"].append(event)
        data["generation"] += 1
        _validate(data)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                prefix=path.name + ".", suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        while True:
            try:
                os.replace(temporary, path)
                temporary = None
                return entry
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(min(RETRY_S, max(0, deadline - time.monotonic())))
    finally:
        # Only the disposable temp created by this operation can be removed.
        try:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        finally:
            try:
                if locked:
                    _unlock(fd)
            finally:
                os.close(fd)  # stable lock file remains; unlinking it could split exclusion

