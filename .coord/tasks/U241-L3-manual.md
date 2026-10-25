# U241-L3 Contract Manual — Implement `collect_control_ux_snapshot` in `v7_harness/control_ux.py`

```contract
work_id: U241-L3
worker: local
goal: Replace collect_control_ux_snapshot in v7_harness/control_ux.py to collect 3-tool states, worker pool, pending wake background tasks, and schedule summary
inputs:
  - v7_harness/control_ux.py sha256=bb0e1473b49cba2f290cb8e33b560bb1a23723c51c946f5b36d76b0a5f6ff704
  - tests/test_u241_control_ux.py sha256=6cc899a06f01dee52c2c13c9b3c453170b4d6d7f0399ebd4b7271dd6d0112b09
allow:
  - v7_harness/control_ux.py
context_allow:
  - tests/test_u241_control_ux.py
acceptance: C:\Python314\python.exe -m unittest tests.test_u241_control_ux
forbidden: editing or deleting tests; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; input hash mismatch; edits outside allow; no output; 300 seconds
judge: claude
timeout_s: 300
remote_budget_tokens: 0
```

## Task Specification (Replace `def collect_control_ux_snapshot`)

Replace `def collect_control_ux_snapshot(project: Path | str) -> dict:` in `v7_harness/control_ux.py` with:

```python
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
```
