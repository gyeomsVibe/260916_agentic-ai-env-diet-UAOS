"""U15 S2: 조율 사건 스트림.

세 도구(Codex, Antigravity, Claude)가 한 프로젝트에서 각자 수행한 작업을 한 곳에 모으기 위한
append-only 기록이다. 사람이 읽는 메모가 아니라 Codex가 판정에 쓰는 사건과 증거를 담는다.

설계 근거는 `.coord/tasks/U15-coordination-stream.md`.
- 한 줄 = 한 사건(JSONL). 수정·삭제는 하지 않는다.
- 판정(`VERDICT`)은 Codex만 기록한다. 실행 결과(`RUN`)와 판정에는 증거(명령·종료 코드)를 요구한다.
- 요약은 200자 상한이고, 긴 내용은 `refs` 경로로 보낸다. 토큰을 아끼기 위한 상한이다.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any, Iterable

ACTORS = ("codex", "antigravity", "claude")
KINDS = ("PLAN", "RUN", "VERDICT", "BLOCKED", "HANDOFF", "NOTE")
EVIDENCE_REQUIRED_KINDS = ("RUN", "VERDICT")
VERDICT_ACTOR = "codex"
SUMMARY_MAX = 200

# 비밀값이 사건 요약을 타고 다른 도구의 대화창으로 흘러가지 않게 막는다.
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(api[_-]?key|secret|token|password|passwd|credential)\b\s*[:=]"),
    re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


class StreamRejected(ValueError):
    """사건이 계약을 어겼을 때. 기록하지 않고 거부한다."""


class StreamBusy(RuntimeError):
    """잠금을 얻지 못했을 때. 조용히 덮어쓰지 않고 실패로 알린다."""


_LOCAL_LOCK = threading.Lock()
LOCK_TIMEOUT_S = 10.0
LOCK_STALE_S = 60.0


@contextmanager
def _exclusive(lock_path: Path):
    """스트림 전체 쓰기를 프로세스·스레드 양쪽에서 직렬화한다.

    Windows 에서는 `O_APPEND` 동시 쓰기가 원자적이지 않아 줄이 통째로 사라졌다(실측).
    잠금은 날짜 파일이 아니라 스트림 폴더 하나에 건다. 날짜 파일마다 걸면 자정 전후나
    보관(롤오버) 중에 다른 파일을 쓰는 작업을 막지 못해 사건이 사라진다.
    60초 넘은 잠금은 죽은 프로세스의 것으로 보고 회수한다.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    with _LOCAL_LOCK:
        handle = None
        while handle is None:
            try:
                handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except (FileExistsError, PermissionError):
                # Windows 는 삭제 대기 중인 잠금 파일을 열면 PermissionError 를 낸다(8프로세스 경합에서
                # 300회당 3~11건 실측). 이것도 "다른 쪽이 잡고 있음"이므로 기다렸다 다시 시도한다.
                try:
                    age = time.time() - lock_path.stat().st_mtime
                except (FileNotFoundError, PermissionError):
                    time.sleep(0.01)
                    continue
                if age > LOCK_STALE_S:
                    lock_path.unlink(missing_ok=True)
                    continue
                if time.monotonic() > deadline:
                    raise StreamBusy("STREAM_LOCK_TIMEOUT")
                time.sleep(0.01)
        try:
            yield
        finally:
            os.close(handle)
            lock_path.unlink(missing_ok=True)


@dataclass(frozen=True)
class Event:
    id: str
    ts: str
    actor: str
    kind: str
    step: str
    summary: str
    refs: tuple[str, ...]
    evidence: dict[str, Any]

    def to_json(self) -> str:
        payload = {
            "id": self.id,
            "ts": self.ts,
            "actor": self.actor,
            "kind": self.kind,
            "step": self.step,
            "summary": self.summary,
            "refs": list(self.refs),
            "evidence": self.evidence,
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def stream_dir(project: Path) -> Path:
    """U84: one stream per repository. A linked worktree's events belong to the main checkout's desk (U59).

    Seen 2026-09-29: `coord log` in `.claude/worktrees/<name>` wrote to that worktree's gitignored stream while
    `coord deliver` from the same folder reached the desk, so 76 acting events never reached the desk's codex_brief.
    """
    from .hook_context import shared_desk

    return shared_desk(Path(project)) / ".coord" / "stream"


def stream_lock(project: Path) -> Path:
    """스트림 폴더 전체를 덮는 단일 잠금 파일."""
    return stream_dir(project) / ".stream.lock"


def stream_path(project: Path, *, now: datetime | None = None) -> Path:
    moment = now or datetime.now().astimezone()
    return stream_dir(project) / f"{moment:%Y-%m-%d}.jsonl"


def _check_secrets(text: str) -> None:
    for pattern in SECRET_PATTERNS:
        if pattern.search(text):
            raise StreamRejected("SECRET_IN_SUMMARY")


def _normalize_refs(refs: Iterable[str] | None) -> tuple[str, ...]:
    normalized: list[str] = []
    for ref in refs or ():
        if not isinstance(ref, str) or not ref.strip():
            raise StreamRejected("INVALID_REF")
        candidate = ref.replace("\\", "/").strip()
        # PureWindowsPath: a drive ref (C:/...) escapes the project on the Windows readers even if written on POSIX.
        if candidate.startswith("/") or ".." in Path(candidate).parts or PureWindowsPath(candidate).drive:
            raise StreamRejected("INVALID_REF")
        if candidate not in normalized:
            normalized.append(candidate)
    return tuple(normalized)


def _validate(actor: str, kind: str, step: str, summary: str, evidence: dict[str, Any] | None) -> dict[str, Any]:
    if actor not in ACTORS:
        raise StreamRejected("UNKNOWN_ACTOR")
    if kind not in KINDS:
        raise StreamRejected("UNKNOWN_KIND")
    if kind == "VERDICT" and actor != VERDICT_ACTOR:
        raise StreamRejected("VERDICT_ACTOR_NOT_ALLOWED")
    if not step or not step.strip():
        raise StreamRejected("MISSING_STEP")
    text = (summary or "").strip()
    if not text:
        raise StreamRejected("EMPTY_SUMMARY")
    if len(text) > SUMMARY_MAX:
        raise StreamRejected("SUMMARY_TOO_LONG")
    if "\n" in text or "\r" in text:
        raise StreamRejected("MULTILINE_SUMMARY")
    _check_secrets(text)

    payload = dict(evidence or {})
    if kind in EVIDENCE_REQUIRED_KINDS:
        command = payload.get("cmd")
        exit_code = payload.get("exit")
        if not isinstance(command, str) or not command.strip():
            raise StreamRejected("MISSING_EVIDENCE_CMD")
        if not isinstance(exit_code, int):
            raise StreamRejected("MISSING_EVIDENCE_EXIT")
        _check_secrets(command)
    return payload


def _next_id(existing: set[str], actor: str, moment: datetime) -> str:
    prefix = f"{moment:%Y%m%dT%H%M}-{actor}-"
    sequence = 1 + sum(1 for value in existing if value.startswith(prefix))
    while f"{prefix}{sequence:04d}" in existing:
        sequence += 1
    return f"{prefix}{sequence:04d}"


def read_events(project: Path) -> list[dict[str, Any]]:
    """스트림 전체를 시간순으로 읽는다. 깨진 줄은 조용히 건너뛰지 않고 알린다."""
    events: list[dict[str, Any]] = []
    directory = stream_dir(project)
    if not directory.is_dir():
        return events
    for path in sorted(directory.glob("*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise StreamRejected(f"CORRUPT_LINE:{path.name}:{number}") from exc
    events.sort(key=lambda event: (event.get("ts", ""), event.get("id", "")))
    return events


def archive_settled(project: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """마지막 판정까지의 사건을 보관함으로 옮긴다.

    지우지 않는다. 판정이 끝난 사건은 브리핑에서 접히지만 기록으로는 남아야 하고,
    현역 스트림은 짧게 유지해야 읽는 비용이 늘지 않는다.
    """
    moment = now or datetime.now().astimezone()
    # 읽기부터 잠금 안에서 한다. 잠금 밖에서 읽으면 그 사이에 들어온 사건을
    # 보관이 통째로 지운다(실측: 7건 중 6건 유실).
    with _exclusive(stream_lock(project)):
        events = read_events(project)
        last_verdict = -1
        for index, event in enumerate(events):
            if event.get("kind") == "VERDICT":
                last_verdict = index
        if last_verdict < 0:
            return {"archived": 0, "kept": len(events), "archive": None}

        settled = events[: last_verdict + 1]
        live = events[last_verdict + 1 :]
        directory = stream_dir(project)
        locks = sorted(directory.glob("*.jsonl"))
        if not locks:
            return {"archived": 0, "kept": 0, "archive": None}

        archive_dir = directory / "archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive_file = archive_dir / f"settled-{moment:%Y%m%dT%H%M%S}.jsonl"
        archive_file.write_text(
            "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in settled),
            encoding="utf-8",
        )
        for path in locks:
            path.unlink()
        if live:
            current = stream_path(project, now=moment)
            current.write_text(
                "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n" for event in live),
                encoding="utf-8",
            )
    # U84-F1 (Codex REJECT of U84): from a worktree the archive is on the desk, outside `project`; relative_to raised
    # after the stream was already rewritten. relpath resolves from either checkout and is unchanged for a plain one.
    return {"archived": len(settled), "kept": len(live), "archive": os.path.relpath(archive_file, project)}


def append_event(
    project: Path,
    *,
    actor: str,
    kind: str,
    step: str,
    summary: str,
    refs: Iterable[str] | None = None,
    evidence: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> Event:
    """사건 한 줄을 원자적으로 덧붙인다. 계약 위반은 기록 없이 거부한다."""
    payload = _validate(actor, kind, step, summary, evidence)
    normalized_refs = _normalize_refs(refs)
    moment = now or datetime.now().astimezone()

    path = stream_path(project, now=moment)
    path.parent.mkdir(parents=True, exist_ok=True)

    with _exclusive(stream_lock(project)):
        existing_events = read_events(project)
        existing = {event.get("id", "") for event in existing_events}
        event = Event(
            id=_next_id(existing, actor, moment),
            ts=moment.isoformat(timespec="seconds"),
            actor=actor,
            kind=kind,
            step=step.strip(),
            summary=summary.strip(),
            refs=normalized_refs,
            evidence=payload,
        )
        line = event.to_json() + "\n"
        handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(handle, line.encode("utf-8"))
        finally:
            os.close(handle)
        snapshot = [*existing_events, json.loads(line)]
        # 일이 일어난 자리에서 운용 표본을 남긴다(U15 S14). 실패해도 무시한다.
        # U84-F1 (Codex REJECT of U84): the desk and its worktrees share one samples file, so it is written under the
        # stream lock; unlocked, a concurrent Windows append lost 1 of 48 rows in 1 of 8 runs on 12 busy cores.
        from v7_harness.coord.metrics import maybe_sample

        maybe_sample(project, events=snapshot)
    return event
