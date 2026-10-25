"""U229: bounded native desk titles; registry identity and UI readback stay separate."""
from __future__ import annotations

import hashlib
import json
import os
import unicodedata
from pathlib import Path

from . import user_window as uw

ADAPTER_VERSION = "U237_NATIVE2"  # U237: a new version resets every desk's native budget once (BLOCKED included)
TOOLS = {"codex", "claude", "antigravity"}
MAX_NATIVE_EMITS = 3  # one native attempt and two bounded repairs per desired title
MAX_TOPIC_CHARS = 16  # deliberately short sidebar label, agreed schedule content only


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _native_event(tool: str, thread: str, event: dict) -> bool:
    if os.environ.get("UAOS_WORKER") or tool not in TOOLS or not isinstance(event, dict):
        return False
    if event.get("agent_type") or event.get("is_subagent"):
        return False
    identity = event.get("session_id") or event.get("conversationId")
    if not thread or identity != thread:
        return False
    allowed = {"SessionStart", "UserPromptSubmit"}
    if tool == "antigravity":
        allowed.add("PreInvocation")
    kind = event.get("hook_event_name")
    native_agy = {"artifactDirectoryPath", "conversationId", "initialNumSteps", "invocationNum",
                  "modelName", "transcriptPath", "workspacePaths"}
    if tool == "antigravity" and kind is None and native_agy.issubset(event):
        kind = "PreInvocation"  # exact native payload shape; never grants a new desk claim
    if kind not in allowed:
        return False
    prompt = event.get("prompt")
    return prompt is None or uw.is_human_prompt(prompt)


def _schedule_topic(project: Path) -> str | None:
    from .title_consensus import accepted_topic  # U234 dedicated store wins over legacy master votes
    exists, topic = accepted_topic(project)
    if exists:
        return topic
    schedule = _json(project / ".coord" / "master_schedule.json")
    consensus, phases = schedule.get("desk_title"), schedule.get("phases")
    if not isinstance(consensus, dict) or not isinstance(phases, list) or not phases:
        return None
    voters = consensus.get("agreed_by")
    if not isinstance(voters, list) or len(voters) != 3 or not all(isinstance(v, str) for v in voters):
        return None
    if set(voters) != TOOLS:
        return None
    canonical = json.dumps(phases, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    if consensus.get("schedule_sha256") != hashlib.sha256(canonical.encode("utf-8")).hexdigest():
        return None
    topic = consensus.get("topic")
    if not isinstance(topic, str) or not 0 < len(topic) <= MAX_TOPIC_CHARS or topic != topic.strip():
        return None
    if any(c in "[]" or unicodedata.category(c).startswith("C") for c in topic):
        return None
    return topic


def _desired_title(project: Path, entry: dict, current: str | None) -> str | None:
    return _desired_parts(project, entry, current)[0]


def _emit_count(entry: dict) -> int:
    try:
        return max(0, int(entry.get("native_emits") or 0))
    except (TypeError, ValueError):
        return MAX_NATIVE_EMITS  # corrupt counters never reopen a retry budget


def _take_native(entry: dict, desired: str, current: str | None, adopted: str | None = None) -> str:
    if adopted:
        entry["topic"] = adopted  # U237/U243: self-named or updated schedule topic becomes this window's topic
        if "shared_topic" in entry:
            entry["shared_topic"] = adopted
    if entry.get("adapter_version") != ADAPTER_VERSION or entry.get("desired_title") != desired:
        entry.update(adapter_version=ADAPTER_VERSION, desired_title=desired, native_emits=0,
                     converged=False, title_state="NATIVE_PENDING")
    if current == desired:
        entry.update(converged=True, title_state="NATIVE_CONFIRMED")
        return "CONVERGED"
    count = _emit_count(entry)
    if count >= MAX_NATIVE_EMITS:
        # U237: UNKNOWN readback (None) is no evidence of a failed rename; only a known other title blocks
        state = "BLOCKED" if current is not None else "UNVERIFIED"
        entry.update(converged=False, title_state=state)
        return state
    entry.update(native_emits=count + 1,
                 converged=False, title_state="NATIVE_PENDING")
    return "PENDING"


def _take_for_primary(project: Path, tool: str, thread: str, entry: dict, desired: str,
                      current: str | None, adopted: str | None = None) -> str:
    # Called by _entry_change under the same registry lock used by claim/handoff.
    if uw.desk_role(project, tool, thread) != "PRIMARY":
        return "SKIPPED"
    return _take_native(entry, desired, current, adopted)


def reconcile_title(project: Path, tool: str, thread: str, event: dict) -> dict:
    empty = {"title": None, "instruction": "", "state": "SKIPPED"}
    if not _native_event(tool, thread, event) or uw.desk_role(project, tool, thread) != "PRIMARY":
        return empty
    record = _json(uw._presence(project) / "user_windows.json")
    entries = record.get(tool)
    if not isinstance(entries, list):
        return empty
    entry = next((e for e in entries if isinstance(e, dict) and e.get("thread") == thread), None)
    if entry is None:
        return empty
    if tool == "claude":
        current = event.get("session_title")
        if not isinstance(current, str):  # U237: the session transcript records the shown title
            current = uw._claude_title(thread, transcript=event.get("transcript_path"))
    else:
        current = uw._current_title(tool, thread)
    current = current if isinstance(current, str) else None
    desired, adopted = _desired_parts(Path(project), entry, current)
    if not desired:
        return empty
    seen = {}

    def take(e: dict) -> str:
        state = _take_for_primary(project, tool, thread, e, desired, current, adopted)
        seen["emits"] = _emit_count(e)
        return state

    state = uw._entry_change(project, tool, thread, take)
    title = desired if state == "PENDING" else None
    # U237: Claude's hook sessionTitle landed late; from the second emit the explicit tool call repairs it
    repair = tool != "claude" or seen.get("emits", 0) >= 2
    instruction = uw._instruction(project, tool, thread, desired, None) if title and repair else ""
    return {"title": title, "instruction": instruction, "state": state or "SKIPPED"}


def _own_suffix(prefix: str, current: str | None, shared: str | None) -> str | None:
    """U237: a title the window gave itself (prefix, one space, a valid topic other than the shared fallback)."""
    from .title_consensus import valid_topic
    if not isinstance(current, str) or not current.startswith(prefix + " "):
        return None
    topic = current[len(prefix) + 1:]
    return topic if valid_topic(topic) and topic != shared else None


def _desired_parts(project: Path, entry: dict, current: str | None) -> tuple[str | None, str | None]:
    """U237/U243: (desired title, topic to adopt). When the shared schedule topic changes after declaration,
    transition to the new process topic; otherwise keep own topic and guard stale desired_title from false adoption."""
    from .title_consensus import valid_topic
    raw = entry.get("title")
    match = uw.TITLE_RE.fullmatch(raw) if isinstance(raw, str) else None
    if not match:
        return None, None
    prefix = match.group(0)
    shared = _schedule_topic(project)
    if shared and "shared_topic" in entry and shared != entry.get("shared_topic"):
        return f"{prefix} {shared}", shared
    own = entry.get("topic") if valid_topic(entry.get("topic")) else None
    adopted = None if (own or current == entry.get("desired_title")) else _own_suffix(prefix, current, shared)
    topic = own or adopted or shared
    if topic:
        return f"{prefix} {topic}", adopted
    for prior in (entry.get("desired_title"), current):
        if isinstance(prior, str) and prior.startswith(prefix + " ") and prior.strip() == prior:
            if not any(unicodedata.category(c).startswith("C") for c in prior):
                return prior, None  # missing/stale consensus never strips an already accepted suffix
    return prefix, None
