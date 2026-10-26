"""U234: transactional three-tool desk-title votes over a semantic schedule digest.

Votes live in a dedicated SQLite store so title agreement never rewrites
master_schedule.json; only phase ids and titles enter the digest, so state,
owner, timestamp and receipt churn cannot invalidate an agreement.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import unicodedata
from pathlib import Path

TOOLS = ("codex", "claude", "antigravity")
MAX_TOPIC_CHARS = 16  # same short sidebar label limit as desk_title
BUSY_TIMEOUT_S = 10.0  # three real voters serialize well under this; longer waits mean a stuck writer
DB_NAME = "title_consensus.sqlite3"


def _root(project: Path) -> Path:
    return Path(project).resolve()


def db_path(project: Path) -> Path:
    return _root(project) / ".coord" / DB_NAME


def schedule_digest(project: Path) -> str:
    """SHA256 of the ordered [{phase_id, title}] list; malformed schedules raise ValueError."""
    path = _root(project) / ".coord" / "master_schedule.json"
    try:
        schedule = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"unreadable master schedule: {exc}") from None
    phases = schedule.get("phases") if isinstance(schedule, dict) else None
    if not isinstance(phases, list) or not phases:
        raise ValueError("master schedule has no phases")
    items, seen = [], set()
    for phase in phases:
        pid = phase.get("phase_id") if isinstance(phase, dict) else None
        if not isinstance(pid, str) or not pid or pid in seen:
            raise ValueError(f"invalid or duplicate phase_id: {pid!r}")
        title = phase.get("title", "")
        if not isinstance(title, str):
            raise ValueError(f"phase {pid} title is not a string")
        seen.add(pid)
        items.append({"phase_id": pid, "title": title})
    canonical = json.dumps(items, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def valid_topic(topic: object) -> bool:
    if not isinstance(topic, str) or not 0 < len(topic) <= MAX_TOPIC_CHARS or topic != topic.strip():
        return False
    return not any(c in "[]" or unicodedata.category(c).startswith("C") for c in topic)


def _schema(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS votes (tool TEXT PRIMARY KEY, topic TEXT NOT NULL,"
                 " schedule_sha256 TEXT NOT NULL, cast_at REAL NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS accepted (id INTEGER PRIMARY KEY CHECK (id = 1),"
                 " topic TEXT NOT NULL, schedule_sha256 TEXT NOT NULL, accepted_at REAL NOT NULL)")


def cast_vote(project: Path, tool: str, topic: str, expected_hash: str) -> dict:
    """Record one tool's current vote; all three on the same topic and digest accept it."""
    if tool not in TOOLS:
        raise ValueError(f"unknown tool: {tool!r}")
    if not valid_topic(topic):
        raise ValueError(f"invalid topic: {topic!r}")
    digest = schedule_digest(project)
    if expected_hash != digest:
        raise ValueError("schedule digest mismatch; re-read the schedule before voting")
    conn = sqlite3.connect(db_path(project), timeout=BUSY_TIMEOUT_S, isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            _schema(conn)
            now = time.time()
            conn.execute("INSERT INTO votes (tool, topic, schedule_sha256, cast_at) VALUES (?, ?, ?, ?)"
                         " ON CONFLICT(tool) DO UPDATE SET topic=excluded.topic,"
                         " schedule_sha256=excluded.schedule_sha256, cast_at=excluded.cast_at",
                         (tool, topic, digest, now))
            agreeing = {row[0] for row in conn.execute(
                "SELECT tool FROM votes WHERE topic = ? AND schedule_sha256 = ?", (topic, digest))}
            accepted = agreeing == set(TOOLS)
            if accepted:
                conn.execute("INSERT INTO accepted (id, topic, schedule_sha256, accepted_at) VALUES (1, ?, ?, ?)"
                             " ON CONFLICT(id) DO UPDATE SET topic=excluded.topic,"
                             " schedule_sha256=excluded.schedule_sha256, accepted_at=excluded.accepted_at",
                             (topic, digest, now))
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return {"tool": tool, "topic": topic, "schedule_sha256": digest,
            "agreeing": sorted(agreeing), "accepted": accepted}


def accepted_topic(project: Path) -> tuple[bool, str | None]:
    """(store_exists, topic). Reading never creates the store; corrupt state yields (True, None)."""
    path = db_path(project)
    if not path.exists():
        return False, None
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=BUSY_TIMEOUT_S)
        try:
            row = conn.execute("SELECT topic, schedule_sha256 FROM accepted WHERE id = 1").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return True, None
    if not row or not valid_topic(row[0]):
        return True, None
    try:
        current = schedule_digest(project)
    except ValueError:
        return True, None
    return True, row[0] if row[1] == current else None
