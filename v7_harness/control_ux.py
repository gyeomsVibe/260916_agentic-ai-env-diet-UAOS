"""Antigravity User-Facing Main Control UX/UI & 3-Tool Parallel Visibility Engine (U241/U241B)."""
from __future__ import annotations

import html
import json
import time
from pathlib import Path

from v7_harness.coord.presence import read as read_presence

SCHEMA = "uaos-control-ux-v1"
TOOLS = ("antigravity", "codex", "claude")
WORKERS = ("ollama", "haiku")
AUTO_TRIGGER_PATTERNS = (
    "사용자 대상 대화창구",
    "사용자와의 대화창구",
    "현재 진행상황",
    "진행상황을 알려줘",
    "진행상황을 브리핑",
    "진행상황 브리핑",
)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def should_auto_render_control_ux(prompt: str) -> bool:
    """Return True when a user prompt declares User Desk or asks for current status/briefing."""
    text = str(prompt or "").strip()
    if not text:
        return False
    return any(tok in text for tok in AUTO_TRIGGER_PATTERNS)


def collect_control_ux_snapshot(project: Path | str, *, now: float | None = None) -> dict:
    root = Path(project)
    coord = root / ".coord"
    ts_now = float(now) if now is not None else time.time()
    tools = {}
    for t in TOOLS:
        rec = read_presence(root, t, now=ts_now)
        tools[t] = {
            "state": str(rec.get("state") or "UNKNOWN"),
            "observed_at": rec.get("observed_at"),
            "expires_at": rec.get("expires_at"),
        }
    workers = {
        "ollama": {"model": "qwen2.5-coder:7b", "role": "local_calculator_0_paid_tokens"},
        "haiku": {"model": "claude-haiku-5-5", "role": "fast_precision_subagent"},
    }
    bg_tasks = []
    wake_root = coord / "presence" / "pending_wake"
    if wake_root.is_dir():
        for wf in sorted(wake_root.rglob("*.json")):
            w = _read_json(wf)
            bg_tasks.append({"kind": "PENDING_WAKE", "target": str(w.get("target") or wf.parent.name), "id": str(w.get("message_id") or wf.stem), "pid": w.get("pid")})
    sched = _read_json(coord / "master_schedule.json")
    phases = [p for p in sched.get("phases", []) if isinstance(p, dict)]
    return {
        "schema": SCHEMA,
        "primary_user_desk": "antigravity",
        "user_desk_role": "ANTIGRAVITY = 사용자와의 메인 대화창구 (Primary User-Facing Control Desk)",
        "desk_thread": str(sched.get("desk_thread") or ""),
        "tools": tools,
        "workers": workers,
        "background_tasks": bg_tasks,
        "phases": phases,
        "schedule_summary": {
            "total": len(phases),
            "done": sum(1 for p in phases if p.get("state") == "DONE"),
            "active": sum(1 for p in phases if p.get("state") == "ACTIVE"),
        },
    }


def render_control_ux_html(snapshot: dict, output_path: Path | str | None = None) -> str:
    rows = "".join(
        f"<tr><td>{html.escape(str(p.get('phase_id', '')))}</td>"
        f"<td>{html.escape(str(p.get('title', '')))}</td>"
        f"<td>{html.escape(str(p.get('owner_tool') or p.get('owner') or ''))}</td>"
        f"<td>{html.escape(str(p.get('state', '')))}</td></tr>"
        for p in snapshot.get("phases", [])
    )
    bgs = "".join(
        f"<li>{html.escape(str(b.get('kind', '')))}: {html.escape(str(b.get('target', '')))} ({html.escape(str(b.get('id', '')))})</li>"
        for b in snapshot.get("background_tasks", [])
    )
    doc = (
        f"<!DOCTYPE html><html lang='ko'><head><meta charset='UTF-8'><title>{SCHEMA}</title></head>"
        f"<body><h1>UAOS-RSI Main Control UX/UI ({SCHEMA})</h1>"
        "<div class='banner'><strong>ANTIGRAVITY = 사용자와의 메인 대화창구 (Primary User-Facing Control Desk)</strong></div>"
        f"<table><thead><tr><th>ID</th><th>Title</th><th>Owner</th><th>State</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<ul>{bgs}</ul></body></html>"
    )
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc, encoding="utf-8")
    return doc


def auto_render_control_ux(
    project: Path | str,
    tool: str,
    prompt: str,
    *,
    output_path: Path | str | None = None,
    now: float | None = None,
) -> dict:
    """Automatically generate the Antigravity Main Control UX dashboard when triggered on Antigravity User Desk."""
    root = Path(project).resolve()
    norm_tool = str(tool or "").strip().lower()
    if norm_tool not in ("antigravity", "agy") or not should_auto_render_control_ux(prompt):
        return {
            "triggered": False,
            "primary_user_desk": "antigravity",
            "dashboard_path": None,
        }
    snap = collect_control_ux_snapshot(root, now=now)
    out = Path(output_path) if output_path is not None else (root / "docs" / "00_CONTROL_UX_DASHBOARD.html")
    render_control_ux_html(snap, out)
    return {
        "triggered": True,
        "primary_user_desk": "antigravity",
        "user_desk_role": snap.get("user_desk_role"),
        "dashboard_path": str(out),
        "snapshot": snap,
    }
