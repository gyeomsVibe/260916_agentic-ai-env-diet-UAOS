# U241B-L1 Contract Manual — Implement `collect_control_ux_snapshot` with TTL Presence and Primary User Desk

```contract
work_id: U241B-L2
worker: local
goal: Replace collect_control_ux_snapshot in v7_harness/control_ux.py to enforce TTL-aware presence (read_presence with root and now), observed_at, and primary_user_desk=antigravity
inputs:
  - v7_harness/control_ux.py sha256=3473ff33a6679f63f755320ff6cb3d9cde8875e58f46852a362d437cd134ce33
  - tests/test_u241_control_ux.py sha256=2baeae405485f22fbd10e847b8452ece6d219a9200cfed7df4f9d0f4e930779b
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

Replace `def collect_control_ux_snapshot(project: Path | str, *, now: float | None = None) -> dict:` in `v7_harness/control_ux.py` with:

```python
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
```
