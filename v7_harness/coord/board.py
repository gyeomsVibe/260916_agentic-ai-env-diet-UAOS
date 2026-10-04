"""U147: the user's board, which shows whether Codex, Claude Code and Antigravity are working right now.

윤겸스 could not tell from the PC apps whether a tool was working, idle, or answering in a window nobody watched
(2026-10-04: letters went to a background Codex thread and the user's window showed nothing). The board reads only
what each app itself writes, never a self-reported heartbeat:
  - Codex: each rollout's last task_started / task_complete event, and the last turn 윤겸스 typed (deliver.py U147);
  - Claude Code: when each session transcript of this project was last written;
  - Antigravity: when each conversation transcript was last written, across all projects (transcripts name none);
  Claude and Antigravity show "최근 기록" (recent activity from write times), only Codex shows "작업 중" (U147-R);
  - the mailbox: the last letters with their target thread, and letters still queued per tool.
It spends no paid tokens: `python -m v7_harness.coord.board --project . --watch 5` rewrites one HTML page that
refreshes itself, and without --watch it prints the board once.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
LETTERS_SHOWN = 6
SESSIONS_SHOWN = 5  # the newest Claude sessions; a day can hold a dozen worktree sessions (8 on 2026-10-04)
HTML_REFRESH_S = 5


def _iso_epoch(stamp: str) -> float:
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}초 전"
    if seconds < 3600:
        return f"{seconds // 60}분 전"
    return f"{seconds // 3600}시간 {seconds % 3600 // 60}분 전"


def _codex_turn(path: Path) -> dict[str, Any]:
    """The last turn event of one rollout: WORKING while a task_started has no later task_complete."""
    started = completed = ""
    message = ""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"task_started"' not in line and '"task_complete"' not in line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                payload = data.get("payload") if isinstance(data, dict) else None
                if not isinstance(payload, dict):
                    continue
                if payload.get("type") == "task_started":
                    started = str(data.get("timestamp") or "")
                elif payload.get("type") == "task_complete":
                    completed = str(data.get("timestamp") or "")
                    message = str(payload.get("last_agent_message") or "")
    except OSError:
        pass
    working = bool(started) and started > completed
    return {"working": working, "since": started if working else completed, "last_message": message}


def codex_threads(project: Path) -> list[dict[str, Any]]:
    root = Path(os.environ.get(CODEX_SESSIONS_ENV) or (Path.home() / ".codex" / "sessions"))
    if not root.is_dir():
        return []
    user_window = deliver._codex_thread(project, "")[0]  # U147-D: exactly where a letter without --thread goes
    verified, _overflow = deliver.verified_rollouts(project, root)
    # U147-R: the newest CODEX_SCAN verified threads, plus the user window even when it is older than all of them.
    shown = verified[:CODEX_SCAN] + [item for item in verified[CODEX_SCAN:] if item[0] == user_window]
    if user_window and all(thread != user_window for thread, _path in shown):
        # U147-D: a designated desk is listed even when the guess overflowed (verified is then empty)
        shown += [(user_window, path) for path in root.glob(f"*/*/*/rollout-*-{user_window}.jsonl")][:1]
    rows = []
    for thread, path in shown:
        if thread != user_window and time.time() - path.stat().st_mtime > RECENT_S:
            continue
        turn = _codex_turn(path)
        rows.append({"thread": thread, "user_window": thread == user_window,
                     "last_human": deliver.last_human_input(path), **turn})
    return rows


def _project_key(project: Path) -> str:
    """Claude Code names a project folder by its path with every non-alphanumeric character turned into '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", project.resolve().name)


def claude_sessions(project: Path, now: float) -> list[dict[str, Any]]:
    root = Path(os.environ.get(CLAUDE_PROJECTS_ENV) or (Path.home() / ".claude" / "projects"))
    if not root.is_dir():
        return []
    key = _project_key(project)
    rows = []
    for folder in root.iterdir():
        if not folder.is_dir() or key not in folder.name or folder.name.endswith("-scratchpad"):
            continue
        for path in folder.glob("*.jsonl"):
            age = now - path.stat().st_mtime
            if age <= RECENT_S:
                where = folder.name.split(key, 1)[1].lstrip("-") or "main"
                rows.append({"session": path.stem, "where": where, "age": age, "working": age <= WORKING_WINDOW_S})
    return sorted(rows, key=lambda row: row["age"])


def _agy_roots() -> list[Path]:
    """U147-R: the desktop app writes ~/.gemini/antigravity/brain (18 conversations on 2026-10-04) and the headless
    `agy` CLI that UAOS pilot reviews and audits run writes ~/.gemini/antigravity-cli/brain (494); both are
    Antigravity working (Antigravity review of U147-A4). AGY_BRAIN_ENV takes an os.pathsep-separated list."""
    configured = os.environ.get(AGY_BRAIN_ENV)
    if configured:
        return [Path(part) for part in configured.split(os.pathsep) if part]
    home = Path.home() / ".gemini"
    return [home / "antigravity" / "brain", home / "antigravity-cli" / "brain"]


def agy_conversations(now: float) -> list[dict[str, Any]]:
    rows = []
    for root in _agy_roots():
        if not root.is_dir():
            continue
        kind = "CLI" if root.parent.name.endswith("-cli") else "앱"
        for folder in root.iterdir():
            transcript = folder / ".system_generated" / "logs" / "transcript_full.jsonl"
            try:
                age = now - transcript.stat().st_mtime
            except OSError:
                continue
            if age <= RECENT_S:
                rows.append({"conversation": folder.name, "kind": kind, "age": age,
                             "working": age <= WORKING_WINDOW_S})
    return sorted(rows, key=lambda row: row["age"])


def mailbox(project: Path) -> dict[str, Any]:
    box = deliver._project_mailbox(project.resolve()).root / "delivery"
    accepted = sorted((box / "accepted").glob("relay_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    letters = []
    for path in accepted[:LETTERS_SHOWN]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        letters.append({"id": path.stem[:14], "target": data.get("target", ""), "thread": data.get("thread", ""),
                        "state": data.get("state", ""), "at": int(data.get("timestamp_ns", 0)) / 1e9})
    queued = {}
    for tool in ("codex", "claude", "antigravity"):
        folder = box / "queued" / tool
        queued[tool] = len(list(folder.glob("relay_*.json"))) if folder.is_dir() else 0
    return {"letters": letters, "queued": queued}


def snapshot(project: Path, now: float | None = None) -> dict[str, Any]:
    moment = time.time() if now is None else now
    return {"at": moment, "codex": codex_threads(project), "claude": claude_sessions(project, moment),
            "antigravity": agy_conversations(moment), "mailbox": mailbox(project)}


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
    """
    moment = time.time() if now is None else now
    working = {"codex": False, "claude": False, "antigravity": False}
    root = Path(os.environ.get(CODEX_SESSIONS_ENV) or (Path.home() / ".codex" / "sessions"))
    if root.is_dir():
        roots = deliver._registered_roots(project)
        paths = sorted(root.glob("*/*/*/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in paths[:STATUS_ROLLOUTS]:
            _thread, cwd, status = deliver._read_rollout_meta(path)
            if status == "OK" and cwd and os.path.normcase(str(cwd)) in roots and _codex_turn(path)["working"]:
                working["codex"] = True
    working["claude"] = any(row["working"] for row in claude_sessions(project, moment))
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
    states = line.rsplit(" | ", 1)[-1].replace("[UAOS] ", "")  # the remembered part: the tool states only
    letter = "📬" in line  # desk_delta hands each letter over once, so a letter always speaks
    try:
        first = not marker.is_file()
        changed = first or marker.read_text(encoding="utf-8") != states
        if changed:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(states, encoding="utf-8")
    except OSError:
        return False  # a hook never fails the session; an unwritable desk shows nothing
    # The first look only records the states (U105: nothing new prints nothing).
    return letter or (changed and not first)


def letters_in(delta: str) -> list[str]:
    """The letter items of a desk delta (`- letter relay_<id>: <text>`), as their text."""
    return [item.split(": ", 1)[1] if ": " in item else item
            for item in delta.splitlines() if item.startswith("- letter ")]


def _state_word(working: bool) -> str:
    """Codex only: a task_started with no later task_complete is a running turn the app itself recorded."""
    return "작업 중" if working else "대기"


def _recent_word(written: bool, everywhere: bool = False) -> str:
    """U147-R: Claude and Antigravity states come from transcript write times, which show recent activity, not a
    verified running turn (Codex review relay_6dfa9184). Antigravity transcripts name no project folder (checked
    2026-10-04), so its state covers every project and says so."""
    word = "최근 기록" if written else "대기"
    return f"{word}(전체 프로젝트)" if everywhere else word


def lines(snap: dict[str, Any]) -> list[str]:
    now = snap["at"]
    out = [f"UAOS 3도구 상태판  {datetime.fromtimestamp(now).strftime('%H:%M:%S')}"]
    out.append("[Codex]" + ("" if snap["codex"] else " 이 프로젝트의 최근 창 없음"))
    for row in snap["codex"]:
        mark = " ← 사용자 창(편지 도착)" if row["user_window"] else ""
        since = _ago(now - _iso_epoch(row["since"])) if row["since"] else "-"
        human = _ago(now - _iso_epoch(row["last_human"])) if row["last_human"] else "없음"
        out.append(f"  {row['thread'][:8]} {_state_word(row['working'])} ({since}) 사용자 입력 {human}{mark}")
        first = row["last_message"].strip().splitlines()[0] if row["last_message"].strip() else ""
        if first and not row["working"]:
            out.append(f"    마지막 답: {first[:70]}")
    out.append("[Claude Code]" + ("" if snap["claude"] else " 최근 세션 없음"))
    for row in snap["claude"][:SESSIONS_SHOWN]:
        out.append(f"  {row['session'][:8]} {_recent_word(row['working'])} ({_ago(row['age'])}) {row['where'][:40]}")
    out.append("[Antigravity 전체 프로젝트]" + ("" if snap["antigravity"] else " 최근 대화 없음"))
    for row in snap["antigravity"][:SESSIONS_SHOWN]:
        out.append(f"  {row['conversation'][:8]} {row.get('kind', '')} {_recent_word(row['working'])} "
                   f"({_ago(row['age'])})")
    box = snap["mailbox"]
    waiting = ", ".join(f"{tool} {count}" for tool, count in box["queued"].items() if count)
    out.append("[편지] 대기 " + (waiting or "없음"))
    for letter in box["letters"]:
        thread = f" 창 {letter['thread'][:8]}" if letter["thread"] else ""
        out.append(f"  {letter['id']} → {letter['target']}{thread} {letter['state']} ({_ago(now - letter['at'])})")
    return out


def render_html(snap: dict[str, Any]) -> str:
    body = []
    for line in lines(snap):
        text = html.escape(line)
        css = "work" if ("작업 중" in line or "최근 기록" in line) else ("head" if line.startswith(("[", "UAOS")) else "")
        body.append(f'<div class="{css}">{text}</div>')
    return ("<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
            f"<meta http-equiv='refresh' content='{HTML_REFRESH_S}'><title>UAOS 상태판</title><style>"
            ":root{--bg:#fff;--fg:#111;--work:#0a7d32;--head:#333}"
            "@media (prefers-color-scheme:dark){:root{--bg:#141414;--fg:#e8e8e8;--work:#4cd47a;--head:#bbb}}"
            "body{background:var(--bg);color:var(--fg);font:15px/1.5 Consolas,'Malgun Gothic',monospace;"
            "margin:16px;white-space:pre-wrap}.work{color:var(--work);font-weight:bold}"
            ".head{color:var(--head);font-weight:bold;margin-top:8px}</style></head><body>"
            + "".join(body) + "</body></html>")


def write_html(project: Path, target: Path | None = None) -> Path:
    path = target or (project / ".work" / "board" / "index.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(render_html(snapshot(project)), encoding="utf-8")
    os.replace(tmp, path)  # the browser never reads a half-written page
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m v7_harness.coord.board")
    parser.add_argument("--project", default=".")
    parser.add_argument("--html", default="", help="page path (default <project>/.work/board/index.html)")
    parser.add_argument("--watch", type=float, default=0, help="rewrite the page every N seconds until stopped")
    args = parser.parse_args(argv)
    project = Path(args.project).resolve()
    target = Path(args.html) if args.html else None
    if not args.watch:
        print("\n".join(lines(snapshot(project))))
        if args.html:
            write_html(project, target)
        return 0
    page = write_html(project, target)
    print(f"board: {page} (refresh {HTML_REFRESH_S}s; stop with Ctrl+C)")
    try:
        while True:
            time.sleep(args.watch)
            write_html(project, target)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
