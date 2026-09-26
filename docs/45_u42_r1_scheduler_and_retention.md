# 45 — U42-R1: fail-closed shipping, scheduler hardening, retention planning

Work ID `U42_R1_CLAUDE_IMPL`. Hardens the U42 evidence-to-PR pipeline against five reproduced P1
defects and adds a deterministic, deletion-free retention planner. `rsi adopt` and `rsi rollback`
stay untouched and fail-closed (B83).

## 1. Shipping (`v7_harness/rsi_release.py::ship_release`)

Every external step — `git status`, `fetch`, `add`, `commit`, `rev-parse HEAD`, `push`,
`ls-remote`, `gh pr create`, `gh pr view` — runs through one helper (`_run_step`) that raises
`ReleaseRefused` naming the stage plus bounded stdout/stderr on any nonzero exit. The remote SHA
after push must exist and equal local HEAD; an empty or mismatched remote SHA raises
`REMOTE_SHA_MISSING`/`REMOTE_SHA_MISMATCH` and is never replaced by the local HEAD. A failed push
can never return `SHIPPED`. Dry run remains the default (`execute=False`); merge is never invoked.

## 2. Scheduler cycle (`run_scheduler_cycle`)

- **Locking**: `.work/rsi-scheduler.lock` is created with exclusive `O_CREAT|O_EXCL` (atomic across
  processes). A live, non-expired lock returns `LOCKED`. A lock is recovered only when its owner PID
  is reported dead (via the injected `pid_alive`, gated by a small age grace period so a
  just-created lock is never mistaken for dead) or its age reaches `lock_ttl_seconds`; recovery
  emits a `STALE_LOCK_RECOVERED` record and retries acquisition once. Only the lock this invocation
  created is ever removed (checked by a per-invocation token).
- **Retry/backoff**: bounded retries per source with the schedule `[60, 120, 240]` for
  `max_retries=3`. The injected `sleeper` is called only *between* attempts (two calls for three
  attempts), never after the last one. On exhaustion, the full schedule and
  `next_run_at = now + 240` are still returned.
- **Dedupe/trigger-once**: every source is fetched and compared first; content-hash changes are
  collected into `deltas`, deduped by URL, and `trigger` is invoked exactly once with
  `{"deltas": [...]}`. ETag/Last-Modified-only changes stay `ACK_ONLY` — content hash is the only
  actionable signal.

## 3. Windows scheduling (`windows_schedule`)

Task names are project-unique (`UAOS_RSI_Watch_<8-hex normalized-project hash>`), so installing on
two projects never collides. Install writes a deterministic wrapper (`.work/rsi-scheduler-wrapper.cmd`)
that `cd`s to the project root and calls absolute python/launcher paths. Actions:
`install`, `status`, `remove`, `manual-now`; all default to dry run (`apply=False`).

```powershell
python -m v7_harness.cli rsi schedule --project D:\proj --action install               # preview
python -m v7_harness.cli rsi schedule --project D:\proj --action install --apply        # register
python -m v7_harness.cli rsi schedule --project D:\proj --action manual-now --apply     # run once, now
python -m v7_harness.cli rsi schedule --project D:\proj --action remove --apply         # unregister
```

## 4. Retention planning (`v7_harness/retention.py`, no deletion)

`default_policy()` covers `.coord/usage`, `.coord/stream`, `.coord/pilot/runs`, `.work/logs`,
`.coord/approvals`, `.coord/rsi`, and Sentinel receipts (`.coord/sentinel/receipts`), each with
explicit `retention_days`/`max_count`/`max_bytes`.

`plan_retention(root, policy, now)`:
- rejects any zone path that would escape `root` (`RetentionRefused: PATH_ESCAPE`);
- enumerates deterministically (sorted paths);
- excludes `ACTIVE`/locked runs (`ACTIVE_EXCLUDE`);
- protects failure/P1/approval evidence regardless of age (`PROTECT`);
- classifies remaining old items as `ARCHIVE_CANDIDATE`, each with a planned `archive_path`,
  `restore_path`, and SHA-256;
- returns a stable `manifest_sha256` over the whole item list.

`apply_retention` defaults to `{"status": "DRY_RUN", ...}` and never deletes anything.
`execute_delete=True` always raises `RetentionRefused("FRESH_DELETE_APPROVAL_REQUIRED...")` — this
task performs no deletion; a real delete needs its own, later, freshly-approved step.

```powershell
python -m v7_harness.cli rsi retention --project D:\proj    # prints the dry-run manifest
```
