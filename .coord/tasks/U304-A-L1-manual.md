```contract
work_id: U304-A-L1
worker: local
goal: In v7_harness/coord/capacity_planner.py, make flagman_liveness check the daemon_pid and render the ops-chip panel always open.
inputs:
- v7_harness/coord/capacity_planner.py sha256=27f2b11f3d5bb55656ac6890ca49af9f7c77d7d4995ca043775a45f99d6e35a0
allow:
- v7_harness/coord/capacity_planner.py
acceptance: python -m pytest tests/test_u286_hud_dark_flagman.py tests/test_u303_hud_render.py -q
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly, in order.

===EDIT: v7_harness/coord/capacity_planner.py===
<<<<<<< SEARCH
    if age > FLAGMAN_STALE_S:
        return out("STOPPED", "PULSE_STALE", age)
    try:
        pid = int(beat_doc.get("pid"))
    except (TypeError, ValueError):
        return out("UNKNOWN", "NO_PID", age)
=======
    if age > FLAGMAN_STALE_S:
        return out("STOPPED", "PULSE_STALE", age)
    # U304-A: short-lived hook processes also pulse, so the writer's PID proves nothing; the resident daemon's
    # PID (`daemon_pid`, null when none was ever recorded) is what must be running. Older beats only carry `pid`.
    if "daemon_pid" in beat_doc and beat_doc.get("daemon_pid") is None:
        return out("STOPPED", "NO_DAEMON", age)
    try:
        pid = int(beat_doc.get("daemon_pid", beat_doc.get("pid")))
    except (TypeError, ValueError):
        return out("UNKNOWN", "NO_PID", age)
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/capacity_planner.py===
<<<<<<< SEARCH
        <div id="schedule-list" class="space-y-2 text-sm"></div>
      </section>
      <details class="rounded-lg border border-[var(--border)] p-2">
        <summary class="acc-sum cursor-pointer text-sm font-semibold px-1 py-1">📟 운영 칩 · 대기 상태</summary>
        <div class="space-y-2 pt-2">
          <div id="five-chip-bar" class="grid grid-cols-1 md:grid-cols-2 gap-2"></div>
          <div id="wait-banner" class="rounded-lg border border-[var(--border)] bg-[var(--secondary)]/40 p-2.5 text-xs"></div>
        </div>
      </details>
      </div>
    </div>
=======
        <div id="schedule-list" class="space-y-2 text-sm"></div>
      </section>
      <!-- U304-A: always open (윤겸스 2026-11-04). U286 v4 folded it into a closed details accordion to give the tool
           console the top; the chips and wait banner then stayed hidden until clicked. -->
      <section id="ops-chip-panel" class="rounded-lg border border-[var(--border)] p-2">
        <div class="text-sm font-semibold px-1 py-1">📟 운영 칩 · 대기 상태</div>
        <div class="space-y-2 pt-2">
          <div id="five-chip-bar" class="grid grid-cols-1 md:grid-cols-2 gap-2"></div>
          <div id="wait-banner" class="rounded-lg border border-[var(--border)] bg-[var(--secondary)]/40 p-2.5 text-xs"></div>
        </div>
      </section>
      </div>
    </div>
>>>>>>> REPLACE
===END===

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
