```contract
work_id: U304-C-L2
worker: local
goal: Implement the live sub-schedule driver write and advance functions in schedule_planner.py
inputs:
- v7_harness/coord/schedule_planner.py sha256=a3981f3251821630e91faee58333587941d23b6f1aeaab976af75cd961137cfc
allow:
- v7_harness/coord/schedule_planner.py
acceptance: python -m pytest tests/test_u304c_schedule_planner.py -q
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Replace the two `raise NotImplementedError("U304-C-L2: ...")` bodies in v7_harness/coord/schedule_planner.py. Change nothing else. Use one ===EDIT block per body; each SEARCH is exactly that raise line.

1. `_write_both(desk, master, driver)` — persist the live sub-schedule driver:
   - `master_path, sub_path = _paths(desk)`; set `driver["updated_at"] = _now_iso()`; `master["sub_schedule_driver"] = driver`; call `_sync_master(master, driver)`.
   - `sub = _read_json(sub_path)`; `sub.setdefault("schema", "uaos-sub-process-schedule-v1")`; `sub["live_driver"] = driver`.
   - For each dict `c` in `sub.get("card_sub_schedules") or []`: `dcard = driver["cards"].get(str(c.get("phase_id") or ""))`; skip if missing; map steps by `sub_id`; for each dict `sp` in `c.get("sub_processes") or []` whose `sub_id` is in the map, set `sp["u304c_assignment"]` to that step's `assignment` (via `.get`) and `sp["state"]` to that step's `state`.
   - Call `_backup(desk, path)` for master_path then sub_path; then `_atomic_write(master_path, master)` and `_atomic_write(sub_path, sub)`.

2. `advance_sub(project, *, card, step=None, to="DONE")` — live driver step:
   - `to = str(to or "DONE").upper()`; if not in `_STEP_STATES` raise `ValueError` naming the allowed states.
   - `desk = shared_desk(Path(project))`; `master_path, _ = _paths(desk)`; do everything below inside `with _locked(desk):`.
   - `master = _read_json(master_path)`; `driver = master.get("sub_schedule_driver")`; if it is not a dict or `card` not in `driver.get("cards") or {}`, raise `KeyError` telling to run `coord schedule --sub plan` first.
   - `steps = driver["cards"][card]["steps"]`. If `step` given: `sid = step if ":" in step else f"{card}:{step}"`, target = the step with that `sub_id` (or None). Else target = first step with state ACTIVE, else first with state READY; and if that target is READY and `to == "DONE"`, set `to = "ACTIVE"` (advancing with nothing running starts the first ready step).
   - If target is None raise `KeyError(f"no step to advance in {card}")`.
   - Set `target["state"] = to` and `target[f"{to.lower()}_at"] = _now_iso()`.
   - `opened = None`; `done` = set of sub_ids whose state is DONE. If no step is ACTIVE: open the first step whose state is PLANNED or READY and all of whose `depends_on` are in `done` (state ACTIVE, `active_at` = now, `opened` = its sub_id), then stop looking.
   - Then every PLANNED step whose `depends_on` are all in `done` becomes READY.
   - `_write_both(desk, master, driver)`.
   - Return `{"ok": True, "card": card, "changed": target["sub_id"], "state": to, "opened": opened, "steps": [_step_line(s) for s in steps]}`.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
