"""Antigravity User-Facing Main Control UX/UI & 3-Tool Parallel Visibility Engine (U241)."""
from __future__ import annotations

import html
import json
from pathlib import Path

SCHEMA = "uaos-control-ux-v1"
TOOLS = ("antigravity", "codex", "claude")
WORKERS = ("ollama", "haiku")


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def collect_control_ux_snapshot(project: Path | str) -> dict:
    root = Path(project)
    coord = root / ".coord"
    tools = {
        t: {
            "state": str(_read_json(coord / "presence" / f"{t}.json").get("state") or "UNKNOWN"),
            "updated_at": str(_read_json(coord / "presence" / f"{t}.json").get("updated_at") or ""),
        }
        for t in TOOLS
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
        f"<td>{html.escape(str(p.get('owner', '')))}</td>"
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
        f"<table><thead><tr><th>ID</th><th>Title</th><th>Owner</th><th>State</th></tr></thead><tbody>{rows}</tbody></table>"
        f"<ul>{bgs}</ul></body></html>"
    )
    if output_path is not None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(doc, encoding="utf-8")
    return doc
