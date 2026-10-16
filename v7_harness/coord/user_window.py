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

from v7_harness.coord.deliver import is_human_prompt, typed_prompt

TITLE_PREFIX = "[사용자 대화창구-"
TITLE_RE = re.compile(r"\[사용자 대화창구-(\d{6})-(\d+)\]")
# Words 윤겸스 used in every real declaration (Codex thread first prompts 09-26..10-04, this session's first prompt);
# typos ("지금부타") included because they were typed.
_DESIGNATION = ("여기", "이대화창", "이 대화창", "지금부터", "지금부타", "이제부터")
# Every real declaration states it: "대화창구이다", "대화창구로 이용한다"; a request about the window does not.
_DECLARE_RE = re.compile(r"대화창구\s*(이다|입니다|이야|다|로)")
# A prompt asking to fix something about the window is a repair request even if it names the window.
_REPAIR = ("오류", "에러", "결함", "버그", "실패", "고쳐", "수정", "안 돼", "안돼", "안됨", "error", "bug", "fix")
AGY_WRITE_ENV = "UAOS_AGY_TITLE_WRITE"  # U207: no longer read; the write is on by default with backup and readback
_AGY_ID = re.compile(r"[A-Za-z0-9-]{1,64}")  # real ids are UUIDs; anything else never reaches a path or SQL
_PB_TITLE = re.compile(r'title:"((?:[^"\\]|\\.)*)"')
AGY_LOCK_WAIT_S = 5.0  # the app holds its write lock for milliseconds; 5 s stays well inside the 10 s hook timeout
# U207: one declaration emit plus two re-issues. A rename that three real prompts did not land is not transient;
# it is recorded BLOCKED instead of being asked forever (Antigravity audit G1).
MAX_EMITS = 3
LOCK_RETRY_S = 0.02  # short sleep; claims are a few ms of file I/O
LOCK_WAIT_S = 10.0  # a hook must not hang a session; 10 s is far beyond 8 parallel claims


def is_declaration(text) -> bool:
    text = typed_prompt(text)  # U176: the harness's own leading reminder is not what was typed
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
    from contextlib import ExitStack
    from .stream import _exclusive
    stack = ExitStack()
    stack.enter_context(_exclusive(lock))
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
        stack.close()


def _codex_db() -> Path:
    return Path.home() / ".codex" / "state_5.sqlite"


def _pb_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _agy_annotation_title(path: Path) -> str | None:
    try:
        match = _PB_TITLE.search(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None
    return re.sub(r"\\(.)", r"\1", match.group(1)) if match else None


def rename_agy_status(conversation_id: str, title: str, *, db: Path | None = None,
                      annotations_dir: Path | None = None, backup_dir: Path | None = None,
                      timeout: float = AGY_LOCK_WAIT_S) -> str:
    """U207: the app's sidebar reads the summary row (title, preview) and annotations/<id>.pbtxt; 10-05..10-15 desks
    renamed through all three stayed renamed. RENAMED only when all three read back the title; else a named failure."""
    if not isinstance(conversation_id, str) or not _AGY_ID.fullmatch(conversation_id):
        return "INVALID_ID"  # the id becomes a file name and an SQL argument
    path = Path(db or Path.home() / ".gemini" / "antigravity" / "conversation_summaries.db")
    if not path.is_file():
        return "NO_STORE"
    ann_dir = Path(annotations_dir) if annotations_dir else path.parent / "annotations"
    ann = ann_dir / f"{conversation_id}.pbtxt"
    stamp = time.time_ns()
    try:
        con = sqlite3.connect(path, timeout=timeout)
    except sqlite3.Error:
        return "DB_ERROR"
    temp = None
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(conversation_summaries)").fetchall()]
        if not con.execute("SELECT 1 FROM conversation_summaries WHERE conversation_id=?",
                           (conversation_id,)).fetchone():
            return "NOT_FOUND"
        try:
            con.execute("BEGIN IMMEDIATE")  # the write lock first: no app commit lands between backup and update
        except sqlite3.OperationalError:
            return "DB_LOCKED"
        if backup_dir is not None:  # global rule: copy every overwritten file to .work/backup_<date>/ first
            Path(backup_dir).mkdir(parents=True, exist_ok=True)
            # Under our RESERVED lock no other writer can commit, so the main file plus any WAL file is one state.
            # (Python's online backup API retries a busy source forever and would hang the hook.)
            for suffix in ("", "-wal"):
                source = Path(f"{path}{suffix}")
                if source.is_file():
                    shutil.copy2(source, Path(backup_dir) / f"conversation_summaries_{stamp}.db{suffix}")
            if ann.is_file():
                shutil.copy2(ann, Path(backup_dir) / f"{conversation_id}_{stamp}.pbtxt")
        # Codex REVISE relay_f3895ddb: a missing annotation store was reported RENAMED unread; write and read it always.
        ann_dir.mkdir(parents=True, exist_ok=True)
        old = ann.read_text(encoding="utf-8") if ann.is_file() else ""
        line = f'title:"{_pb_escape(title)}"'
        new = _PB_TITLE.sub(lambda _m: line, old, count=1) if _PB_TITLE.search(old) else f"{line}  {old}"
        temp = ann_dir / f".{conversation_id}.{stamp}.tmp"
        temp.write_text(new if new.endswith("\n") else new + "\n", encoding="utf-8")
        sets = "title=?, preview=?" if "preview" in cols else "title=?"
        args = (title, title) if "preview" in cols else (title,)
        con.execute(f"UPDATE conversation_summaries SET {sets} WHERE conversation_id=?", args + (conversation_id,))
        con.commit()
        if temp is not None:
            try:
                os.replace(temp, ann)  # atomic: the app never reads a half-written annotation
                temp = None
            except OSError:
                return "PARTIAL"  # the summary row changed, the annotation did not: never reported as renamed
        got = con.execute(f"SELECT {'title, preview' if 'preview' in cols else 'title, title'} "
                          "FROM conversation_summaries WHERE conversation_id=?", (conversation_id,)).fetchone()
        return "RENAMED" if got and got[0] == got[1] == _agy_annotation_title(ann) == title else "PARTIAL"
    except (sqlite3.Error, OSError):
        try:
            con.rollback()
        except sqlite3.Error:
            pass
        return "DB_ERROR"
    finally:
        if temp is not None:
            try:
                temp.unlink()
            except OSError:
                pass
        con.close()


def rename_agy(conversation_id: str, title: str, **kwargs) -> bool:
    return rename_agy_status(conversation_id, title, **kwargs) == "RENAMED"


def _claude_sessions_root() -> Path:
    appdata = os.environ.get("APPDATA")  # Windows desktop app; macOS keeps the same folder under Application Support
    base = Path(appdata) / "Claude" if appdata else Path.home() / "Library" / "Application Support" / "Claude"
    return base / "claude-code-sessions"


def _claude_title(thread: str, *, root: Path | None = None) -> str | None:
    """Read-only: the desktop app keeps one JSON per session with `cliSessionId` (the hook's session_id) and `title`."""
    folder = Path(root) if root else _claude_sessions_root()
    if not thread or not folder.is_dir():
        return None
    for path in folder.glob("*/*/local_*.json"):
        try:
            text = path.read_text(encoding="utf-8")
            if thread not in text:
                continue  # cheap filter: most files never mention this session
            data = json.loads(text)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("cliSessionId") == thread:
            title = data.get("title")
            return title if isinstance(title, str) else None
    return None


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


def _agy_title(thread: str, *, base: Path | None = None) -> str | None:
    """Read-only: the title only when the summary title, preview and annotation agree; any disagreement or a
    missing store is UNKNOWN (None), so a PARTIAL rename is repaired instead of converged (Codex relay_f3895ddb)."""
    base = Path(base) if base else Path.home() / ".gemini" / "antigravity"
    db = base / "conversation_summaries.db"
    if not db.is_file() or not isinstance(thread, str) or not _AGY_ID.fullmatch(thread):
        return None
    try:
        con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True, timeout=5)
        try:
            cols = [r[1] for r in con.execute("PRAGMA table_info(conversation_summaries)").fetchall()]
            row = con.execute(f"SELECT title, {'preview' if 'preview' in cols else 'title'} "
                              "FROM conversation_summaries WHERE conversation_id=?", (thread,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return None
    shown = _agy_annotation_title(base / "annotations" / f"{thread}.pbtxt")
    return row[0] if row and row[0] == row[1] == shown else None


def _current_title(tool: str, thread: str) -> str | None:
    """Read-only lookup of the thread's own title: Codex thread name, Antigravity summary title."""
    if tool == "codex":
        return _read_one(f"{_codex_db().as_uri()}?mode=ro", "SELECT name FROM threads WHERE id=?", thread)
    if tool == "antigravity":
        return _agy_title(thread)
    if tool == "claude":
        return _claude_title(thread)
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


def _shows(current: str | None, title: str) -> bool:
    match = TITLE_RE.search(current or "")
    return bool(match) and match.group(0) == title  # None (no readback) is UNKNOWN, never a match


def _entry_change(project: Path, tool: str, thread: str, change):
    """Apply `change(entry)` to this thread's claimed entry under the claim lock; None when the thread is no desk."""
    folder = _presence(project)
    record_path = folder / "user_windows.json"
    if not record_path.is_file():
        return None  # nothing claimed: a worker or headless session never creates a desk here
    from .stream import _exclusive
    with _exclusive(folder / "user_windows.lock"):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        for entry in (record.get(tool) or []) if isinstance(record, dict) else []:
            if entry.get("thread") == thread:
                result = change(entry)
                temp = record_path.with_name(f"{record_path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
                temp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
                os.replace(temp, record_path)
                return result
    return None


def _converge(entry: dict) -> None:
    entry.update(converged=True, title_state="CONVERGED")


def _take_emit(entry: dict) -> bool:
    """One emit from the bounded budget; concurrent hooks count under the lock, so the cap holds in parallel."""
    if entry.get("converged"):
        return False
    if int(entry.get("emits") or 0) >= MAX_EMITS:
        entry["title_state"] = "BLOCKED"
        return False
    entry["emits"] = int(entry.get("emits") or 0) + 1
    entry["title_state"] = "PENDING"
    return True


def _instruction(project: Path, tool: str, thread: str, title: str, now: datetime | None) -> str:
    if tool == "codex":
        return f"USER WINDOW: rename this Codex thread now to {title} with your thread rename operation."
    if tool == "antigravity":
        date = (now or datetime.now()).strftime("%Y%m%d")
        status = rename_agy_status(thread, title, backup_dir=Path(project) / ".work" / f"backup_{date}")
        note = "" if status == "RENAMED" else f" (title store write: {status})"
        return f"USER WINDOW: this Antigravity conversation is {title}; start your first reply line with it.{note}"
    if tool == "claude":
        return f'USER WINDOW: rename this session now with set_session_title(session_id="self", title="{title}").'
    return ""


def reconcile(project: Path, tool: str, thread: str, *, now: datetime | None = None) -> str:
    """U207: on every real prompt of a claimed desk, re-issue the rename until the tool's own store shows it.
    A lost hook output (timeout, dropped line) is therefore repaired by the next prompt, not lost for good."""
    try:
        record = json.loads((_presence(project) / "user_windows.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    entry = next((e for e in (record.get(tool) or []) if e.get("thread") == thread), None) \
        if isinstance(record, dict) else None
    if not entry or entry.get("converged") or entry.get("title_state") == "BLOCKED":
        return ""  # converged desks cost no readback at all
    title = entry["title"]
    if _shows(_current_title(tool, thread), title):
        _entry_change(project, tool, thread, _converge)
        return ""
    if not _entry_change(project, tool, thread, _take_emit):
        return ""
    return _instruction(project, tool, thread, title, now)


def on_prompt(project: Path, tool: str, thread: str, prompt, *, now: datetime | None = None,
              current: str | None = None) -> str:
    if not thread:
        return ""
    if not is_declaration(prompt):
        return reconcile(project, tool, thread, now=now)
    current = current if current is not None else _current_title(tool, thread)
    existing = _codex_names() if tool == "codex" else []
    got = claim(project, tool, thread, now=now, existing=existing, current=current)
    title = got["title"]
    if _shows(current, title):
        _entry_change(project, tool, thread, _converge)
        return ""  # the window already shows its permanent title; nothing to rename

    def restart(entry: dict) -> bool:  # a fresh declaration opens a fresh bounded budget
        entry.update(converged=False, emits=0, title_state="PENDING")
        return _take_emit(entry)

    _entry_change(project, tool, thread, restart)
    return _instruction(project, tool, thread, title, now)
