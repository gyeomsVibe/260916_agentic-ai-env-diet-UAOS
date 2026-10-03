```contract
work_id: U148-FIN
worker: apply
apply_after: U148-H1R2
goal: U148 one bundle carrying the five Codex-passed final files (diff 7e046010) from HEAD, for judge approval
inputs:
- v7_harness/coord/deliver.py sha256=8e2dac3233238f5c41b0a8755064a85fc67574b702ce138a71644ca1ee991b89
- v7_harness/coord/agy_dispatch.py sha256=1b66b1afe71f65713d6f95e993af8c720c91ba26eca9ab4f34a7462b3417d8c9
- v7_harness/coord/board.py sha256=80b7f7cafca602d832e23ad105dc63dc895e355ba381a5ba7d0871a3b8f082ee
- v7_harness/coord/hook_context.py sha256=f9a69fa177396511d75942ce33363753e20ac712756d258bdf04a123844a170b
- v7_harness/cli.py sha256=1fc0f60f1ebe84cafeec5ae48f53f422a46b7e458d5847ef1f13acdd6f021fa5
allow:
- v7_harness/coord/deliver.py
- v7_harness/coord/agy_dispatch.py
- v7_harness/coord/board.py
- v7_harness/coord/hook_context.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u148_agy_desk_visible tests.test_u148_hook_registers_nothing tests.test_u147_user_window_board tests.test_u147_route_counterexamples
forbidden: edits outside allow; editing or deleting tests; network; commit/push
stop: input hash mismatch; any SEARCH block not found once; no output
judge: codex
timeout_s: 900
```
Card U148. The serial driver copied each passing stage file into the source by hand instead of a judge
--approve, so no U148 run is APPLIED and the replay check can no longer match. This run applies the same
final bytes Codex passed (codex_u148_final_code_pass_7e046010; Ollama receipts U148-B1, U148-B1R2,
U148-H1, U148-H1R2, U148-C2, U148-A2R2) from the HEAD versions as one bundle. Each block below is one
hunk of `git diff -U5`; copy them exactly and change nothing else.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH

from v7_harness.coord.stream import SECRET_PATTERNS, _try_lock, _unlock
from v7_harness.coord.mailbox import Mailbox


@dataclass(frozen=True)
class DeliverResult:
    delivered: bool
    target: str          # "codex" | "claude" | "mailbox_only"
    reason: str          # SENT | CLI_NOT_FOUND | DELIVERY_FAILED | ABSENT_ALL | ...
=======

from v7_harness.coord.stream import SECRET_PATTERNS, _try_lock, _unlock
from v7_harness.coord.mailbox import Mailbox


AGY_APP_HOME_ENV = "UAOS_AGY_APP_HOME"  # tests point this at a fixture; default ~/.gemini/antigravity


REPLACE_TRIES = 20  # Windows refuses os.replace while another process replaces the same file; 20 x 50 ms = 1 s


@dataclass(frozen=True)
class DeliverResult:
    delivered: bool
    target: str          # "codex" | "claude" | "mailbox_only"
    reason: str          # SENT | CLI_NOT_FOUND | DELIVERY_FAILED | ABSENT_ALL | ...
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
#   follows the user to a new window on their next prompt; `register_user_desk` is also callable directly.
# - stored: `.coord/presence/user_desk_<tool>.json`, one file per tool so two tools' hooks never overwrite each other;
#   written by temp file + os.replace, so a reader sees the old or the new record, never half of one.
# - verified at every delivery (`_verify_thread`); a stale desk (rollout gone, other project) fails closed as
#   USER_DESK_STALE and the letter stays in the mailbox until the next human prompt registers a live desk.
USER_DESK_TOOLS = ("codex", "claude")


def user_desk_path(project: Path, tool: str) -> Path:
    return Path(project) / ".coord" / "presence" / f"user_desk_{tool}.json"

=======
#   follows the user to a new window on their next prompt; `register_user_desk` is also callable directly.
# - stored: `.coord/presence/user_desk_<tool>.json`, one file per tool so two tools' hooks never overwrite each other;
#   written by temp file + os.replace, so a reader sees the old or the new record, never half of one.
# - verified at every delivery (`_verify_thread`); a stale desk (rollout gone, other project) fails closed as
#   USER_DESK_STALE and the letter stays in the mailbox until the next human prompt registers a live desk.
USER_DESK_TOOLS = ("codex", "claude", "antigravity")


def user_desk_path(project: Path, tool: str) -> Path:
    return Path(project) / ".coord" / "presence" / f"user_desk_{tool}.json"

>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
        return True  # every prompt in the same window would otherwise rewrite the record
    path = user_desk_path(project, tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(json.dumps({"thread": thread, "at": time.time(), "source": source}), encoding="utf-8")
    os.replace(temp, path)
    return True


def _queue_dir(project: Path, tool: str) -> Path:
    """U134: letters waiting for `tool` to turn ACTIVE live beside the mailbox's other delivery records."""
    return _project_mailbox(Path(project).resolve()).root / "delivery" / "queued" / tool
=======
        return True  # every prompt in the same window would otherwise rewrite the record
    path = user_desk_path(project, tool)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    temp.write_text(json.dumps({"thread": thread, "at": time.time(), "source": source}), encoding="utf-8")
    for _attempt in range(REPLACE_TRIES):
        try:
            os.replace(temp, path)
            return True
        except PermissionError:
            time.sleep(0.05)
    temp.unlink(missing_ok=True)
    return False


def _queue_dir(project: Path, tool: str) -> Path:
    """U134: letters waiting for `tool` to turn ACTIVE live beside the mailbox's other delivery records."""
    return _project_mailbox(Path(project).resolve()).root / "delivery" / "queued" / tool
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner, pending_owner=pending_owner,
                                 card=card, window=window or "")
    finally:
        _release_guard(guard, owner)
=======
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner, pending_owner=pending_owner,
                                 card=card, window=window or "")
    finally:
        _release_guard(guard, owner)


def agy_desktop_conversation(conversation: object) -> bool:
    if not isinstance(conversation, str) or not UUID_RE.fullmatch(conversation):
        return False
    home = Path(os.environ.get(AGY_APP_HOME_ENV) or (Path.home() / ".gemini" / "antigravity"))
    return (home / "conversations" / f"{conversation}.db").is_file() or (home / "brain" / conversation).is_dir()
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

AUTO_TAG = "[agy-auto]"
# 20 answers x ~28k tokens (U119 live) = at most ~560k Antigravity tokens a day; past it letters wait (U118 route).
=======

import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

AUTO_TAG = "[agy-auto]"
# 20 answers x ~28k tokens (U119 live) = at most ~560k Antigravity tokens a day; past it letters wait (U118 route).
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
MAX_REPLY_CHARS = 1500
# U127: a resumed turn re-reads the conversation (probe: 53,072 input tokens against about 25,000 fresh, +28,000 a
# turn). Past this the card starts fresh, so the next turn still fits the 100,000 review budget (U127-A audit).
RESUME_MAX_INPUT = 70_000

def _ledger(project: Path) -> Path:
    return Path(project) / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"

def _today_count(project: Path, now: float) -> int:
    ledger = _ledger(project)
=======
MAX_REPLY_CHARS = 1500
# U127: a resumed turn re-reads the conversation (probe: 53,072 input tokens against about 25,000 fresh, +28,000 a
# turn). Past this the card starts fresh, so the next turn still fits the 100,000 review budget (U127-A audit).
RESUME_MAX_INPUT = 70_000

# U148: every daily count names one day for all 3 tools, the user's: Asia/Seoul, a fixed UTC+9 because Korea has had
# no daylight saving since 1988 and Windows Python has no tz database without the tzdata package.
SEOUL = timezone(timedelta(hours=9))


def seoul_day(ts: float) -> str:
    """U148: the Asia/Seoul calendar day of a Unix time, as YYYY-MM-DD."""
    return datetime.fromtimestamp(ts, SEOUL).strftime("%Y-%m-%d")

def _ledger(project: Path) -> Path:
    return Path(project) / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"

def _today_count(project: Path, now: float) -> int:
    ledger = _ledger(project)
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
        record_window(project, card, "antigravity", str(outcome.conversation_id), now=now,
                      last_input_tokens=int(outcome.usage.get("input_tokens", 0)))
    row = {"ts": now, "message_id": message_id, "state": "ANSWERED", "reply_id": sent.message_id, "usage": dict(outcome.usage), "conversation_id": outcome.conversation_id}
    _record(project, row)
    return row
=======
        record_window(project, card, "antigravity", str(outcome.conversation_id), now=now,
                      last_input_tokens=int(outcome.usage.get("input_tokens", 0)))
    row = {"ts": now, "message_id": message_id, "state": "ANSWERED", "reply_id": sent.message_id, "usage": dict(outcome.usage), "conversation_id": outcome.conversation_id}
    _record(project, row)
    return row


def answered_today(project: Path, now: float) -> list[str]:
    """U148: message ids Antigravity answered headless on the Asia/Seoul day of `now`, newest first, each id once
    (a letter answered twice is one answer). FAILED rows are not answers. The board line and the desk conversation's
    hook line both read this one ledger."""
    ledger = _ledger(project)
    try:
        lines = ledger.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    day = seoul_day(now)
    kept: list[str] = []
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("state") != "ANSWERED":
            continue
        ts, message_id = row.get("ts"), row.get("message_id")
        if isinstance(ts, bool) or not isinstance(ts, (int, float)) or not isinstance(message_id, str):
            continue
        if seoul_day(ts) == day and message_id not in kept:
            kept.append(message_id)
    return kept
>>>>>>> REPLACE

===EDIT: v7_harness/coord/board.py===
<<<<<<< SEARCH
from v7_harness.coord import deliver
from v7_harness.coord.presence import CODEX_SESSIONS_ENV

CLAUDE_PROJECTS_ENV = "UAOS_CLAUDE_PROJECTS"  # tests point these at fixtures
AGY_BRAIN_ENV = "UAOS_AGY_BRAIN"
# A transcript written in the last 120 s counts as a running turn: Claude Code and Antigravity write one line per
# message or tool call, and a single model call rarely thinks longer than two minutes without a line.
WORKING_WINDOW_S = 120
RECENT_S = 24 * 3600  # sessions untouched for a day are not on the board
CODEX_SCAN = 12  # the same 12 newest rollouts deliver.py routes among
=======
from v7_harness.coord import deliver
from v7_harness.coord.presence import CODEX_SESSIONS_ENV

CLAUDE_PROJECTS_ENV = "UAOS_CLAUDE_PROJECTS"  # tests point these at fixtures
AGY_BRAIN_ENV = "UAOS_AGY_BRAIN"
OLLA_USAGE_ENV = "OLLA_USAGE"  # the override olla.py reads; default ~/.cache/olla/usage.jsonl, shared by all 3 tools
# U148: olla usage events that are real local-model calls (hints, plans and turn shapes are not calls). Each row is
# one call; olla writes no call id, so rows are not deduplicated. A failed call (status ERROR) still ran and counts.
OLLAMA_CALLS = ("ask", "edit", "digest", "find", "pilot_local", "pilot_local_repair")
# A preflight refusal never reached the model (Codex: a zero-input preflight is not a call), so it does not count.
OLLAMA_PREFLIGHT = ("PROMPT_TOO_LARGE",)
OLLAMA_STEP = 10  # the line shows tens past 10, so the remembered state changes once per 10 calls, not every call
# A transcript written in the last 120 s counts as a running turn: Claude Code and Antigravity write one line per
# message or tool call, and a single model call rarely thinks longer than two minutes without a line.
WORKING_WINDOW_S = 120
RECENT_S = 24 * 3600  # sessions untouched for a day are not on the board
CODEX_SCAN = 12  # the same 12 newest rollouts deliver.py routes among
>>>>>>> REPLACE

===EDIT: v7_harness/coord/board.py===
<<<<<<< SEARCH

STATUS_ROLLOUTS = 3  # the in-app line reads only the newest Codex rollouts: a hook runs on every tool call
NAMES = {"codex": "Codex", "claude": "Claude", "antigravity": "Antigravity"}


def status_line(project: Path, tool: str, letters: list[str], now: float | None = None) -> str:
    """U147: one line for the user inside `tool`'s own app: new letters, and whether the other two work right now.

    It carries states, never ages, so it changes only when a letter arrives or a tool starts or stops; the hook
    shows it only then (`line_is_new`). The line goes to the user (Claude/Codex `systemMessage`), not to the model.
=======

STATUS_ROLLOUTS = 3  # the in-app line reads only the newest Codex rollouts: a hook runs on every tool call
NAMES = {"codex": "Codex", "claude": "Claude", "antigravity": "Antigravity"}


def ollama_calls_today(now: float) -> int:
    """U148: local-model calls on the Asia/Seoul day of `now`, from the usage log every tool's olla writes.
    olla stamps rows in the machine's local time without a zone; that time is the user's, Asia/Seoul."""
    from v7_harness.coord.agy_dispatch import seoul_day

    path = Path(os.environ.get(OLLA_USAGE_ENV) or (Path.home() / ".cache" / "olla" / "usage.jsonl"))
    day = seoul_day(now)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return 0
    count = 0
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        # A row may be a JSON list or number, and a ts may be a number, so both are checked before use.
        if not isinstance(row, dict) or not isinstance(row.get("ts"), str):
            continue
        if row.get("event") in OLLAMA_CALLS and row.get("status") not in OLLAMA_PREFLIGHT \
                and row["ts"].startswith(day):
            count += 1
    return count


def status_line(project: Path, tool: str, letters: list[str], now: float | None = None) -> str:
    """U147: one line for the user inside `tool`'s own app: new letters, and whether the other two work right now.

    It carries states, never ages, so it changes only when a letter arrives or a tool starts or stops; the hook
    shows it only then (`line_is_new`). The line goes to the user (Claude/Codex `systemMessage`), not to the model.
>>>>>>> REPLACE

===EDIT: v7_harness/coord/board.py===
<<<<<<< SEARCH
    working["antigravity"] = any(row["working"] for row in agy_conversations(moment))
    words = {"codex": _state_word(working["codex"]), "claude": _recent_word(working["claude"]),
             "antigravity": _recent_word(working["antigravity"], everywhere=True)}
    others = " · ".join(f"{NAMES[name]} {words[name]}" for name in working if name != tool)
    mail = f"📬 새 편지 {len(letters)}통: {letters[0][:50]} | " if letters else ""
    return f"[UAOS] {mail}{others}"


def line_is_new(project: Path, tool: str, line: str) -> bool:
    """Show the in-app line once per change: the last shown line per tool lives beside the presence records."""
    marker = project / ".coord" / "presence" / f"user_line_{tool}.txt"
=======
    working["antigravity"] = any(row["working"] for row in agy_conversations(moment))
    words = {"codex": _state_word(working["codex"]), "claude": _recent_word(working["claude"]),
             "antigravity": _recent_word(working["antigravity"], everywhere=True)}
    others = " · ".join(f"{NAMES[name]} {words[name]}" for name in working if name != tool)
    mail = f"📬 새 편지 {len(letters)}통: {letters[0][:50]} | " if letters else ""
    from v7_harness.coord.agy_dispatch import answered_today

    calls = ollama_calls_today(moment)
    ollama = f"올라마 오늘 {calls}회" if calls < OLLAMA_STEP else f"올라마 오늘 {calls - calls % OLLAMA_STEP}회 이상"
    return f"[UAOS] {mail}{others} · {ollama} · Antigravity 답장 {len(answered_today(project, moment))}통"


def line_is_new(project: Path, tool: str, line: str) -> bool:
    """Show the in-app line once per change: the last shown line per tool lives beside the presence records."""
    marker = project / ".coord" / "presence" / f"user_line_{tool}.txt"
>>>>>>> REPLACE

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
import hashlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Iterable

from v7_harness.coord.presence import desk_label

=======
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from v7_harness.coord.presence import desk_label

>>>>>>> REPLACE

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    if event.get("invocationNum", 0) != 0:
        return ""
    letters = agy_letters(project)
    desk = ", ".join(f"{tool}={desk_label(info)}" for tool, info in presence.items())
    conversation = str(event.get("conversationId") or "")
    from .mode import mode_phrase  # U95-T

    mode = mode_phrase(project)
    fingerprint = hashlib.sha256("\n".join([conversation, desk, mode, *letters]).encode("utf-8")).hexdigest()
    seen = Path(project) / AGY_SEEN
    try:
        if seen.read_text(encoding="utf-8").strip() == fingerprint:
            return ""
    except OSError:
=======
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
>>>>>>> REPLACE

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
        seen.write_text(fingerprint, encoding="utf-8")
    except OSError:
        pass  # a hook never fails the session; the line is said again next time
    line = (f"UAOS project {Path(project).name}: desk {desk}. Antigravity conducts only while codex and claude are "
            "both LIMITED/ABSENT; otherwise it does only work orders addressed to antigravity and never judges its "
            f"own work. {mode} ")
    if letters:
        try:
            newest = json.loads((Path(project) / ".coord" / "mailbox" / "inbox" / f"{letters[0]}.json")
                                .read_text(encoding="utf-8"))["payload"].get("message", "")
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
=======
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
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                                       "nothing when there is no news (U105)")
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
    # (U47-A1b) already existed in presence.mark, only the flag was missing.
    p_coord_presence.add_argument("--lease", action="store_true", default=False,
                                  help="Record a capability lease that ordinary heartbeats cannot overwrite until --ttl")
    p_coord_presence.set_defaults(func=cmd_coord_presence)

    p_coord_watch = p_coord_subs.add_parser("watch", help="Block until a new mailbox letter for a target arrives")
    p_coord_watch.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_watch.add_argument("--target", action="append", required=True, choices=["codex", "claude", "antigravity"])
=======
                                       "nothing when there is no news (U105)")
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
    # (U47-A1b) already existed in presence.mark, only the flag was missing.
    p_coord_presence.add_argument("--lease", action="store_true", default=False,
                                  help="Record a capability lease that ordinary heartbeats cannot overwrite until --ttl")
    # U148: a hook never moves an OK Antigravity desk (Codex review); this explicit registration does.
    p_coord_presence.add_argument("--desk-thread", default=None,
                                  help="U148: record this Antigravity desktop conversation id as the user's desk")
    p_coord_presence.set_defaults(func=cmd_coord_presence)

    p_coord_watch = p_coord_subs.add_parser("watch", help="Block until a new mailbox letter for a target arrives")
    p_coord_watch.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_watch.add_argument("--target", action="append", required=True, choices=["codex", "claude", "antigravity"])
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
            print("{}")
        elif say == "agy":
            # Antigravity reads one JSON object on stdout; a skip, an error or an unchanged line prints {}.
            print(json.dumps({"injectSteps": [{"ephemeralMessage": line}]}, ensure_ascii=False) if line else "{}")

    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            agy_line,
            brief_line,
            hook_project,
=======
            print("{}")
        elif say == "agy":
            # Antigravity reads one JSON object on stdout; a skip, an error or an unchanged line prints {}.
            print(json.dumps({"injectSteps": [{"ephemeralMessage": line}]}, ensure_ascii=False) if line else "{}")

    if getattr(args, "desk_thread", None) is not None:
        from .coord.deliver import agy_desktop_conversation, register_user_desk

        # Only a conversation of the Antigravity desktop app can be the user's Antigravity desk.
        ok = args.tool == "antigravity" and agy_desktop_conversation(args.desk_thread) \
            and register_user_desk(Path(args.project), "antigravity", args.desk_thread, source="explicit")
        print(json.dumps({"ok": bool(ok), "tool": args.tool, "desk_thread": args.desk_thread}))
        return 0 if ok else 2
    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            agy_line,
            brief_line,
            hook_project,
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
            if args.tool:
                # U147-D: a human-typed prompt designates this window as the user's desk for letters. It runs before
                # mark(dispatch=True) so letters queued for the old desk go to the window the user just typed in
                # (Codex relay_48fb8d38).
                try:
                    from .coord.deliver import is_human_prompt, register_user_desk

                    event = json.loads(stdin_text) if stdin_text.strip() else {}
                    if isinstance(event, dict) and event.get("hook_event_name") == "UserPromptSubmit" \
                            and is_human_prompt(event.get("prompt")):
                        register_user_desk(project, args.tool, hook_session(stdin_text) or "",
                                           source="UserPromptSubmit")
                except Exception:  # noqa: BLE001 - a hook never fails the session
                    pass
            if args.tool and args.state:
                # U58: the hook payload names its session, so one session ending leaves the others at the desk.
                # U134: a turn start clears a stale LIMITED/ABSENT lease; an ACTIVE beat sends queued letters.
=======
            if args.tool:
                # U147-D: a human-typed prompt designates this window as the user's desk for letters. It runs before
                # mark(dispatch=True) so letters queued for the old desk go to the window the user just typed in
                # (Codex relay_48fb8d38).
                try:
                    from .coord.deliver import agy_desktop_conversation, is_human_prompt, register_user_desk

                    event = json.loads(stdin_text) if stdin_text.strip() else {}
                    if isinstance(event, dict) and event.get("hook_event_name") == "UserPromptSubmit" \
                            and is_human_prompt(event.get("prompt")):
                        register_user_desk(project, args.tool, hook_session(stdin_text) or "",
                                           source="UserPromptSubmit")
                    elif args.tool == "antigravity" and isinstance(event, dict) \
                            and event.get("invocationNum", 0) == 0 \
                            and agy_desktop_conversation(event.get("conversationId")):
                        # U148: Antigravity has no UserPromptSubmit, and nothing in its PreInvocation payload proves
                        # a human turn (Codex review: subagents, restarts and continuations look the same), so the
                        # hook never writes the desk; coord presence --desk-thread does (U148-C2). The key names
                        # (never values) are the evidence a future human-origin field would need.
                        keys = project / ".coord" / "presence" / "agy_hook_keys.json"
                        keys.parent.mkdir(parents=True, exist_ok=True)
                        keys.write_text(json.dumps(sorted(event)), encoding="utf-8")
                except Exception:  # noqa: BLE001 - a hook never fails the session
                    pass
            if args.tool and args.state:
                # U58: the hook payload names its session, so one session ending leaves the others at the desk.
                # U134: a turn start clears a stale LIMITED/ABSENT lease; an ACTIVE beat sends queued letters.
>>>>>>> REPLACE
