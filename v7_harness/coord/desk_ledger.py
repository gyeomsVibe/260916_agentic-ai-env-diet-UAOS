"""U332 (spec 9.8): one shared, append-only directive ledger so the 3 desks act as one body.

A user directive given at any desk is appended here verbatim, ordered by an atomic sequence number (never a clock).
Every desk keeps a read cursor; a prompt hook or watcher event calls `inject` and gets the entries after its cursor
as "received" lines (a link plus a one-line gist, never the full text), so the other two desks behave as if they had
received it themselves. A tool that was offline replays from its cursor before acting. "Stop" is one more ledger
entry kind: appending it halts every open card at once (`desk_router.propagate_stop`), and each desk sees it first.

Worst case first: the sequence is taken and the line appended under one cross-process lock (Windows loses concurrent
appends otherwise); a replayed or repeated ack never moves a cursor back; a crash between the verbatim file and the
ledger line leaves the next append to reuse the same number only after the ledger, the single truth, says so.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from . import desk_router as dr

LEDGER = "ledger.jsonl"
GIST_CHARS = 80
# Why 10: spec 9.4-1 real-time ACK deadline; a hook must show a new entry within this.
ACK_DEADLINE_S = 10.0
# Why 60: two desks hearing the user within one minute are "near-simultaneous"; later seq wins.
CONFLICT_WINDOW_S = 60.0
INJECT_MAX_LINES = 8  # a 50-directive burst shows this many gists plus one "+N more" line, never full texts
KINDS = ("directive", "stop")
_STOP_RE = re.compile(r"^\s*(?:/?stop|멈춰|중단|그만|정지)\b", re.I)


def _folder(project: Path) -> Path:
    return dr._dir(project)


def _entries(project: Path) -> list[dict[str, Any]]:
    out = []
    try:
        lines = (_folder(project) / LEDGER).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue  # a torn last line is ignored; the next append rewrites past it under the lock
        if isinstance(row, dict) and isinstance(row.get("seq"), int):
            out.append(row)
    return out


def append_directive(project: Path, raw: bytes | str, *, tool: str, kind: str = "", event_id: str = "",
                     now: float | None = None) -> dict[str, Any]:
    """Atomically take the next seq, store the verbatim `D-<seq>.md` and append one ledger line. Returns the entry.

    `kind` defaults to "stop" for a bare stop word, else "directive". The same `event_id` again returns the first entry.
    """
    data = raw.encode("utf-8") if isinstance(raw, str) else bytes(raw)
    text = data.decode("utf-8", errors="replace")
    kind = kind or ("stop" if _STOP_RE.match(text) else "directive")
    if kind not in KINDS:
        raise ValueError(f"unknown kind: {kind}")
    folder = _folder(project)
    with dr._Lock(folder / ".ledger.lock"):
        rows = _entries(project)
        if event_id:
            for row in rows:
                if row.get("event_id") == event_id:
                    return {**row, "replay": True}
        seq = (rows[-1]["seq"] if rows else 0) + 1
        d_id = f"D-{seq:04d}"
        with open(folder / f"{d_id}.md", "wb") as handle:  # same seq after a crash: the verbatim file is rewritten, never lost
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        entry = {"seq": seq, "d_id": d_id, "tool": tool, "kind": kind, "event_id": event_id, "sha256": hashlib.sha256(data).hexdigest(),
                 "bytes": len(data), "at": time.time() if now is None else now, "gist": " ".join(text.split())[:GIST_CHARS], "text": text}
        ledger = folder / LEDGER
        with open(ledger, "ab") as handle:
            if ledger.stat().st_size and ledger.read_bytes()[-1:] != b"\n":
                handle.write(b"\n")  # a torn last line must not swallow this entry: start it on its own line
            handle.write((json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    if kind == "stop":
        dr.propagate_stop(project, d_id)
    return entry


def text_of(project: Path, d_id: str) -> str:
    """The verbatim text of one ledger entry ('' when absent); used to resume a routing that died midway."""
    for row in _entries(project):
        if row.get("d_id") == d_id:
            return str(row.get("text", ""))
    return ""


def read_since(project: Path, cursor: int) -> list[dict[str, Any]]:
    """Entries with seq > cursor, in seq order (an offline tool replays everything it missed)."""
    return [row for row in _entries(project) if row["seq"] > int(cursor)]


def cursor_of(project: Path, tool: str) -> int:
    data = dr._read_json(_folder(project) / "cursors" / f"{tool}.json", {})
    return int(data.get("seq", 0)) if isinstance(data, dict) else 0


def ack(project: Path, tool: str, seq: int) -> int:
    """Advance the tool's cursor to `seq`; never backwards, so processing the same seq twice is harmless."""
    folder = _folder(project) / "cursors"
    folder.mkdir(parents=True, exist_ok=True)
    with dr._Lock(folder / f".{tool}.lock"):
        current = cursor_of(project, tool)
        if int(seq) > current:
            dr._write_json(folder / f"{tool}.json", {"seq": int(seq), "tool": tool, "acked_at": time.time()})
            return int(seq)
        return current


def conflicts(rows: list[dict[str, Any]], window_s: float = CONFLICT_WINDOW_S) -> list[str]:
    """Near-simultaneous directives from different desks about the same files/topic: the later seq wins, one line each."""
    out = []
    live = [r for r in rows if r.get("kind") == "directive"]
    for i, early in enumerate(live):
        for late in live[i + 1:]:
            if late["tool"] == early["tool"] or abs(late["at"] - early["at"]) > window_s:
                continue
            shared = dr.extract_files(early["text"]) & dr.extract_files(late["text"])
            if shared or dr.similarity(early["text"], late["text"]) >= dr.SIMILARITY_THRESHOLD:
                out.append(f"CONFLICT {late['d_id']}({late['tool']}) overrides {early['d_id']}({early['tool']}): "
                           f"same topic within {int(window_s)} s, later seq wins")
    return out


def inject(project: Path, tool: str, *, limit: int = INJECT_MAX_LINES, auto_ack: bool = True) -> list[str]:
    """Lines a desk hook shows "as received". STOP first, then conflicts, then gists with links; a burst is cut to
    `limit` gists plus one count line. Advances the cursor (ack) after building the lines."""
    cursor = cursor_of(project, tool)
    rows = read_since(project, cursor)
    if not rows:
        return []
    lines = [f"STOP {r['d_id']} ({r['tool']}): halt now, all open cards signal STOP" for r in rows if r["kind"] == "stop"]
    # conflicts are judged against the recent window, not only the unseen rows: the earlier one may already be acked
    # conflicts are judged against the recent window (the earlier one may already be acked), but only pairs whose
    # later entry is still unseen are shown, so an old conflict is never re-announced on every call
    fresh = [c for c in conflicts(read_since(project, max(0, rows[0]["seq"] - 1 - 20)))
             if int(c.split()[1].split("(")[0][2:]) > cursor]
    lines += fresh[:2]
    limit = max(1, int(limit))  # a zero or negative limit would slice from the end and miscount; at least one gist per call
    shown = [r for r in rows if r["kind"] == "directive"]
    cut = len(shown) > limit
    for r in shown[:limit]:
        lines.append(f"{r['d_id']} [{r['tool']}] {r['gist']} -> .coord/directives/{r['d_id']}.md")
    # P1-4: a truncated burst must not skip the unseen tail; the cursor stops at the last directive actually shown
    # (stop rows are always shown), so the next call continues with the "+N more" part.
    new_cursor = rows[-1]["seq"]
    if cut:
        last_shown = shown[limit - 1]["seq"]
        new_cursor = max([last_shown, *(r["seq"] for r in rows if r["kind"] == "stop" and r["seq"] <= last_shown)])
        lines.append(f"+{len(shown) - limit} more directives, see .coord/directives/{LEDGER} (cursor {cursor} -> {new_cursor})")
    if auto_ack:
        ack(project, tool, new_cursor)
    return lines
