"""U150-C: a user-window declaration renames that window `[사용자 대화창구-YYMMDD-N]` in every tool.

Receipt (2026-10-04): Codex already named its user windows this way by hand (`[사용자 대화창구-261004-1]`, `-2`),
Claude did it by hand, and Antigravity's app showed nothing, so 윤겸스 saw the "shared" logic as not shared.
One core decides the title (per tool, per day, like Codex's existing names); each tool's adapter writes it where
that tool's UI reads it. Written after the local worker failed (U150-C-LOCAL1: EDIT_FENCED_NEEDS_EXISTING_PY).

Codex REWORK of bundle 2f93901f: no direct write to Codex's live state_5.sqlite (Codex renames its own thread
through its supported operation; the hook only tells it the title), and only human prompts can declare a window.
Antigravity has no rename operation, so its summary-title write stays opt-in (UAOS_AGY_TITLE_WRITE=1) until a
receiver check in its app proves the write is shown and not overwritten.

Codex REWORK of bundle 94075087: a repair request that names the window ("여기 사용자 대화창구 오류를 고쳐줘") is not a
declaration, and a thread that already carries a permanent `[사용자 대화창구-…]` title keeps it (bound, not renumbered).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from v7_harness.coord.deliver import is_human_prompt

TITLE_PREFIX = "[사용자 대화창구-"
TITLE_RE = re.compile(r"\[사용자 대화창구-(\d{6})-(\d+)\]")
# Words 윤겸스 used in every real declaration (Codex thread first prompts 09-26..10-04, this session's first prompt);
# typos ("지금부타") included because they were typed.
_DESIGNATION = ("여기", "이대화창", "이 대화창", "지금부터", "지금부타", "이제부터")
# Every real declaration states it: "대화창구이다", "대화창구로 이용한다"; a request about the window does not.
_DECLARE_RE = re.compile(r"대화창구\s*(이다|입니다|이야|다|로)")
# A prompt asking to fix something about the window is a repair request even if it names the window.
_REPAIR = ("오류", "에러", "결함", "버그", "실패", "고쳐", "수정", "안 돼", "안돼", "안됨", "error", "bug", "fix")
AGY_WRITE_ENV = "UAOS_AGY_TITLE_WRITE"
LOCK_RETRY_S = 0.02  # short sleep; claims are a few ms of file I/O
LOCK_WAIT_S = 10.0  # a hook must not hang a session; 10 s is far beyond 8 parallel claims


def is_declaration(text) -> bool:
    if not is_human_prompt(text) or "대화창구" not in text or TITLE_PREFIX in text:
        return False  # a "[사용자 대화창구-…]" mention refers to an existing window, it does not open one
    # U159: one prompt can declare the window and then list requirements that name errors (Codex relay_89ccebf3);
    # a declaration is one sentence, so a repair word only rejects the sentence it is in.
    for sentence in re.split(r"[\n.!?。]+", text):
        if (_DECLARE_RE.search(sentence) and any(word in sentence for word in _DESIGNATION)
                and not any(word in sentence.lower() for word in _REPAIR)):
            return True
    return False


def _presence(project: Path) -> Path:
    return Path(project) / ".coord" / "presence"


def claim(project: Path, tool: str, thread: str, *, now: datetime | None = None,
          existing: list[str] | None = None, current: str | None = None) -> dict:
    """`current` is the thread's title in its own tool; a permanent one is bound as is, never renumbered."""
    folder = _presence(project)
    folder.mkdir(parents=True, exist_ok=True)
    record_path, lock = folder / "user_windows.json", folder / "user_windows.lock"
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            os.close(os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"user window lock busy: {lock}")
            time.sleep(LOCK_RETRY_S)
    try:
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            record = {}
        record = record if isinstance(record, dict) else {}
        entries = record.setdefault(tool, [])
        for entry in entries:
            if entry.get("thread") == thread:
                return {"title": entry["title"], "new": False, "tool": tool, "thread": thread}
        date = (now or datetime.now()).strftime("%y%m%d")
        kept = TITLE_RE.search(current or "")
        numbers = [0]
        for title in [e.get("title", "") for e in entries] + list(existing or []):
            match = TITLE_RE.search(title or "")
            if match and match.group(1) == date:
                numbers.append(int(match.group(2)))
        title = kept.group(0) if kept else f"{TITLE_PREFIX}{date}-{max(numbers) + 1}]"
        entries.append({"thread": thread, "title": title, "date": kept.group(1) if kept else date, "at": time.time()})
        temp = record_path.with_name(f"{record_path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
        temp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp, record_path)
        return {"title": title, "new": not kept, "tool": tool, "thread": thread}
    finally:
        lock.unlink(missing_ok=True)


def _codex_db() -> Path:
    return Path.home() / ".codex" / "state_5.sqlite"


def rename_agy(conversation_id: str, title: str, *, db: Path | None = None, backup_dir: Path | None = None) -> bool:
    # The Antigravity app lists conversations from this summary table (titles seen there match its sidebar).
    path = Path(db or Path.home() / ".gemini" / "antigravity" / "conversation_summaries.db")
    if not path.is_file():
        return False
    if backup_dir is not None:  # global rule: copy every overwritten file to .work/backup_<date>/ first
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, Path(backup_dir) / f"conversation_summaries_{int(time.time() * 1000)}.db")
    try:
        con = sqlite3.connect(path, timeout=5)
        try:
            cur = con.execute("UPDATE conversation_summaries SET title=? WHERE conversation_id=?",
                              (title, conversation_id))
            con.commit()
            return cur.rowcount == 1
        finally:
            con.close()
    except sqlite3.Error:
        return False


def _read_one(uri: str, sql: str, arg: str) -> str | None:
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            row = con.execute(sql, (arg,)).fetchone()
            return row[0] if row else None
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _current_title(tool: str, thread: str) -> str | None:
    """Read-only lookup of the thread's own title: Codex thread name, Antigravity summary title."""
    if tool == "codex":
        return _read_one(f"{_codex_db().as_uri()}?mode=ro", "SELECT name FROM threads WHERE id=?", thread)
    if tool == "antigravity":
        db = Path.home() / ".gemini" / "antigravity" / "conversation_summaries.db"
        if db.is_file():
            return _read_one(f"{db.as_uri()}?mode=ro",
                             "SELECT title FROM conversation_summaries WHERE conversation_id=?", thread)
    return None


def _codex_names() -> list[str]:
    """Read-only (`mode=ro`): today's existing Codex titles seed the number so Codex's hand-made -1, -2 continue."""
    try:
        con = sqlite3.connect(f"{_codex_db().as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            return [row[0] for row in con.execute(
                "SELECT name FROM threads WHERE name LIKE '[사용자 대화창구-%'") if row[0]]
        finally:
            con.close()
    except sqlite3.Error:
        return []


def on_prompt(project: Path, tool: str, thread: str, prompt, *, now: datetime | None = None,
              current: str | None = None) -> str:
    if not thread or not is_declaration(prompt):
        return ""
    current = current if current is not None else _current_title(tool, thread)
    existing = _codex_names() if tool == "codex" else []
    got = claim(project, tool, thread, now=now, existing=existing, current=current)
    title = got["title"]
    if TITLE_RE.search(current or "") and TITLE_RE.search(current).group(0) == title:
        return ""  # the window already shows its permanent title; nothing to rename
    if tool == "codex":
        return f"USER WINDOW: rename this Codex thread now to {title} with your thread rename operation."
    if tool == "antigravity":
        date = (now or datetime.now()).strftime("%Y%m%d")
        if os.environ.get(AGY_WRITE_ENV) == "1":
            rename_agy(thread, title, backup_dir=Path(project) / ".work" / f"backup_{date}")
        return f"USER WINDOW: this Antigravity conversation is {title}; start your first reply line with it."
    if tool == "claude":
        return f'USER WINDOW: rename this session now with set_session_title(session_id="self", title="{title}").'
    return ""
