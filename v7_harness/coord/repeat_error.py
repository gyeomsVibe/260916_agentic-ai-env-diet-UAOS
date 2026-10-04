"""U150-B: one user error report reaches all three tools; a repeat becomes P1 instead of a third instruction.

Receipt (2026-10-04): 윤겸스 had to tell each tool about the same failure (message-id collision, Antigravity's app
showing no change). The shared prompt hook (`coord presence --delta`, run by all three tools) records each error
report and delivers it once to each other tool's next turn, with a durable receipt per (report, tool); a repeat of
the same report is P1. Deterministic and local: keyword classification and term overlap, 0 model tokens.

Codex REWORK of bundle 2f93901f (2026-10-04) fixed here: injected relays are not reports (provenance), secret-like
prompts are stored redacted, delivery state advances only after a successful read (receipts, not a time cursor),
and delivery is proved by receipts instead of prose asking the model to relay.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from v7_harness.coord.deliver import is_human_prompt
from v7_harness.coord.mailbox import SECRET_PATTERNS as _MAILBOX_SECRETS
from v7_harness.coord.stream import SECRET_PATTERNS as _STREAM_SECRETS

# Both lists the mailbox and the event stream refuse (stream's misses `sk-ant-…` keys with dashes; mailbox's has them).
SECRET_PATTERNS = (*_STREAM_SECRETS, *_MAILBOX_SECRETS)

# Words 윤겸스 uses when reporting a failure (this session's prompts and the U103/U121 receipts).
ERROR_WORDS = ("오류", "에러", "결함", "버그", "실패", "안 돼", "안돼", "안됨", "안 됨", "변화가 없", "고쳐",
               "error", "bug", "broken", "fail")
# Beyond deliver.INJECTED_PREFIXES: Antigravity auto replies, relay tokens and app notices are not 윤겸스's words.
_INJECTED = ("[agy-auto]", "ACK_ONLY", "ACTIONABLE_DELTA", "[SYSTEM", "[UAOS")
_STOP = {"고쳐줘", "고쳐라", "고쳐", "결함", "오류", "에러", "버그", "실패", "다시", "아직도", "지금", "이거", "그리고",
         "있다", "없다", "했다", "났다", "해줘", "하라", "again", "the", "is", "fix"}
WINDOW_S = 7 * 24 * 3600  # one week: a report older than that is a new incident, not a repeat
SAME_RATIO = 0.4  # term overlap (Jaccard) at which two reports are one error; "충돌 결함 고쳐줘" vs "충돌 결함 또 났다" = 0.5
SNIPPET = 120  # characters of the report shown to the other tools
REDACTED = "[redacted: secret-like content]"
LOCK_RETRY_S, LOCK_WAIT_S = 0.02, 10.0


def is_error_report(text) -> bool:
    if not is_human_prompt(text) or text.lstrip().startswith(_INJECTED):
        return False
    low = text.lower()
    return any(word in low for word in ERROR_WORDS)


def terms(text: str) -> set[str]:
    out = set()
    for word in re.findall(r"[가-힣A-Za-z0-9_]{2,}", text.lower()):
        word = re.sub(r"(이다|이며|에서|으로|하라|해줘|은|는|이|가|을|를|도|에|의)$", "", word)
        if len(word) >= 2 and word not in _STOP:
            out.add(word)
    return out


def _usage(project: Path) -> Path:
    return Path(project) / ".coord" / "usage"


def _reports(project: Path) -> Path:
    return _usage(project) / "user_error_reports.jsonl"


def _receipts(project: Path) -> Path:
    return _usage(project) / "user_error_receipts.jsonl"


def _read_jsonl(path: Path) -> list[dict]:
    """A missing file is empty; any other read error propagates so no caller mistakes it for "nothing new"."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def load(project: Path) -> list[dict]:
    return _read_jsonl(_reports(project))


class _Lock:
    # Windows loses lines on concurrent appends (global rule), so every append holds an exclusive lock file.
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except (FileExistsError, PermissionError):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"lock busy: {self.path}")
                time.sleep(LOCK_RETRY_S)

    def __exit__(self, *_exc):
        self.path.unlink(missing_ok=True)


def _append(path: Path, rows: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _same(a: set[str], b: set[str]) -> bool:
    return bool(a and b) and len(a & b) / len(a | b) >= SAME_RATIO


def _safe(prompt: str) -> tuple[str, set[str]]:
    """Secret-like prompts keep only hashed terms: repeats still match, nothing readable is stored."""
    mine = terms(prompt)
    if any(pattern.search(prompt) for pattern in SECRET_PATTERNS):
        return REDACTED, {hashlib.sha256(t.encode("utf-8")).hexdigest()[:16] for t in mine}
    return prompt.strip()[:SNIPPET], mine


def record(project: Path, tool: str, prompt: str, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    text, mine = _safe(prompt)
    path = _reports(project)
    with _Lock(path.with_suffix(".lock")):
        prior = [r for r in load(project) if now - r.get("at", 0) <= WINDOW_S and _same(mine, set(r.get("terms", [])))]
        row = {"id": uuid.uuid4().hex, "at": now, "tool": tool, "terms": sorted(mine), "text": text}
        _append(path, [row])
    tools = sorted({r.get("tool", "") for r in prior} | {tool})
    return {"id": row["id"], "count": len(prior) + 1, "tools": tools, "text": text}


def deliver_unseen(project: Path, tool: str, *, now: float | None = None) -> list[dict]:
    """Reports typed in the other tools' windows that `tool` has not received; each is receipted exactly once.

    The receipt is written only after both files were read, so a failed read delivers nothing and loses nothing."""
    now = time.time() if now is None else now
    path = _receipts(project)
    # One lock for the one shared receipt file: per-tool locks let two tools append at once (Codex REWORK 94075087).
    with _Lock(path.with_suffix(".lock")):
        try:
            reports = load(project)
            got = {r.get("report") for r in _read_jsonl(path) if r.get("tool") == tool}
        except OSError:
            return []
        fresh = [r for r in reports if r.get("tool") != tool and r.get("id") and r["id"] not in got
                 and now - r.get("at", 0) <= WINDOW_S]
        if fresh:
            _append(path, [{"report": r["id"], "tool": tool, "at": now} for r in fresh])
    return fresh


def on_prompt(project: Path, tool: str, prompt, *, now: float | None = None) -> str:
    now = time.time() if now is None else now
    lines = []
    for row in deliver_unseen(project, tool, now=now):
        lines.append(f"USER ERROR REPORTED TO {row.get('tool')} (U150-B): \"{row.get('text')}\" — check and fix "
                     "your side of it now; 윤겸스 must not repeat it to you.")
    if is_error_report(prompt):
        got = record(project, tool, prompt, now=now)
        if got["count"] >= 2:
            lines.append(f"P1 REPEATED USER ERROR (U150-B, report #{got['count']}, tools: {', '.join(got['tools'])}): "
                         "윤겸스 reported this before. Stop other work: open a root-cause card with a reproducing test "
                         "in the shared core and apply it to all 3 tools.")
        else:
            lines.append("USER ERROR REPORT (U150-B): fix the root cause once in the shared core for all 3 tools; "
                         "the other two receive this report on their next turn (receipted).")
    return "\n".join(lines)
