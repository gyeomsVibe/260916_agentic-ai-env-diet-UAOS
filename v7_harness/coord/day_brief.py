"""U213: the day briefing 윤겸스 sees when a tool opens on a UAOS project.

Receipt 2026-10-18: opening the three tools told 윤겸스 nothing about where the work stood, so each day began with a
typed "진행상황을 브리핑해라 / 현재 UAOS-RSI 버전은? / 다음 수행계획은?". The briefing answers those three from local
files at 0 paid tokens: the installed runtime version and the newest merged PR, the master schedule's progress and
blocks, the desk, and the step `coord next` gives this tool. Claude Code and Codex show a hook's `systemMessage` to the
user, not the model (code.claude.com/docs/en/hooks, learn.chatgpt.com/docs/hooks). Antigravity's user-visible hook
field is UNKNOWN, so only its registered user desk is told to open its next reply with the briefing.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

# Four lines (version, progress, desk, next), each cut at LINE_CHARS so the box reads at one glance.
LINE_CHARS = 120
SHOWN_IDS = 3  # card ids named per list; the rest is a count
STATE_WORDS = {"ACTIVE": "활동", "LIMITED": "한도", "ABSENT": "부재", "UNKNOWN": "미확인"}
NAMES = {"codex": "Codex", "claude": "Claude", "antigravity": "Antigravity"}
# One marker file per tool session (.coord/presence/ is git-ignored). Claude runs the project and the global
# SessionStart hook in parallel; an exclusive create lets exactly one of them show the briefing.
SEEN_DIR = Path(".coord") / "presence" / "day_brief"
MERGE_REFS = ("origin/main", "HEAD")  # the main checkout may sit on a feature branch


def runtime_version(home: Path) -> str:
    try:
        version = json.loads((Path(home) / ".uaos" / "runtime" / "current.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError, TypeError):
        version = None
    if not isinstance(version, str) or not version:
        return "미확인"
    base, _, digest = version.partition("-")
    return f"{base}-{digest[:7]}" if digest else base


def last_merge(root: Path) -> str:
    for ref in MERGE_REFS:
        try:
            done = subprocess.run(["git", "-C", str(root), "log", "-1", "--merges", "--format=%cs%x09%s", ref],
                                  capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        except (OSError, subprocess.SubprocessError):
            return ""
        day, _, subject = done.stdout.strip().partition("\t")
        if done.returncode == 0 and subject:
            number = next((word for word in subject.split() if word.startswith("#")), "")
            branch = subject.split(" from ", 1)[1].split()[0].rsplit("/", 1)[-1] if " from " in subject else ""
            return " ".join(part for part in (number, branch, f"({day[5:]})") if part)
    return ""


def read_phases(path: Path) -> list[dict[str, Any]] | None:
    try:
        return [p for p in json.loads(Path(path).read_text(encoding="utf-8"))["phases"] if isinstance(p, dict)]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def blocked_cards(phases: list[dict[str, Any]]) -> list[str]:
    return [f"{p.get('phase_id')}({p.get('owner_tool')})" for p in phases if p.get("state") == "BLOCKED"]


def schedule_progress(phases: list[dict[str, Any]] | None) -> str:
    if phases is None:
        return "일정 미확인"
    states = [str(p.get("state")) for p in phases]
    done = sum(1 for state in states if state.startswith("DONE"))
    blocked = blocked_cards(phases)
    parked = states.count("PARKED")
    parts = [f"일정 {done}/{len(states)} 완료"]
    if len(states) - done - len(blocked) - parked:
        parts.append(f"진행 {len(states) - done - len(blocked) - parked}")
    if blocked:
        parts.append(f"막힘 {len(blocked)}")
    if parked:
        parts.append(f"보류 {parked}")
    return " · ".join(parts)


def desk_words(presence: dict[str, Any]) -> str:
    from .presence import desk_label

    words = []
    for tool, info in presence.items():
        label = desk_label(info)
        words.append(f"{NAMES.get(tool, tool)} {STATE_WORDS.get(label, label)}")
    return " · ".join(words)


# The reasons next_step gives in English, said in Korean; an unknown reason is shown as given.
WAIT_WORDS = (("SCHEDULE_MISSING", "일정 파일 없음"), ("review stack", "Codex 판정 대기 상한"),
              ("claimed", "다른 세션이 진행 중"), ("unreadable", "일정 읽기 실패"))


def next_words(step: dict[str, Any], blocked: list[str]) -> str:
    state = step.get("state")
    if state == "NEXT":
        return f"{step.get('card')} 착수 (이 도구 차례)"
    if state == "HANDOFF":
        return f"{step.get('card')} — {NAMES.get(step.get('owner'), step.get('owner'))} 차례"
    if state == "HUMAN":
        return "사람 확인 필요: " + ", ".join(str(item) for item in (step.get("items") or [])[:SHOWN_IDS])
    if state == "DONE":
        return "일정 완료 — 새 카드 없음"
    text = "바로 착수할 카드 없음"
    if blocked:
        text += f" — 막힘 해소가 먼저: {', '.join(blocked[:SHOWN_IDS])}"
    reason = str(step.get("code") or step.get("reason") or "")
    word = next((korean for key, korean in WAIT_WORDS if key in reason), reason)
    return text + (f" ({word})" if word else "")


def day_brief(project: Path, tool: str | None, presence: dict[str, Any], home: Path | None = None) -> str:
    from .next_card import coord_root, next_step, schedule_path

    project = Path(project)
    head = f"[UAOS-RSI 브리핑] 버전 {runtime_version(Path.home() if home is None else home)}"
    merge = last_merge(coord_root(project))
    if merge:
        head += f" · 최근 병합 {merge}"
    inbox = project / ".coord" / "mailbox" / "inbox"
    wakes = len(list(inbox.glob("wake_*.json"))) if inbox.is_dir() else 0
    phases = read_phases(schedule_path(project))
    progress = f"진행: {schedule_progress(phases)}" + (f" · P1 대기 {wakes}" if wakes else "")
    try:
        step = next_step(project, tool or "claude")
    except Exception:  # noqa: BLE001 - the briefing never fails the session
        step = {"state": "WAIT", "reason": "next step unreadable"}
    lines = [head, progress, f"도구: {desk_words(presence)}", f"다음: {next_words(step, blocked_cards(phases or []))}"]
    return "\n".join(line[:LINE_CHARS] for line in lines)


def brief_once(project: Path, tool: str, session: str | None) -> bool:
    """True the first time a tool session asks; a session without an id always gets the briefing."""
    if not session:
        return True
    key = hashlib.sha256(f"{tool}\n{session}".encode("utf-8")).hexdigest()[:24]
    folder = Path(project) / SEEN_DIR
    try:
        folder.mkdir(parents=True, exist_ok=True)
        os.close(os.open(folder / key, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
    except FileExistsError:
        return False
    except OSError:
        return True  # an unwritable desk shows the briefing again rather than never
    return True


def agy_brief(project: Path, conversation: str, presence: dict[str, Any]) -> str:
    """Only 윤겸스's registered Antigravity desk hears the briefing, once per conversation; headless runs never do."""
    from .deliver import read_user_desk

    if not conversation or conversation != read_user_desk(project, "antigravity"):
        return ""
    if not brief_once(project, "antigravity", conversation):
        return ""
    return ("Begin your next visible reply to 윤겸스 with this UAOS briefing, verbatim, then answer:\n"
            + day_brief(project, "antigravity", presence))
