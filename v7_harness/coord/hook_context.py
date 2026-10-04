"""Find the UAOS project a tool's session hook fired for, and say one line about it.

Global hooks fire in every project, from wherever the tool chose to run them:
- Claude Code passes `cwd` on stdin and sets CLAUDE_PROJECT_DIR.
- Codex passes `cwd` on stdin (SessionStart, UserPromptSubmit).
- Antigravity runs hooks inside ~/.gemini/config/ (antigravity-cli#1005) and passes `workspacePaths` on stdin (#893).
So the project comes from the payload first, the environment second and the current folder last, and the search walks
up to the folder that holds `.coord/PLAN.md` (a session may start in a subfolder). No such folder means no UAOS project,
and the hook stays silent: other projects pay nothing, not even a line of context.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from v7_harness.coord.presence import desk_label

PLAN = Path(".coord") / "PLAN.md"
_PAYLOAD_KEYS = ("cwd", "workspacePaths", "workspace_paths", "workspaceRoots", "workspace_roots", "project_dir")


def read_stdin(timeout_s: float = 2.0) -> str:
    """The hook payload, or "" for a terminal or a runner that never closes stdin."""
    stream = sys.stdin
    if stream is None or stream.closed:
        return ""
    try:
        if stream.isatty():
            return ""
    except (ValueError, OSError):
        return ""
    box: list[str] = []

    def _read() -> None:
        try:
            box.append(stream.read())
        except (OSError, ValueError, UnicodeDecodeError):
            box.append("")

    reader = threading.Thread(target=_read, daemon=True)
    reader.start()
    reader.join(timeout_s)
    return box[0] if box else ""


def payload_candidates(stdin_text: str) -> list[str]:
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, dict):
        return []
    found: list[str] = []
    for key in _PAYLOAD_KEYS:
        value = payload.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict):
                item = item.get("path") or item.get("uri")
            if isinstance(item, str) and item.strip():
                item = item.removeprefix("file://")
                # file:///C:/work becomes /C:/work; the drive letter needs the leading slash removed on Windows.
                if len(item) > 2 and item[0] == "/" and item[2] == ":" and item[1].isalpha():
                    item = item[1:]
                found.append(item)
    return found


def hook_session(stdin_text: str) -> str | None:
    """U58: the session id a Claude Code or Codex hook payload carries, or None (a terminal, or no id)."""
    try:
        payload = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        return None
    value = payload.get("session_id") if isinstance(payload, dict) else None
    # 200 characters bounds a key that lands in a small JSON file; real ids are 36-character UUIDs.
    return value.strip()[:200] if isinstance(value, str) and value.strip() else None


def shared_desk(project: str | Path) -> Path:
    """U59: a linked git worktree shares the main checkout's desk (presence, mailbox, watch files).

    Seen 2026-09-28: the acting conductor ran in `.claude/worktrees/<name>`, a worktree with its own tracked
    `.coord/PLAN.md`. Its hooks wrote presence there, `coord watch` there crashed on a missing mailbox, and the main
    checkout, where letters and routing live, kept claude ABSENT. Presence and mail are gitignored runtime state, so
    one desk per repository is the main checkout. A submodule (`.git/modules/...`) or a plain folder is unchanged.
    """
    path = Path(project)
    marker = path / ".git"
    try:
        if not marker.is_file():
            return path
        text = marker.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return path
    if not text.startswith("gitdir:"):
        return path
    gitdir = Path(text[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = path / gitdir
    # <main>/.git/worktrees/<name> -> <main>
    if gitdir.parent.name != "worktrees" or gitdir.parent.parent.name != ".git":
        return path
    main = gitdir.parent.parent.parent
    return main if (main / PLAN).is_file() else path


def find_project(candidates: Iterable[str | Path], max_depth: int = 25) -> Path | None:
    for candidate in candidates:
        try:
            current = Path(candidate).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        for _ in range(max_depth):
            if (current / PLAN).is_file():
                return shared_desk(current)
            if current.parent == current:
                break
            current = current.parent
    return None


def hook_project(stdin_text: str, fallback: str | Path | None, env: dict[str, str] | None = None) -> Path | None:
    env = os.environ if env is None else env
    candidates: list[str | Path] = payload_candidates(stdin_text)
    if env.get("CLAUDE_PROJECT_DIR"):
        candidates.append(env["CLAUDE_PROJECT_DIR"])
    if fallback is not None:
        candidates.append(fallback)
    return find_project(candidates)


def brief_line(project: Path, presence: dict[str, Any]) -> str:
    """One line of session context (a SessionStart hook's stdout becomes context in Claude Code and Codex)."""
    inbox: list[str] = []
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    if box_dir.is_dir():
        inbox = sorted(path.stem for path in box_dir.glob("*.json"))
    wakes = sum(1 for item in inbox if item.startswith("wake_"))
    reviews = sum(1 for item in inbox if item.startswith("rsi_review_"))
    desk = ", ".join(f"{tool}={desk_label(info)}" for tool, info in presence.items())
    from .mode import mode_phrase  # U95-T: every session learns the operating mode from code, not only the rules

    return (f"UAOS project {Path(project).name}: inbox {len(inbox)} (P1 {wakes}, RSI reviews {reviews}); desk {desk}. "
            f"{mode_phrase(project)} "
            "Read .coord/PLAN.md; `coord inbox` lists what waits. "
            # U57-B: the only way a session wakes on a letter without the user relaying or approving it.
            "Keep `coord watch --target <you>` running in the background; send by `coord deliver`, never via the user."
            )[:400]


def p1_line(project: Path, presence: dict[str, Any]) -> str:
    """U38: the P1 hand-off to Claude while Codex is away. Empty unless a wake waits and Codex is not ACTIVE, so an
    ordinary prompt carries nothing (a hook's stdout on UserPromptSubmit is added to the prompt)."""
    if (presence.get("codex") or {}).get("state") == "ACTIVE":
        return ""  # the sentinel rings Codex itself (codex queue)
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    wakes = sorted(box_dir.glob("wake_*.json")) if box_dir.is_dir() else []
    if not wakes:
        return ""
    reason = ""
    try:
        data = json.loads(wakes[0].read_text(encoding="utf-8"))
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict):
            reason = str(payload.get("wake_reason") or "")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    codex = (presence.get("codex") or {}).get("state", "UNKNOWN")
    return (f"UAOS P1 waiting ({len(wakes)}), Codex {codex}: {reason or 'see mailbox'}. Claude acts as deputy: "
            "`coord inbox`, handle it, then `coord ack --id <id>`.")[:400]


# Runtime state beside the presence files (.coord/presence/ is git-ignored); presence reads only <tool>.json.
P1_SEEN = Path(".coord") / "presence" / "p1_hook_seen.txt"


def p1_is_new(project: Path, line: str) -> bool:
    """U46-P1: say a P1 line only when it differs from the last one said. The line carries the wake count, Codex's
    state and the first reason, and the fingerprint adds the wake ids, so any new wake or state change speaks again."""
    if not line:
        return False
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    ids = sorted(path.stem for path in box_dir.glob("wake_*.json")) if box_dir.is_dir() else []
    fingerprint = hashlib.sha256("\n".join([line, *ids]).encode("utf-8")).hexdigest()
    seen = Path(project) / P1_SEEN
    try:
        if seen.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    except OSError:
        pass
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass  # a hook never fails the session; the line is said again next time
    return True


# U95-A: Antigravity's dedupe record, beside p1_hook_seen.txt (.coord/presence/ is git-ignored).
AGY_SEEN = Path(".coord") / "presence" / "agy_hook_seen.txt"
AGY_TARGET = "antigravity"
# Five ids (38 characters each) keep the line near 200 tokens; `coord inbox` lists the rest.
AGY_SHOWN = 5


def agy_letters(project: Path) -> list[str]:
    """Ids of inbox letters addressed to Antigravity (requested_target or to), newest first (U104)."""
    box_dir = Path(project) / ".coord" / "mailbox" / "inbox"
    found: list[tuple[float, str]] = []
    if not box_dir.is_dir():
        return []
    for path in box_dir.glob("*.json"):
        try:
            mtime = path.stat().st_mtime
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue  # claimed or mid-write: the next turn looks again
        payload = data.get("payload") if isinstance(data, dict) else None
        if isinstance(payload, dict) and AGY_TARGET in (payload.get("requested_target"), payload.get("to")):
            found.append((mtime, path.stem))
    # U104: name order showed the five oldest (2026-09-26) and hid a new verdict order; newest first instead.
    return [stem for _, stem in sorted(found, reverse=True)]


def agy_line(project: Path, presence: dict[str, Any], stdin_text: str) -> str:
    """U95-A: what Antigravity learns about UAOS on the first model call of a turn, said only when it changed.

    Seen 2026-09-30: Antigravity's presence hook printed only {} and `coord deliver` could not address it, so its only
    UAOS knowledge was GEMINI.md and every work order reached it through the user. The line names Antigravity's role
    and the letters addressed to it. It repeats only when the conversation, the desk or those letters change, so an
    unchanged desk costs no tokens; later calls of the same turn read nothing from disk.
    """
    try:
        event = json.loads(stdin_text) if stdin_text.strip() else {}
    except json.JSONDecodeError:
        event = {}
    if not isinstance(event, dict):
        event = {}
    if event.get("invocationNum", 0) != 0:
        return ""
    letters = agy_letters(project)
    desk = ", ".join(f"{tool}={desk_label(info)}" for tool, info in presence.items())
    conversation = str(event.get("conversationId") or "")
    # U148: only the user's Antigravity desk hears what its headless runs answered (agy_dispatch, U120)
    answers = ""
    from .agy_dispatch import answered_today
    from .deliver import read_user_desk

    if conversation and conversation == read_user_desk(project, "antigravity"):
        done = answered_today(project, time.time())
        if done:
            answers = (f"Your headless runs sent {len(done)} headless answer(s) today, newest re {done[0]} "
                       "(.coord/mailbox/delivery/agy_auto.jsonl). This hook text reaches only you, never the user "
                       "(Antigravity review relay_39c3f5be), so begin your next visible reply with one line naming "
                       "these answers. ")
    # U148 REPLAN (Codex codex_u148_c1_human_origin_gate_unmet): the hook never registers a desk, so a desktop
    # conversation with no valid desk learns the explicit registration, to be used only on the user's own turn.
    from .deliver import agy_desktop_conversation, user_desk_state

    if conversation and user_desk_state(project, "antigravity")[0] != "OK" and agy_desktop_conversation(conversation):
        runtime = Path.home() / ".uaos" / "uaos.py"
        answers += (f"No valid Antigravity user desk is registered for this project. Only if 윤겸스 is the one "
                    f"typing to you in this conversation, register it once with: python \"{runtime}\" coord presence "
                    f"--tool antigravity --desk-thread {conversation} --project \"{project}\" ")
    from .mode import mode_phrase  # U95-T

    mode = mode_phrase(project)
    fingerprint = hashlib.sha256("\n".join([conversation, desk, mode, answers, *letters]).encode("utf-8")).hexdigest()
    seen = Path(project) / AGY_SEEN
    try:
        if seen.read_text(encoding="utf-8").strip() == fingerprint:
            return ""
    except OSError:
        pass
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass  # a hook never fails the session; the line is said again next time
    line = (f"UAOS project {Path(project).name}: desk {desk}. Antigravity conducts only while codex and claude are "
            "both LIMITED/ABSENT; otherwise it does only work orders addressed to antigravity and never judges its "
            f"own work. {mode} {answers}")
    if letters:
        try:
            newest = json.loads((Path(project) / ".coord" / "mailbox" / "inbox" / f"{letters[0]}.json")
                                .read_text(encoding="utf-8"))["payload"].get("message", "")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            newest = ""  # claimed or mid-write: the ids still name it
        line += (f"{len(letters)} letter(s) for antigravity in .coord/mailbox/inbox, newest first: "
                 f"{', '.join(letters[:AGY_SHOWN])}. Newest says: {str(newest)[:160]} "
                 "Each names a work manual: keep to its allow, acceptance, forbidden and stop lines, then report with "
                 "`uaos coord deliver --actor antigravity --target claude --message ...`.")
    else:
        line += "No letter waits for antigravity; .coord/PLAN.md lists the cards."
    return line[:1100]  # U104: +160 chars for the newest letter's text, so the report instruction is not cut


RETENTION_SEEN = Path(".coord") / "presence" / "retention_seen.txt"


def _scan_zone(target_path: Path | str) -> tuple[int, int]:
    count = 0
    total_bytes = 0
    stack = [str(target_path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as it:
                for entry in it:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            count += 1
                            total_bytes += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return count, total_bytes


def retention_alert(project: Path | str, policy: dict[str, Any] | None = None) -> str:
    """Walk retention zones with stat only and return an alert line if any zone exceeds count or byte caps."""
    if policy is None:
        from v7_harness.retention import default_policy
        policy = default_policy()

    root = Path(project)
    over_cap: list[str] = []

    for zone in policy.get("zones", []):
        zone_path = zone.get("path")
        if not zone_path:
            continue
        target = root / zone_path
        if not target.is_dir():
            continue
        count, total_bytes = _scan_zone(target)
        max_count = zone.get("max_count")
        max_bytes = zone.get("max_bytes")

        is_over_count = max_count is not None and count > max_count
        is_over_bytes = max_bytes is not None and total_bytes > max_bytes

        if is_over_count or is_over_bytes:
            cur_mb = round(total_bytes / 10**6, 1)
            max_mb = round((max_bytes or 0) / 10**6, 1)
            cur_mb_s = f"{int(cur_mb) if cur_mb.is_integer() else cur_mb}"
            max_mb_s = f"{int(max_mb) if max_mb.is_integer() else max_mb}"
            over_cap.append(f"{zone_path} {count}/{max_count} files, {cur_mb_s}/{max_mb_s} MB")

    if not over_cap:
        return ""

    line = f"UAOS retention: {'; '.join(over_cap)} - run `rsi retention` (dry run), then `--archive`"
    line = line.replace("\n", " ")
    return line[:299]


def retention_alert_is_new(project: Path | str, line: str) -> bool:
    """Say a retention alert line only when it differs from the last one said."""
    if not line:
        return False
    fingerprint = hashlib.sha256(line.encode("utf-8")).hexdigest()
    seen = Path(project) / RETENTION_SEEN
    try:
        if seen.read_text(encoding="utf-8").strip() == fingerprint:
            return False
    except OSError:
        pass
    try:
        seen.parent.mkdir(parents=True, exist_ok=True)
        seen.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass  # a hook never fails the session
    return True
