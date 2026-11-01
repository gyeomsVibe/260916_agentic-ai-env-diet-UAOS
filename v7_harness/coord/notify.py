"""U15 S4: Codex 대화창으로 브리핑을 밀어 넣는 전달기.

`codex queue --thread <세션> --message <텍스트>`가 app-server의 `thread/queue/add`로 메시지를 넣고,
그 스레드를 소유한 클라이언트가 사용자 창에 "다른 작업에서 …이(가) 보냄"으로 배달한다.

여기서 지키는 것은 배달 자체가 아니라 배달의 절제다.
- 브리핑 해시가 바뀐 상태 전이에서만 한 건 보낸다(중복·루프 차단).
- 메시지는 6줄·500자 상한, 값이 아니라 경로·종료 코드만 싣는다(토큰·유출 차단).
- 보낸 기록은 커서에 남겨 같은 브리핑을 두 번 보내지 않는다.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from v7_harness.coord.brief import brief_hash
from v7_harness.coord.stream import SECRET_PATTERNS

CURSOR_PATH = Path(".work") / "coord" / "codex_notify_cursor.json"
MESSAGE_MAX_LINES = 6
MESSAGE_MAX_CHARS = 500
MIN_INTERVAL = timedelta(minutes=1)
# U290 (윤겸스 2026-11-01): no daily notice cap by default; an int re-enables it. NO_CHANGE and MIN_INTERVAL still stop floods.
DAILY_LIMIT: int | None = None
DATA_HEADER = "[DATA] from={actor} verdict_requested={verdict}"


class NotifyRefused(RuntimeError):
    """보내지 않는 편이 맞을 때. 조용히 넘기지 않고 이유를 남긴다."""


@dataclass(frozen=True)
class NotifyResult:
    sent: bool
    reason: str
    command: tuple[str, ...]
    message: str


def resolve_thread(project: Path, *, sessions_dir: Path | None = None, max_scan: int = 12) -> str:
    """이 프로젝트를 다루는 가장 최근 Codex 세션 id 를 고른다.

    스레드 id 를 손으로 넘기면 남의 작업 창에 배달될 수 있다. 세션 기록의 머리 부분에서
    프로젝트 경로와 세션 id 만 읽고, 대화 내용은 읽지 않는다. 확실하지 않으면 빈 문자열이다.
    """
    root = sessions_dir or (Path.home() / ".codex" / "sessions")
    if not root.is_dir():
        return ""
    marker = project.resolve().name
    candidates = sorted(root.rglob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in candidates[:max_scan]:
        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                head = handle.read(800)
        except OSError:
            continue
        if marker not in head:
            continue
        match = re.search(r'"session_id"\s*:\s*"([0-9a-fA-F-]{8,})"', head)
        if match:
            return match.group(1)
    return ""


def _cursor_file(project: Path) -> Path:
    return project / CURSOR_PATH


def read_cursor(project: Path) -> dict[str, Any]:
    path = _cursor_file(project)
    if not path.is_file():
        return {"last_hash": "", "last_sent_at": "", "sent_today": 0, "day": ""}
    return json.loads(path.read_text(encoding="utf-8"))


def write_cursor(project: Path, cursor: dict[str, Any]) -> None:
    path = _cursor_file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cursor, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def is_codex_absent(project: Path | None) -> bool:
    """A fresh heartbeat decides (.coord/presence/codex.json). Without one, fall back to the PLAN.md state line."""
    if project is None:
        return False
    from v7_harness.coord.presence import read as read_presence

    state = read_presence(project, "codex")["state"]
    if state in ("LIMITED", "ABSENT"):
        return True
    if state == "ACTIVE":
        return False
    plan_path = project / ".coord" / "PLAN.md"
    if not plan_path.is_file():
        return False
    try:
        content = plan_path.read_text(encoding="utf-8")
        return bool(re.search(r"codex:\s*(LIMITED|ABSENT)", content, re.IGNORECASE))
    except OSError:
        return False


def build_message(
    *,
    actor: str,
    brief_path: str,
    headline: str,
    pending: Sequence[str],
    verdict_requested: bool | None = None,
    project: Path | None = None,
) -> str:
    """Codex가 한눈에 읽고 판정으로 들어갈 수 있는 최소 메시지."""
    if verdict_requested is False:
        verdict = "no"
    elif verdict_requested is True:
        verdict = "yes"
    elif is_codex_absent(project):
        verdict = "no"
    else:
        verdict = "yes" if pending else "no"

    actor_label = "안티그래비티에서 온 대화" if actor.lower() in ("agy", "antigravity") else ("클로드에게서 온 대화" if actor.lower() == "claude" else f"{actor}에서 온 대화")
    clean_hl = headline.strip()
    if not clean_hl.startswith(f"<{actor_label}>") and not clean_hl.startswith(f"[{actor_label}]"):
        display_hl = f"[{actor_label}] {clean_hl}"
    else:
        display_hl = clean_hl

    lines = [
        DATA_HEADER.format(actor=actor, verdict=verdict),
        display_hl,
        f"브리핑: {brief_path}",
    ]
    for item in list(pending)[:2]:
        lines.append(f"판정대기: {item}")
    message = "\n".join(lines[:MESSAGE_MAX_LINES])
    if len(message) > MESSAGE_MAX_CHARS:
        message = message[: MESSAGE_MAX_CHARS - 1] + "…"
    for pattern in SECRET_PATTERNS:
        if pattern.search(message):
            raise NotifyRefused("SECRET_IN_MESSAGE")
    return message


def notify(
    project: Path,
    *,
    thread: str,
    actor: str,
    brief_text: str,
    headline: str,
    pending: Sequence[str] = (),
    brief_path: str = ".coord/codex_brief.md",
    verdict_requested: bool | None = None,
    now: datetime | None = None,
    dry_run: bool = True,
    runner: Any = None,
) -> NotifyResult:
    """상태가 바뀌었을 때만 한 건 보낸다. 기본은 드라이런이다."""
    # An explicit no-verdict event is an attendance/transport acknowledgement, not a user-visible update.
    # Stop before resolving a thread, building a message, applying rate limits, or waking a paid coordinator.
    # Meaningful progress may still use the automatic mode (`None`); callers must reserve False for ACK_ONLY.
    if verdict_requested is False:
        return NotifyResult(False, "ACK_ONLY", (), "")

    if not thread or not thread.strip():
        raise NotifyRefused("MISSING_THREAD")

    if is_codex_absent(project):
        raise NotifyRefused("CODEX_ABSENT")

    moment = now or datetime.now().astimezone()
    cursor = read_cursor(project)
    digest = brief_hash(brief_text)
    message = build_message(
        actor=actor,
        brief_path=brief_path,
        headline=headline,
        pending=pending,
        verdict_requested=verdict_requested,
        project=project,
    )
    command = ("codex", "queue", "--thread", thread, "--message", message)

    if cursor.get("last_hash") == digest:
        return NotifyResult(False, "NO_CHANGE", command, message)

    today = f"{moment:%Y-%m-%d}"
    sent_today = int(cursor.get("sent_today") or 0) if cursor.get("day") == today else 0
    if DAILY_LIMIT is not None and sent_today >= DAILY_LIMIT:
        return NotifyResult(False, "DAILY_LIMIT", command, message)

    last_sent_at = cursor.get("last_sent_at") or ""
    if last_sent_at:
        try:
            previous = datetime.fromisoformat(last_sent_at)
        except ValueError:
            previous = None
        if previous and moment - previous < MIN_INTERVAL:
            return NotifyResult(False, "RATE_LIMIT", command, message)

    if dry_run:
        return NotifyResult(False, "DRY_RUN", command, message)

    execute = runner or subprocess.run
    argv = list(command)
    if runner is None:
        # Windows 에서 `codex` 는 PATH 의 .cmd 래퍼다. shell 없이 실행하려면 실제 경로가 필요하다.
        resolved = shutil.which(argv[0])
        if not resolved:
            raise NotifyRefused("CODEX_CLI_NOT_FOUND")
        argv[0] = resolved
    completed = execute(argv, capture_output=True, text=True, timeout=60)
    if getattr(completed, "returncode", 1) != 0:
        raise NotifyRefused(f"QUEUE_FAILED:{getattr(completed, 'returncode', 'NA')}")

    write_cursor(
        project,
        {
            "last_hash": digest,
            "last_sent_at": moment.isoformat(timespec="seconds"),
            "sent_today": sent_today + 1,
            "day": today,
            "thread": thread,
        },
    )
    return NotifyResult(True, "SENT", command, message)
