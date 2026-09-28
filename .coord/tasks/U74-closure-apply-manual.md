```contract
work_id: U74
worker: apply
goal: Close the U72/U73 ledger gaps (pilot wall time, qualification rows, Codex rollout sessions), stop ACK_ONLY letters from spending a paid turn, and record the delegated re-review and U72 cost verdict
inputs:
- v7_harness/pilot.py sha256=fde653541ba1ac454cabeafe9e34e5dbf8bc48ac765967b583e7a3c1ecf0adc4
- .coord/PLAN.md sha256=e8bcc80de4d7bb014cfb1ff880ed45d26381b77b1728dd57deb5140a2b3352d4
allow:
- v7_harness/pilot.py
- v7_harness/model_qualification.py
- v7_harness/coord/session_usage.py
- v7_harness/coord/deliver.py
- v7_harness/cli.py
- tests/test_u74_closure.py
- docs/62_u74-ledger-closure-and-review.md
- .coord/PLAN.md
- tests/test_u71_three_tool_e2e.py
acceptance: python -m unittest tests.test_u74_closure tests.test_u73_session_usage tests.test_u54_firewall_audit tests.test_u54_s2_caller_review tests.test_u72l_desk_ledger tests.test_u69_admission_gate tests.test_u51_model_qualification tests.test_u70_local_qualification tests.test_u38_cost_gate_and_claude_worker tests.test_u64_nonstop_dispatch tests.test_u64f_no_double_wake tests.test_u71_three_tool_e2e tests.test_u60_replace_retry tests.test_u61_watcher_routes
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1200
remote_budget_tokens: 0
```

## Instructions for the worker

U72 cost gate needs complete ledgers; a full-suite U71 flake exposed ACK_ONLY paid dispatch. Claude acts with Codex's authority at the user's instruction (2026-09-28). Write the nine files below exactly.

===FILE: v7_harness/pilot.py===
"""M2/M4 pilot runner: end-to-end execution of headless agy pilot with acceptance and reconciliation."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import time
from typing import Any

from v7_harness.accept_triage import classify as classify_acceptance
from v7_harness.adapters.agy import AgyOutcome, AgyRequest
from v7_harness.broker.core import BrokerCore
from v7_harness.execution.agy_launcher import AgyProcessLauncher
from v7_harness.execution.circuit import set_quota_state
from v7_harness.execution.engine import DurableExecutionEngine
from v7_harness.execution.errors import WorkerExecutionError
from v7_harness.isolation.errors import (
    ExternalWriteDetectedError,
    IsolationError,
    ScopeExpansionError,
    SourceDivergenceError,
    WatchScanUnavailableError,
)
from v7_harness.isolation.manifest import PatchBundle, build_manifest
from v7_harness.isolation.promotion import apply_promotion, dry_run_promotion
from v7_harness.isolation.security import snapshot_watch_roots
from v7_harness.isolation.staging import NonGitStagingAdapter, StagingWorkspace

_orig_sqlite3_connect = sqlite3.connect


class _AutoCloseReadOnlyConnection(sqlite3.Connection):
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> Any:
        res = super().__exit__(exc_type, exc_val, exc_tb)
        self.close()
        return res


def _patched_sqlite3_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
    database = args[0] if args else kwargs.get("database", "")
    if isinstance(database, str) and "mode=ro" in database:
        kwargs["factory"] = _AutoCloseReadOnlyConnection
    return _orig_sqlite3_connect(*args, **kwargs)


sqlite3.connect = _patched_sqlite3_connect


@dataclass
class PilotConfig:
    task_id: str
    title: str
    prompt: str
    source_dir: Path
    work_dir: Path
    agy_command: list[str]
    watch_roots: list[Path]
    print_timeout_s: int = 600
    approve_bundle_id: str | None = None
    accept_cmd: str | None = None
    model: str | None = None
    allow_no_changes: bool = False
    # Paths/globs the work manual allows the worker to change. None keeps the old unrestricted behavior.
    allowed_scopes: list[str] | None = None
    # B85: the contract's remote_budget_tokens for a paid worker. The gate runs before summary.json and the ledger
    # row are written, so an over-budget bundle is BLOCKED everywhere, including the --approve replay.
    remote_budget_tokens: int | None = None


def worker_label(command: list[str] | tuple[str, ...]) -> str:
    """Which worker ran, for the ledger. lane used to be recorded as agy, which mixed a free local run into the
    paid worker's RSI window."""
    text = " ".join(str(part) for part in command)
    for marker, label in (("apply_worker", "apply"), ("claude_worker", "claude"), ("lane_worker", "lane"),
                          ("ollama", "ollama")):
        if marker in text:
            return label
    # Only the real agy binary is the paid Antigravity worker; any other command (a test stand-in, a custom script)
    # is recorded as what it is instead of being counted as paid work.
    first = Path(str(command[0])).name.lower() if command else ""
    return "agy" if first in ("agy", "agy.exe", "agy.cmd") else "custom"


PAID_WORKERS = ("agy", "claude")


# Every kind the worker reports is spent: cached input is still billed and still counts against the quota.
COST_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def delegator() -> str | None:
    """U45-F4: which tool ordered this run (codex, claude, antigravity), from its shell environment; None for a plain
    terminal. The ledger needs it to measure how much Claude conducted while Codex was away."""
    import os as _os

    names = _os.environ.keys()
    if any(n.upper().startswith(("ANTIGRAVITY", "GEMINI_CLI")) for n in names):
        return "antigravity"
    if "CLAUDECODE" in names:
        return "claude"
    if any(n.upper().startswith("CODEX_") for n in names):
        return "codex"
    return None


def evaluate_cost_gate(usage: dict[str, Any] | None, budget: int) -> str:
    """WITHIN, EXCEEDED:<used>><budget>, or UNKNOWN when input or output is not reported (never read as zero)."""
    if not isinstance(usage, dict):
        return "UNKNOWN"
    values = {}
    for key in COST_TOKEN_KEYS:
        value = usage.get(key)
        if value is None and key.startswith("cache_"):
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return "UNKNOWN"
        values[key] = value
    used = sum(values.values())
    return "WITHIN" if used <= budget else f"EXCEEDED:{used}>{budget}"


_PYTHON_NAMES = frozenset({"python", "python.exe", "python3", "py"})


def _resolve_accept_tokens(cmd: str) -> list[str]:
    """Parse *cmd* into tokens; replace a leading Python interpreter with ``sys.executable``.

    ``shlex.split(cmd, posix=False)`` preserves Windows-style quoting, then
    each token has surrounding quotes stripped.  If the first token matches a
    well-known Python binary name (case-insensitive) it is replaced with the
    interpreter that is running the harness so that a ``python.exe`` planted in
    the staging *cwd* is never picked up via ``PATH``.
    """
    raw_tokens = shlex.split(cmd, posix=False)
    tokens = [t.strip('"').strip("'") for t in raw_tokens]
    if tokens and tokens[0].lower() in _PYTHON_NAMES:
        tokens[0] = sys.executable
    return tokens


def _derive_isolation_mode(workspace: StagingWorkspace) -> str:
    if isinstance(workspace, StagingWorkspace):
        return "staging"
    raise TypeError("workspace must be an instance of StagingWorkspace")


def _write_summary(path: Path, summary: dict[str, Any]) -> None:
    """Persist a summary with an atomic same-directory replace."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _write_identity(path: Path, identity: dict[str, Any]) -> None:
    """Persist an identity with an atomic same-directory replace."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(identity, indent=2, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _normalize_hex64(val: str | None) -> str:
    s = str(val or "")
    if len(s) == 64 and all(c in "0123456789abcdefABCDEF" for c in s):
        return s.lower()
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _record_checkpoint_and_identity(
    core: BrokerCore,
    *,
    task_id: str,
    attempt_id: str,
    runs_dir: Path,
    base_manifest_hash: str,
    bundle_id: str,
    default_resource_id: str,
) -> None:
    fence_row = core.connection.execute(
        "SELECT fencing_token, resource_id FROM leases WHERE attempt_id=? ORDER BY fencing_token DESC LIMIT 1",
        (attempt_id,),
    ).fetchone()
    if fence_row:
        fence = max(1, int(fence_row[0]))
        resource_id = fence_row[1]
    else:
        fence = 1
        resource_id = default_resource_id

    db_base_hash = _normalize_hex64(base_manifest_hash)
    db_bundle_id = _normalize_hex64(bundle_id)
    checkpoint_id = f"chk-{attempt_id}"
    with core.connection:
        # B47: refuse to checkpoint if the attempt doesn't exist in the ledger
        attempt_exists = core.connection.execute(
            "SELECT 1 FROM attempts WHERE attempt_id=?",
            (attempt_id,),
        ).fetchone()
        if not attempt_exists:
            raise RuntimeError(
                f"Cannot record checkpoint: attempt '{attempt_id}' does not exist in the ledger. "
                "The attempt must be created by the execution engine before checkpointing."
            )
        core.connection.execute(
            "INSERT OR IGNORE INTO resources(resource_id, kind, canonical_value, next_fencing_token) VALUES(?, 'EXTERNAL', ?, 0)",
            (resource_id, resource_id),
        )
        existing_chk = core.connection.execute(
            "SELECT 1 FROM checkpoints WHERE checkpoint_id=?",
            (checkpoint_id,),
        ).fetchone()
        core.connection.execute(
            """
            INSERT OR REPLACE INTO checkpoints(checkpoint_id, attempt_id, resource_id, base_manifest_hash, artifact_set_hash, fence)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (checkpoint_id, attempt_id, resource_id, db_base_hash, db_bundle_id, fence),
        )
        if existing_chk is None:
            _event(core.connection, checkpoint_id, "CHECKPOINT_CREATED", {"fence": fence})

    identity_data = {
        "task_id": task_id,
        "run_id": attempt_id,
        "source_hash": f"sha256:{base_manifest_hash}",
        "bundle_id": bundle_id,
    }
    _write_identity(runs_dir / "identity.json", identity_data)


def _event(connection: sqlite3.Connection, aggregate_id: str, kind: str, payload: dict[str, Any]) -> None:
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    connection.execute(
        "INSERT INTO events(aggregate_id,kind,payload_hash,created_at) VALUES(?,?,?,datetime('now'))",
        (aggregate_id, kind, digest),
    )


def _release_active_leases(core: BrokerCore, attempt_id: str) -> None:
    try:
        with core.connection:
            active_leases = core.connection.execute(
                "SELECT lease_id FROM leases WHERE attempt_id=? AND state='ACTIVE'",
                (attempt_id,),
            ).fetchall()
            if active_leases:
                core.connection.execute(
                    "UPDATE leases SET state='RELEASED' WHERE attempt_id=? AND state='ACTIVE'",
                    (attempt_id,),
                )
                for (lid,) in active_leases:
                    _event(core.connection, lid, "LEASE_RELEASED", {"attempt_id": attempt_id})
    except Exception:
        pass


def work_dir_excludes(work_dir: Path, source_dir: Path, task_id: str) -> list[str]:
    """Source-relative paths the pilot itself writes while it hashes the source (U48-W1).

    With the default `--work-dir .coord` the broker DB, its held writer lock, this run's records and the staging copy
    sit inside the source: hashing the lock raised PermissionError, and the run records written mid-run read as
    SOURCE_DIVERGED. Only this task's run folder is excluded, because older run records under runs/ are tracked files.
    """
    try:
        rel = Path(work_dir).resolve().relative_to(Path(source_dir).resolve()).as_posix()
    except ValueError:
        return []  # work dir outside the source: nothing of the pilot's is hashed
    prefix = "" if rel == "." else rel + "/"
    names = ("coord.sqlite3", "coord.sqlite3-wal", "coord.sqlite3-shm", "coord.sqlite3-journal",
             "coord.sqlite3.writer.lock", "stage", f"runs/{task_id}")
    return [prefix + name for name in names]


def reconcile_pilot(*, work_dir: Path, task_id: str) -> dict[str, Any]:
    work_dir = Path(work_dir)
    db_path = work_dir / "coord.sqlite3"
    if not db_path.exists():
        return {"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0}

    core = BrokerCore(db_path)
    core.start()
    try:
        with core.connection:
            target_attempts = core.connection.execute(
                "SELECT attempt_id, idempotency_key FROM attempts WHERE task_id=? AND state IN ('RUNNING','PENDING','VERIFYING','NEEDS_RECONCILIATION')",
                (task_id,),
            ).fetchall()

            if not target_attempts:
                return {"state": "NOTHING_TO_RECONCILE", "reconciled_attempts": 0}

            reconciled_count = len(target_attempts)
            for att_id, idem_key in target_attempts:
                core.connection.execute(
                    "UPDATE attempts SET state='FAILED' WHERE attempt_id=?",
                    (att_id,),
                )
                _event(core.connection, att_id, "ATTEMPT_RECONCILED", {"attempt_id": att_id, "state": "FAILED"})

                core.connection.execute(
                    "UPDATE deliveries SET state='DEAD' WHERE (dedupe_key=? OR dedupe_key LIKE ? OR delivery_id IN (SELECT delivery_id FROM execution_stage_events WHERE attempt_id=?)) AND state IN ('CLAIMED','PENDING')",
                    (idem_key, f"{task_id}:%", att_id),
                )

                active_leases = core.connection.execute(
                    "SELECT lease_id FROM leases WHERE attempt_id=? AND state='ACTIVE'",
                    (att_id,),
                ).fetchall()
                core.connection.execute(
                    "UPDATE leases SET state='REVOKED' WHERE attempt_id=? AND state='ACTIVE'",
                    (att_id,),
                )
                for (lid,) in active_leases:
                    _event(core.connection, lid, "LEASE_REVOKED", {"attempt_id": att_id, "reason": "RECONCILE"})

        runs_dir = work_dir / "runs" / task_id
        runs_dir.mkdir(parents=True, exist_ok=True)
        summary_path = runs_dir / "summary.json"

        staging_dir = work_dir / "stage" / task_id
        abandoned_summary = {
            "state": "ABANDONED",
            "error_class": "ABANDONED",
            "effect_state": "UNKNOWN",
            "promotion": "BLOCKED",
            "bundle_id": None,
            "changed_files": [],
            "conversation_id": None,
            "agy_usage": {},
            "agy_workspace": str(staging_dir),
            "raw_stdout_path": str(runs_dir / f"{task_id}.json"),
            "raw_stderr_path": str(runs_dir / f"{task_id}.err"),
            "summary_path": str(summary_path),
            "acceptance_exit": None,
            "verdict_hint": "BLOCKED",
        }
        if summary_path.is_file():
            try:
                existing = json.loads(summary_path.read_text(encoding="utf-8"))
                existing.update({
                    "state": "ABANDONED",
                    "error_class": "ABANDONED",
                    "effect_state": "UNKNOWN",
                    "promotion": "BLOCKED",
                    "acceptance_exit": None,
                    "verdict_hint": "BLOCKED",
                })
                abandoned_summary = existing
            except Exception:
                pass
        _write_summary(summary_path, abandoned_summary)

        return {"state": "ABANDONED", "reconciled_attempts": reconciled_count}
    finally:
        core.close()


def run_pilot(config: PilotConfig) -> dict[str, Any]:
    # U74-A: the ledger row's wall time. Seen 2026-09-28 (U72): every pilot row had wall_time_s null, so the cost
    # evidence fell back to the full-suite times written by hand in PLAN.
    started_monotonic = time.monotonic()
    # 1. work_dir creation, db = work_dir / "coord.sqlite3", BrokerCore(db).start()
    work_dir = Path(config.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    runs_dir = work_dir / "runs" / config.task_id
    runs_dir.mkdir(parents=True, exist_ok=True)
    summary_path = runs_dir / "summary.json"
    source_excludes = work_dir_excludes(work_dir, Path(config.source_dir), config.task_id)

    db_path = work_dir / "coord.sqlite3"
    core = BrokerCore(db_path)
    core.start()

    try:
        # Check for unreconciled attempts first
        unreconciled = core.connection.execute(
            "SELECT attempt_id, state FROM attempts WHERE task_id=? AND state IN ('RUNNING','PENDING','VERIFYING','NEEDS_RECONCILIATION')",
            (config.task_id,),
        ).fetchall()
        if unreconciled:
            staging_dir = work_dir / "stage" / config.task_id
            summary = {
                "state": "FAILED",
                "error_class": "NEEDS_RECONCILIATION",
                "effect_state": "UNKNOWN",
                "promotion": "BLOCKED",
                "bundle_id": None,
                "changed_files": [],
                "conversation_id": None,
                "agy_usage": {},
                "agy_workspace": str(staging_dir),
                "raw_stdout_path": str(runs_dir / f"{config.task_id}.json"),
                "raw_stderr_path": str(runs_dir / f"{config.task_id}.err"),
                "summary_path": str(summary_path),
                "acceptance_exit": None,
                "verdict_hint": "BLOCKED",
                "next_action": f"python -m v7_harness.cli pilot reconcile --task {config.task_id}",
            }
            _write_summary(summary_path, summary)
            return summary

        # 2. set_quota_state
        task_scope_id = f"pilot:{config.task_id}"
        set_quota_state(
            core.connection,
            scope_id=task_scope_id,
            provider="antigravity",
            quota_state="AVAILABLE",
        )

        # 3. command definition
        prompt_hash = hashlib.sha256(config.prompt.encode("utf-8")).hexdigest()
        acceptance_hash = prompt_hash

        attempts_rows = core.connection.execute(
            "SELECT attempt_id FROM attempts WHERE task_id=?",
            (config.task_id,),
        ).fetchall()
        n = len(attempts_rows)
        dead_delivery = core.connection.execute(
            "SELECT 1 FROM deliveries WHERE state='DEAD' AND (dedupe_key LIKE ? OR delivery_id LIKE ?)",
            (f"{config.task_id}:%", f"{config.task_id}-cmd%"),
        ).fetchone()

        is_already_succeeded = False
        if summary_path.is_file():
            try:
                saved_summary = json.loads(summary_path.read_text(encoding="utf-8"))
                if saved_summary.get("state") == "SUCCEEDED":
                    is_already_succeeded = True
            except Exception:
                pass

        if n > 0 and dead_delivery is not None and not is_already_succeeded:
            attempt_id = f"{config.task_id}-a{n+1:03d}"
            command_id = f"{config.task_id}-cmd-r{n+1}"
            idempotency_key = f"{config.task_id}:{acceptance_hash}:r{n+1}"
        else:
            if is_already_succeeded and n > 0:
                attempt_id = attempts_rows[-1][0]
                if n == 1:
                    command_id = f"{config.task_id}-cmd"
                    idempotency_key = f"{config.task_id}:{acceptance_hash}"
                else:
                    command_id = f"{config.task_id}-cmd-r{n}"
                    idempotency_key = f"{config.task_id}:{acceptance_hash}:r{n}"
            else:
                attempt_id = f"{config.task_id}-a001"
                command_id = f"{config.task_id}-cmd"
                idempotency_key = f"{config.task_id}:{acceptance_hash}"

        command = {
            "schema_version": 1,
            "command_id": command_id,
            "task_id": config.task_id,
            "card_revision": 1,
            "acceptance_hash": acceptance_hash,
            "idempotency_key": idempotency_key,
            "operation": "DISPATCH",
            "payload_ref": f"prompt:{config.task_id}",
            "scope_id": task_scope_id,
            "provider": "antigravity",
            "resource_id": f"res-{config.task_id}",
            "attempt_id": attempt_id,
            "owner": "antigravity",
        }

        # Filter schema-conforming fields for BrokerCore.enqueue document validation
        enqueue_payload = {
            "schema_version": command["schema_version"],
            "command_id": command["command_id"],
            "task_id": command["task_id"],
            "card_revision": command["card_revision"],
            "acceptance_hash": command["acceptance_hash"],
            "idempotency_key": command["idempotency_key"],
            "operation": command["operation"],
            "payload_ref": command["payload_ref"],
        }
        enqueue_res = core.enqueue(enqueue_payload)

        # 4. Check for replay
        if summary_path.is_file() and enqueue_res.get("duplicate") is True:
            saved = json.loads(summary_path.read_text(encoding="utf-8"))
            if saved.get("state") != "ABANDONED":
                replayed_summary = dict(saved)
                replayed_summary["replayed"] = True

                if config.approve_bundle_id is not None:
                    if saved.get("state") != "SUCCEEDED" or saved.get("verdict_hint") in ("REWORK", "BLOCKED"):
                        replayed_summary["promotion"] = "BLOCKED"
                        return replayed_summary
                    # B85 rework (Codex): a paid run is promotable only with a recorded WITHIN gate, whatever
                    # worker or flags the approval call itself names.
                    try:
                        built_by = (runs_dir / "worker").read_text(encoding="utf-8").strip()
                    except OSError:
                        built_by = ""
                    paid = built_by in PAID_WORKERS or worker_label(config.agy_command) in PAID_WORKERS
                    if (paid or config.remote_budget_tokens) and saved.get("cost_gate") != "WITHIN":
                        replayed_summary["promotion"] = "BLOCKED"
                        replayed_summary["error_detail"] = f"COST_GATE_NOT_WITHIN:{saved.get('cost_gate')}"
                        return replayed_summary
                    saved_bundle_id = saved.get("bundle_id")
                    if saved.get("promotion") == "APPLIED" and config.approve_bundle_id == saved_bundle_id:
                        return replayed_summary
                    if config.approve_bundle_id != saved_bundle_id:
                        replayed_summary["promotion"] = "APPROVAL_MISMATCH"
                        return replayed_summary

                    staging_dir = work_dir / "stage" / config.task_id
                    base_manifest = build_manifest(Path(config.source_dir), excludes=source_excludes)
                    replay_workspace = StagingWorkspace(
                        source_dir=Path(config.source_dir).resolve(),
                        staging_dir=staging_dir.resolve(),
                        base_manifest=base_manifest,
                        base_manifest_hash=base_manifest.manifest_hash,
                        excludes=source_excludes,
                    )
                    replay_bundle = replay_workspace.create_patch_bundle()
                    if replay_bundle.bundle_id != saved_bundle_id:
                        replayed_summary["promotion"] = "APPROVAL_MISMATCH"
                        return replayed_summary
                    apply_promotion(
                        source_dir=Path(config.source_dir),
                        staging_dir=staging_dir,
                        patch_bundle=replay_bundle,
                        approve_bundle_id=config.approve_bundle_id,
                        excludes=source_excludes,
                    )
                    replayed_summary["promotion"] = "APPLIED"
                    try:
                        _record_checkpoint_and_identity(
                            core,
                            task_id=config.task_id,
                            attempt_id=attempt_id,
                            runs_dir=runs_dir,
                            base_manifest_hash=replay_workspace.base_manifest_hash,
                            bundle_id=replay_bundle.bundle_id,
                            default_resource_id=f"res-{config.task_id}",
                        )
                    except RuntimeError as _chk_err:
                        replayed_summary["error_detail"] = f"CHECKPOINT_REFUSED: {_chk_err}"
                    _write_summary(summary_path, replayed_summary)
                return replayed_summary

        # 5. Staging directory setup
        staging_dir = work_dir / "stage" / config.task_id
        workspace = NonGitStagingAdapter(excludes=source_excludes).create_staging(config.source_dir, staging_dir)

        # 6. AgyRequest (isolation_mode derived exclusively from workspace object)
        request = AgyRequest(
            task_id=config.task_id,
            title=config.title,
            prompt=config.prompt,
            workspace=workspace.staging_dir,
            isolation_mode=_derive_isolation_mode(workspace),
            print_timeout_s=config.print_timeout_s,
            model=config.model,
        )

        # 7. Watch roots snapshot (B46: retry once on transient scan failure)
        stage_root = (work_dir / "stage").resolve()
        watch_roots = list(dict.fromkeys(list(config.watch_roots) + [stage_root]))
        _watch_scan_err: WatchScanUnavailableError | None = None
        for _watch_try in range(2):
            try:
                watch = snapshot_watch_roots(
                    watch_roots,
                    excludes=[config.task_id, f"{config.task_id}/**"],
                )
                _watch_scan_err = None
                break
            except WatchScanUnavailableError as exc:
                _watch_scan_err = exc
                if _watch_try == 0:
                    time.sleep(1)

        if _watch_scan_err is not None:
            # Persistent instability — return structured summary without running agy
            staging_dir = work_dir / "stage" / config.task_id
            error_detail = str(_watch_scan_err)[:300]
            summary: dict[str, Any] = {
                "state": "FAILED",
                "error_class": "WATCH_SCAN_UNAVAILABLE",
                "effect_state": "UNKNOWN",
                "promotion": "BLOCKED",
                "bundle_id": None,
                "changed_files": [],
                "conversation_id": None,
                "agy_usage": {},
                "agy_workspace": str(staging_dir),
                "raw_stdout_path": str(runs_dir / f"{config.task_id}.json"),
                "raw_stderr_path": str(runs_dir / f"{config.task_id}.err"),
                "summary_path": str(summary_path),
                "acceptance_exit": None,
                "verdict_hint": "BLOCKED",
                "error_detail": error_detail,
            }
            _write_summary(summary_path, summary)
            return summary

        # 8. Launcher and execution engine
        launcher = AgyProcessLauncher(
            agy_command=config.agy_command,
            request=request,
            runs_dir=runs_dir,
        )
        engine = DurableExecutionEngine(core, launcher=launcher)

        execute_error: Exception | None = None
        try:
            engine.execute(
                command,
                worker_capability="effectful",
                timeout_sec=config.print_timeout_s + 60,
            )
        except Exception as exc:
            execute_error = exc

        # 9. Watch roots invariant check
        watch_error: tuple[str, str] | None = None
        external_paths: list[str] = []
        try:
            watch.assert_unchanged()
        except ExternalWriteDetectedError as exc:
            watch_error = ("EXTERNAL_WRITE", "UNKNOWN")
            external_paths = list(getattr(exc, "changed_paths", []))
        except WatchScanUnavailableError:
            watch_error = ("WATCH_SCAN_UNAVAILABLE", "UNKNOWN")
        except Exception:
            watch_error = ("EXTERNAL_WRITE", "UNKNOWN")

        # 10. Success check and bundle creation
        outcome: AgyOutcome | None = launcher.last_outcome
        is_success = (
            outcome is not None
            and outcome.successful
            and execute_error is None
            and watch_error is None
        )

        bundle: PatchBundle | None = None
        bundle_id: str | None = None
        changed_files: list[str] = []
        acceptance_exit: int | None = None
        accept_log_path: Path | None = None
        _accept_not_run: str | None = None
        _scope_detail: str | None = None
        rework_class: str | None = None
        _rework_sig = ""
        verdict_hint: str = "BLOCKED"
        _checkpoint_refused: str | None = None

        cost_gate = None
        if is_success:
            state = "SUCCEEDED"
            error_class = "NONE"
            effect_state = "CONFIRMED"

            bundle = workspace.create_patch_bundle()
            bundle_id = bundle.bundle_id
            changed_files = sorted(item.path for item in bundle.items)

            try:
                _record_checkpoint_and_identity(
                    core,
                    task_id=config.task_id,
                    attempt_id=attempt_id,
                    runs_dir=runs_dir,
                    base_manifest_hash=workspace.base_manifest_hash,
                    bundle_id=bundle_id,
                    default_resource_id=f"res-{config.task_id}",
                )
            except RuntimeError as _chk_err:
                _checkpoint_refused = f"CHECKPOINT_REFUSED: {_chk_err}"

            dry_run_passed = False
            try:
                dry = dry_run_promotion(
                    source_dir=config.source_dir, patch_bundle=bundle, allowed_scopes=config.allowed_scopes,
                    excludes=source_excludes,
                )
                promotion = "DRY_RUN_PASSED" if dry.success else dry.status
                dry_run_passed = dry.success
            except SourceDivergenceError:
                state = "FAILED"
                error_class = "SOURCE_DIVERGED"
                promotion = "REJECTED"
                verdict_hint = "BLOCKED"
            except ScopeExpansionError as exc:
                # The worker changed a file the manual does not allow: its output is wrong, the environment is fine.
                # REWORK (not BLOCKED) so the sentinel does not page the commander for a worker mistake.
                error_class = "SCOPE_VIOLATION"
                promotion = "REJECTED"
                verdict_hint = "REWORK"
                _scope_detail = str(exc)[:300]
            except IsolationError as exc:
                state = "FAILED"
                error_class = getattr(exc, "error_class", "ISOLATION_ERROR")
                promotion = "REJECTED"
                verdict_hint = "BLOCKED"

            if dry_run_passed and config.accept_cmd is not None:
                has_shell_ops = any(op in config.accept_cmd for op in ("|", "&&", "||", ";", ">", "<"))
                accept_stdout = b""
                accept_stderr = b""
                try:
                    if has_shell_ops:
                        res = subprocess.run(
                            config.accept_cmd,
                            cwd=str(workspace.staging_dir),
                            shell=True,
                            timeout=300,
                            capture_output=True,
                        )
                    else:
                        tokens = _resolve_accept_tokens(config.accept_cmd)
                        res = subprocess.run(
                            tokens,
                            cwd=str(workspace.staging_dir),
                            shell=False,
                            timeout=300,
                            capture_output=True,
                        )
                    acceptance_exit = res.returncode
                    accept_stdout = res.stdout or b""
                    accept_stderr = res.stderr or b""
                except subprocess.TimeoutExpired as te:
                    acceptance_exit = 124
                    accept_stdout = te.stdout or b""
                    accept_stderr = te.stderr or b""
                except Exception as exc:
                    # U18: 인수 명령을 띄우지 못했으면 작업자 결과를 잰 적이 없다. REWORK 로 두면 cascade 가
                    # 같은 이유로 실패할 lane 을 또 돌린다.
                    acceptance_exit = None
                    _accept_not_run = f"{type(exc).__name__}: {exc}"[:300]

                # Save acceptance log (last 4000 chars of combined stdout+stderr)
                accept_log_path = runs_dir / "acceptance.log"
                try:
                    combined = accept_stdout + b"\n--- STDERR ---\n" + accept_stderr
                    # U52: head+tail with a marked cut instead of a silent tail; the full log sits beside it.
                    from .output_gate import gate_output

                    gated = gate_output(combined.decode("utf-8", "replace"), 4000,
                                        runs_dir / "acceptance.full.log")
                    accept_log_path.write_text(gated.text, encoding="utf-8", errors="replace")
                except OSError:
                    pass

                if _accept_not_run is not None:
                    verdict_hint = "BLOCKED"
                    error_class = "ACCEPT_NOT_RUN"
                elif acceptance_exit == 0:
                    verdict_hint = "PASS"
                else:
                    # U18: 실패 원인을 나눈다. INFRA 만 멈추고 CODE·UNKNOWN 은 지금처럼 REWORK(cascade 승격).
                    # 분류는 4000바이트로 자르기 전 전체 출력으로 한다.
                    changed_texts = []
                    for rel in changed_files:
                        try:
                            changed_texts.append((workspace.staging_dir / rel).read_text(encoding="utf-8", errors="replace"))
                        except OSError:
                            pass
                    rework_class, _rework_sig = classify_acceptance(
                        (accept_stdout + b"\n" + accept_stderr).decode("utf-8", "replace"), acceptance_exit,
                        changed_files, changed_texts, workspace.staging_dir)
                    if rework_class == "INFRA":
                        verdict_hint = "BLOCKED"
                        error_class = "ACCEPT_INFRA"
                    else:
                        verdict_hint = "REWORK"
            elif dry_run_passed:
                acceptance_exit = None
                verdict_hint = "NEEDS_ACCEPTANCE"

            # B30: no-change verdict — REWORK unless allow_no_changes
            if not changed_files and verdict_hint not in ("REWORK", "BLOCKED"):
                if not config.allow_no_changes:
                    verdict_hint = "REWORK"

            # B85: a paid worker that went over its budget (or did not say what it spent) is not promotable.
            if config.remote_budget_tokens:
                cost_gate = evaluate_cost_gate(outcome.usage if outcome else None, int(config.remote_budget_tokens))
                if cost_gate != "WITHIN":
                    verdict_hint = "BLOCKED"
                    error_class = "COST_UNKNOWN" if cost_gate == "UNKNOWN" else "COST_EXCEEDED"

            # 11. Approval promotion handling
            if config.approve_bundle_id is not None:
                if verdict_hint in ("REWORK", "BLOCKED"):
                    promotion = "BLOCKED"
                elif worker_label(config.agy_command) in PAID_WORKERS and cost_gate != "WITHIN":
                    # B85 rework: a paid run approved in the same call still needs its budget measured as WITHIN.
                    promotion = "BLOCKED"
                elif config.approve_bundle_id == bundle.bundle_id:
                    try:
                        apply_promotion(
                            source_dir=config.source_dir,
                            staging_dir=workspace.staging_dir,
                            patch_bundle=bundle,
                            approve_bundle_id=config.approve_bundle_id,
                            excludes=source_excludes,
                        )
                        promotion = "APPLIED"
                    except SourceDivergenceError:
                        promotion = "REJECTED"
                        state = "FAILED"
                        error_class = "SOURCE_DIVERGED"
                        verdict_hint = "BLOCKED"
                    except IsolationError as exc:
                        promotion = "REJECTED"
                        state = "FAILED"
                        error_class = getattr(exc, "error_class", "ISOLATION_ERROR")
                        verdict_hint = "BLOCKED"
                else:
                    promotion = "APPROVAL_MISMATCH"
        else:
            state = "FAILED"
            promotion = "BLOCKED"
            acceptance_exit = None
            verdict_hint = "BLOCKED"
            if watch_error is not None:
                error_class = watch_error[0]
                effect_state = watch_error[1]
            elif outcome is not None:
                error_class = outcome.error_class
                effect_state = outcome.effect_state if outcome.effect_state in ("CONFIRMED", "UNKNOWN") else "UNKNOWN"
            elif isinstance(execute_error, WorkerExecutionError):
                error_class = getattr(execute_error, "error_class", "EXECUTION_ERROR")
                effect_state = "UNKNOWN"
            elif execute_error is not None:
                # Extract meaningful error_class from non-worker execution errors
                # (CircuitOpenError, QuotaFailClosedError, etc.)
                error_class = getattr(execute_error, "error_class", None) or str(execute_error).split("(")[0].split(":")[0].strip() or "EXECUTION_ERROR"
                effect_state = "UNKNOWN"
            else:
                error_class = "EXECUTION_ERROR"
                effect_state = "UNKNOWN"

        raw_stdout = launcher.raw_paths[0] if launcher.raw_paths else runs_dir / f"{attempt_id}.json"
        raw_stderr = launcher.raw_paths[1] if launcher.raw_paths else runs_dir / f"{attempt_id}.err"

        # Release active leases after finished run
        _release_active_leases(core, attempt_id)

        # 12. Summary
        summary: dict[str, Any] = {
            "state": state,
            "error_class": error_class,
            "effect_state": effect_state,
            "promotion": promotion,
            "bundle_id": bundle_id,
            "changed_files": changed_files,
            "conversation_id": outcome.conversation_id if outcome else None,
            "agy_usage": outcome.usage if outcome else {},
            "agy_workspace": str(workspace.staging_dir),
            "raw_stdout_path": str(raw_stdout),
            "raw_stderr_path": str(raw_stderr),
            "summary_path": str(summary_path),
            "acceptance_exit": acceptance_exit,
            "verdict_hint": verdict_hint,
        }

        # Which worker built this bundle, beside the summary (the summary stays within its key budget). `pilot review`
        # reads it so a reviewer never reviews its own worker's bundle (U38).
        try:
            (runs_dir / "worker").write_text(worker_label(config.agy_command), encoding="utf-8")
        except OSError:
            pass
        if config.remote_budget_tokens and cost_gate is None:
            # A failed run spent tokens too; record the gate even though there is nothing to promote.
            cost_gate = evaluate_cost_gate(outcome.usage if outcome else None, int(config.remote_budget_tokens))
        if cost_gate is not None:
            summary["cost_gate"] = cost_gate
            summary["remote_budget_tokens"] = int(config.remote_budget_tokens)

        # B30: no-change reason
        if not changed_files and verdict_hint == "REWORK" and state == "SUCCEEDED":
            summary["reason"] = "NO_CHANGES"

        # B30: acceptance_log_path
        if accept_log_path is not None and accept_log_path.is_file():
            summary["acceptance_log_path"] = str(accept_log_path)

        # B30: error_detail for non-worker errors
        if execute_error is not None and state == "FAILED":
            detail = f"{type(execute_error).__name__}: {execute_error}"
            summary["error_detail"] = detail[:300]
        if _scope_detail is not None:
            summary["error_detail"] = _scope_detail

        # U18: 인수 실패 원인. 14키 밖 선택 키라 PASS·미실행 요약에는 넣지 않는다.
        if rework_class is not None:
            summary["rework_class"] = rework_class
            if _rework_sig:
                summary.setdefault("error_detail", _rework_sig)
        if _accept_not_run is not None:
            summary.setdefault("error_detail", _accept_not_run)

        # B52: checkpoint refusal must not be hidden
        if _checkpoint_refused is not None:
            summary.setdefault("error_detail", _checkpoint_refused)

        if state == "FAILED" and (error_class in ("TIMEOUT", "NEEDS_RECONCILIATION") or effect_state == "UNKNOWN"):
            summary["next_action"] = f"python -m v7_harness.cli pilot reconcile --task {config.task_id}"

        # B41: external_paths for EXTERNAL_WRITE
        if external_paths and error_class == "EXTERNAL_WRITE":
            summary["external_paths"] = external_paths

        # 13. Persist summary and return
        _write_summary(summary_path, summary)

        # U27 / RSI: Automatically record run into usage ledger for zero-cost tracking
        try:
            from v7_harness.coord.usage_ledger import record_usage
            proj_root = config.source_dir.resolve()
            if (proj_root / ".git").is_dir() or (proj_root / ".coord" / "PLAN.md").is_file():
                command_text = " ".join(str(c) for c in config.agy_command)
                worker_type = worker_label(config.agy_command)
                usage_dict = outcome.usage if outcome else {}
                in_tok = usage_dict.get("input_tokens")
                out_tok = usage_dict.get("output_tokens")
                input_tokens = int(in_tok) if (in_tok is not None and not isinstance(in_tok, bool)) else None
                output_tokens = int(out_tok) if (out_tok is not None and not isinstance(out_tok, bool)) else None
                ledger_entry = {
                    "schema": "uaos-usage-v2",
                    "work_id": config.task_id,
                    "actor": "coordinator",
                    "model": config.model or {"ollama": "qwen2.5-coder:7b", "apply": "deterministic"}.get(worker_type),
                    "kind": "pilot",
                    "collection_mode": "automatic",
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "wall_time_s": round(time.monotonic() - started_monotonic, 3),
                    "outcome": verdict_hint,
                    "receipt": str(summary_path),
                    "independent_verifier": None,
                    "rsi_eligible": False,
                    "exclusion_reason": "PENDING_INDEPENDENT_VERIFICATION",
                    "worker": worker_type,
                    "delegator": delegator(),
                    "exit_code": acceptance_exit if acceptance_exit is not None else (0 if state == "SUCCEEDED" else 1),
                    "bundle_id": bundle_id,
                    "rework_class": rework_class,
                    # RSI groups failures by cause; verdict_hint alone cannot tell SCOPE_VIOLATION from a failed test.
                    "error_class": error_class,
                    "error_detail": summary.get("error_detail"),
                }
                # U38: cached tokens and the dollar cost, when the worker reports them (Claude does).
                for extra in ("cache_creation_input_tokens", "cache_read_input_tokens", "cost_microusd",
                              "usd_cap_overshoot_microusd"):
                    value = usage_dict.get(extra) if isinstance(usage_dict, dict) else None
                    if isinstance(value, int) and not isinstance(value, bool):
                        ledger_entry[extra] = value
                if summary.get("cost_gate"):
                    ledger_entry["cost_gate"] = summary["cost_gate"]
                record_usage(proj_root, ledger_entry)
        except Exception as ledger_exc:
            summary["usage_ledger_error"] = f"{type(ledger_exc).__name__}: {ledger_exc}"[:300]
            _write_summary(summary_path, summary)

        return summary
    finally:
        core.close()
===FILE: v7_harness/model_qualification.py===
"""U51: task-specific model qualification gate bound to execution provenance. docs/49 §2·§5 U-MQ-1.

"The model runs in Ollama" is not "the model may do this task". A model is QUALIFIED per task type only when a
deterministic source check passes on outputs that this module itself obtained from the provider, and the verdict is
tied to the digest the provider reports, not to a name somebody typed.

Two commands, two kinds of evidence (Codex U51-R1b verdict: a hand-made output file scored under any typed identity
forged a QUALIFIED record):
- `score`   scores existing output files. Evidence kind SCORER_ONLY: it prints, it never records, and it takes no
            provider, model or digest, so no identity can be attached to outputs it did not see produced.
- `qualify` calls the provider itself for every source, reads the model digest from the provider before and after the
            run, hashes source, prompt and output into one receipt per call, scores those outputs and only then
            records. A typed --expect-digest that differs from the provider's digest is refused (IDENTITY_MISMATCH).
`lookup` accepts only records that carry receipts for the asked digest.

Limit, stated: a record file is still plain JSON in the user's own account; someone who edits it by hand can forge
it (B83: a label in the same account is not authentication). The gate stops the tool path from minting a verdict for
a model that never ran; it does not defend against the account owner.

Usage: python -m v7_harness.model_qualification qualify --model qwen3.5-32k --sources <dir> --record <dir>
       python -m v7_harness.model_qualification score --runs <dir> --sources <dir> [--pattern art*.json]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

# A task type is QUALIFIED when at least this share of items passes the source check. 0.8 = at most one item in five
# is thrown away by the independent gate; below that the checking and rework cost more than the local call saves.
# Initial value, to be re-tuned after three fixture runs (docs/49 §5 U-MQ-1).
QUALIFY_MIN = 0.8
# Fewer checked items than this cannot qualify: one lucky pass out of two says nothing about the model.
MIN_ITEMS = 20
TASK_TYPES = ("list_extract", "verbatim_quote")
# Another writer holds the target only for the length of its own replace (milliseconds), so 50 tries x 10 ms
# bounds the wait at 0.5 s before the error surfaces.
REPLACE_TRIES = 50
REPLACE_WAIT_S = 0.01
STATUSES = ("QUALIFIED", "REJECTED", "UNQUALIFIED", "UNQUALIFIED_DIGEST_CHANGED")
EVIDENCE = "PROVENANCE_BOUND"
# Each source asks for at most this many items; an output that does not parse counts as this many failed items, so a
# broken answer lowers the share instead of shrinking the denominator.
MAX_CANDIDATES = 6
# The docs/49 extraction contract (.work/article_ollama_20260927/extract.py), reduced to the two scored fields.
EXTRACT_PROMPT = """TASK: extract, do not judge. Output one JSON object only:
{{"candidates": [{{"name": str (the item's name as written in the document), "quote": str (EXACT substring copied from
the document, 10-80 chars)}}] (max {m})}}
Forbidden: inventing text not in the document; paraphrasing inside "quote".
Every name and quote is checked as a literal substring of the document by an independent script.

DOCUMENT (sha256={h}):
{text}"""
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
# One article of ~20 KB Korean took up to 72 s in docs/49; 900 s leaves room for a cold model load.
CALL_TIMEOUT_S = 900


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def candidate_key(name: str) -> str:
    """The item name without the model's appended explanation ("C09 — Firewall" -> "C09", "X :: y" -> "X")."""
    return re.split(r" — | ::", name or "")[0].strip()


def score_extraction(candidates: list[dict[str, Any]], source_text: str) -> dict[str, tuple[int, int]]:
    """Per task type: (items passing the literal source check, items checked)."""
    flat = _norm(source_text)
    names = [candidate_key(str(c.get("name") or "")) for c in candidates]
    quotes = [_norm(str(c.get("quote") or "")) for c in candidates]

    def passed(items: list[str], haystack: str) -> int:
        # U70: a repeated item is a failed item. U67-O1b answered with duplicates, and each copy of a true item used
        # to count as another pass, so repeating one easy line could lift a model over QUALIFY_MIN.
        seen: set[str] = set()
        count = 0
        for item in items:
            if item and item not in seen and item in haystack:
                count += 1
            seen.add(item)
        return count

    return {
        "list_extract": (passed(names, source_text), len(names)),
        "verbatim_quote": (passed(quotes, flat), len(quotes)),
    }


def score_output(output: str, source_text: str) -> dict[str, tuple[int, int]]:
    """Score one raw model answer; an answer without a candidates list fails MAX_CANDIDATES items per task."""
    try:
        data = json.loads(output)
        candidates = data.get("candidates") if isinstance(data, dict) else None
    except json.JSONDecodeError:
        candidates = None
    if not isinstance(candidates, list):
        return {t: (0, MAX_CANDIDATES) for t in TASK_TYPES}
    return score_extraction([c for c in candidates if isinstance(c, dict)], source_text)


def verdict(passed: int, total: int) -> str:
    if total < MIN_ITEMS:
        return "UNQUALIFIED"
    return "QUALIFIED" if passed / total >= QUALIFY_MIN else "REJECTED"


def score_fixture(runs_dir: Path, sources_dir: Path, pattern: str = "art*.json") -> dict[str, Any]:
    """SCORER_ONLY: score saved outputs against their sources. The result names no model and is never recorded."""
    totals = {t: [0, 0] for t in TASK_TYPES}
    files = sorted(Path(runs_dir).glob(pattern))
    if not files:
        raise ValueError(f"NO_FIXTURE: no {pattern} in {runs_dir}")
    for path in files:
        run = json.loads(path.read_text(encoding="utf-8"))
        meta, data = run["meta"], run.get("data") or {}
        # The pin is the sha256 of the text as Python reads it (newlines normalised to \n), the same text the model
        # was given, so a CRLF checkout of an unchanged document still matches.
        text = (Path(sources_dir) / meta["file"]).read_text(encoding="utf-8")
        if _sha(text) != meta["sha256"]:
            raise ValueError(f"SOURCE_HASH_MISMATCH:{meta['file']}")
        candidates = data.get("candidates") if isinstance(data, dict) else None
        for task, (ok, n) in score_extraction(candidates or [], text).items():
            totals[task][0] += ok
            totals[task][1] += n
    return {"evidence": "SCORER_ONLY", "items": len(files),
            "tasks": {t: {"passed": p, "total": n, "verdict": verdict(p, n)} for t, (p, n) in totals.items()}}


class Provider(Protocol):
    name: str

    def digest(self, model: str) -> str | None: ...

    def generate(self, model: str, prompt: str) -> tuple[str, dict[str, int]]: ...


class OllamaProvider:
    """The local Ollama API: the digest comes from /api/tags, the answer from /api/chat (temperature 0, JSON)."""

    name = "ollama"

    def __init__(self, host: str = OLLAMA_HOST) -> None:
        self.host = host

    def digest(self, model: str) -> str | None:
        with urllib.request.urlopen(f"{self.host}/api/tags", timeout=10) as response:
            tags = json.loads(response.read().decode("utf-8"))
        wanted = {model, f"{model}:latest"}
        for row in tags.get("models", []):
            if row.get("name") in wanted or row.get("model") in wanted:
                return str(row.get("digest") or "") or None
        return None

    def generate(self, model: str, prompt: str) -> tuple[str, dict[str, int]]:
        body = json.dumps({"model": model, "stream": False, "format": "json", "think": False,
                           "options": {"temperature": 0, "num_ctx": 32768},
                           "messages": [{"role": "user", "content": prompt}]}).encode("utf-8")
        request = urllib.request.Request(f"{self.host}/api/chat", body, {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=CALL_TIMEOUT_S) as response:
            raw = json.loads(response.read().decode("utf-8"))
        usage = {"input_tokens": int(raw.get("prompt_eval_count") or 0), "output_tokens": int(raw.get("eval_count") or 0)}
        return str((raw.get("message") or {}).get("content") or ""), usage


@dataclass(frozen=True)
class Receipt:
    """One provider call: who answered (digest read from the provider), on what (source, prompt), with what (output)."""
    provider: str
    model: str
    digest: str
    source_file: str
    source_sha256: str
    prompt_sha256: str
    output_sha256: str
    started_at: float
    elapsed_s: float
    input_tokens: int
    output_tokens: int


def measure(provider: Provider, model: str, sources: list[Path]) -> tuple[list[Receipt], list[str], list[str]]:
    """Run the extraction on every source through the provider. The digest is read before and after; a model that is
    missing or was replaced during the run yields no receipts."""
    before = provider.digest(model)
    if not before:
        raise ValueError(f"MODEL_NOT_INSTALLED:{provider.name}/{model}")
    receipts, outputs, texts = [], [], []
    for path in sources:
        text = Path(path).read_text(encoding="utf-8")
        prompt = EXTRACT_PROMPT.format(m=MAX_CANDIDATES, h=_sha(text), text=text)
        started = time.time()
        output, usage = provider.generate(model, prompt)
        receipts.append(Receipt(provider.name, model, before, Path(path).name, _sha(text), _sha(prompt), _sha(output),
                                round(started, 3), round(time.time() - started, 3),
                                usage.get("input_tokens", 0), usage.get("output_tokens", 0)))
        outputs.append(output)
        texts.append(text)
    after = provider.digest(model)
    if after != before:
        raise ValueError(f"DIGEST_CHANGED_DURING_RUN:{before}->{after}")
    return receipts, outputs, texts


def _key(provider: str, model: str, task_type: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", f"{provider}__{model}__{task_type}")


def _write(store: Path, name: str, entry: dict[str, Any]) -> None:
    """Atomic write (temp file + os.replace): parallel writers never leave a half-written record."""
    store = Path(store)
    store.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=store, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(entry, handle, ensure_ascii=False, indent=1)
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, store / f"{name}.json")
            return
        except PermissionError:
            # Windows refuses a replace while another writer's replace holds the target (U51 8-thread test).
            if attempt == REPLACE_TRIES - 1:
                Path(tmp).unlink(missing_ok=True)
                raise
            time.sleep(REPLACE_WAIT_S)


def qualify(store: Path, provider: Provider, model: str, sources: list[Path],
            expect_digest: str | None = None) -> dict[str, Any]:
    """Measure, verify the provenance, score and record one verdict per task type."""
    if not sources:
        raise ValueError("NO_SOURCES")
    if expect_digest:
        actual = provider.digest(model)
        if actual != expect_digest:
            raise ValueError(f"IDENTITY_MISMATCH: expected digest {expect_digest}, provider reports {actual}")
    receipts, outputs, texts = measure(provider, model, sources)
    totals = {t: [0, 0] for t in TASK_TYPES}
    for receipt, output, text in zip(receipts, outputs, texts):
        # Re-check each receipt against the bytes it describes before any of them may count.
        if receipt.output_sha256 != _sha(output) or receipt.source_sha256 != _sha(text):
            raise ValueError(f"RECEIPT_MISMATCH:{receipt.source_file}")
        for task, (ok, n) in score_output(output, text).items():
            totals[task][0] += ok
            totals[task][1] += n
    digest = receipts[0].digest
    result = {"provider": provider.name, "model": model, "digest": digest, "tasks": {}}
    for task, (passed, total) in totals.items():
        entry = {"evidence": EVIDENCE, "provider": provider.name, "model": model, "digest": digest,
                 "task_type": task, "passed": passed, "total": total, "verdict": verdict(passed, total),
                 "qualify_min": QUALIFY_MIN, "receipts": [asdict(r) for r in receipts]}
        _write(store, _key(provider.name, model, task), entry)
        result["tasks"][task] = {"passed": passed, "total": total, "verdict": entry["verdict"]}
    result["usage_ledger"] = record_qualification_usage(store, result, [asdict(r) for r in receipts])
    return result


def record_qualification_usage(store: Path, result: dict[str, Any], receipts: list[dict[str, Any]]) -> str | None:
    """U74-B: one usage-ledger row for a qualification run, when the store is a project's `.coord/qualification`.

    Seen 2026-09-28 (U72): the U70/U71 qualification calls spent local tokens that only the qualification records
    held; the ledger had no row. A store elsewhere (a test folder, a scratch copy) has no project ledger: None.
    A ledger failure is reported, never allowed to undo a verdict that is already written.
    """
    store = Path(store).resolve()
    if store.name != QUALIFICATION_STORE.name or store.parent.name != QUALIFICATION_STORE.parent.name:
        return None
    from .coord.usage_ledger import UsageRejected, record_usage

    entry = {
        "schema": "uaos-usage-v2", "work_id": f"QUALIFY-{result['model']}-{str(result['digest'])[:12]}",
        "actor": "coordinator", "worker": result["provider"], "model": result["model"], "kind": "qualification",
        "collection_mode": "automatic",
        "input_tokens": sum(int(r["input_tokens"]) for r in receipts),
        "output_tokens": sum(int(r["output_tokens"]) for r in receipts),
        # A local model has no prompt cache; zeros make the four-kind count complete instead of unknown.
        "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
        "wall_time_s": round(sum(float(r["elapsed_s"]) for r in receipts), 3),
        "outcome": ",".join(f"{task}={info['verdict']}" for task, info in sorted(result["tasks"].items())),
        "receipt": str(store), "independent_verifier": None, "rsi_eligible": False,
        "exclusion_reason": "QUALIFICATION_MEASUREMENT", "calls": len(receipts),
    }
    try:
        return str(record_usage(store.parent.parent, entry))
    except (UsageRejected, OSError) as exc:
        return f"ERROR:{type(exc).__name__}:{exc}"[:300]


def lookup(store: Path, *, provider: str, model: str, digest: str, task_type: str) -> str:
    """Status of this exact model artifact for this task. A different digest never inherits a verdict, and a record
    without receipts for that digest (hand-made or from the old `score --record`) counts as no record."""
    path = Path(store) / f"{_key(provider, model, task_type)}.json"
    try:
        entry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "UNQUALIFIED"
    if entry.get("digest") != digest:
        return "UNQUALIFIED_DIGEST_CHANGED"
    receipts = entry.get("receipts") or []
    if entry.get("evidence") != EVIDENCE or not receipts or any(
            r.get("digest") != digest or r.get("model") != model or r.get("provider") != provider for r in receipts):
        return "UNQUALIFIED"
    return entry.get("verdict") if entry.get("verdict") in ("QUALIFIED", "REJECTED") else "UNQUALIFIED"


PROVIDERS = {"ollama": OllamaProvider}
# U70: where `qualify --record` keeps a project's verdicts, so the pilot's routing gate finds them.
QUALIFICATION_STORE = Path(".coord") / "qualification"


def local_admission(project: Path, *, model: str, task_type: str, provider: Provider | None = None) -> str:
    """U70: may this local model take a task of *task_type* now? Only QUALIFIED admits.

    The digest is read from the provider at call time, so a re-pulled model under the same name starts UNQUALIFIED.
    A provider that cannot be asked counts as MODEL_NOT_INSTALLED: the gate fails closed, it never guesses.
    """
    if task_type not in TASK_TYPES:
        return "UNKNOWN_TASK_TYPE"
    provider = provider or OllamaProvider()
    try:
        digest = provider.digest(model)
    except (OSError, ValueError):
        digest = None
    if not digest:
        return "MODEL_NOT_INSTALLED"
    return lookup(Path(project) / QUALIFICATION_STORE, provider=provider.name, model=model, digest=digest,
                  task_type=task_type)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="model_qualification")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("score", help="SCORER_ONLY: score saved outputs; never records, takes no identity")
    sc.add_argument("--runs", type=Path, required=True)
    sc.add_argument("--sources", type=Path, required=True)
    sc.add_argument("--pattern", default="art*.json", help="Run file glob inside --runs")
    qu = sub.add_parser("qualify", help="Call the provider on every source, then score and record with receipts")
    qu.add_argument("--provider", default="ollama", choices=sorted(PROVIDERS))
    qu.add_argument("--model", required=True)
    qu.add_argument("--sources", type=Path, required=True)
    qu.add_argument("--pattern", default="*.md", help="Source file glob inside --sources")
    qu.add_argument("--record", type=Path, required=True, help="Store dir for the verdict records")
    qu.add_argument("--expect-digest", default=None, help="Refuse to run unless the provider reports this digest")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "score":
            result = score_fixture(args.runs, args.sources, args.pattern)
        else:
            sources = sorted(args.sources.glob(args.pattern))
            result = qualify(args.record, PROVIDERS[args.provider](), args.model, sources, args.expect_digest)
    except (OSError, ValueError, KeyError) as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
===FILE: v7_harness/coord/session_usage.py===
"""U73: record the tokens a Claude Code session spent, read from its own transcript, as usage-ledger rows.

Seen 2026-09-28 (U72): pilot rows showed 0 paid tokens for U68-U72-L because the apply worker is free, while the
acting Claude session that designed, verified and reported every card left no row at all. The "no 3x cost
regression" gate was therefore UNKNOWN. The session transcript already holds each API call's usage; this module
sums it deterministically (no model call, no subprocess) and appends one `kind: session` row per recording.

Recording is incremental: a row covers only the calls after the latest row already recorded for the same session,
so recording at the end of every card attributes each stretch of the session to that card exactly once.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .usage_ledger import SECRET_PATTERNS, UsageRejected, _check_secrets, _ledger_lock, _rows

TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# Claude Code writes locally generated notices as assistant turns with this model; they are not API calls.
SYNTHETIC_MODEL = "<synthetic>"


def _codex_call(entry: dict[str, Any], state: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """U74-B: one Codex rollout `token_count` event whose cumulative total grew, as the delta since the last one.

    Codex writes cumulative `total_token_usage` and repeats the event without a new call; only a larger total is a
    call. Its `input_tokens` include the cached part, so the uncached input is input minus cached.
    """
    payload = entry.get("payload")
    info = payload.get("info") if isinstance(payload, dict) else None
    total = info.get("total_token_usage") if isinstance(info, dict) else None
    stamp = entry.get("timestamp")
    if not isinstance(total, dict) or not isinstance(stamp, str):
        return None
    counts = {key: total.get(key) for key in ("input_tokens", "cached_input_tokens", "cache_write_input_tokens",
                                                "output_tokens", "total_tokens")}
    if any(not isinstance(value, int) or isinstance(value, bool) for value in counts.values()):
        return None
    previous = state.get("total") or dict.fromkeys(counts, 0)
    if counts["total_tokens"] <= previous["total_tokens"]:
        return None
    state["total"] = counts
    delta = {key: counts[key] - previous[key] for key in counts}
    return f"codex-{counts['total_tokens']}", {
        "ts": stamp, "model": state.get("model"),
        "input_tokens": delta["input_tokens"] - delta["cached_input_tokens"],
        "output_tokens": delta["output_tokens"],
        "cache_creation_input_tokens": delta["cache_write_input_tokens"],
        "cache_read_input_tokens": delta["cached_input_tokens"],
    }


def _session_calls(transcript: Path) -> dict[str, dict[str, Any]]:
    """One entry per API call: a Claude Code message id (repeated once per content block, all with its usage) or a
    Codex rollout token_count event that grew the cumulative total."""
    calls: dict[str, dict[str, Any]] = {}
    codex: dict[str, Any] = {}
    with open(transcript, encoding="utf-8") as handle:
        for line in handle:
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            payload = entry.get("payload")
            if entry.get("type") == "turn_context" and isinstance(payload, dict) and payload.get("model"):
                codex["model"] = str(payload["model"])
                continue
            if entry.get("type") == "event_msg" and isinstance(payload, dict) and payload.get("type") == "token_count":
                call = _codex_call(entry, codex)
                if call:
                    calls[call[0]] = call[1]
                continue
            if entry.get("type") != "assistant":
                continue
            message = entry.get("message")
            if not isinstance(message, dict) or message.get("model") == SYNTHETIC_MODEL:
                continue
            usage, message_id, stamp = message.get("usage"), message.get("id"), entry.get("timestamp")
            if not isinstance(usage, dict) or not isinstance(message_id, str) or not isinstance(stamp, str):
                continue
            call = calls.setdefault(message_id, {"ts": stamp, "model": message.get("model"),
                                                 **{key: 0 for key in TOKEN_KEYS}})
            call["ts"] = min(call["ts"], stamp)
            for key in TOKEN_KEYS:
                value = usage.get(key)
                # The repeated blocks carry the same final usage; max() keeps a partial first block from undercounting.
                if isinstance(value, int) and not isinstance(value, bool) and value > call[key]:
                    call[key] = value
    return calls


def _recorded_until(ledger: Path, session_id: str) -> str:
    """The end of the latest window already recorded for this session ('' when none)."""
    until = ""
    for line in _rows(ledger):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("kind") == "session" and row.get("session_id") == session_id:
            until = max(until, str(row.get("window_end") or ""))
    return until


def _seconds(start: str, end: str) -> float:
    def parse(stamp: str) -> datetime:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00"))

    return round((parse(end) - parse(start)).total_seconds(), 3)


def record_session(project_root: Path, transcript: Path, *, work_id: str, actor: str | None = None,
                   apply: bool = False, lock_timeout_s: float = 10.0) -> dict[str, Any]:
    """Sum the session's calls after its last recorded window; with apply, append them as one ledger row.

    The read of the ledger, the window choice and the append all run under the ledger lock, so two recordings at
    once cannot count the same calls twice.
    """
    transcript = Path(transcript)
    if not work_id.strip():
        raise UsageRejected("work_id must be a non-empty string")
    if not transcript.is_file():
        raise UsageRejected(f"transcript not found: {transcript}")
    session_id = transcript.stem
    calls = _session_calls(transcript)
    # The transcript's own format names the tool: Codex rollouts yield codex-* calls.
    actor = actor or ("codex" if any(key.startswith("codex-") for key in calls) else "claude")
    with _ledger_lock(Path(project_root), lock_timeout_s) as ledger:
        since = _recorded_until(ledger, session_id)
        window = sorted((call for call in calls.values() if call["ts"] > since), key=lambda call: call["ts"])
        if not window:
            return {"ledger": str(ledger), "session_id": session_id, "since": since or None, "api_calls": 0,
                    "mode": "NOTHING_NEW", "appended": 0}
        models = sorted({str(call["model"]) for call in window if call["model"]}) or ["unknown"]
        row: dict[str, Any] = {
            "schema": "uaos-usage-v2", "work_id": work_id, "actor": actor, "worker": actor,
            "model": ",".join(models), "kind": "session", "collection_mode": "transcript",
            "wall_time_s": _seconds(window[0]["ts"], window[-1]["ts"]), "outcome": "MEASURED",
            "receipt": str(transcript), "independent_verifier": None, "rsi_eligible": False,
            # A session row is a cost measurement, not a worker attempt: RSI and admission read pilot/review rows.
            "exclusion_reason": "SESSION_COST_NOT_WORKER_ATTEMPT",
            "session_id": session_id, "window_start": window[0]["ts"], "window_end": window[-1]["ts"],
            "api_calls": len(window),
            **{key: sum(call[key] for call in window) for key in TOKEN_KEYS},
        }
        _check_secrets(row)
        if apply:
            row["ts"] = time.time()
            line = json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            if any(pattern.search(line) for pattern in SECRET_PATTERNS):
                raise UsageRejected("secret detected in usage record")
            with open(ledger, "ab") as handle:
                handle.write(line.encode("utf-8"))
                handle.flush()
                os.fsync(handle.fileno())
    return {"ledger": str(ledger), "since": since or None, "mode": "APPLY" if apply else "DRY_RUN",
            "appended": 1 if apply else 0, **{key: row[key] for key in (
                "session_id", "work_id", "model", "window_start", "window_end", "api_calls", "wall_time_s",
                *TOKEN_KEYS)}}
===FILE: v7_harness/coord/deliver.py===
"""coord deliver: 도구 간 직접 전달기 — 사용자 수동 릴레이 영구 제거.

근본 결함(2026-09-27 사용자 지적):
  사서함(mailbox)에 메시지를 넣은 뒤 사용자에게 "전달해달라"고 부탁하는 것은
  UAOS의 존재 이유를 부정하는 설계 결함이다.

해결:
  수신 도구를 자동 판별하여 직접 전달한다.
  - Codex ACTIVE → `codex queue --thread <session> --message <text>`
  - Claude ACTIVE → `claude -p "<text>" --allowedTools "Read" --output-format json`
  - 둘 다 부재 → 사서함에만 보존(사용자 릴레이 요청 금지)

불변식:
  1. 사용자에게 "전달해달라", "붙여넣기해달라" 등의 릴레이를 요청하지 않는다.
  2. 전달 실패 시 사서함에 보존하고, 실패 사실만 보고한다.
  3. 비밀(secret)은 전달하지 않는다.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v7_harness.coord.stream import SECRET_PATTERNS
from v7_harness.coord.mailbox import Mailbox


@dataclass(frozen=True)
class DeliverResult:
    delivered: bool
    target: str          # "codex" | "claude" | "mailbox_only"
    reason: str          # SENT | CLI_NOT_FOUND | DELIVERY_FAILED | ABSENT_ALL | ...
    command: tuple[str, ...]
    output: str
    message_id: str = ""
    digest: str = ""
    receipt: str = ""


# U64-F (Claude acting, 2026-09-28): whole tokens only. Substrings woke a paid cold turn for "inbox 140 (P1 0)",
# "STEP1" and "no ACTIONABLE_DELTA since last"; an ACK_ONLY marker always wins.
_TOKEN = r"(?<![A-Z0-9_=]){}(?![A-Z0-9_])"
_ACK_RE = re.compile(_TOKEN.format("ACK_ONLY"))
_NEGATED_RE = re.compile(r"\b(?:NO|NOT|WITHOUT|NON)[\s-]+ACTIONABLE_DELTA\b")
_WAKE_RES = tuple(re.compile(_TOKEN.format(token)) for token in (
    "ACTIONABLE_DELTA", "VERDICT_REQUESTED=YES", "APPROVAL_REQUIRED", r"(?:PRIORITY|SEVERITY|P1)=(?:P1|YES|1)"))


def _requires_wake(message: str) -> bool:
    """Only a real delta may spend a paid turn; ACK_ONLY, negated or incidental tokens never do."""
    upper = message.upper()
    if _ACK_RE.search(upper):
        return False
    upper = _NEGATED_RE.sub(" ", upper)
    return any(pattern.search(upper) for pattern in _WAKE_RES)


# ── 비밀 검사 ────────────────────────────────────────────────
def _check_secrets(text: str) -> None:
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("SECRET_IN_DELIVERY: 비밀이 포함된 메시지는 전달하지 않는다.")


# ── Codex 전달 ───────────────────────────────────────────────
def _project_mailbox(project: Path) -> Mailbox:
    """Use one runtime mailbox per repository while preserving the caller's source worktree separately."""
    from v7_harness.coord.hook_context import shared_desk
    root = shared_desk(Path(project)) / ".coord" / "mailbox"
    root.mkdir(parents=True, exist_ok=True)
    return Mailbox(root)


def _deliver_to_codex(
    message: str,
    thread: str,
    *,
    runner: Any = None,
    timeout: int = 60,
) -> DeliverResult:
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return DeliverResult(False, "codex", "CLI_NOT_FOUND", (), "")

    argv = (codex_bin, "queue", "--thread", thread, "--message", message)
    execute = runner or subprocess.run
    try:
        cp = execute(list(argv), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:{exc}", argv, "")

    if getattr(cp, "returncode", 1) != 0:
        stderr = getattr(cp, "stderr", "") or ""
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:rc={cp.returncode}", argv, stderr[:500])

    return DeliverResult(True, "codex", "SENT", argv, "")


# ── Claude 전달 ──────────────────────────────────────────────
@contextmanager
def _claude_turn(project_dir: Path | None, timeout: int):
    """Serialize messages through the one persisted Claude conversation, including across processes."""
    if project_dir is None:
        yield
        return
    lock = project_dir / ".coord" / "mailbox" / "delivery" / "claude-session.turn.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout + 5
    fd = None
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            break
        except PermissionError:
            # U53-F1: on Windows the previous holder's unlink leaves the lock delete-pending for a moment and
            # O_EXCL then raises PermissionError, not FileExistsError (1 of 30 eight-process runs). Wait, do not crash.
            time.sleep(CLAIM_SLEEP_S)
            continue
        except FileExistsError:
            try:
                stale = time.time() - lock.stat().st_mtime > timeout + 30
            except OSError:
                stale = False
            if stale:
                try:
                    os.rename(lock, lock.with_name(f"{lock.name}.stale-{uuid.uuid4().hex}"))
                except OSError:
                    pass
            time.sleep(CLAIM_SLEEP_S)
    if fd is None:
        raise TimeoutError("CLAUDE_TURN_TIMEOUT")
    with os.fdopen(fd, "wb") as handle:
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)


def _deliver_to_claude(
    message: str,
    *,
    project_dir: Path | None = None,
    runner: Any = None,
    timeout: int = 120,
    allowed_tools: tuple[str, ...] = ("Read",),
) -> DeliverResult:
    try:
        with _claude_turn(project_dir, timeout):
            return _deliver_to_claude_locked(
                message, project_dir=project_dir, runner=runner, timeout=timeout, allowed_tools=allowed_tools
            )
    except TimeoutError as exc:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:{exc}", (), "")


def _deliver_to_claude_locked(
    message: str,
    *,
    project_dir: Path | None = None,
    runner: Any = None,
    timeout: int = 120,
    allowed_tools: tuple[str, ...] = ("Read",),
) -> DeliverResult:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return DeliverResult(False, "claude", "CLI_NOT_FOUND", (), "")

    session_path: Path | None = None
    session_id = ""
    resume = False
    if project_dir:
        session_path = project_dir / ".coord" / "mailbox" / "delivery" / "claude-session.json"
        session_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            state = json.loads(session_path.read_text(encoding="utf-8"))
            session_id = str(state.get("session_id") or "")
            resume = bool(state.get("ready"))
        except (FileNotFoundError, OSError, ValueError, AttributeError):
            state = {}
        if not session_id:
            session_id = str(uuid.uuid4())
            initial = (json.dumps({"session_id": session_id, "ready": False}, sort_keys=True) + "\n").encode("utf-8")
            try:
                fd = os.open(str(session_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                state = json.loads(session_path.read_text(encoding="utf-8"))
                session_id = str(state["session_id"])
                resume = bool(state.get("ready"))
            else:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(initial)
                    handle.flush()
                    os.fsync(handle.fileno())

    argv_list = [claude_bin, "-p", message, "--output-format", "json"]
    if session_id:
        argv_list.extend(["--resume" if resume else "--session-id", session_id])
    for tool in allowed_tools:
        argv_list.extend(["--allowedTools", tool])

    execute = runner or subprocess.run
    # Claude emits UTF-8. Windows' locale is CP949 on this host, so text=True without an explicit encoding loses the
    # reply in subprocess' reader thread even when Claude exits successfully.
    kwargs: dict[str, Any] = dict(capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if project_dir:
        kwargs["cwd"] = str(project_dir)

    try:
        cp = execute(argv_list, **kwargs)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:{exc}", tuple(argv_list), "")

    rc = getattr(cp, "returncode", 1)
    stdout = getattr(cp, "stdout", "") or ""
    stderr = getattr(cp, "stderr", "") or ""

    if rc != 0:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:rc={rc}", tuple(argv_list), stderr[:500])

    # Claude CLI JSON 응답에서 result 추출
    result_text = ""
    try:
        data = json.loads(stdout)
        if not isinstance(data, dict) or data.get("is_error") or data.get("type") == "error_max_budget_usd":
            return DeliverResult(False, "claude", "DELIVERY_FAILED:UNUSABLE_RESPONSE", tuple(argv_list), stdout[:500])
        result_text = data.get("result", stdout[:500])
    except (json.JSONDecodeError, AttributeError):
        result_text = stdout[:500]

    if session_path and session_id:
        temporary = session_path.with_suffix(f".tmp-{uuid.uuid4().hex}")
        temporary.write_text(json.dumps({"session_id": session_id, "ready": True}, sort_keys=True) + "\n",
                             encoding="utf-8")
        os.replace(temporary, session_path)
    reply = str(result_text)[:2000]
    try:
        _check_secrets(reply)
    except ValueError:
        return DeliverResult(False, "claude", "DELIVERY_FAILED:SECRET_IN_RESPONSE", tuple(argv_list), "")
    return DeliverResult(True, "claude", "SENT", tuple(argv_list), reply)


def _receipt_output(path: Path) -> str:
    """Return a previously persisted reply; malformed receipts fail closed to an empty reply."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("output") or "") if isinstance(data, dict) else ""


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Create one immutable receipt; concurrent attempts get separate names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _clear_owned_pending(path: Path, owner: str | None) -> None:
    """Remove only the direct-dispatch marker owned by this guard winner."""
    if not owner:
        return
    try:
        if json.loads(path.read_text(encoding="utf-8")).get("owner") == owner:
            path.unlink(missing_ok=True)
    except (OSError, ValueError, AttributeError):
        pass


# ── 통합 전달기 ──────────────────────────────────────────────
# Why 300 s: a live dispatcher holds the guard at most for the Claude CLI timeout (120 s) plus receipt writes; 300 s
# gives 2.5x margin so a slow but live dispatcher is never taken for a crashed one.
GUARD_STALE_S = 300.0
# The recovery lock is held only for a stat, a rename and an open (milliseconds); 60 s means its holder crashed.
RECOVER_STALE_S = 60.0
# 50 x 20 ms bounds the claim retry at about 1 s, well above the few ms a concurrent publish holds the file open.
CLAIM_TRIES = 50
CLAIM_SLEEP_S = 0.02
# Release waits for the recovery lock at most 5 s: recovery holds it for milliseconds, so 5 s only runs out when a
# recoverer crashed inside it; the guard is then left for stale recovery, which can delay but never double-dispatch.
RELEASE_WAIT_S = 5.0


def _payload(actor: str, message: str, digest: str, target: str | None) -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    return {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}


def _open_excl(path: Path) -> int | None:
    """Create path exclusively; None if it exists. On Windows a file being unlinked by its holder raises
    PermissionError (delete pending, seen 1 of 50 eight-process runs), so that case is retried, not raised."""
    for _ in range(CLAIM_TRIES):
        try:
            return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return None
        except PermissionError:
            time.sleep(CLAIM_SLEEP_S)
    return None


def _acquire_guard(guard: Path, box: Mailbox, message_id: str, digest: str) -> int | None:
    """Take the per-message dispatch guard, recovering one left by a crashed dispatcher. None means IN_FLIGHT.

    Recovery runs under a second exclusive lock so the age check and the rename cannot interleave with another
    recoverer (otherwise one could rename a guard that another had just re-created). The stale guard is renamed,
    not deleted, and an attempt receipt records the recovery.
    """
    fd = _open_excl(guard)
    if fd is not None:
        return fd
    try:
        if time.time() - guard.stat().st_mtime < GUARD_STALE_S:
            return None
    except OSError:
        pass  # released since (or delete pending on Windows); the exclusive open below decides
    recover = guard.with_name(guard.name + ".recover")
    rfd = _open_excl(recover)
    if rfd is None:
        try:
            if time.time() - recover.stat().st_mtime >= RECOVER_STALE_S:
                os.rename(recover, recover.with_name(f"{recover.name}.stale-{uuid.uuid4().hex}"))
        except OSError:
            pass
        return None  # another recoverer is working now; this caller's message is already published
    os.close(rfd)
    try:
        try:
            age = time.time() - guard.stat().st_mtime
        except OSError:
            age = None
        if age is not None:
            if age < GUARD_STALE_S:
                return None  # a live dispatcher re-created it between our checks
            stale = guard.with_name(f"{guard.name}.stale-{uuid.uuid4().hex}")
            os.rename(guard, stale)
            _write_receipt(box.root / "delivery" / "attempts" / f"{message_id}_{uuid.uuid4().hex}.json",
                           {"message_id": message_id, "digest": digest, "state": "GUARD_RECOVERED",
                            "stale_guard": str(stale), "age_s": round(age, 1), "timestamp_ns": time.time_ns()})
        return _open_excl(guard)
    finally:
        recover.unlink(missing_ok=True)


def _release_guard(guard: Path, owner: str) -> None:
    """Remove the dispatch guard only if this dispatcher still owns it, under the same lock recovery uses.

    U49-G1R (Codex REJECT of G1, 2026-09-27): an unconditional unlink by a dispatcher that outlived GUARD_STALE_S removed
    the new holder's guard, and G1's owner check alone still let a recovery land between the read and the unlink.
    Holding `<guard>.recover` across compare and unlink makes release and recovery mutually exclusive, because recovery
    ages, renames and re-creates the guard only while holding that lock too.
    """
    recover = guard.with_name(guard.name + ".recover")
    deadline = time.monotonic() + RELEASE_WAIT_S
    rfd = _open_excl(recover)
    while rfd is None and time.monotonic() < deadline:
        try:
            if time.time() - recover.stat().st_mtime >= RECOVER_STALE_S:
                os.rename(recover, recover.with_name(f"{recover.name}.stale-{uuid.uuid4().hex}"))
        except OSError:
            pass
        time.sleep(CLAIM_SLEEP_S)
        rfd = _open_excl(recover)
    if rfd is None:
        return  # left for stale recovery: a delay, never a second dispatcher
    os.close(rfd)
    try:
        data = None
        for _ in range(CLAIM_TRIES):  # a Windows sharing violation is transient; do not strand our own guard
            try:
                data = json.loads(guard.read_text(encoding="utf-8"))
                break
            except PermissionError:
                time.sleep(CLAIM_SLEEP_S)
            except (OSError, ValueError):
                return
        if isinstance(data, dict) and data.get("owner") == owner:
            guard.unlink(missing_ok=True)
    finally:
        recover.unlink(missing_ok=True)


def _dispatch_count(attempts: Path, message_id: str) -> int:
    """Count earlier dispatch attempts (DISPATCHED or FAILED) for one message; GUARD_RECOVERED receipts do not count.

    Called while holding the claim, so dispatchers of the same id are serialized and the count cannot race. A receipt
    that cannot be read yet (Windows delete-pending) or is not JSON is still counted: it can only be an attempt.
    U49-D2: valid JSON that is not an object (e.g. a list) is counted the same way instead of raising AttributeError.
    """
    count = 0
    for path in attempts.glob(f"{message_id}_*.json") if attempts.is_dir() else ():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        state = data.get("state") if isinstance(data, dict) else None
        if state != "GUARD_RECOVERED":
            count += 1
    return count


def _deliver_unlocked(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
    pending_owner: str | None = None,
) -> DeliverResult:
    """메시지를 대상 도구에게 직접 전달한다.

    target: "codex" | "claude" | None (자동 판별).
    자동 판별 시 presence를 읽어 ACTIVE인 도구에게 보낸다.
    Codex ACTIVE면 Codex, 아니면 Claude에게 보낸다.

    불변식: 사용자에게 수동 릴레이를 요청하지 않는다.
    """
    _check_secrets(message)
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    # Stable id makes repeated calls with the same sender and bytes idempotent.
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
    ack_file = box.ack_dir / f"{message_id}.json"
    if ack_file.is_file():
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(True, target or "auto", "ACKED", (), "", message_id, digest, str(ack_file))

    # U64 (2026-09-28): coord watch only returns to the shell process that launched it; it cannot start a new AI turn.
    # It may suppress an ACK-only/liveness delivery, but a real delta must use the direct Claude dispatch path.
    if target == "claude":
        from v7_harness.coord.watch import watcher_live
        if watcher_live(desk, "claude") and not _requires_wake(message):
            return DeliverResult(False, "claude", "QUEUED_INTERACTIVE", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))
        # U74-D: an explicit ACK_ONLY never spends a paid turn, even with no watcher (global relay rule). The letter
        # is already published; the next session reads it from the inbox.
        if _ACK_RE.search(message.upper()):
            return DeliverResult(False, "claude", "QUEUED_ACK_ONLY", (), "", message_id, digest,
                                 str(box.inbox_dir / f"{message_id}.json"))

    accepted = box.root / "delivery" / "accepted" / f"{message_id}.json"
    if accepted.is_file():
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(False, target, "DISPATCHED", (), _receipt_output(accepted),
                             message_id, digest, str(accepted))

    # A same-id caller publishing outside the guard may hold the inbox file open for a moment, and Windows then
    # refuses the claim's rename. Retry briefly instead of reporting IN_FLIGHT with nobody dispatching.
    inbox_file = box.inbox_dir / f"{message_id}.json"
    claim = None
    for _ in range(CLAIM_TRIES):
        claim = box.claim(message_id, "dispatcher")
        if claim is not None or not inbox_file.is_file():
            break
        time.sleep(CLAIM_SLEEP_S)
    if claim is None:
        _clear_owned_pending(pending, pending_owner)
        return DeliverResult(False, target, "IN_FLIGHT", (), "", message_id, digest)

    result: DeliverResult
    try:
        # A contender may have checked before the first sender wrote this
        # receipt, then acquired the claim after the first sender returned it.
        if accepted.is_file():
            return DeliverResult(False, target, "DISPATCHED", (), _receipt_output(accepted),
                                 message_id, digest, str(accepted))
        # The claim serializes competing dispatchers. The original is returned
        # to inbox after the attempt; only recipient coord ack may settle it.
        envelope = f"[UAOS relay id={message_id} digest={digest}]\n{message}"
        if target != "claude":
            envelope += (f"\nAfter processing, run coord ack --id {message_id} for this project. "
                         "The sender keeps this message in the inbox until ACK.")
        if target == "codex":
            if not thread:
                from v7_harness.coord.notify import resolve_thread
                thread = resolve_thread(desk)
            result = (_deliver_to_codex(envelope, thread, runner=runner) if thread else
                      DeliverResult(False, "codex", "NO_THREAD", (), ""))
        elif target == "claude":
            prefix = "[안티그래비티에서 온 대화] " if actor.lower() in ("agy", "antigravity") else (
                "[코덱스에서 온 대화] " if actor.lower() == "codex" else "")
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner)
        else:
            result = DeliverResult(False, str(target), f"UNKNOWN_TARGET:{target}", (), "")

        attempts = box.root / "delivery" / "attempts"
        receipt = {"message_id": message_id, "digest": digest, "target": target,
                   "state": "DISPATCHED" if result.delivered else "FAILED", "reason": result.reason,
                   "attempt": _dispatch_count(attempts, message_id) + 1, "timestamp_ns": time.time_ns(),
                   "output": result.output}
        attempt_path = attempts / f"{message_id}_{uuid.uuid4().hex}.json"
        _write_receipt(attempt_path, receipt)
        if result.delivered:
            try:
                _write_receipt(accepted, receipt)
            except FileExistsError:
                pass
            return DeliverResult(False, target, "DISPATCHED", result.command, result.output,
                                 message_id, digest, str(accepted))
        return DeliverResult(False, str(target), result.reason, result.command, result.output,
                             message_id, digest, str(attempt_path))
    finally:
        _clear_owned_pending(pending, pending_owner)
        try:
            box.nack(claim)
        except OSError:
            # A same-id publisher reading the claimed copy can block its unlink on Windows. The bytes are already in
            # the inbox or stay in claimed/ for recover_stale_claims, so nothing is lost; do not fail the dispatch.
            pass


def deliver(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.

    On Windows, another publisher opening a claimed file can prevent NACK
    from unlinking it. This outer guard prevents same-id callers from touching
    mailbox files while the owner is publishing or dispatching.
    """
    _check_secrets(message)
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    requested_target = target
    if target is None:
        from v7_harness.coord.presence import read as read_presence
        from v7_harness.coord.watch import watcher_live
        if read_presence(desk, "codex")["state"] == "ACTIVE":
            target = "codex"
        elif read_presence(desk, "claude")["state"] == "ACTIVE" or watcher_live(desk, "claude"):
            target = "claude"
    # U66: the intent marker exists before the inbox letter. A racing watcher waits instead of starting a second
    # paid turn; on failure `_deliver_unlocked` removes it and the same unseen letter becomes the fallback route.
    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
    if target == "claude" and _requires_wake(message) and not pending.is_file():
        try:
            _write_receipt(pending, {"message_id": message_id, "target": "claude", "state": "PENDING"})
        except FileExistsError:
            pass
    # U48-D0 re-review (Claude, 2026-09-27): publish before the guard. A guard left by a crashed dispatcher used to
    # return IN_FLIGHT before any publish, so the message never reached the inbox. Publish is idempotent by id+bytes.
    box.publish(message_id, _payload(actor, message, digest, requested_target))
    if target is None:
        return DeliverResult(False, "mailbox_only", "PUBLISHED", (), "", message_id, digest)
    guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    fd = _acquire_guard(guard, box, message_id, digest)
    if fd is None:
        return DeliverResult(False, target or "mailbox_only", "IN_FLIGHT", (), "", message_id, digest)
    owner = uuid.uuid4().hex
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps({"message_id": message_id, "digest": digest, "actor": actor,
                                 "message": message, "target": target, "owner": owner},
                                ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    pending_owner = None
    if target == "claude" and _requires_wake(message):
        # The guard winner takes ownership even if another contender created the provisional marker. Guard losers
        # cannot remove it; this closes the last window where a watcher could start a second paid turn.
        pending.parent.mkdir(parents=True, exist_ok=True)
        pending.write_text(json.dumps({"message_id": message_id, "target": "claude", "state": "PENDING",
                                       "owner": owner}, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        pending_owner = owner
    try:
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner, pending_owner=pending_owner)
    finally:
        _release_guard(guard, owner)
===FILE: v7_harness/cli.py===
"""
Command-line interface for v7 harness.

Provides unified commands for:
- context lease validation
- intent ledger operations & integrity verification
- proof receipt execution
- deterministic snapshot capture
- next-stage eligibility evaluation
- A/B benchmark execution
- concise reporting
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from typing import Optional

from .benchmark_hook import BenchmarkHook
from .context_lease import ContextLease, ContextLeaseValidator
from .intent_ledger import IntentLedger
from .proof_receipt import ProofReceiptStore, run_with_receipt
from .reporter import generate_report
from .snapshot import take_snapshot
from .stage_evaluator import AcceptanceCheck, StageEvaluator

# 로컬 계산기가 멈추면(시간 초과·공급자 오류) 다음 계산기로 넘긴다 (실측 2026-09-23: qwen2.5-coder 7b 가 cli.py 과제에서 600초 PROVIDER_ERROR).


def cmd_lease_check(args: argparse.Namespace) -> int:
    lease_path = Path(args.file)
    if not lease_path.exists():
        print(f"Error: lease file '{lease_path}' does not exist.", file=sys.stderr)
        return 1

    with open(lease_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        leases = [ContextLease.from_dict(d) for d in data]
    else:
        leases = [ContextLease.from_dict(data)]

    validator = ContextLeaseValidator()
    results, valid_ids = validator.validate_lease_set(leases, target_scope=args.scope)

    all_valid = len(valid_ids) == len(leases)
    for lid, res in results.items():
        status = "VALID" if res.valid else "INVALID"
        print(f"[{status}] Lease {lid}: errors={res.errors}, warnings={res.warnings}")

    return 0 if all_valid else 2


def cmd_ledger_append(args: argparse.Namespace) -> int:
    ledger = IntentLedger(args.ledger_file)
    entry = ledger.append(
        task_id=args.task_id,
        actor=args.actor,
        category=args.category,
        content=args.content,
        rationale=args.rationale,
        assumption=args.assumption,
        invalidation_condition=args.invalidation_condition,
    )
    print(f"Appended entry: {entry.entry_id} (hash: {entry.entry_hash[:12]}...)")
    return 0


def cmd_ledger_verify(args: argparse.Namespace) -> int:
    ledger = IntentLedger(args.ledger_file)
    valid, reason = ledger.verify_integrity()
    if valid:
        print(f"Ledger integrity OK: {len(ledger.entries)} entries verified.")
        return 0
    else:
        print(f"Ledger integrity FAILED: {reason}", file=sys.stderr)
        return 1


def cmd_receipt_run(args: argparse.Namespace) -> int:
    cmd = list(args.cmd)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("Error: No command specified for receipt-run.", file=sys.stderr)
        return 2
    store = ProofReceiptStore(args.store) if args.store else None
    receipt = run_with_receipt(
        command=cmd,
        task_id=args.task_id,
        actor=args.actor,
        receipt_store=store,
    )
    print(json.dumps(receipt.to_dict(), indent=2, ensure_ascii=False))
    return receipt.exit_code


def cmd_snapshot(args: argparse.Namespace) -> int:
    snap = take_snapshot(target_path=args.target_path, force_non_git=args.force_non_git)
    if args.output:
        out_p = Path(args.output)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w", encoding="utf-8") as f:
            json.dump(snap.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"Snapshot written to {out_p} (hash: {snap.snapshot_hash[:12]}..., type: {snap.snapshot_type})")
    else:
        print(json.dumps(snap.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_eval_next(args: argparse.Namespace) -> int:
    evaluator = StageEvaluator()
    # Dummy or CLI checks
    check = AcceptanceCheck(
        criterion_id="ALL",
        description="CLI passed checks",
        passed=not args.has_failures,
    )
    pending_actions = args.pending_actions or []
    eligibility = evaluator.evaluate_eligibility(
        current_task_id=args.current_task_id,
        checks=[check],
        pending_actions=pending_actions,
        next_task_candidate=args.next_task,
    )
    print(json.dumps(eligibility.to_dict(), indent=2, ensure_ascii=False))
    return 0 if eligibility.is_eligible else 1


def cmd_benchmark(args: argparse.Namespace) -> int:
    hook = BenchmarkHook(args.name)

    def dummy_baseline():
        sum(i * i for i in range(100_000))

    def dummy_candidate():
        sum(i * i for i in range(50_000))

    res = hook.run_comparison(dummy_baseline, dummy_candidate)
    print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    verification_str: Optional[str] = None
    if args.verification is not None:
        verification_str = ", ".join(args.verification)

    checks = [] if verification_str is not None else [("CLI test", 0)]
    rep = generate_report(
        result=args.result,
        changed=args.changed or [],
        checks=checks,
        risks=args.risks,
        next_action=args.next_action,
        user_action_required=args.user_action_required,
        verification=verification_str,
    )
    print(rep.to_concise_markdown())
    return 0


def manual_project(manual: Path) -> Path:
    """U45-F1: the project a manual's paths are relative to, when no --source is given: the nearest folder above the
    manual that holds .coord/PLAN.md, else the current folder. Lint run from another cwd used to report INPUT_MISSING
    for files that exist under the pilot source (U45-O1b)."""
    for folder in Path(manual).resolve().parents:
        if (folder / ".coord" / "PLAN.md").is_file():
            return folder
    return Path(".")


def mandatory_watch_roots(work_dir: Path, source_dir: Path) -> list[Path]:
    """Shallow roots a worker must not write into during a run.

    U45-F5: the work dir's parent used to be watched always. When that parent is a shared `.work/` folder, the
    conductor keeps writing its own notes there during a paid run (U45-G7 a001: two conductor files flagged, run
    abandoned, $0.319 lost). A shared `.work/` is therefore not watched; home, temp, the source's parent and the stage
    stay watched. A worker writing a sibling file inside `.work/` goes unseen, and `.work/` is never committed.
    """
    work = work_dir.resolve()
    return list(dict.fromkeys([
        Path.home().resolve(),
        Path(tempfile.gettempdir()).resolve(),
        *([] if work.parent.name == ".work" else [work.parent]),
        source_dir.resolve().parent,
        (work_dir / "stage").resolve(),
    ]))


def _admission(source_dir: Path, worker: str, contract: Optional[dict]) -> dict:
    """U69 admission for a paid pilot run under *contract* (see v7_harness/admission.py)."""
    from .admission import admit

    contract = contract or {}
    try:
        usd = float(contract.get("remote_budget_usd") or 0)
    except ValueError:
        usd = 0.0
    return admit(source_dir, worker=worker, kind="pilot", budget_tokens=int(contract.get("remote_budget_tokens") or 0),
                 budget_usd=usd, timeout_s=int(contract.get("timeout_s") or 0))


def cmd_pilot_run(args: argparse.Namespace) -> int:
    task_id = args.task
    source_dir = Path(args.source)
    if not source_dir.exists():
        print(f"Error: source directory '{source_dir}' does not exist.", file=sys.stderr)
        return 1

    # U34: a manual is a contract. It is linted before anything runs and its fields drive the run, so the
    # worker receives exactly the checked text and cannot change files outside `allow`.
    contract: Optional[dict] = None
    manual_path = getattr(args, "manual", None)
    if manual_path:
        from .manual import lint

        mfile = Path(manual_path)
        if not mfile.is_file():
            print(f"Error: manual '{mfile}' does not exist.", file=sys.stderr)
            return 1
        prompt = mfile.read_text(encoding="utf-8")
        report = lint(prompt, source_dir)
        if not report.ok:
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "MANUAL_INVALID",
                              "verdict_hint": "BLOCKED", "manual_errors": report.errors,
                              "manual_warnings": report.warnings}, indent=2, ensure_ascii=False))
            return 2
        contract = report.contract
        for warning in report.warnings:
            print(f"[manual] {warning}", file=sys.stderr)
        if contract.get("work_id") != task_id:
            # U45-F7: refuse before any worker runs. A warning here let a paid run finish first (U45-G7r, $0.263 lost).
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "MANUAL_TASK_MISMATCH",
                              "verdict_hint": "BLOCKED", "manual_work_id": contract.get("work_id")},
                             indent=2, ensure_ascii=False))
            return 2
        if args.approve:
            approver = getattr(args, "coord_actor", None) or detect_actor()
            # An approver the harness cannot identify used to pass silently (B85 review). Name it with --coord-actor.
            # This is a speed bump, not authentication: on one OS account every name can be forged (B83).
            if approver is None or approver != contract["judge"].lower():
                print(json.dumps({"task_id": task_id, "state": "REFUSED",
                                  "error_class": "APPROVER_UNKNOWN" if approver is None else "APPROVER_NOT_JUDGE",
                                  "verdict_hint": "BLOCKED", "judge": contract["judge"], "approver": approver},
                                 indent=2, ensure_ascii=False))
                return 2
    elif args.prompt_file:
        pfile = Path(args.prompt_file)
        if not pfile.is_file():
            print(f"Error: prompt file '{pfile}' does not exist.", file=sys.stderr)
            return 1
        prompt = pfile.read_text(encoding="utf-8")
    elif args.prompt:
        prompt = args.prompt
    else:
        print("Error: one of --manual, --prompt-file or --prompt must be provided.", file=sys.stderr)
        return 2

    # 실행 전에 지시문의 구체성을 알려 준다. 막지는 않는다. 벤치에서 로컬 모델이 실패한
    # 유일한 축이 모호함이었으므로, 고르기 전에 한 줄이라도 보이는 편이 낫다.
    from .adapters.ollama_worker import dictated_paths
    from .adapters.worker_advice import advise

    advice = advise(prompt)
    chosen = contract["worker"] if contract else getattr(args, "worker", "agy")
    # auto: 지휘자가 코드를 이미 적었으면(받아쓰기) 모델 없이 그대로 적용하고, 아니면 구체성으로 고른다.
    if chosen == "auto":
        if dictated_paths(prompt):
            chosen = "apply"
        else:
            chosen = "cascade" if advice.worker == "local" else "agy"
        routed = {"worker": chosen, "specificity": advice.specificity}
    else:
        routed = None
    if advice.worker != chosen and chosen != "apply":
        print(
            f"[조언] 지시문 구체성 {advice.specificity}/100 → --worker {advice.worker} 권장"
            f" (현재 {chosen}): {'; '.join(advice.reasons[:2])}",
            file=sys.stderr,
        )

    # U38: a Claude worker spends the same subscription as the Claude commander. When Claude reports LIMITED, the
    # commander keeps the remaining quota (docs/40 §2-1).
    uses_claude = chosen == "claude" or (chosen == "cascade" and getattr(args, "escalate_to", "agy") == "claude")
    if uses_claude and not args.approve:
        from .coord.presence import read as read_presence

        if read_presence(source_dir, "claude")["state"] == "LIMITED":
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "CLAUDE_LIMITED",
                              "verdict_hint": "BLOCKED",
                              "message": "Claude presence is LIMITED; its quota is kept for the commander"},
                             indent=2, ensure_ascii=False))
            return 2

    # B85 rework (Codex): a paid worker runs only under a contract. Without a manual there is no budget and no dollar
    # cap, and an approval could promote a run nothing ever measured.
    from .manual import REMOTE_WORKERS

    if chosen in REMOTE_WORKERS and contract is None:
        print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "REMOTE_WITHOUT_MANUAL",
                          "verdict_hint": "BLOCKED", "worker": chosen,
                          "message": "paid workers (agy, claude) need --manual with remote_budget_tokens"},
                         indent=2, ensure_ascii=False))
        return 2

    # U69: refuse before the call when the contract cannot pay for the cheapest call this worker has made here.
    # An --approve replays the saved bundle and spends nothing, so it is not admitted again.
    if chosen in REMOTE_WORKERS and not args.approve:
        admission = _admission(source_dir, chosen, contract)
        if admission["decision"] == "REFUSE":
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "ADMISSION_REFUSED",
                              "verdict_hint": "BLOCKED", "worker": chosen, "admission": admission},
                             indent=2, ensure_ascii=False))
            return 2

    # U70: a contract that names a task type reaches the local model only when this model artifact is QUALIFIED for
    # it. U67-O1b sent a JSON extraction to a model that fails that format; the gate would have refused it for free.
    task_type = (contract or {}).get("task_type", "")
    if chosen in ("local", "cascade") and task_type and not args.approve:
        from .adapters.ollama_worker import DEFAULT_MODEL as LOCAL_MODEL
        from .model_qualification import local_admission

        local_model = getattr(args, "model", None) or (contract or {}).get("model") or LOCAL_MODEL
        status = local_admission(source_dir, model=local_model, task_type=task_type)
        if status != "QUALIFIED":
            print(json.dumps({"task_id": task_id, "state": "REFUSED", "error_class": "LOCAL_NOT_QUALIFIED",
                              "verdict_hint": "BLOCKED", "worker": chosen, "model": local_model,
                              "task_type": task_type, "qualification": status},
                             indent=2, ensure_ascii=False))
            return 2

    work_dir = Path(args.work_dir) if args.work_dir else Path(".coord")
    mandatory_roots = mandatory_watch_roots(work_dir, source_dir)
    explicit_roots = [Path(w).resolve() for w in args.watch_root] if args.watch_root else []
    watch_roots = list(dict.fromkeys(mandatory_roots + explicit_roots))
    agy_cmd = resolve_worker_command(chosen, args.agy_command)
    # Pre-spend hard cap for a Claude worker (Codex): the contract's dollar cap goes to `claude --max-budget-usd`.
    # The token gate after the run stays; dollars are never inferred from tokens (model and cache prices differ).
    usd_cap = str(contract.get("remote_budget_usd") or "") if contract else ""

    def _with_cap(command: list[str], worker: str) -> list[str]:
        return [*command, "--max-budget-usd", usd_cap] if worker == "claude" and usd_cap else command

    agy_cmd = _with_cap(agy_cmd, chosen)

    from .pilot import PilotConfig, run_pilot

    allowed = list(contract["allow"]) if contract else []
    allowed += list(getattr(args, "allow", None) or [])
    remote_budget = int(contract.get("remote_budget_tokens") or 0) if contract else None
    config = PilotConfig(
        task_id=task_id,
        title=args.title or f"Pilot task {task_id}",
        prompt=prompt,
        source_dir=source_dir,
        work_dir=work_dir,
        agy_command=agy_cmd,
        watch_roots=watch_roots,
        print_timeout_s=int(contract["timeout_s"]) if contract else args.print_timeout,
        approve_bundle_id=args.approve,
        accept_cmd=args.accept_cmd or (contract["acceptance"] if contract else None),
        # U38: a contract may name its model (e.g. a Claude worker's Haiku or Sonnet); --model on the command line wins.
        model=getattr(args, "model", None) or ((contract.get("model") or None) if contract else None),
        allow_no_changes=getattr(args, "allow_no_changes", False),
        allowed_scopes=allowed or None,
        # B85: every paid run is checked against the contract budget, not only a cascade escalation.
        remote_budget_tokens=(remote_budget or None) if chosen in REMOTE_WORKERS else None,
    )

    from .broker.core import BrokerAlreadyRunning
    from .isolation.errors import SourceDivergenceError

    try:
        summary = run_pilot(config)
    except BrokerAlreadyRunning:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "BROKER_ALREADY_RUNNING",
            "effect_state": "NONE",
            "verdict_hint": "BLOCKED",
            "message": "Another broker is currently running on this work directory.",
        }
    except SourceDivergenceError as exc:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "SOURCE_DIVERGED",
            "effect_state": "NONE",
            "verdict_hint": "BLOCKED",
            "message": f"Source directory diverged from staging baseline: {exc}",
        }
    except sqlite3.DatabaseError as exc:
        summary = {
            "task_id": task_id,
            "state": "FAILED",
            "error_class": "DB_UNAVAILABLE",
            "effect_state": "UNKNOWN",
            "verdict_hint": "BLOCKED",
            "message": f"Database error or corruption: {exc}. Recovery hint: run 'python -m v7_harness.cli pilot reconcile --task {task_id}' or backup coord.sqlite3.",
        }

    # cascade: 싼 local 을 먼저 쓰고 실패 종류에 따라 한 번만 넘긴다. A/B(2026-09-23, 10과제): local 6/10·51.8초,
    # lane 9/10·218초(4.2배), 계산상 cascade 10/10·2.7배. 같은 id 재실행은 원장이 막으므로 단계마다 id가 다르다.
    # U39 (docs/41 §5): deterministic → Ollama once → Antigravity once. Only a format-only failure gets one more local
    # try, inside the same local budget; a semantic failure never loops locally; a remote failure goes to splitting.
    # The approval run stays on the original task. Every stage runs under its own task id.
    def _run(cfg: Any) -> dict[str, Any]:
        try:
            return run_pilot(cfg)
        except (BrokerAlreadyRunning, SourceDivergenceError, sqlite3.DatabaseError) as exc:
            return {"task_id": cfg.task_id, "state": "FAILED", "error_class": type(exc).__name__,
                    "effect_state": "UNKNOWN", "verdict_hint": "BLOCKED", "message": str(exc)}

    if chosen == "cascade" and not args.approve:
        from .routing import classify_failure, local_tokens, next_route

        failure = classify_failure(summary)
        used_local = local_tokens(summary)
        trace = [f"local:{failure or 'PASS'}"]
        route = next_route("local", failure, local_attempts=1, local_tokens=used_local)
        if route == "local_retry":
            config.task_id = f"{task_id}-retry"
            summary = _run(config)
            failure = classify_failure(summary)
            used_local += local_tokens(summary)
            trace.append(f"local_retry:{failure or 'PASS'}")
            route = next_route("local_retry", failure, local_attempts=2, local_tokens=used_local)
        if route == "remote":
            first = summary
            escalate_to = getattr(args, "escalate_to", "agy")
            escalation = (_admission(source_dir, escalate_to, contract)
                          if escalate_to in REMOTE_WORKERS and remote_budget else None)
            if escalate_to in REMOTE_WORKERS and not remote_budget:
                # B85 rework: no contract budget, no paid escalation (lane runs the local model and stays allowed).
                summary["escalation"] = "REFUSED:REMOTE_WITHOUT_MANUAL"
                trace.append("refused")
            elif escalation is not None and escalation["decision"] == "REFUSE":
                # U69: the same admission as a direct paid run; the local result stays the answer.
                summary["escalation"] = "REFUSED:ADMISSION:" + ";".join(escalation["reasons"])
                summary["admission"] = escalation
                trace.append("refused")
            else:
                config.task_id = f"{task_id}-{escalate_to}"
                config.agy_command = _with_cap(resolve_worker_command(escalate_to, None), escalate_to)
                config.remote_budget_tokens = (remote_budget or None) if escalate_to in REMOTE_WORKERS else None
                summary = _run(config)
                summary["cascade_from"] = {"task_id": task_id, "verdict_hint": first.get("verdict_hint"),
                                           "error_class": first.get("error_class"), "escalated_to": escalate_to}
                remote_failure = classify_failure(summary)
                trace.append(f"remote:{remote_failure or 'PASS'}")
                if next_route("remote", remote_failure, local_attempts=2, local_tokens=used_local) == "split":
                    trace.append("split")
        elif route == "stop":
            trace.append("stop")
        summary["route"] = trace
    # The pilot gates the budget itself (B85). This covers a summary that came back without the gate.
    if remote_budget and "cost_gate" not in summary and (chosen in REMOTE_WORKERS or "cascade_from" in summary):
        from .pilot import evaluate_cost_gate

        summary["cost_gate"] = evaluate_cost_gate(summary.get("agy_usage"), remote_budget)
        if summary["cost_gate"] != "WITHIN":
            summary["verdict_hint"] = "BLOCKED"
            summary["error_class"] = "COST_UNKNOWN" if summary["cost_gate"] == "UNKNOWN" else "COST_EXCEEDED"

    # U33: 보고는 기억이 아니라 실행 끝에서 저절로 남는다(비둘기 퇴출). 기록 대상은 --source 프로젝트이고,
    # .coord/PLAN.md 가 있는 UAOS 프로젝트일 때만 쓴다. 예전에 기본을 켰을 때 CLI 를 부르는 테스트가 실제
    # 스트림에 사건 8건을 흘렸다. 테스트 패키지는 UAOS_STREAM_AUTOLOG=0 으로 끈다(tests/__init__.py).
    if getattr(args, "coord_log", False) and os.environ.get("UAOS_STREAM_AUTOLOG", "1") != "0":
        coord_project = Path(getattr(args, "coord_project", None) or source_dir)
        actor = getattr(args, "coord_actor", None) or detect_actor()
        if (coord_project / ".coord" / "PLAN.md").is_file() and actor:
            record_pilot_in_stream(coord_project, summary, actor=actor, task=summary.get("task_id") or task_id)

    if routed is not None:
        summary["routed_by"] = routed
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    # ACCEPT_INFRA·ACCEPT_NOT_RUN으로 state가 SUCCEEDED여도 BLOCKED 판정이면 1 반환
    if summary.get("verdict_hint") == "BLOCKED":
        return 1
    return 0 if summary.get("state") == "SUCCEEDED" else 1


def cmd_pilot_manual_lint(args: argparse.Namespace) -> int:
    from .manual import lint

    source = Path(args.source) if args.source else manual_project(Path(args.manual))
    report = lint(Path(args.manual).read_text(encoding="utf-8"), source)
    print(json.dumps(report.as_dict(), indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def cmd_pilot_manual_new(args: argparse.Namespace) -> int:
    from .manual import lint, new_manual

    source = Path(args.source)
    instructions = Path(args.instructions_file).read_text(encoding="utf-8") if args.instructions_file else ""
    text = new_manual(
        source,
        work_id=args.work_id,
        worker=args.worker,
        goal=args.goal,
        inputs=args.input,
        allow=args.allow,
        acceptance=args.accept,
        judge=args.judge,
        timeout_s=args.timeout,
        remote_budget_tokens=args.remote_budget,
        remote_budget_usd=args.remote_budget_usd,
        instructions=instructions,
        context_allow=args.context_allow,
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    report = lint(text, source)
    print(json.dumps({"written": str(out), **report.as_dict()}, indent=2, ensure_ascii=False))
    return 0 if report.ok else 1


def cmd_pilot_reconcile(args: argparse.Namespace) -> int:
    from .pilot import reconcile_pilot

    work_dir = Path(args.work_dir) if args.work_dir else Path(".coord")
    try:
        report = reconcile_pilot(work_dir=work_dir, task_id=args.task)
    except sqlite3.DatabaseError as exc:
        report = {
            "task_id": args.task,
            "state": "FAILED",
            "error_class": "DB_UNAVAILABLE",
            "message": f"Database corruption detected during reconcile: {exc}. Recovery hint: restore coord.sqlite3 from backup.",
        }
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="v7_harness", description="v7 Minimal Automation Harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # lease-check
    p_lease = subparsers.add_parser("lease-check")
    p_lease.add_argument("--file", required=True)
    p_lease.add_argument("--scope", default=None)
    p_lease.set_defaults(func=cmd_lease_check)

    # ledger-append
    p_lapp = subparsers.add_parser("ledger-append")
    p_lapp.add_argument("--ledger-file", required=True)
    p_lapp.add_argument("--task-id", required=True)
    p_lapp.add_argument("--actor", required=True)
    p_lapp.add_argument("--category", required=True)
    p_lapp.add_argument("--content", required=True)
    p_lapp.add_argument("--rationale", default=None)
    p_lapp.add_argument("--assumption", default=None)
    p_lapp.add_argument("--invalidation-condition", default=None)
    p_lapp.set_defaults(func=cmd_ledger_append)

    # ledger-verify
    p_lver = subparsers.add_parser("ledger-verify")
    p_lver.add_argument("--ledger-file", required=True)
    p_lver.set_defaults(func=cmd_ledger_verify)

    # receipt-run
    p_run = subparsers.add_parser("receipt-run")
    p_run.add_argument("--task-id", required=True)
    p_run.add_argument("--actor", required=True)
    p_run.add_argument("--store", default=None)
    p_run.add_argument("cmd", nargs=argparse.REMAINDER)
    p_run.set_defaults(func=cmd_receipt_run)

    # snapshot
    p_snap = subparsers.add_parser("snapshot")
    p_snap.add_argument("--target-path", default=None)
    p_snap.add_argument("--output", default=None)
    p_snap.add_argument("--force-non-git", action="store_true")
    p_snap.set_defaults(func=cmd_snapshot)

    # eval-next
    p_eval = subparsers.add_parser("eval-next")
    p_eval.add_argument("--current-task-id", required=True)
    p_eval.add_argument("--next-task", default="U08")
    p_eval.add_argument("--has-failures", action="store_true")
    p_eval.add_argument("--pending-actions", nargs="*", default=[])
    p_eval.set_defaults(func=cmd_eval_next)

    # benchmark
    p_bench = subparsers.add_parser("benchmark")
    p_bench.add_argument("--name", default="sample_bench")
    p_bench.set_defaults(func=cmd_benchmark)

    # report
    p_rep = subparsers.add_parser("report")
    p_rep.add_argument("--result", required=True)
    p_rep.add_argument("--changed", nargs="*", default=[])
    p_rep.add_argument("--verification", nargs="*", default=None, help="Explicit verification items or summary")
    p_rep.add_argument("--risks", default="None")
    p_rep.add_argument("--next-action", default="Proceed to review")
    p_rep.add_argument("--user-action-required", action="store_true")
    p_rep.set_defaults(func=cmd_report)

    # pilot run
    p_pilot = subparsers.add_parser("pilot")
    p_pilot_subs = p_pilot.add_subparsers(dest="pilot_subcommand", required=True)
    p_pilot_run = p_pilot_subs.add_parser("run")
    p_pilot_run.add_argument("--task", "--task-id", dest="task", required=True, help="Pilot task ID (e.g. P01)")
    p_pilot_run.add_argument("--source", "--source-dir", dest="source", required=True, help="Source directory path")
    p_pilot_run.add_argument("--prompt-file", default=None, help="Path to prompt file")
    p_pilot_run.add_argument("--prompt", default=None, help="Prompt text directly")
    p_pilot_run.add_argument("--title", default=None, help="Task title")
    p_pilot_run.add_argument("--work-dir", default=".coord", help="Work directory (default: .coord)")
    p_pilot_run.add_argument("--approve", default=None, help="Approve bundle ID for live promotion")
    p_pilot_run.add_argument("--watch-root", action="append", default=[], help="Watch roots for external write detection")
    p_pilot_run.add_argument("--print-timeout", type=int, default=600, help="Print timeout in seconds")
    p_pilot_run.add_argument("--agy-command", nargs="*", default=None, help="Custom worker command prefix (overrides --worker)")
    p_pilot_run.add_argument("--worker", choices=["agy", "local", "lane", "cascade", "auto", "apply", "claude"], default="agy", help="claude = Claude Code on the paid account (needs a manual with remote_budget_tokens; judge codex or user); agy = remote worker (uses account quota); local = this machine's Ollama model, one-shot; lane = Claude Code tool loop on the local model; apply = apply the ===FILE/===EDIT blocks written in the prompt, no model (0 tokens)")
    p_pilot_run.add_argument("--manual", default=None,
                             help="Work manual with a ```contract block: linted first, then its worker, acceptance, allow list and timeout drive the run")
    p_pilot_run.add_argument("--allow", action="append", default=[],
                             help="Path or glob the worker may change (repeatable); anything else is rejected as SCOPE_VIOLATION")
    # cascade 승격 대상 작업자(lane의 e2e 실패 빈발로 기본값은 agy)
    p_pilot_run.add_argument("--escalate-to", choices=["agy", "lane", "claude"], default="agy", help="Worker for cascade second stage when local gets REWORK (default: agy)")
    p_pilot_run.add_argument("--coord-log", dest="coord_log", action="store_true", default=True,
                             help="Record this run in the coordination stream (.coord/stream); on by default")
    p_pilot_run.add_argument("--no-coord-log", dest="coord_log", action="store_false",
                             help="Do not record this run in the coordination stream")
    p_pilot_run.add_argument("--coord-project", default=None,
                             help="Project whose coordination stream records this run (default: the --source project)")
    p_pilot_run.add_argument("--coord-actor", choices=["codex", "claude", "antigravity", "user"], default=None,
                             help="Who ran this pilot (default: detected from the calling tool's environment)")
    p_pilot_run.add_argument("--model", default=None, help="Model name to pass to agy (e.g. gemini-3.7-flash)")
    p_pilot_run.add_argument("--accept-cmd", default=None, help="Acceptance test command to run in staging")
    p_pilot_run.add_argument("--allow-no-changes", action="store_true", default=False, help="Allow PASS verdict even when no files were changed (for read-only tasks)")
    p_pilot_run.set_defaults(func=cmd_pilot_run)

    # pilot manual: U34 work-manual contracts
    p_pilot_manual = p_pilot_subs.add_parser("manual")
    p_manual_subs = p_pilot_manual.add_subparsers(dest="manual_subcommand", required=True)
    p_manual_lint = p_manual_subs.add_parser("lint")
    p_manual_lint.add_argument("--manual", required=True)
    p_manual_lint.add_argument("--source", default=None,
                               help="Project the manual's paths are relative to (default: the folder above the manual "
                                    "that holds .coord/PLAN.md, else the current folder)")
    p_manual_lint.set_defaults(func=cmd_pilot_manual_lint)
    p_manual_new = p_manual_subs.add_parser("new")
    p_manual_new.add_argument("--out", required=True, help="Manual file to write")
    p_manual_new.add_argument("--source", default=".")
    p_manual_new.add_argument("--work-id", required=True)
    p_manual_new.add_argument("--worker", required=True, choices=["local", "apply", "agy", "lane", "cascade", "claude"])
    p_manual_new.add_argument("--goal", required=True)
    p_manual_new.add_argument("--input", action="append", default=[], help="Input file to pin by SHA-256 (repeatable)")
    p_manual_new.add_argument("--allow", action="append", default=[], required=True)
    p_manual_new.add_argument("--context-allow", action="append", default=None,
                              help="U50: extra file or pattern the worker may see (repeatable); omit to keep all")
    p_manual_new.add_argument("--accept", required=True, help="Acceptance command")
    p_manual_new.add_argument("--judge", required=True, choices=["codex", "claude", "antigravity", "user"])
    p_manual_new.add_argument("--timeout", type=int, default=180)
    p_manual_new.add_argument("--remote-budget", type=int, default=0)
    p_manual_new.add_argument("--remote-budget-usd", type=float, default=0.0,
                              help="Dollar cap for worker claude (claude --max-budget-usd); lint requires it > 0")
    p_manual_new.add_argument("--instructions-file", default=None, help="Prose instructions to append")
    p_manual_new.set_defaults(func=cmd_pilot_manual_new)

    # pilot reconcile
    p_pilot_review = p_pilot_subs.add_parser("review", help="U38: read-only advisory review of a bundle by Claude Code")
    p_pilot_review.add_argument("--task", required=True)
    p_pilot_review.add_argument("--work-dir", required=True)
    p_pilot_review.add_argument("--source", default=".")
    p_pilot_review.add_argument("--manual", required=True, help="The contract manual the bundle was built from")
    p_pilot_review.add_argument("--reviewer", default="claude", choices=["claude", "agy"],
                                help="agy = Antigravity CLI, read-only, token budget only (U46-J1, docs/47)")
    # U47-C2 (2026-09-28): still required, but the help names the decided value; a measured claude review took
    # 94,953 counted tokens (cache reads included) and $0.176, so 80,000 failed as UNUSABLE (docs/47 §1-1 C2).
    p_pilot_review.add_argument("--budget", type=int, required=True,
                                help="Token budget for the review call, cache reads included; "
                                     "claude review: 120000 (U47-C2)")
    # Not required by argparse any more: run_review refuses a claude review without it (agy has no dollar option).
    p_pilot_review.add_argument("--budget-usd", type=float, default=0.0,
                                help="Dollar cap passed to claude --max-budget-usd (checked before spending); "
                                     "required for --reviewer claude; claude review: 0.25 (U47-C2)")
    p_pilot_review.add_argument("--model", default=None)
    p_pilot_review.add_argument("--timeout", type=int, default=600)
    p_pilot_review.set_defaults(func=cmd_pilot_review)

    # U46-J4: binding judgement by the contract's judge tool through its CLI, only while Codex is LIMITED/ABSENT.
    p_pilot_judge = p_pilot_subs.add_parser("judge", help="U46-J4: Antigravity judges a bundle via its CLI while Codex is away")
    p_pilot_judge.add_argument("--task", required=True)
    p_pilot_judge.add_argument("--work-dir", required=True)
    p_pilot_judge.add_argument("--source", default=".")
    p_pilot_judge.add_argument("--manual", required=True, help="The contract manual the bundle was built from")
    p_pilot_judge.add_argument("--project", default=None, help="Project whose presence desk says Codex is away")
    p_pilot_judge.add_argument("--judge", default="agy", choices=["agy", "codex"])
    p_pilot_judge.add_argument("--budget", type=int, default=None,
                               help="Token cap; default scales with the diff: clamp(30,000 + 3 x diff chars, "
                                    "100,000, 250,000) (U47-J5: R1c's 34 KB bundle cost 114,644)")
    p_pilot_judge.add_argument("--timeout", type=int, default=600)
    p_pilot_judge.add_argument("--no-apply", action="store_true", help="Record the verdict without running --approve")
    p_pilot_judge.set_defaults(func=cmd_pilot_judge)

    p_pilot_rec = p_pilot_subs.add_parser("reconcile")
    p_pilot_rec.add_argument("--task", "--task-id", dest="task", required=True, help="Pilot task ID to reconcile")
    p_pilot_rec.add_argument("--work-dir", default=".coord", help="Work directory (default: .coord)")
    p_pilot_rec.set_defaults(func=cmd_pilot_reconcile)

    # coord: U15 조율 스트림
    p_coord = subparsers.add_parser("coord")
    p_coord_subs = p_coord.add_subparsers(dest="coord_subcommand", required=True)

    p_coord_log = p_coord_subs.add_parser("log")
    p_coord_log.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_log.add_argument("--actor", required=True, choices=["codex", "antigravity", "claude"])
    p_coord_log.add_argument("--kind", required=True, choices=["PLAN", "RUN", "VERDICT", "BLOCKED", "HANDOFF", "NOTE"])
    p_coord_log.add_argument("--step", required=True, help="Step or task id (e.g. U15-S4)")
    p_coord_log.add_argument("--summary", required=True, help="One line, 200 chars max")
    p_coord_log.add_argument("--ref", action="append", default=[], help="Evidence path (repeatable)")
    p_coord_log.add_argument("--cmd", default=None, help="Command that produced the evidence")
    p_coord_log.add_argument("--exit-code", dest="exit_code", type=int, default=None, help="Exit code of that command")
    p_coord_log.add_argument("--bundle", default=None, help="Bundle id when a promotion is involved")
    p_coord_log.set_defaults(func=cmd_coord_log)

    p_coord_status = p_coord_subs.add_parser("status")
    p_coord_status.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_status.set_defaults(func=cmd_coord_status)

    p_coord_brief = p_coord_subs.add_parser("brief")
    p_coord_brief.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_brief.add_argument("--owner", default=None, help="Current step owner")
    p_coord_brief.add_argument("--lock", default=None, help="Active lock, if any")
    p_coord_brief.add_argument("--pending", action="append", default=[], help="Item waiting for a Codex verdict (repeatable)")
    p_coord_brief.add_argument("--next", action="append", default=[], help="Next candidate (repeatable)")
    p_coord_brief.add_argument("--write", action="store_true", default=False, help="Write .coord/codex_brief.md instead of printing")
    p_coord_brief.set_defaults(func=cmd_coord_brief)

    p_coord_notify = p_coord_subs.add_parser("notify")
    p_coord_notify.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_notify.add_argument("--actor", required=True, choices=["codex", "antigravity", "claude"])
    p_coord_notify.add_argument("--headline", required=True, help="One line for the Codex window")
    p_coord_notify.add_argument("--thread", default=None, help="Codex session id (default: newest session for this project)")
    p_coord_notify.add_argument("--pending", action="append", default=[], help="Verdict-waiting item (default: read from PLAN)")
    p_coord_notify.add_argument(
        "--verdict-requested",
        choices=["yes", "no", "auto"],
        default="auto",
        help="Override verdict_requested (yes/no/auto; auto sets no if codex is absent)",
    )
    p_coord_notify.add_argument("--send", action="store_true", default=False, help="Actually queue it (default: dry run)")
    p_coord_notify.set_defaults(func=cmd_coord_notify)

    p_coord_archive = p_coord_subs.add_parser("archive")
    p_coord_archive.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_archive.set_defaults(func=cmd_coord_archive)

    p_coord_deliver = p_coord_subs.add_parser("deliver", help="Durable direct tool delivery")
    p_coord_deliver.add_argument("--project", default=".")
    p_coord_deliver.add_argument("--actor", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_deliver.add_argument("--target", default=None, choices=["codex", "claude"])
    p_coord_deliver.add_argument("--message", required=True)
    p_coord_deliver.add_argument("--thread", default="")
    p_coord_deliver.set_defaults(func=cmd_coord_deliver)

    p_coord_sentinel = p_coord_subs.add_parser("sentinel")
    p_coord_sentinel.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_sentinel.add_argument("--once", action="store_true", default=False, help="Run single cycle and exit")
    p_coord_sentinel.add_argument("--loop", action="store_true", default=False, help="Run continuous monitoring loop")
    p_coord_sentinel.add_argument("--interval", type=int, default=30, help="Loop interval in seconds (default: 30)")
    p_coord_sentinel.add_argument("--write-brief", action="store_true", default=False, help="Write .coord/codex_brief.md")
    p_coord_sentinel.add_argument("--recipient", default="codex", help="P1 alert recipient (default: codex)")
    p_coord_sentinel.add_argument("--log", default=None,
                                  help="Append each cycle's JSON line to this file (a resident loop has no console)")
    p_coord_sentinel.add_argument("--ring", action="store_true", default=False,
                                  help="Ring Codex (codex queue) for waiting P1 wakes while Codex has a fresh ACTIVE heartbeat")
    p_coord_sentinel.set_defaults(func=cmd_coord_sentinel)

    p_coord_presence = p_coord_subs.add_parser("presence")
    p_coord_presence.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_presence.add_argument("--tool", choices=["codex", "claude", "antigravity"], default=None)
    p_coord_presence.add_argument("--state", choices=["ACTIVE", "LIMITED", "ABSENT"], default=None)
    p_coord_presence.add_argument("--ttl", type=int, default=3600, help="Seconds until the heartbeat reads UNKNOWN")
    p_coord_presence.add_argument("--if-uaos", action="store_true", default=False,
                                  help="Do nothing unless the project has .coord/PLAN.md (for global session hooks)")
    p_coord_presence.add_argument("--from-hook", action="store_true", default=False,
                                  help="Find the project from the hook payload on stdin (cwd, workspacePaths), "
                                       "CLAUDE_PROJECT_DIR or --project, walking up to .coord/PLAN.md; never fails the hook")
    p_coord_presence.add_argument("--say", choices=["json", "brief", "none", "empty-json", "p1"], default="json",
                                  help="What to print: presence JSON (default), one context line, nothing, {}, or "
                                       "p1 = one line only when a P1 wake waits and Codex is not ACTIVE (U38)")
    # U57-D: the acting conductor had to write a Codex quota lease through Python (2026-09-27); the lease itself
    # (U47-A1b) already existed in presence.mark, only the flag was missing.
    p_coord_presence.add_argument("--lease", action="store_true", default=False,
                                  help="Record a capability lease that ordinary heartbeats cannot overwrite until --ttl")
    p_coord_presence.set_defaults(func=cmd_coord_presence)

    p_coord_watch = p_coord_subs.add_parser("watch", help="Block until a new mailbox letter for a target arrives")
    p_coord_watch.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_watch.add_argument("--target", action="append", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_watch.add_argument("--timeout", type=float, default=4 * 3600.0, help="Seconds before exit 3 (default: 4 h)")
    p_coord_watch.add_argument("--interval", type=float, default=30.0, help="Seconds between inbox scans (default: 30)")
    p_coord_watch.set_defaults(func=cmd_coord_watch)

    p_coord_route = p_coord_subs.add_parser("route", help="Choose the sole authority from fresh presence states")
    p_coord_route.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_route.set_defaults(func=cmd_coord_route)
    p_coord_collect = p_coord_subs.add_parser(
        "usage-collect", help="Find usage rows left only in linked worktrees; --apply appends them to the desk ledger")
    p_coord_collect.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_collect.add_argument("--apply", action="store_true", help="Append the orphan rows (default: dry run)")
    p_coord_collect.set_defaults(func=cmd_coord_usage_collect)
    p_coord_session = p_coord_subs.add_parser(
        "usage-session", help="Record a Claude Code transcript's or Codex rollout's tokens since its last recorded window (U73, U74)")
    p_coord_session.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_session.add_argument("--transcript", required=True, help="The Claude Code transcript .jsonl or Codex rollout-*.jsonl; the actor is read from its format")
    p_coord_session.add_argument("--work-id", required=True, help="Card the recorded window is attributed to")
    p_coord_session.add_argument("--apply", action="store_true", help="Append the row (default: dry run)")
    p_coord_session.set_defaults(func=cmd_coord_usage_session)

    p_coord_thrift = p_coord_subs.add_parser("thrift", help="Prepare a deterministic local budget handoff packet")
    p_coord_thrift.add_argument("--project", default=".")
    p_coord_thrift.add_argument("--tool", required=True, choices=["codex", "claude", "antigravity"])
    p_coord_thrift.add_argument("--remaining-percent", required=True, type=float)
    p_coord_thrift.add_argument("--reset-at", default=None)
    p_coord_thrift.add_argument("--thrift-at", type=float, default=20)
    p_coord_thrift.add_argument("--handoff-at", type=float, default=7)
    p_coord_thrift.add_argument("--current-card", default="")
    p_coord_thrift.add_argument("--next-action", default="")
    p_coord_thrift.add_argument("--acceptance", default="")
    p_coord_thrift.add_argument("--stop-condition", default="")
    p_coord_thrift.set_defaults(func=cmd_coord_thrift)

    p_coord_init = p_coord_subs.add_parser("init")
    p_coord_init.add_argument("--project", default=".", help="Project to prepare for UAOS (default: .)")
    p_coord_init.set_defaults(func=cmd_coord_init)

    p_coord_inbox = p_coord_subs.add_parser("inbox")
    p_coord_inbox.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_inbox.set_defaults(func=cmd_coord_inbox)

    p_coord_ack = p_coord_subs.add_parser("ack")
    p_coord_ack.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_ack.add_argument("--id", dest="message_id", required=True, help="Mailbox message id to mark handled")
    p_coord_ack.add_argument("--consumer", default="commander", help="Who handled it (default: commander)")
    p_coord_ack.set_defaults(func=cmd_coord_ack)

    p_coord_pub = p_coord_subs.add_parser("publish-thread")
    p_coord_pub.add_argument("--actor", required=True, choices=["agy", "claude", "antigravity"])
    p_coord_pub.add_argument("--task", required=True, help="Task name (e.g. 'MIA 전략 레드팀')")
    p_coord_pub.add_argument("--prompt", default="", help="User prompt text (optional if --transcript is given)")
    p_coord_pub.add_argument("--response", default=None, help="Assistant response text")
    p_coord_pub.add_argument("--response-file", default=None, help="File containing assistant response text")
    p_coord_pub.add_argument("--transcript", default=None, help="Path to transcript.jsonl for full session import")
    p_coord_pub.add_argument("--thread-id", default=None, help="Optional thread UUID")
    p_coord_pub.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_pub.set_defaults(func=cmd_coord_publish_thread)

    # rsi: evidence-gated self-improvement (docs/38). observe → propose → try → gate → judge → rollback.
    p_rsi = subparsers.add_parser("rsi", help="Evidence-gated self-improvement: report, propose, gate, adopt, rollback")
    p_rsi_subs = p_rsi.add_subparsers(dest="rsi_subcommand", required=True)
    p_rsi_report = p_rsi_subs.add_parser("report", help="Per-worker pass/rework/blocked rates and recurring causes")
    p_rsi_report.add_argument("--project", default=".")
    p_rsi_report.set_defaults(func=cmd_rsi_report)
    p_rsi_propose = p_rsi_subs.add_parser("propose", help="Deterministic remedies for the causes in the ledger")
    p_rsi_propose.add_argument("--project", default=".")
    p_rsi_propose.add_argument("--candidate-for", default=None, metavar="PROPOSAL_ID",
                               help="Print a candidate file to fill after the trial runs")
    p_rsi_propose.add_argument("--author", default=None, help="Author of the candidate (default: detected tool)")
    p_rsi_propose.set_defaults(func=cmd_rsi_propose)
    p_rsi_gate = p_rsi_subs.add_parser("gate", help="Judge a tried candidate on ledger evidence (read only)")
    p_rsi_gate.add_argument("--project", default=".")
    p_rsi_gate.add_argument("--candidate", required=True, help="Candidate JSON file")
    p_rsi_gate.set_defaults(func=cmd_rsi_gate)
    p_rsi_adopt = p_rsi_subs.add_parser("adopt", help="Refused by design (B83): prints the gate evidence and the proposed file for a PLAN card")
    p_rsi_adopt.add_argument("--project", default=".")
    p_rsi_adopt.add_argument("--candidate", required=True)
    p_rsi_adopt.add_argument("--judge", required=True, choices=["codex", "claude", "user"],
                             help="Codex, Claude while Codex is absent, or the user (docs/31 §3)")
    p_rsi_adopt.set_defaults(func=cmd_rsi_adopt)
    p_rsi_rollback = p_rsi_subs.add_parser("rollback", help="Refused by design (B83): prints the previous policy as a proposed file")
    p_rsi_rollback.add_argument("--project", default=".")
    p_rsi_rollback.add_argument("--judge", required=True, choices=["codex", "claude", "user"])
    p_rsi_rollback.add_argument("--reason", required=True)
    p_rsi_rollback.set_defaults(func=cmd_rsi_rollback)

    p_rsi_watch = p_rsi_subs.add_parser("watch", help="Deterministic change detection cycle (U42)")
    p_rsi_watch.add_argument("--project", default=".")
    p_rsi_watch.add_argument("--config", default=None, help="Watcher config JSON path")
    p_rsi_watch.set_defaults(func=cmd_rsi_watch)

    p_rsi_prepare = p_rsi_subs.add_parser("prepare", help="Prepare a release packet (dry-run by default, --apply to write)")
    p_rsi_prepare.add_argument("--project", default=".")
    p_rsi_prepare.add_argument("--packet", required=True, help="Release packet JSON file")
    p_rsi_prepare.add_argument("--apply", action="store_true", help="Write version and update documents")
    p_rsi_prepare.add_argument("--date", default="2026-09-25", help="Release date string")
    p_rsi_prepare.set_defaults(func=cmd_rsi_prepare)

    p_rsi_ship = p_rsi_subs.add_parser("ship", help="Ship an approved release (dry-run by default, --execute to push & pr)")
    p_rsi_ship.add_argument("--project", default=".")
    p_rsi_ship.add_argument("--packet", required=True, help="Release packet JSON file")
    p_rsi_ship.add_argument("--approval", required=True, help="Approval receipt JSON file")
    p_rsi_ship.add_argument("--execute", action="store_true", help="Execute git commit, push, and gh pr create")
    p_rsi_ship.set_defaults(func=cmd_rsi_ship)

    p_rsi_schedule = p_rsi_subs.add_parser("schedule", help="Manage Windows Task Scheduler for RSI watch")
    p_rsi_schedule.add_argument("--project", default=".")
    p_rsi_schedule.add_argument("--action", choices=["install", "status", "remove", "manual-now"], default="status")
    p_rsi_schedule.add_argument("--apply", action="store_true", help="Apply schtasks command / run manual-now")
    p_rsi_schedule.add_argument("--python-bin", default=None, help="Python executable path")
    p_rsi_schedule.set_defaults(func=cmd_rsi_schedule)

    p_rsi_retention = p_rsi_subs.add_parser("retention", help="Deletion-free retention plan (dry-run manifest, U42-R1)")
    p_rsi_retention.add_argument("--project", default=".")
    p_rsi_retention.add_argument("--archive", action="store_true", help="Archive candidate files into a verified zip")
    p_rsi_retention.add_argument("--rollup-olla", action="store_true", help="Roll up olla usage ledger")
    p_rsi_retention.add_argument("--purge", default=None, metavar="ZIP",
                                 help="Validate an archive then return the fail-closed deletion boundary")
    p_rsi_retention.add_argument("--approval", default=None, metavar="FILE",
                                 help="Compatibility only; file labels are never treated as authentication")
    p_rsi_retention.set_defaults(func=cmd_rsi_retention)

    return parser


def detect_actor() -> Optional[str]:
    """Which of the three tools is running this command, from its shell environment. None for a plain terminal."""
    from .olla import _caller

    caller = _caller()
    return caller if caller in ("codex", "claude", "antigravity") else None


def record_pilot_in_stream(project: Path, summary: dict, *, actor: str = "claude", task: Optional[str] = None) -> Optional[str]:
    """파일럿 결과를 조율 스트림에 한 줄로 남긴다.

    사람이 기억해서 적으면 빠뜨린다. 실행이 끝나는 자리에서 바로 남겨야 지휘자가
    무엇을 판정해야 하는지 알 수 있다. 기록이 실패해도 파일럿 결과 보고는 막지 않는다.
    """
    from .coord.stream import StreamRejected, append_event

    verdict = str(summary.get("verdict_hint") or "UNKNOWN")
    state = str(summary.get("state") or "UNKNOWN")
    # run_pilot's summary has no task_id on a normal run, so every event used to read "pilot".
    task = str(task or summary.get("task_id") or "pilot")
    changed = summary.get("changed_files") or []
    bundle = summary.get("bundle_id") or ""
    promotion = summary.get("promotion") or ""
    kind = "RUN" if state == "SUCCEEDED" else "BLOCKED"
    detail = f"{state}/{verdict}"
    if promotion:
        detail += f"/{promotion}"
    summary_line = f"파일럿 {task}: {detail}, 변경 {len(changed)}개"
    if summary.get("error_class") not in (None, "", "NONE"):
        summary_line += f", {summary['error_class']}"

    evidence = {"cmd": f"pilot run --task {task}", "exit": 0 if state == "SUCCEEDED" else 1}
    if bundle:
        evidence["bundle"] = bundle
    refs = []
    if summary.get("summary_path"):
        # The stream refuses absolute refs, which silently dropped the whole event when --work-dir was absolute.
        ref = Path(str(summary["summary_path"]).replace("\\", "/"))
        if ref.is_absolute():
            try:
                ref = ref.resolve().relative_to(Path(project).resolve())
            except ValueError:
                ref = None
        if ref is not None:
            refs = [ref.as_posix()]
    try:
        event = append_event(
            project,
            actor=actor,
            kind=kind,
            step=task,
            summary=summary_line[:200],
            refs=refs,
            evidence=evidence,
        )
        return event.id
    except (StreamRejected, OSError, RuntimeError):
        # 기록 실패가 실행 보고를 덮지 않게 한다. 다음 브리핑에서 빈자리로 드러난다.
        return None


def cmd_pilot_review(args: argparse.Namespace) -> int:
    from .review import ReviewRefused, run_review

    try:
        manual_text = Path(args.manual).read_text(encoding="utf-8")
        record = run_review(task_id=args.task, work_dir=Path(args.work_dir), source=Path(args.source),
                            manual_text=manual_text, reviewer=args.reviewer, budget=args.budget,
                            budget_usd=args.budget_usd, model=args.model,
                            timeout_s=args.timeout)
    except (ReviewRefused, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **record}, ensure_ascii=False, indent=2))
    return 0


def cmd_pilot_judge(args: argparse.Namespace) -> int:
    from .judge import JudgeRefused, run_judge

    try:
        record = run_judge(task_id=args.task, work_dir=Path(args.work_dir), source=Path(args.source),
                           manual_path=Path(args.manual), project=Path(args.project) if args.project else None,
                           judge=args.judge, budget=args.budget, timeout_s=args.timeout, apply=not args.no_apply)
    except (JudgeRefused, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)[:400]}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **record}, ensure_ascii=False, indent=2))
    return 0 if record["verdict"] in ("APPROVE", "REJECT") else 3


def resolve_worker_command(worker: str, explicit: Optional[Sequence[str]]) -> list[str]:
    """어느 작업자에게 맡길지 정한다.

    `agy`는 계정 할당량을 쓰는 원격 작업자, `local`은 이 PC의 Ollama 모델이다.
    할당량이 소진돼도 진행이 멈추지 않도록 두 번째 손을 둔다. 판정은 어느 쪽이든
    파일럿의 인수 검사와 게이트가 하므로, 작업자가 약해도 거짓 성공은 통과하지 못한다.
    """
    if explicit:
        return list(explicit)
    if worker in ("local", "cascade"):  # cascade starts on local; cmd_pilot_run switches to lane on REWORK
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "ollama_worker.py")]
    if worker == "lane":  # Claude Code's tool loop on the local model; kept beside "local" for the A/B
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "lane_worker.py")]
    if worker == "apply":  # U34: the commander already wrote the code; apply it without a model
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "apply_worker.py")]
    if worker == "claude":  # U38: Claude Code on the paid account, budget-gated (docs/40)
        return [sys.executable, str(Path(__file__).resolve().parent / "adapters" / "claude_worker.py")]
    return ["agy"]


def cmd_coord_log(args: argparse.Namespace) -> int:
    """U15: 조율 사건 한 줄을 스트림에 남긴다. 세 도구가 같은 입구를 쓴다."""
    from .coord.stream import StreamRejected, append_event

    evidence: dict[str, object] = {}
    if args.cmd:
        evidence["cmd"] = args.cmd
    if args.exit_code is not None:
        evidence["exit"] = args.exit_code
    if args.bundle:
        evidence["bundle"] = args.bundle
    try:
        event = append_event(
            Path(args.project),
            actor=args.actor,
            kind=args.kind,
            step=args.step,
            summary=args.summary,
            refs=args.ref,
            evidence=evidence or None,
        )
    except StreamRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "id": event.id, "ts": event.ts}, ensure_ascii=False))
    return 0


def cmd_coord_status(args: argparse.Namespace) -> int:
    """Report coordinator and harness health status."""
    project = Path(args.project)
    lock_file = project / ".work" / "QUIET_LOCK"
    lock_status = "LOCKED" if lock_file.is_file() else "CLEAN"

    mailbox_dir = project / ".coord" / "mailbox" / "inbox"
    mailbox_count = len(list(mailbox_dir.glob("*.json"))) if mailbox_dir.is_dir() else 0

    from .coord.stream import StreamRejected, read_events

    try:
        stream_count = len(read_events(project))
    except StreamRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 1

    usage_file = project / ".coord" / "usage" / "runs.jsonl"
    usage_count = len(usage_file.read_text(encoding="utf-8").splitlines()) if usage_file.is_file() else 0

    out = {
        "ok": True,
        "lock": lock_status,
        "mailbox_pending": mailbox_count,
        "stream_events": stream_count,
        "ledger_entries": usage_count,
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_coord_brief(args: argparse.Namespace) -> int:
    """U15: 스트림을 접어 Codex 브리핑을 만든다. 같은 입력이면 같은 결과다."""
    from .coord.brief import brief_hash, pending_from_plan, render_brief, write_brief

    project = Path(args.project)
    # 판정 대기를 손으로 넘기지 않으면 PLAN 상태 칸에서 읽는다. 사람이 넘기면 빠뜨린다.
    pending = list(args.pending) or pending_from_plan(project)
    text = render_brief(
        project,
        owner=args.owner,
        lock=args.lock,
        pending=pending,
        next_candidates=args.next,
    )
    if args.write:
        path = write_brief(project, text)
        print(json.dumps({"ok": True, "path": str(path), "hash": brief_hash(text)[:12], "lines": len(text.splitlines())}, ensure_ascii=False))
    else:
        print(text, end="")
    return 0


def cmd_coord_notify(args: argparse.Namespace) -> int:
    """U15: 브리핑이 바뀌었을 때만 Codex 대화창으로 한 건 보낸다. 기본은 드라이런이다."""
    from .coord.brief import pending_from_plan
    from .coord.notify import NotifyRefused, notify, resolve_thread

    project = Path(args.project)
    brief_file = project / ".coord" / "codex_brief.md"
    if not brief_file.is_file():
        print(json.dumps({"ok": False, "error": "BRIEF_MISSING"}, ensure_ascii=False))
        return 1

    thread = args.thread or resolve_thread(project)
    if not thread:
        # 스레드를 못 고르면 보내지 않는다. 엉뚱한 작업 창에 배달하는 것보다 안 보내는 편이 낫다.
        print(json.dumps({"ok": False, "error": "THREAD_UNRESOLVED"}, ensure_ascii=False))
        return 1

    vr_arg = getattr(args, "verdict_requested", "auto")
    vr_val = True if vr_arg == "yes" else (False if vr_arg == "no" else None)

    try:
        result = notify(
            project,
            thread=thread,
            actor=args.actor,
            brief_text=brief_file.read_text(encoding="utf-8"),
            headline=args.headline,
            pending=list(args.pending) or pending_from_plan(project),
            verdict_requested=vr_val,
            dry_run=not args.send,
        )
    except NotifyRefused as exc:
        print(json.dumps({"ok": False, "error": str(exc), "thread": thread}, ensure_ascii=False))
        return 1

    print(json.dumps({"ok": True, "sent": result.sent, "reason": result.reason, "thread": thread, "message": result.message}, ensure_ascii=False))
    return 0


def cmd_coord_archive(args: argparse.Namespace) -> int:
    """U15: 판정이 끝난 사건을 보관함으로 옮겨 현역 스트림을 짧게 유지한다."""
    from .coord.stream import archive_settled

    report = archive_settled(Path(args.project))
    print(json.dumps({"ok": True, **report}, ensure_ascii=False))
    return 0


def cmd_coord_deliver(args: argparse.Namespace) -> int:
    from .coord.deliver import deliver

    result = deliver(Path(args.project), message=args.message, actor=args.actor,
                     target=args.target, thread=args.thread)
    # U57-C: QUEUED_INTERACTIVE means a live `coord watch` holds the letter for the interactive session; not a failure.
    # U74-D: QUEUED_ACK_ONLY is an ACK_ONLY letter left in the inbox without a paid turn; also not a failure.
    ok = result.reason in ("PUBLISHED", "DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY")
    print(json.dumps({"ok": ok, "target": result.target, "reason": result.reason,
                      "message_id": result.message_id, "digest": result.digest,
                      "receipt": result.receipt, "output": result.output[:500]}, ensure_ascii=False))
    return 0 if ok else 1


def cmd_coord_publish_thread(args: argparse.Namespace) -> int:
    """U24 / docs/24: 도구의 프로세스 대화를 Codex 데스크톱 프로젝트 대화로 편입·발행한다."""
    from .coord.codex_session_bridge import parse_transcript_to_turns, publish_codex_thread

    if args.transcript:
        turns = parse_transcript_to_turns(Path(args.transcript))
        if not turns:
            print(json.dumps({"ok": False, "error": "EMPTY_OR_INVALID_TRANSCRIPT"}, ensure_ascii=False))
            return 1
    else:
        resp_text = args.response or ""
        if args.response_file:
            resp_text = Path(args.response_file).read_text(encoding="utf-8")
        if not resp_text:
            print(json.dumps({"ok": False, "error": "MISSING_RESPONSE"}, ensure_ascii=False))
            return 1
        turns = [(args.prompt, resp_text)]

    result = publish_codex_thread(
        actor=args.actor,
        task_name=args.task,
        turns=turns,
        project_dir=Path(args.project),
        thread_id=args.thread_id,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


def cmd_coord_sentinel(args: argparse.Namespace) -> int:
    """U23 S4 / U32b: 0-token sentinel (deterministic rules, no model call) — one cycle or a resident loop."""
    import time
    from .coord.mailbox import Mailbox
    from .coord.sentinel import generate_briefing, run_sentinel_cycle

    project = Path(args.project)
    mailbox_dir = project / ".coord" / "mailbox"
    mailbox_dir.mkdir(parents=True, exist_ok=True)
    box = Mailbox(mailbox_dir)

    def _execute_once() -> dict[str, Any]:
        cycle_res = run_sentinel_cycle(project, box, recipient=args.recipient, ring=getattr(args, "ring", False))
        if args.write_brief:
            brief_text = generate_briefing(project, box=box)
            brief_file = project / ".coord" / "codex_brief.md"
            brief_file.parent.mkdir(parents=True, exist_ok=True)
            brief_file.write_text(brief_text, encoding="utf-8")
        return cycle_res

    log_path = Path(args.log) if getattr(args, "log", None) else None

    def _report(res: dict[str, Any]) -> None:
        line = json.dumps(res, ensure_ascii=False)
        print(line, flush=True)  # a no-op under pythonw, where stdout is None
        if log_path is not None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            # One line a minute is ~0.4 MB a day; keep one previous file instead of growing forever.
            if log_path.is_file() and log_path.stat().st_size > SENTINEL_LOG_MAX_BYTES:
                os.replace(log_path, log_path.with_name(log_path.name + ".1"))
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")

    if args.loop:
        # A logon task and a manual start must not run two operators on one project.
        from .coord.sentinel import _is_pid_alive

        pid_file = project / ".work" / "sentinel" / "loop.pid"
        try:
            running = int(pid_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            running = 0
        if running and running != os.getpid() and _is_pid_alive(running):
            _report({"ok": True, "skipped": "ALREADY_RUNNING", "pid": running})
            return 0
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(os.getpid()), encoding="utf-8")
        while True:
            # A resident operator must outlive one bad cycle (locked file, corrupt line); it reports and goes on.
            try:
                res = _execute_once()
            except Exception as exc:  # noqa: BLE001
                res = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
            _report(res)
            time.sleep(args.interval)
        return 0

    _report(_execute_once())
    return 0


def cmd_coord_presence(args: argparse.Namespace) -> int:
    """U32b: record one tool's heartbeat, or show all three. Called from each tool's session hooks."""
    from .coord.presence import conductor, mark, read_all

    say = getattr(args, "say", "json")

    def _emit(data: dict[str, Any], line: str = "") -> None:
        if say == "json":
            print(json.dumps(data, ensure_ascii=False))
        elif say in ("brief", "p1") and line:
            print(line)
        elif say == "empty-json":
            print("{}")

    if getattr(args, "from_hook", False):
        from .coord.hook_context import (
            brief_line,
            hook_project,
            hook_session,
            p1_is_new,
            p1_line,
            read_stdin,
            retention_alert,
            retention_alert_is_new,
        )

        # A pilot worker (U38) runs inside a staged copy that holds .coord/PLAN.md; a hook there must write nothing.
        if os.environ.get("UAOS_WORKER"):
            _emit({"ok": True, "skipped": "UAOS_WORKER"})
            return 0
        # A session hook must never break the session: every failure is reported and the exit code stays 0.
        try:
            stdin_text = read_stdin()
            project = hook_project(stdin_text, args.project)
            if project is None:
                _emit({"ok": True, "skipped": "NOT_A_UAOS_PROJECT"})
                return 0
            if args.tool and args.state:
                # U58: the hook payload names its session, so one session ending leaves the others at the desk.
                mark(project, args.tool, args.state, ttl_s=args.ttl, session=hook_session(stdin_text))
            presence = read_all(project)
            line = p1_line(project, presence) if say == "p1" else brief_line(project, presence)
            if say == "brief":
                alert = retention_alert(project)
                if retention_alert_is_new(project, alert):
                    line = line + " " + alert
            elif say == "p1" and not p1_is_new(project, line):
                line = ""  # U46-P1: an unchanged P1 set is ACK_ONLY; it was repeated on every prompt
            _emit({"ok": True, "project": str(project), "presence": presence, "conductor": conductor(presence)}, line)
        except Exception as exc:  # noqa: BLE001
            _emit({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return 0

    project = Path(args.project)
    if getattr(args, "if_uaos", False) and not (project / ".coord" / "PLAN.md").is_file():
        # Global hooks fire in every project; only UAOS projects get a presence file.
        _emit({"ok": True, "skipped": "NOT_A_UAOS_PROJECT"})
        return 0
    if args.tool or args.state:
        if not (args.tool and args.state):
            print(json.dumps({"ok": False, "error": "--tool and --state go together"}, ensure_ascii=False))
            return 2
        mark(project, args.tool, args.state, ttl_s=args.ttl, lease=getattr(args, "lease", False))
    presence = read_all(project)
    _emit({"ok": True, "presence": presence, "conductor": conductor(presence)})
    return 0


def cmd_coord_watch(args: argparse.Namespace) -> int:
    """U57-B: wait at zero model tokens until a new letter for one of the targets lands; exit 3 on timeout."""
    from .coord.watch import watch

    found = watch(Path(args.project), tuple(args.target), timeout_s=args.timeout, interval_s=args.interval)
    if found is None:
        print(json.dumps({"ok": False, "reason": "TIMEOUT", "targets": args.target}, ensure_ascii=False))
        return 3
    print(json.dumps({"ok": True, "reason": "NEW_LETTER", **found}, ensure_ascii=False))
    return 0


def cmd_coord_usage_collect(args: argparse.Namespace) -> int:
    """U72-L: recover ledger rows written into worktree copies before the desk routing existed. Append-only."""
    from .coord.usage_ledger import UsageRejected, collect

    try:
        result = collect(Path(args.project), apply=args.apply)
    except UsageRejected as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


def cmd_coord_usage_session(args: argparse.Namespace) -> int:
    """U73: one ledger row for the session tokens spent since the last recording. Transcript-only, no model call."""
    from .coord.session_usage import record_session
    from .coord.usage_ledger import UsageRejected

    try:
        result = record_session(Path(args.project), Path(args.transcript), work_id=args.work_id, apply=args.apply)
    except (UsageRejected, OSError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


def cmd_coord_route(args: argparse.Namespace) -> int:
    """Choose authority from provider states; percentages and reset windows are never token balances."""
    from .budget_route import route_authority
    from .coord.presence import read_all

    presence = read_all(Path(args.project))
    states = {tool: (presence.get(tool) or {}).get("state", "UNKNOWN")
              for tool in ("codex", "claude", "antigravity")}
    authority = route_authority(states["codex"], states["claude"], states["antigravity"])
    print(json.dumps({"ok": not authority.startswith("BLOCKED_"), "authority": authority,
                      "states": states, "quota_conversion": "FORBIDDEN"}, ensure_ascii=False))
    return 0 if not authority.startswith("BLOCKED_") else 1


def cmd_coord_thrift(args: argparse.Namespace) -> int:
    from .coord.thrift import ThriftRejected, apply
    try:
        result = apply(Path(args.project), tool=args.tool, remaining_percent=args.remaining_percent,
                       current_card=args.current_card, next_action=args.next_action, acceptance=args.acceptance,
                       stop_condition=args.stop_condition, reset_at=args.reset_at,
                       thrift_at=args.thrift_at, handoff_at=args.handoff_at)
    except ThriftRejected as exc:
        print(json.dumps({"status": "REFUSED", "reason": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


SENTINEL_LOG_MAX_BYTES = 5 * 1024 * 1024

UAOS_GITIGNORE_LINES = (
    ".work/",
    ".coord/pilot/",
    ".coord/stream/",
    ".coord/codex_brief.md",
    ".coord/mailbox/",
    ".coord/presence/",
    ".coord/usage/runs.jsonl",
)

PLAN_TEMPLATE = """# 통합 실행 계획 (UAOS)

상태 기준: `READY → ACTIVE → REVIEW → DONE`. 한 번에 활성 단계 하나, 단계마다 소유자 한 명.

| ID | 상태 | 소유자 | 산출물/판정 |
|---|---|---|---|
| S01 | READY | (지휘자) | 첫 단계: 인수 명령을 먼저 정한다 |

도구 상태(시각이 지나면 UNKNOWN): `python -m v7_harness.cli coord presence`로 확인한다.
"""

PROJECT_MANUAL_TEMPLATE = """# 프로젝트 총괄 매뉴얼 (UAOS Project Manual)

- work_id: PROJECT
- 프로젝트 목표: 프로젝트 전체 목적과 해결 과제를 정의한다.
- 승인 경계: 데이터 삭제, push·배포, 결제, 권한 변경은 사용자 승인 필수.
- 권한 상태기계: Codex ACTIVE → Claude ACTIVE → 둘 다 LIMITED/ABSENT일 때 Antigravity ACTIVE. UNKNOWN은 fail-closed.
- 예산: 잔여율·리셋 창을 토큰으로 환산하지 않고, 호출별 token/USD/time 상한을 각각 집행한다.
- 위임: 계약 파일을 먼저 발행·lint하고 그 내용 전체를 호출에 포함한다.
- 단일 원장: `.coord/PLAN.md`; 작성자와 최종 판정자는 분리한다.
- 보존: archive candidate와 복구 manifest만 만들고 실제 삭제는 별도 최신 승인을 요구한다.

## Goal
One sentence: what is done when this project is done.

## Scope
Files and folders the tools may change.

## Forbidden
Actions that always need the user: deletion, push/deploy/publish, payment, account/permission/credential changes.

## Gates
The commands that decide done (tests, checks). A step without a gate is unmeasured.

## Workers
Who does what: apply (0 tokens) when the code is known, Ollama for narrow mechanical work, Antigravity or `worker: claude` with a token and dollar cap for judgment work.

## Judge
The tool that approves, never the author of the same change.
"""

CONTRACT_MANUAL_TEMPLATE = "Generated per project by cmd_coord_init with a pinned .coord/PLAN.md hash."


def cmd_coord_init(args: argparse.Namespace) -> int:
    """Prepare any project for UAOS. Idempotent: existing files are never overwritten, only missing lines are added."""
    project = Path(args.project)
    if not project.is_dir():
        print(json.dumps({"ok": False, "error": f"not a directory: {project}"}, ensure_ascii=False))
        return 1
    created: list[str] = []
    plan = project / ".coord" / "PLAN.md"
    if not plan.is_file():
        plan.parent.mkdir(parents=True, exist_ok=True)
        plan.write_text(PLAN_TEMPLATE, encoding="utf-8")
        created.append(".coord/PLAN.md")
    project_manual = project / ".coord" / "PROJECT_MANUAL.md"
    if not project_manual.is_file():
        project_manual.write_text(PROJECT_MANUAL_TEMPLATE, encoding="utf-8")
        created.append(".coord/PROJECT_MANUAL.md")
    for folder in (".coord/tasks", ".coord/mailbox", ".work"):
        if not (project / folder).is_dir():
            (project / folder).mkdir(parents=True)
            created.append(folder + "/")
    task_tpl = project / ".coord" / "tasks" / "contract_template.md"
    if not task_tpl.is_file():
        from .manual import new_manual

        task_tpl.parent.mkdir(parents=True, exist_ok=True)
        task_tpl.write_text(new_manual(
            project,
            work_id="T01_EXTRACT_READY_ID",
            worker="local",
            goal="Extract the first exact READY work item ID from `.coord/PLAN.md` into `.work/T01-result.txt`.",
            inputs=[".coord/PLAN.md"],
            allow=[".work/T01-result.txt"],
            acceptance='python -c "from pathlib import Path; assert Path(\'.work/T01-result.txt\').is_file()"',
            judge="codex",
            timeout_s=300,
        ), encoding="utf-8")
        created.append(".coord/tasks/contract_template.md")
    gitignore = project / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    missing = [line for line in UAOS_GITIGNORE_LINES if line not in existing]
    if missing:
        prefix = "" if not existing or existing[-1] == "" else "\n"
        with gitignore.open("a", encoding="utf-8") as handle:
            handle.write(prefix + "# UAOS runtime state (coord init)\n" + "\n".join(missing) + "\n")
    print(json.dumps({"ok": True, "created": created, "gitignore_added": missing,
                      "contract_manuals": ".coord/tasks/<work_id>-manual.md",
                      "next": ["coord presence --tool <codex|claude|antigravity> --state ACTIVE",
                               "fill .coord/PROJECT_MANUAL.md (big picture) before the first delegation",
                               "pilot manual new ... then pilot manual lint ... then pilot run --manual ..."]},
                     ensure_ascii=False))
    return 0


def cmd_coord_inbox(args: argparse.Namespace) -> int:
    """U32b: list what waits in the voicemail without claiming it."""
    from .coord.mailbox import Mailbox

    mailbox_dir = Path(args.project) / ".coord" / "mailbox"
    if not mailbox_dir.is_dir():
        print(json.dumps({"ok": True, "messages": [], "bad": []}, ensure_ascii=False))
        return 0
    box = Mailbox(mailbox_dir)
    messages = []
    for message_id, payload in box.peek():
        data = payload if isinstance(payload, dict) else {}
        messages.append({
            "id": message_id,
            "kind": data.get("kind") or ("P1" if data.get("p1_alert") else None),
            "step": data.get("step"),
            "summary": data.get("summary") or data.get("wake_reason"),
        })
    print(json.dumps({"ok": True, "messages": messages, "bad": box.list_bad()}, ensure_ascii=False))
    return 0


def cmd_coord_ack(args: argparse.Namespace) -> int:
    """U32b: mark one voicemail message as handled so it stops showing up in briefs and bells."""
    from .coord.mailbox import Mailbox, MailboxRejected

    box = Mailbox(Path(args.project) / ".coord" / "mailbox")
    claim = box.claim(args.message_id, consumer_id=args.consumer)
    if claim is None:
        already = (box.ack_dir / f"{args.message_id}.json").is_file()
        print(json.dumps({"ok": already, "id": args.message_id,
                          "error": None if already else "NOT_IN_INBOX"}, ensure_ascii=False))
        return 0 if already else 1
    try:
        box.ack(claim)
    except (MailboxRejected, OSError) as exc:
        box.nack(claim)
        print(json.dumps({"ok": False, "id": args.message_id, "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps({"ok": True, "id": args.message_id}, ensure_ascii=False))
    return 0


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_rsi_report(args: argparse.Namespace) -> int:
    from .olla import USAGE_LOG
    from .rsi import analyze, load_policy, load_rows, local_usage, open_trials, read_decisions

    project = Path(args.project)
    policy = load_policy(project)
    rows = load_rows(project)
    report = analyze(rows, policy)
    # U47-D1: the local model's real work (fake 1/1 rows excluded), joined to the pilot ledger by work_id.
    report["local"] = local_usage(USAGE_LOG, rows)
    report["policy"] = policy
    report["decisions"] = len(read_decisions(project))
    # An adopted change whose window is complete is due for its re-check: keep it or `rsi rollback`.
    report["trials"] = open_trials(project, rows)
    _print_json(report)
    return 0


def cmd_rsi_propose(args: argparse.Namespace) -> int:
    from .rsi import analyze, candidate_template, load_policy, load_rows, propose

    project = Path(args.project)
    policy = load_policy(project)
    proposals = propose(analyze(load_rows(project), policy), policy)
    if args.candidate_for:
        match = [proposal for proposal in proposals if proposal["id"] == args.candidate_for]
        if not match:
            _print_json({"ok": False, "error": f"unknown proposal id: {args.candidate_for}"})
            return 1
        _print_json(candidate_template(match[0], args.author or detect_actor() or "unknown"))
        return 0
    _print_json({"proposals": proposals,
                 "next": "try one proposal on a trial manual, then `rsi gate --candidate FILE` and hand it to the judge"})
    return 0


def _read_candidate(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("the candidate file must hold a JSON object")
    return data


def cmd_rsi_gate(args: argparse.Namespace) -> int:
    from .rsi import gate_from_ledger

    try:
        candidate = _read_candidate(args.candidate)
    except (OSError, ValueError) as exc:
        _print_json({"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]})
        return 1
    verdict = gate_from_ledger(Path(args.project), candidate)
    _print_json(verdict)
    return 0 if verdict["decision"] == "ADOPT_CANDIDATE" else 2


def cmd_rsi_adopt(args: argparse.Namespace) -> int:
    from .rsi import RsiRefused, adopt

    try:
        result = adopt(Path(args.project), _read_candidate(args.candidate), args.judge)
    except RsiRefused as exc:
        # B83: always refused; the evidence and the proposed file go into a PLAN card instead.
        _print_json({"ok": False, "error": str(exc)[:500], "evidence": exc.evidence,
                     "proposed_policy_json": exc.proposed_policy})
        return 2
    except (OSError, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)[:500]})
        return 2
    _print_json({"ok": True, **result})
    return 0


def cmd_rsi_rollback(args: argparse.Namespace) -> int:
    from .rsi import RsiRefused, rollback

    try:
        result = rollback(Path(args.project), args.judge, args.reason)
    except RsiRefused as exc:
        _print_json({"ok": False, "error": str(exc), "proposed_policy_json": exc.proposed_policy})
        return 2
    _print_json({"ok": True, **result})
    return 0


def cmd_rsi_watch(args: argparse.Namespace) -> int:
    import time
    from .rsi_release import run_scheduler_cycle

    project = Path(args.project)
    config_path = Path(args.config) if args.config else project / ".coord" / "rsi" / "watcher.json"
    if not config_path.is_file():
        config = {
            "interval_seconds": 86400,
            "timeout_seconds": 15,
            "max_retries": 3,
            "backoff_base_seconds": 60,
            "lock_ttl_seconds": 3600,
            "sources": [],
        }
    else:
        config = json.loads(config_path.read_text(encoding="utf-8"))

    def _record(event: dict[str, Any]) -> None:
        # A quiet local scheduler still leaves one line when it recovers a dead/stale lock.
        print(json.dumps({"scheduler_event": event}, ensure_ascii=False))

    res = run_scheduler_cycle(project, config, now=time.time(), sleeper=time.sleep, record=_record)
    _print_json(res)
    return 0 if res.get("status") in ("ACK_ONLY", "ACTIONABLE_DELTA") else 1


def cmd_rsi_retention(args: argparse.Namespace) -> int:
    import time

    from . import olla
    from .retention import (
        RetentionRefused,
        apply_retention,
        archive_candidates,
        default_policy,
        plan_retention,
        purge_archived,
        rollup_jsonl,
        work_dir_report,
    )

    now = time.time()
    project = Path(args.project)
    policy = default_policy()
    plan = plan_retention(project, policy, now=now)
    result = apply_retention(project, plan)
    out: dict = {"ok": True, **result}

    if getattr(args, "archive", False):
        out["archive"] = archive_candidates(project, plan, now=now)

    if getattr(args, "rollup_olla", False):
        out["rollup"] = rollup_jsonl(olla.USAGE_LOG, olla.USAGE_LOG.parent / "archive")

    if getattr(args, "purge", None):
        approval_path = Path(args.approval) if getattr(args, "approval", None) else project / "unused_approval.json"
        try:
            purge_archived(project, Path(args.purge), approval_path)
        except RetentionRefused as exc:
            _print_json({
                "ok": False,
                "status": "FRESH_DELETE_APPROVAL_REQUIRED",
                "error": str(exc),
                "purge": {"status": "REFUSED", "deleted": 0},
            })
            return 2
        raise AssertionError("purge_archived must always fail closed")

    out["work_report"] = work_dir_report(project, now=now)
    _print_json(out)
    return 0


def cmd_rsi_prepare(args: argparse.Namespace) -> int:
    from .rsi_release import ReleaseRefused, prepare_release

    project = Path(args.project)
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    try:
        plan = prepare_release(project, packet, apply=args.apply, date=args.date)
    except (ReleaseRefused, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    _print_json({"ok": True, **plan})
    return 0


def cmd_rsi_ship(args: argparse.Namespace) -> int:
    from .rsi_release import ReleaseRefused, ship_release

    project = Path(args.project)
    packet = json.loads(Path(args.packet).read_text(encoding="utf-8"))
    approval = json.loads(Path(args.approval).read_text(encoding="utf-8"))
    try:
        res = ship_release(project, packet, approval, execute=args.execute)
    except (ReleaseRefused, ValueError) as exc:
        _print_json({"ok": False, "error": str(exc)})
        return 1
    _print_json({"ok": True, **res})
    return 0


def cmd_rsi_schedule(args: argparse.Namespace) -> int:
    from .rsi_release import windows_schedule

    project = Path(args.project)
    python_bin = args.python_bin or sys.executable
    res = windows_schedule(project, python_bin, action=args.action, apply=args.apply)
    _print_json(res)
    return 0 if res.get("status") == "DRY_RUN" or res.get("ok") else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    # Windows 콘솔 기본(cp949)에서는 `coord brief` 등의 한국어가 깨진다. olla.main 과 같은 처리.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (ValueError, OSError):
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "coord_subcommand", None) in _DESK_COMMANDS and getattr(args, "project", None):
        from .coord.hook_context import shared_desk

        desk = shared_desk(args.project)
        if desk != Path(args.project):  # unchanged paths keep the caller's spelling
            args.project = str(desk)
    return args.func(args)


# U59: commands that read or write gitignored desk state (presence, mail, watch files) run against the main checkout
# when called from a linked worktree, so every session of a repository shares one desk. PLAN readers (log, status,
# brief) keep the worktree's own branch copy.
_DESK_COMMANDS = frozenset({"presence", "watch", "route", "sentinel", "inbox", "ack", "archive"})


if __name__ == "__main__":
    sys.exit(main())
===FILE: tests/test_u74_closure.py===
"""U74: close the ledger gaps U72/U73 left open.

Seen 2026-09-28 (U72/U73): every pilot row had wall_time_s null, the U70/U71 qualification calls left no ledger row,
and a Codex session's tokens could not be recorded because its rollout format differs from a Claude transcript.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import model_qualification as mq
from v7_harness.admission import ledger_rows, observed_floor
from v7_harness.coord.deliver import deliver
from v7_harness.coord.session_usage import record_session
from v7_harness.rsi import load_rows

from tests.test_u38_cost_gate_and_claude_worker import _run
from tests.test_u51_model_qualification import SOURCES, FakeProvider


def _ledger(root: Path) -> list[dict]:
    path = root / ".coord" / "usage" / "runs.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class PilotWallTimeTests(unittest.TestCase):
    def test_the_pilot_row_records_a_measured_wall_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run(root, {"input_tokens": 1, "output_tokens": 1}, None, task="U74_WALL")
            row = _ledger(root / "proj")[-1]
            wall = row["wall_time_s"]
            self.assertIsInstance(wall, float)
            self.assertGreater(wall, 0.0)
            self.assertLess(wall, 600.0)


def _token_count(stamp: str, total_input: int, cached: int, output: int) -> str:
    total = {"input_tokens": total_input, "cached_input_tokens": cached, "cache_write_input_tokens": 0,
             "output_tokens": output, "reasoning_output_tokens": 0, "total_tokens": total_input + output}
    return json.dumps({"timestamp": stamp, "type": "event_msg",
                       "payload": {"type": "token_count", "info": {"total_token_usage": total}}})


class CodexRolloutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / ".coord").mkdir()
        self.rollout = self.root / "rollout-2026-09-27-x.jsonl"
        lines = [
            json.dumps({"timestamp": "2026-09-27T00:00:00.000Z", "type": "turn_context",
                        "payload": {"model": "gpt-5.5-codex"}}),
            _token_count("2026-09-27T00:00:01.000Z", 1000, 800, 50),
            _token_count("2026-09-27T00:00:02.000Z", 1000, 800, 50),  # repeated without a new call
            json.dumps({"timestamp": "2026-09-27T00:00:03.000Z", "type": "event_msg",
                        "payload": {"type": "token_count", "info": None}}),  # rate-limit-only event
            _token_count("2026-09-27T00:00:11.000Z", 2500, 2000, 80),
        ]
        self.rollout.write_text("".join(line + "\n" for line in lines), encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_cumulative_totals_become_per_call_deltas_with_the_cached_part_split(self) -> None:
        dry = record_session(self.root, self.rollout, work_id="U74-CODEX")
        self.assertEqual(("DRY_RUN", 2, "gpt-5.5-codex"), (dry["mode"], dry["api_calls"], dry["model"]))
        # input 2500 of which cached 2000 -> uncached 500; output 80; no cache writes.
        self.assertEqual((500, 80, 2000, 0), (dry["input_tokens"], dry["output_tokens"],
                                              dry["cache_read_input_tokens"], dry["cache_creation_input_tokens"]))
        self.assertEqual(10.0, dry["wall_time_s"])

    def test_the_row_names_codex_and_stays_out_of_rsi_and_admission(self) -> None:
        record_session(self.root, self.rollout, work_id="U74-CODEX", apply=True)
        rows = _ledger(self.root)
        self.assertEqual([("codex", "codex", "session")], [(r["actor"], r["worker"], r["kind"]) for r in rows])
        self.assertEqual([], load_rows(self.root))
        self.assertIsNone(observed_floor(ledger_rows(self.root), "codex", "review"))
        self.assertEqual("NOTHING_NEW", record_session(self.root, self.rollout, work_id="U74-X", apply=True)["mode"])


class QualificationLedgerTests(unittest.TestCase):
    def test_a_project_store_gets_one_qualification_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mq.qualify(root / mq.QUALIFICATION_STORE, FakeProvider(["sha256:abc123def4567890"]), "m", SOURCES)
            rows = _ledger(root)
            self.assertEqual(1, len(rows))
            row = rows[0]
            self.assertEqual(("qualification", "ollama", "m", len(SOURCES)),
                             (row["kind"], row["worker"], row["model"], row["calls"]))
            self.assertEqual("QUALIFY-m-sha256:abc12", row["work_id"])
            self.assertGreater(row["input_tokens"] + row["output_tokens"], 0)
            self.assertEqual(Path(result["usage_ledger"]).resolve(),
                             (root / ".coord" / "usage" / "runs.jsonl").resolve())
            # A measurement row never becomes an RSI attempt or a pilot/review admission floor.
            self.assertEqual([], load_rows(root))
            self.assertIsNone(observed_floor(ledger_rows(root), "ollama", "pilot"))

    def test_a_store_outside_a_project_writes_no_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = mq.qualify(root / "scratch", FakeProvider(["sha256:abc123def4567890"]), "m", SOURCES)
            self.assertIsNone(result["usage_ledger"])
            self.assertEqual([], _ledger(root))


class _Completed:
    returncode = 0
    stdout = json.dumps({"result": "processed", "is_error": False})
    stderr = ""


class AckOnlyNeverPaidTests(unittest.TestCase):
    """U74-D. Seen 2026-09-28: the U71 E2E failed once under full-suite load with an ACK_ONLY letter DISPATCHED to a
    paid `claude -p` turn. The watcher had already returned on the published letter and cleared its file, so a later
    racer saw no watcher and dispatched (measured by instrumenting watcher_live: 3 of 4 parallel runs)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.calls: list = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _deliver(self, message: str):
        def runner(argv, **kwargs):
            self.calls.append(argv)
            return _Completed()

        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            return deliver(self.project, message=message, actor="codex", target="claude", runner=runner)

    def test_an_ack_only_letter_without_a_watcher_is_queued_not_dispatched(self) -> None:
        result = self._deliver("ACK_ONLY liveness: U74 unchanged")
        self.assertEqual(("QUEUED_ACK_ONLY", []), (result.reason, self.calls))
        self.assertTrue((self.project / ".coord" / "mailbox" / "inbox" / f"{result.message_id}.json").is_file())

    def test_a_real_delta_without_a_watcher_is_still_dispatched(self) -> None:
        result = self._deliver("ACTIONABLE_DELTA verdict_requested=yes: U74 check")
        self.assertEqual(("DISPATCHED", 1), (result.reason, len(self.calls)))


if __name__ == "__main__":
    unittest.main()
===FILE: docs/62_u74-ledger-closure-and-review.md===
# U74 장부 공백 마감과 대행 카드 재검토

## 왜 필요한가

U72 증거(`docs/60`)와 U73(`docs/61`)을 마친 뒤에도 비용 장부에 빈칸이 네 군데 남아 있었다. 빈칸이 있으면 "작업 비용이 3배 넘게 늘지 않았다"는 관문을 판정할 수 없다.

1. **파일럿 벽시계가 비어 있었다.** 모든 `pilot` 행의 `wall_time_s`가 `null`이었다. 그래서 입장 관문(U69)의 "초" 바닥은 한 번도 계산된 적이 없다.
2. **로컬 자격 측정(`qualify`)이 장부에 없었다.** U70/U71에서 Ollama를 실제로 불렀지만 토큰은 자격 기록 파일에만 남았다.
3. **Codex 세션 토큰을 기록할 수 없었다.** U73의 `usage-session`은 Claude Code 기록 형식만 읽었다. Codex 기록(rollout)은 형식이 다르다.
4. **판정이 끝나지 않은 항목이 남아 있었다.** 리뷰 상한 충돌(U69), RSI 검토 제안 6건, 중복 편지 1통, `DONE-ACTING` 카드들, U72 비용 관문.

## 무엇을 바꿨나

### A. 파일럿 행에 실제 벽시계 기록 (`v7_harness/pilot.py`)

- `run_pilot`이 시작할 때 단조 시계(`time.monotonic()`)를 한 번 읽는다.
- 장부 행을 쓸 때 흐른 시간을 초 단위(소수 셋째 자리)로 적는다. 전에는 `None`을 적었다.
- 단조 시계를 쓰는 이유: 벽시계(`time.time()`)는 시스템 시간 보정으로 거꾸로 갈 수 있다. 단조 시계는 거꾸로 가지 않는다.

### B-1. Codex 기록 읽기 (`v7_harness/coord/session_usage.py`)

Codex 기록의 `event_msg` 중 `token_count` 이벤트는 **누적** 사용량(`total_token_usage`)을 담는다. 그래서 다음과 같이 읽는다.

- **누적값이 늘었을 때만 호출 1회로 센다.** Codex는 새 호출 없이 같은 이벤트를 다시 쓰기도 한다(요금 한도 정보만 갱신할 때). 누적 합계(`total_tokens`)가 그대로면 무시한다.
- **증가분만 그 호출의 사용량이다.** 이번 누적값에서 직전 누적값을 뺀다.
- **캐시 부분을 나눈다.** Codex의 `input_tokens`에는 캐시에서 읽은 입력(`cached_input_tokens`)이 포함되어 있다. 그래서 캐시 아닌 입력 = 입력 − 캐시로 계산한다. 캐시 읽기는 `cache_read_input_tokens`, 캐시 쓰기는 `cache_creation_input_tokens` 칸에 넣는다. 이렇게 하면 Claude 행과 같은 4칸 구조가 된다.
- **모델 이름**은 `turn_context` 이벤트에서 읽는다.
- **도구 이름은 형식에서 판단한다.** 호출이 Codex 형식이면 `actor`와 `worker`가 `codex`, 아니면 `claude`다. 사람이 이름을 잘못 적을 여지를 없앤다.
- 검증: 실제 첫 기록 파일에서 계산한 입력 + 출력 + 캐시 읽기 = 482,841 + 63,771 + 21,551,360 = 22,097,972. Codex 자신이 적은 누적 합계 22,097,972와 정확히 같다.

### B-2. 자격 측정을 장부에 기록 (`v7_harness/model_qualification.py`)

- `qualify`가 판정을 쓴 뒤 `record_qualification_usage`를 부른다.
- 저장소가 프로젝트의 `.coord/qualification`일 때만 `kind: qualification` 행 1개를 추가한다. 시험 폴더나 임시 사본에는 프로젝트 장부가 없으므로 아무것도 쓰지 않는다(`None`).
- 토큰은 영수증(receipt)들의 합이다. 로컬 모델에는 프롬프트 캐시가 없으므로 캐시 두 칸은 0이다. 0을 적어야 4칸이 모두 채워져 "알 수 없음"이 아니게 된다.
- 장부 쓰기가 실패해도 이미 기록된 판정은 되돌리지 않는다. 실패는 결과의 `usage_ledger` 칸에 `ERROR:...`로 보고한다.

### D. ACK_ONLY 편지가 유료 턴을 쓰던 결함 (`coord/deliver.py`) — 검증 중 발견

- **발견**: U74 전체 회귀 1회차에서 U71 E2E가 1건 실패했다. 기대값은 `QUEUED_INTERACTIVE`였는데 실제로는 `DISPATCHED`가 나왔다. 단독으로 3번 다시 돌리면 모두 통과했다. 부하가 걸릴 때만 나는 경쟁 조건이다.
- **원인 (계측으로 확인)**
  - 발송자 6개가 같은 ACK_ONLY 편지를 동시에 보낸다. 편지는 먼저 우편함에 게시된다.
  - 감시자(`coord watch`)는 0.2초마다 우편함을 본다. 새 편지를 찾으면 돌아가면서 자기 감시 파일을 지운다.
  - 부하가 걸리면 늦게 도착한 발송자는 감시 파일을 보지 못한다. 그래서 "감시자 없음"으로 판단한다.
  - 수정 전 코드는 감시자가 없으면 ACK_ONLY도 `claude -p` 유료 턴으로 발송했다. 감시자가 이미 전달한 편지에 유료 턴을 한 번 더 쓴 것이다. 이는 전역 규칙("ACK_ONLY는 유료 모델을 깨우지 않는다") 위반이다.
  - 계측 방법: `watcher_live`에 기록을 넣고 병렬 4회를 돌렸다. 놓친 경우는 모두 파일 없음(FileNotFoundError)이었다. 읽기 거부(PermissionError)는 0건이었다. 그래서 읽기 재시도는 넣지 않았다.
- **수정 (`deliver.py`)**: 명시적 `ACK_ONLY` 편지는 감시자가 없어도 발송하지 않는다. 결과는 `QUEUED_ACK_ONLY`다. 편지는 이미 우편함에 있으므로 다음 세션이 읽는다. CLI는 이 결과를 실패가 아닌 정상(ok)으로 본다.
- **고정 인수 보정 (`tests/test_u71_three_tool_e2e.py`)**
  - 이전 단언은 "`QUEUED_INTERACTIVE`가 반드시 하나 있다"였다. 이 단언 자체가 위 경쟁을 품고 있었다.
  - 새 단언은 "`QUEUED_INTERACTIVE` 또는 `QUEUED_ACK_ONLY`가 하나 이상 있고, 그 외에는 `IN_FLIGHT`뿐"이다.
  - 유료 턴 0, 편지 id 1개, 감시자 기상 단언은 그대로 둔다.
  - 수정 후 병렬 부하 8/8 통과. 수정 전 코드에 새 시험을 돌리면 4번 중 3번 `DISPATCHED`로 실패한다(red).
- **보존**: 실제 변화(`ACTIONABLE_DELTA` 등)가 담긴 편지는 감시자가 없으면 예전처럼 발송한다.

### 다른 계산을 오염시키지 않음

`session`과 `qualification` 행은 RSI(`pilot`만 읽음)와 입장 관문(같은 작업자·같은 종류만 읽음)에 들어가지 않는다. 실제 데스크 장부로 확인했다.

- RSI 행 169개: 추가 전후 같음
- Claude 리뷰 바닥: 94,953토큰(표본 4): 추가 전후 같음

## 데스크 장부 소급 기록 (2026-09-28)

백업: `.work/backup_20260928/runs.jsonl.pre_u74`

- **Codex 세션 17행** (`CODEX-SESSION-<날짜>`)
  - 대상: 2026-09-24~28 기록 중 작업 폴더가 이 프로젝트(데스크 또는 Codex 작업트리)인 최상위 세션.
  - 제외: 파일럿이 띄운 작업자 실행(`.work\...\stage`, `.work\u45_claude` 등). 이들은 이미 `pilot`·`review` 행이 있으므로 다시 세면 이중 계산이 된다.
  - 합계: 호출 3,022회, 입력 15,086,815, 출력 1,424,013, 캐시 읽기 493,657,984, 캐시 쓰기 0.
  - 다시 실행하면 새로 추가되는 행은 0이다(증분 기록).
- **자격 측정 1행** (`QUALIFY-qwen2.5-coder:7b-dae161e27b0e`)
  - 호출 5회, 입력 3,872, 출력 1,399, 115.9초.
  - 판정: list_extract=QUALIFIED, verbatim_quote=REJECTED.
  - 한계: 자격 기록은 같은 모델·작업유형이면 덮어쓴다. 그래서 U70/U71에서 그 전에 실행한 측정의 토큰은 복구할 수 없다(UNKNOWN).

## 남은 판정 마감

### 리뷰 상한 충돌 (U69) — 데이터로 해소

- U69 당시: Claude 리뷰 바닥이 124,769토큰(표본 3)이었다. 그래서 U47-C2의 기본 상한 120,000으로는 리뷰가 거부되었다.
- U72-L 회수 뒤: 표본 4개, 바닥 94,953토큰으로 내려갔다.
- 결론: 94,953 < 120,000이므로 기본 상한으로 입장한다. 코드 변경은 필요 없다.
- 주의: 바닥은 가장 싼 실제 호출이다. 더 싼 리뷰가 기록되면 더 내려가고, 표본이 바뀌어도 올라가지는 않는다.

### RSI 검토 제안 6건 — 과거 기록으로 종결

- 6건 모두 "등록된 처방 없음; 판정자가 영수증 검토"였다.
- 근거가 된 행은 U42~U67이다. U72-L의 수집(collect)이 작업트리에서 회수한 과거 실패들이다.
- U68 이후 실패 행은 0이다.
- 이미 끝난 카드의 역사 기록이므로 새 작업 카드를 만들지 않는다.

### 중복 편지

- `relay_6a02258a…`는 `relay_a0cb8905…`(U72 검토 요청)와 내용이 같다(`docs/60` 정정 3).
- 둘 다 이 문서로 처리했으므로 `coord ack`로 처리 표시한다. 삭제가 아니라 처리 표시다.
- `relay_d6ff28b1…`(RSI ACK_ONLY 알림)도 같이 표시한다.

### DONE-ACTING 카드 재검토 (U63~U73)

- **누가**: 사용자 지시(2026-09-28, "너는 codex이다… 무승인 완수하라")로 Claude가 Codex 권한을 행사했다.
- **어떻게**: 각 카드의 고정 인수 테스트를 U74 코드 위에서 다시 실행했다. 전체 회귀 결과는 PLAN의 U74 행에 있다.
- **한계**: 설계자와 판정자가 같은 계보(Claude)라 독립 검토가 아니다. 그래서 상태를 `DONE-DELEGATED`로 적는다. Codex가 복귀하면 이 판정을 다시 볼 수 있다.

### U72 비용 관문 최종 판정

- **기준선**
  - `U67-U73-ACTING` 세션 행: 325호출, 총 46,206,721토큰(출력 235,078), 약 9개 카드.
  - 카드당 평균: 총 5,134,080, 출력 26,120.
  - 3배 상한: 총 15,402,240, 출력 78,360.
- **U74 카드** (PR 작성 전까지, 세션 행 `U74` 2개 합)
  - 호출 94회, 총 14,292,763토큰 = 기준의 2.78배.
  - 출력 63,098토큰 = 기준의 2.42배.
  - PR 작성 뒤에 쓴 꼬리 구간은 `U74-TAIL`로 따로 기록해 합산한다. 합이 3배를 넘으면 이 판정을 FAIL로 정정한다.
- **판정**: 3배 미만이므로 "작업 비용 3배 회귀 0"(PASS)이다. 다만 여유가 크지 않다(2.78배). 이 카드는 부분 작업 4개(A~D)를 한 카드로 묶었기 때문이다. 다음부터는 부분 작업마다 기록한다. 한계는 두 가지다.
  - 같은 대행 계열 안의 비교다. 표본은 새 카드 1개와 여러 카드를 합친 기준선 1행뿐이다.
  - Codex 시기와 비교하지 않는다. Codex 행은 다른 모델의 토큰이라 같은 단위가 아니고, 카드별로 나뉘어 있지도 않다.

## 고정 인수

`tests/test_u74_closure.py`(7시험)가 확인하는 것:

- 파일럿 행의 `wall_time_s`는 0보다 크고 600보다 작은 실수다.
- Codex 기록: 누적값이 증가분으로 바뀐다. 반복 이벤트와 `info: null` 이벤트는 무시한다. 캐시 부분을 나누고, 모델을 읽고, 벽시계를 계산한다.
- Codex 행은 `actor`·`worker`가 `codex`, 종류가 `session`이다. RSI와 입장 관문에 들어가지 않는다. 다시 기록하면 NOTHING_NEW다.
- 프로젝트 저장소에서 `qualify`를 실행하면 `kind: qualification` 행이 정확히 1개 생긴다. RSI와 파일럿 바닥에는 들어가지 않는다.
- 프로젝트 밖 저장소에서는 행이 생기지 않는다.
- 감시자가 없을 때 ACK_ONLY 편지는 `QUEUED_ACK_ONLY`로 끝난다. 발송 0회이고 우편함에는 편지가 있다.
- 감시자가 없을 때 실제 변화 편지는 여전히 1회 발송된다(보존 시험).
- 수정 전 코드(5c1104f)에서는 7개 중 6개가 실패한다. 통과하는 1개는 보존 시험이다.
===FILE: .coord/PLAN.md===
# 통합 실행 계획

상태 기준: `READY → ACTIVE → REVIEW → DONE`; 한 번에 활성 단계 하나, 단계별 단일 소유자 한 명.

참여 도구(2026-09-24 사용자 지정 고정 갱신): Codex(조율·판정)·Claude Code(부지휘자)·Antigravity(독립검증·임시대행)·로컬 Ollama("생각 없는 전자계산기이자 유선 전화기, 3대 도구의 토큰절약도구"). Codex와 Claude Code 둘 다 사용 제한·부재 시 Antigravity는 총괄 조율 및 수행 권한을 임시 위임받아 독자행동(Autonomous Action)을 수행한다. 올라마는 스스로 생각할 수 없는 비용 0원의 계산기/유선 전화기이므로, 지휘자가 세밀한 작업명령서(`docs/24`, 구체성 80점 이상)를 작성하여 구동하며 판정권은 0이다. 부재 중 Codex 대화창 큐 오염 방지를 위해 `verdict_requested=no`가 강제된다. 대행 산출물은 아래 「Codex 복귀 재검토 목록」에 올린다.

| ID | 상태 | 소유자 | 산출물/판정 |
|---|---|---|---|
| U01 | DONE | Codex | 3대 AI 전역 규칙·skills·memory·MCP 실측 감사 |
| U02 | DONE | Codex | 웹 조사·레드팀·대안 3개 비교 및 경량 v5 제안본 |
| U03 | DONE (역반영 완료) | Codex·Antigravity | 라이브 v9.1 정본을 shared/global-rules 저장소에 역반영 완료. 추천 섹션 영구 삭제 및 사용자 부재 시 3대 도구 직접 완결 원칙 고정 — docs/claude-assist/66 |
| U04 | DONE | Codex·Claude·Antigravity | 승인된 v5.3.0 백업·적용(RuntimeDeployment ALIGNED) 및 도구별 스모크/회귀 335 OK 전수 통과 — docs/claude-assist/68, 69 |
| U05 | DONE | Codex | 현행 구현·전체 대화·두 참조 프로젝트·C3P 비용절감 로직의 증거 기반 전수 감사 |
| U06 | DONE | Codex | 기사 인사이트를 포함한 v7 컨텍스트·의도·검증·이중 역할 계약 설계 |
| U07 | DONE | Antigravity | 승인된 v7 최소 구현과 로컬 벤치마크 하네스 구축 |
| U08 | DONE | Codex | 전역 AI 환경 감사·최적화 및 SQLite/MCP 후보 비교 |
| U09 | DONE | Codex | 사용자 원문·U08·Claude 보고서를 비판적으로 통합한 구현 설계서 |
| U10 | DONE | Codex | capability·schema contract 반례 재작업·독립 재검증 통과 |
| U11 | DONE | Codex | broker·IPC core silent-client 반례 재작업·독립 재검증 통과 |
| U12 | DONE | Codex | timeout·process-tree·late-result·lease-renew P1 재작업 독립 인수 통과 |
| U13 | DONE | Claude(구현)·Antigravity(독립검증) | host-shape rework: exclude-before-reparse·LINK identity·LOCKED metadata; U13 30·전체 146·compileall exit 0; 라이브 HOME(121 entries 0.21s)·TEMP(43 entries 0.07s) 거짓양성 0; R1-R3·R5 잔여(U14+ 처리) |
| U14 | DONE (=M1) | Claude(M1 구현)·Antigravity(V2 독립검증) | P1 6건 수정; U14 32·U10-14 123·전체 178·compileall exit 0; Antigravity V2 PASS(6/6 FIXED); 비차단 2건 BACKLOG |
| U15 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Claude Code 단독 구현(사용자 지시)·Codex 재검토 | S1 `.coord/stream`·`codex_brief.md` manifest 제외 + 격리 테스트 5. S2 `v7_harness/coord/stream.py`(권한 매트릭스·증거 강제·비밀 차단·파일 잠금 append) + 테스트 10. S3 `coord/brief.py`(고정 헤더·마지막 판정 이후만·60줄/6KB 상한·결정적) + 테스트 7. S4 `coord/notify.py`(`codex queue` 전달, 해시 커서·분당 1건·일 24건·[DATA] 헤더) + 테스트 10. 전체 367 OK(1 skip), compileall 0, 고정 테스트 해시 불변. S5 실배달 성공(2026-09-20 20:18, thread 01a0b77f…, 큐 메시지 01a0be89…, 커서 기록). S7 coord CLI·S8 메모 색인 추가(전체 371 OK). S6 부분 실측: 브리핑 828자(메모 평균 1,552자 대비 −46.6%), 큐 메시지 81자, 중복 차단 확인, 상한 준수. Codex 소비 시각·판정 지연·실토큰은 UNKNOWN 유지 — `.coord/tasks/U15-coordination-stream.md` |
| U16 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Claude Code 단독 구현 | 로컬 Ollama 작업자: `v7_harness/adapters/ollama_worker.py` + `pilot run --worker local`. 형식 이탈·경로 이탈·서버 부재 차단 테스트 9건. 실측 WL03 — qwen2.5-coder:7b가 전역 규칙 4파일 패치를 6분 43초에 작성해 인수 통과, 승인 반영·배포 ALIGNED, 계정 한도 소모 0. 성공률은 표본 부족으로 UNMEASURED — `ollama/02_작업자로_들이기_도입근거와_벤치실측.md` |
| U17 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Claude Code 단독 구현 | `olla` 공용 명령(`v7_harness/olla.py`, PATH `olla`): status·ask·edit(백업·diff·범위 밖 거부)·find·estimate·route·digest(내용 해시 캐시)·hook-read(Read 직전 알림, 비차단). 실측: pilot.py 요약본 −91.8%, 위치 질문 적중 8/8(구간 19~42줄)·150줄 조각 7/8·3b 모델 6/8, 캐시 52초→0초, 요약본+해당 구간 열기 경로 −85.9%(8문항, 한 번 읽기 기준). U17 테스트 21. 자율 사용으로 인한 실제 유료 토큰 절감은 UNMEASURED — `ollama/01_작동원리와_운영_Ollama는_어떻게_돌아가나.md`, `.coord/runs/U17/` |
| U18 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Claude Code(부지휘자 대행, 직접 편집 — agy·Codex 한도) | 인수 실패 원인 분류 `v7_harness/accept_triage.py`: CODE/INFRA/UNKNOWN. INFRA만 BLOCKED(`ACCEPT_INFRA`), CODE·UNKNOWN은 REWORK 유지(cascade 승격). 인수 명령 실행 실패는 BLOCKED(`ACCEPT_NOT_RUN`, acceptance_exit=null). 요약에 선택 키 `rework_class`. cli.py 무변경(INFRA가 BLOCKED라 기존 조건으로 승격 안 됨). 관문: U18 테스트 15(Red 5→Green), 전체 회귀 518 OK·79초, 기존 테스트 56개 해시 불변, U17 e2e 실제 실패 로그 15건 전부 비INFRA. 재검토 포인트: 오분류 비대칭 설계(INFRA는 강한 신호만), 모듈 존재 여부로 PYTHONPATH 판별 — `.coord/tasks/U18-accept-triage.md` |
| U19 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Antigravity(`pilot run --worker agy`, 대화 6a271d75) | 로컬 작업자 `ollama_worker._apply`가 파일 전체를 감싼 마크다운 펜스를 벗긴다(U17 실패 15건 중 12건 원인). 관문: 숨은 인수 `.work/u19/accept_fence.py` Red→PASS, bundle 6c51004 APPLIED, 전체 회귀 518 OK. 효과: 로컬 10과제 6/10·693초 → 7/10·65.8초(`.work/u19/e2e_local_after.log`). Antigravity 사용량 입력 60.7k·출력 16.4k(캐시 읽기 175k), Claude 쪽 절감은 UNMEASURED |
| U20 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Antigravity(자문 대화 U20-consult, 구현 대화 11b38aab) | Antigravity 읽기 전용 자문 5건 중 3건 채택·1건 반박·1건 채택: cascade 2단계 기본 agy(`--escalate-to agy|lane`), BLOCKED면 CLI 종료코드 1, `database is locked`·WinError 32 를 INFRA에서 제외, staging 안의 `can't open file` 은 CODE, `.md` 는 펜스 유지. 반박: 모듈 파일 존재 시 INFRA 규칙은 유지(존재하는 모듈의 ModuleNotFoundError 는 경로 문제). 관문: 숨은 인수 `.work/u20/accept_u20.py` Red→PASS, bundle b548521 APPLIED, 전체 회귀 527 OK, 테스트 해시 변경 2개(지시한 범위만: test_u17 기대값 1건, test_u18 추가). 비용: Antigravity 자문 138k·구현 565k 토큰(U19의 7.3배) |
| U21 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Ollama qwen2.5-coder:7b 우선, 실패 시 Antigravity(`pilot run --worker auto/cascade`) | 계산기 원칙(사용자 지정): 지휘자(Claude·Codex)는 코드를 손으로 쓰지 않고 Ollama·Antigravity에 맡긴다. U21a `--worker auto`(구체성 ≥60 → cascade, 미만 → agy)와 로컬 실패(PROVIDER_ERROR·TIMEOUT·EXECUTION_ERROR) 시 agy 승격, U21b 커밋 관문 `v7_harness/calculator_gate.py`+`.githooks/commit-msg`(APPLIED pilot 결과물과 해시가 다른 `v7_harness/*.py` 커밋 차단, 예외는 `Calculator-Exempt:` 줄), U21c AGENTS·docs/01 §16 규칙(Antigravity도 단순 노동은 Ollama에 맡김), U21d 테스트 12개 `tests/test_u21_calculator.py`. 관문: 숨은 인수 4개 Red→PASS, 관문 음성시험(손 편집 rc 1·예외 rc 0), 전체 회귀 539 OK, 기존 테스트 해시 변경 0. 실측: U21a 로컬 605초 PROVIDER_ERROR→agy 370초·335k, U21b 로컬 REWORK→agy 207초·267k, U21c 로컬 PROVIDER_ERROR→agy 479초·276k, U21d 구체성 45로 agy 직행 148초·154k. 로컬 7b 실과제 성공 0/3(PROVIDER_ERROR 2·REWORK 1). Claude 쪽 절감은 UNMEASURED. Antigravity IDE의 Ollama 사용은 규칙만 있고 강제는 없음 |
| U22 | DONE (Claude 대행 판정 2026-09-23 · Antigravity 독립검증 U22-consult PASS · 회귀 547 OK · Codex 복귀 재검토 대상) | Ollama→Antigravity(`pilot run --worker auto`) | 개발 완료 마감: Antigravity 읽기 전용 자문(U22-consult, 202k)으로 U15–U21 PASS 판정, 과제 제안 3건 중 2건 채택. U22a 로컬 출력 상한 `num_predict` 4096·과대 프롬프트 즉시 실패 `PROMPT_TOO_LARGE`(600초 대기 제거), U22b 형식 자리표시자 `<relative/path>` 블록 무시(U22a 로컬 실패 원인 UNKNOWN_DIR 실측), U22c 관문 `--install`(core.hooksPath 설정), U22d U22c에서 로컬이 지운 `--pilot-dir` 복구(인수 보강: HEAD 대비 삭제 줄 대조), U22e 테스트 8개 `tests/test_u22_worker_limits.py`(변이 3종 검출). 경로·비용: a 로컬 PROVIDER_ERROR→agy 94k, b 로컬 REWORK(SEARCH 블록 깨짐)→agy 118k, c **로컬 PASS 73초·0토큰**, d 로컬 REWORK→agy 42k(+인수 개수 오기 재실행 62k), e 로컬 REWORK→agy 181k. 제안 3(대형 파일 함수 발췌)은 보류: 발췌 문맥에서 ===FILE 재작성 시 파일 손상 위험, a·b로 원인 2개를 먼저 제거. 위험: 로컬 7b 실과제 1/9 성공, 인수가 약하면 지시 밖 줄 삭제를 놓침(U22c 실측). Claude 쪽 절감 UNMEASURED |
| U23 | DONE (2대 결함 0원 파일럿 해결 및 회귀 검증 완료, 2026-09-24) | Ollama 로컬 파일럿(U23_RECOVER_MB2, U23_ADD_TEST3, U23_FIX_SENTINEL3), Antigravity 조율 | 코덱스 지적 2대 반례 완전 해결: (1) `mailbox.py` stale recovery 밑줄 ID 손실 결함 해결(JSON `message_id` 직접 참조, bundle `70481ad0…` APPLIED), (2) 회귀 테스트 `test_stale_claim_recovery_preserves_underscored_message_id_and_payload` 추가(bundle `4458884a…` APPLIED, 39/39 OK), (3) `sentinel.py` 동일 초 wake_id 충돌 해결(나노초 타임스탬프 고유 식별자, bundle `81866152…` APPLIED, 5회 연속 사이클 검증 exit 0). 유료 API 0토큰(로컬 100% 무비용) 완결 — `.coord/tasks/U23-mailbox-foundation.md` |
| U24 | SUPERSEDED (U15 정본 실시간 큐로 환원) | Codex·Antigravity | 사이드바 독립 대화창 직접 생성 방식은 Electron 데스크톱 앱의 UI 실시간 갱신 불가(재시작/새로고침 불요 원칙 위배)로 인해 사용자 지시에 따라 실시간 표준에서 배제하고, 기존 U15 정본 인-윈도우 큐(`codex queue`) 및 `[안티그래비티에서 온 대화]` 규약으로 완전 환원. bridge 코드는 보조 아카이브로 보존 |
| U25 | DONE (문서·운영 규칙 범위; 2026-09-24 Codex 판정) | Codex 설계·판정, Antigravity 독립 검토, Ollama 원문 수치 추출 | 계정별 잔여율 예측·판정 예약량·Claude 절약 모드·Antigravity 대행 최소화·Ollama 전화기 실사용 장부를 `docs/27`~`docs/30`와 3도구 진입 규칙에 고정. Antigravity 링크·불변식 검토와 Codex 공백·링크·정본 검사를 대조했다. 계정 절감·예측 정확도는 `UNMEASURED`; U23은 별도 READY — `.coord/tasks/U25-token-budget-policy.md` |
| U26 | DONE (RSI 연구·운영 정본, 2026-09-24) | Codex 연구·정본 작성, Ollama 숫자 추출, Antigravity 권한대행 독립 판정 완료 | 문헌 찬반과 현재 U23/C3P 반례를 대조해 증거 관문형 RSI를 `docs/31`에 설계. `.coord/usage` 장부를 개시하고 3도구 진입 규칙에 연결. 정본 링크·JSONL 무결성 검증 통과 — `.coord/tasks/U26-rsi-research-and-policy.md` |
| U27 | DONE (Codex 독립 재검토·수리, 2026-09-25) | Ollama 초안·Antigravity 제한 승격·Codex 판정 | v2 fail-closed 장부 `60246863…`, Windows 다중 프로세스 테스트 `e25fb43d…`, pilot 자동 기록 `c7fb6e25…` APPLIED. 숨은 8프로세스×25건 201행 무손실·잠금 timeout append 0·실제 장부 24→25행, U27 5/5·전체 580 OK. 원격 토큰 사용 때문에 0원/100% 절감 주장은 기각, 계정 절감 `UNMEASURED` — `.coord/tasks/U27-usage-ledger-automation.md` |
| U28 | DONE (Codex 조율·발행, 2026-09-25) | Codex | 초보자용 종합 사용자 가이드 및 완결 브리핑(docs/33) 발행, Ollama 증거 추출 및 Antigravity 검토 완료 — `docs/33_uaos-final-user-guide-and-completion-briefing.md` |
| U29 | DONE (2026-09-25) | Codex 조율·Antigravity 대행 검증 | 전역 규칙 v5.24.0 정본 동기화 및 3대 도구(Codex, Antigravity, Claude) 배포 일치 검증(ALIGNED, exit 0) — `.coord/tasks/U29-global-rule-deployment.md` |
| U30 | DONE (운영 규칙·매뉴얼 및 런타임 검증기 구현 완료; 2026-09-25 Antigravity 완결) | Codex 기획·Antigravity 권한대행 마무리 | 올라마 실패 격리 운영 가이드(`docs/올라마_오류를_막는_검증과_대체_절차.md`) 정본 편입, 전역 규칙 v5.24.0 배포 완료, 런타임 자동 검증기(`v7_harness/olla_evidence.py` 및 `tests/test_u30_olla_evidence.py`) 구현 완결, 전체 588 회귀 OK(exit 0) — `.coord/tasks/U30-ollama-evidence-gate-design.md` |
| M2 | DONE | Codex | P1 해소, P01 APPLIED·6/6, A/B 기록, 독립 검증 PASS, M2 18·U10~U14 124·전체 197·compileall exit 0 — .coord/tasks/M2-live-pilot.md |
| M3 | DONE | Codex | 백업·정확한 diff 후 프로젝트/Codex/Gemini/양쪽 MIA 규칙 반영, 신규 P02 세션 pilot run 자동 라우팅 PASS — .coord/tasks/M3-global-application.md |
| M4 | DONE (효율 판정 INVALID_MEASUREMENT → UNMEASURED, R0 정정) | Codex 조율·Antigravity 구현/독립검증 | 기능·안전성 12/12 PASS, blocking P1 0. 동일 P05에서 B가 A 대비 Codex input +277.7%, wall +1022.2%로 절약 목표 실패; 현 pilot 기본화·추가 튜닝 STOP |
| R0 | DONE | Codex 조율·Antigravity 단일 pilot 구현 | 기존 P05 B를 `INVALID_SETUP`, 비교를 `INVALID_MEASUREMENT`, 절감 효과를 `UNMEASURED`로 정정하고 측정 유효성 게이트를 고정; R0V1 SUPERSEDED_SOURCE_DIVERGENCE, R6FIX3 APPLIED, Codex R0 12/12·B46 3/3·전체 279 OK(1 skipped)·compileall 0·원본 ab hash 불변 검증 완료 — `.coord/tasks/R0-cost-measurement-validity.md` |
| R1 | SUPERSEDED (역사적 실패 표본 보존) | Codex 조율·Antigravity 실행 | A는 유효했으나 B 컨트롤러가 pilot 시작 전 `helper_unknown_error` 2회로 실패해 비교 `INVALID_INFRASTRUCTURE`. 삭제하지 않고 실패 분모에 보존하며 유효 대체 측정 R2/R4를 사용 — `.coord/tasks/R1-live-remeasurement.md` |
| R2 | DONE | Codex 설계·검토·Antigravity 단일 pilot 구현 | R2FIX15 bundle fec3bded… APPLIED(control.py만). Codex 독립 재검토: focused 39/39, R0·B46 15/15, 전체 331 OK(1 skip), compileall 0, P05 역사 해시 불변; APPLY_NOT_OBSERVED/APPLY_MISMATCH 거짓 PASS 차단 인수 — `.coord/tasks/R2-minimal-control-layer.md`, 메모 61 |
| B58 | DONE | Codex 조율·Antigravity 단일 pilot 구현·Claude Code 읽기 전용 검증 | B58R3 APPLIED(bundle 331b009b…). relay 런타임 로그 manifest 격리 완결, 보호 경로 감시 유지, focused 8/8·전체 335 OK(1 skip)·compileall 0·Claude PASS/P1 none — `.coord/tasks/B58-relay-manifest-isolation.md` |
| R4-FINAL | DONE (2026-09-25 Codex 복귀 재검토) | Claude Code 대행·Codex 최종 판정 | R2 DONE·B58 DONE 게이트와 산식 재검토. P05·P06·P07 n=3 MEASURED_AND_VERIFIED: Codex 입력 평균 −76.7%, 출력 −97.0%, 도구 호출 4~6→0, 품질 게이트 전건 PASS. 실제 계정 한도 절감은 UNMEASURED — `.coord/tasks/R4-additional-measurements.md`, 메모 64 |
| R3 | DONE (판정 복원) | Claude Code 조율·Antigravity 실행 | R2 P1 해소 후 기존 독립 source manifest·숨은 인수 증거를 재인수하여 `MEASURED_AND_VERIFIED`: P05 Codex 입력 73.7% 절감, 벽시계 6.4% 단축 — `.coord/tasks/R3-live-measurement.md` |
| P08 | REVIEW (Claude 결함 수정 2026-09-25 · Codex 재검토 대상) | Ollama 로컬 pilot(bundle 9f4da7542ebe)·Claude 수정 | `coord status` 추가. 결함 2건: (1) 인수가 새 테스트 1개뿐이라 로컬 작업자가 U15 `coord log` 명령을 통째로 지운 bundle이 APPLIED됨 → P09에서 복구 (2) 스트림을 존재하지 않는 `events.jsonl`에서 세어 `stream_events` 항상 0 → `read_events`로 수정, 실제 개수 검증 테스트 추가(Red 0≠2 → Green, 실제 저장소 21건). 카드의 `reconcile_tasks` 필드는 미구현 — `.coord/tasks/P08-coord-status-command.md` |
| U31 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(감사)·Antigravity(대행 판정) | 사용자 5대 비유 실현도 전수 감사 및 U32~U35 보강 완료: 5대 비유 결함 5/5 NOT_REPRODUCED 통과 — `docs/35_five-metaphors-realization-audit_2026-09-25.md` |
| U32 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(구현)·Antigravity(대행 판정) | 음성사서함·교환원: U32a 우편함 무손실(임대 시각·원자적 링크), U32b 감시관·출석부·벨(`--ring`) 완결, 신규 30 통과 — docs/36 §2-1·2-2 |
| U33 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(구현)·Antigravity(대행 판정) | 비둘기 퇴출: 파일럿 스트림 자동 보고 기본 활성화, 도구 자동 식별, 절대 경로 참조 처리, 신규 7 통과 — docs/36 §2-3 |
| U34 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(구현)·Antigravity(대행 판정) | 작업자 정밀 하네스: 계약 매뉴얼 `pilot manual new/lint`·`pilot run --manual`, 허용 범위 강제(`SCOPE_VIOLATION`), `--worker apply`(0토큰) 완결, 신규 30 통과 — docs/36 §2-4, docs/37 |
| U35 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude(P1 실행·판정), Antigravity(대행 판정) | 새 하네스 실제 1회 실행: U35-P1 apply 파일럿 PASS·토큰 0·번들 `e9fcb89b…4d05` APPLIED, O1/O2/A1 계약 매뉴얼 발행 완결 — docs/36 §5, 메모 72 |
| U36 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(구현)·Antigravity(대행 판정) | 증거 관문형 RSI 코드화: `v7_harness/rsi.py`, 18대 맹점 방어, R1(재실행 단일 표본화)·R2(작업자별 재검증 격리) 보정 완료, 27 OK 전건 통과, B83 fail-closed 완결 — docs/38 |
| U37 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(구현)·Codex/Antigravity(Windows 검증·대행 판정) | UAOS 전 프로젝트 가동: `uaos_everywhere/install_uaos_everywhere.py`, U37-W1 47/47 OK·전체 710 OK 무결점 통과, Windows 설치기 미리보기 exit 0 — docs/39, 메모 73·74 |
| U38 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(구현)·Antigravity(대행 판정) | Claude Code 정식 작업자/검증자 파이프라인 편입: `worker: claude` 계약 매뉴얼, `remote_budget_tokens` 필수 강제, `pilot review --reviewer claude` 참고 증거 분리 완결 — docs/40 |
| U39 | DONE (Antigravity 권한대행 판정 2026-09-25) | Codex(기획)·Claude(수학적 정제)·Antigravity(대행 판정) | 3대 도구 토큰예산 절약 및 상태 기계 라우팅 규칙 완결: FORMAT 1회 재시도, SEMANTIC 즉시 원격 승격 상한 120k — docs/41, `.coord/tasks/U39-token-budget-escalation-policy.md` |
| U40 | DONE (Antigravity 권한대행 판정 2026-09-25) | Codex(기획)·Claude(수학적 정제)·Antigravity(대행 판정) | Ollama 시스템 수준 학습(2층) 및 LoRA 관문(3층: 좁은 과제 1개, 정답 100+보류 30, 20 그림자) 설계 완결 — docs/42, `.coord/tasks/U40-ollama-rsi-learning-system.md` |
| U41 | DONE (Antigravity 권한대행 판정 2026-09-25) | Claude Code(구현)·Codex/Antigravity(PC 배포·검증) | deploy_to_this_pc 단일 명령 사용자 PC 전역 배포(0~12단계 OK, 정본 sync/Apply/Check 통과, PR #3 완료) — docs/43 |
| U42 | DONE (Codex 독립판정 2026-09-26) | Codex 조율·Claude 격리 후보·Ollama 기계 분류·Antigravity 반례 | 차단된 유료 bundle은 승인하지 않고 정확한 코드를 0토큰 apply bundle 5개로 반영. focused 56/56·전체 783 OK(skip 4)·compileall 0·고정 SHA 불변·test-fitting 0. 전역 설치 check drift 0, Windows `UAOS_RSI_Watch_39b238e0` Ready·manual-now dry-run 0. 삭제·자동 병합 금지 — `.coord/tasks/U42-rsi-research-pr-automation.md` |
| U44 | DONE (Codex 독립 판정 2026-09-26, APPLIED bundle 사슬 FIX5 `46297542330a` → FIX6B `70e33fe304cf`) | Claude Code(진단·계약)·apply(0토큰 구현)·Codex 실행창(재구성·검증) | Claude UAOS 편입 계약 실행 결함 6건 보강 원본 반영: W1 블록 회신 지시로 NO_CHANGES, W2 manual new 달러 상한 불가, W3 judge user 거부, W4 실호출 0회 DONE(카나리아 규칙), W5 검토 578k토큰 UNUSABLE, W6 Windows 32,767자 명령줄 초과(검토·작업자 두 경로 모두 보강); FIX5 768개·FIX6B 777개 회귀 exit 0, U44-FIX2 ABANDONED 조정 — .coord/tasks/U44-claude-contract.md |
| U45 | DONE (Claude 대행 구현 · Antigravity 판정 및 전역 배포 완결 · Codex 복귀 18:50 재검토 대상) | Claude Code(대행 지휘·계약) · Antigravity(A1 전수맵·독립판정·전역배포) · apply(0토큰) | UAOS 범용화 완결: G1 도구상태 기반 승계 presence.conductor(G1a/G1b APPLIED, 6/6 OK) · G2 coord init이 PROJECT_MANUAL.md 생성(G2b APPLIED, 33/33 OK) · G7 전역규칙 3파일 = core + role adapter (G7b APPLIED, canon v5.26.0, sync-global-rules -Mode Apply exit 0, ALIGNED) · U45-A1 Codex 전수 프로세스 맵(.coord/notes/U45_CODEX_PROCESS_MAP.md) 완결 · 전체 812 테스트 OK(skip 4) — .coord/notes/U45_ACTING_LOG.md, .coord/tasks/U45-* |
| U45-F1 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | manual_project(): lint resolves --source against manual's nearest UAOS root |
| U45-F2 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | BLOCK_RE ends at ===END=== and ## Output section |
| U45-F3 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | context_files() sends pinned contract inputs to local worker |
| U45-F4 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | delegator() identifies codex/claude/antigravity from env vars |
| U45-F5 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | mandatory_watch_roots() skips shared .work/ parent to avoid conductor writes flagged |
| U45-F6 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | cap_overshoot() records claude --max-budget-usd overshoot in micro-dollars |
| U45-F7 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | task mismatch check refuses before any worker runs (was post-run failure) |
| U46-J1 | DONE (Antigravity 판정 16:01, 50 OK) | claude(구현 apply) · antigravity(판정) · codex(재검토) | `pilot review --reviewer agy`: 지휘자가 Antigravity를 CLI로 깨우는 읽기 전용 검토, 토큰 관문. bundle dcc617c7 DRY_RUN_PASSED, 실측 agy 1회 71,299 토큰 UNUSABLE(예산 60k 초과) — docs/47 |
| U46-J2 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | review ledger receipt path stored as absolute path |
| U46-J3 | DONE | antigravity(agy CLI 상의) · claude(판정) | 사람 전달 없는 판정 방법 상의: A안 `pilot judge --judge agy` + 교환원 예비 권고, `*/10` 데몬 없음(NOT_FOUND) — .coord/notes/U46_J3_agy_consult.md, 89,263 토큰 |
| U46-J4 | DONE (Antigravity 16:21 APPLIED, Claude 재실행 67 OK) | claude→antigravity | 사용자 허용(2026-09-26, Codex 부재 중 권한대행 한정). `pilot judge --judge agy`: Codex LIMITED/ABSENT일 때만 Antigravity CLI 판정→기존 `--approve` 관문; ACTIVE/UNKNOWN이면 Codex 판정. apply 번들 7e3e2606… DRY_RUN_PASSED(67 OK, 16:16). 판정 편지 `claude_u46j4_judge_20260926_1618`. Codex 복귀 시 재검토 |
| U46-H | DONE (커밋 b4c0fba, 전체 836 OK) | claude(설계) · antigravity(적용·검증) | F1..F7 + J2 + P1 + T1 10개 후속 결함 일괄 수정 번들 8eaa1da71a86... APPLIED, 회귀 836 OK(skip 4) 통과 |
| U46-G1 | READY | codex·user | calculator gate: route for merge commits whose v7_harness content is fully explained by parents or APPLIED digests, so no `Calculator-Exempt` is needed (근거: 6e02901·1e5b316 used it) — docs/47 §2-2 |
| U46-P1 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | p1_is_new() deduplicates unchanged P1 hook lines (ACK_ONLY) — docs/47 C3 |
| U46-S1 | DONE (Antigravity 16:02:05 적용·사용자 확인·Claude 대조 일치) | user | apply the permission proposal `.coord/notes/U46_claude_permissions_proposal.json` (remove `gh pr merge *` allow, add UAOS/test/commit allows, deny force push) — docs/47 §4 |
| U46-T1 | DONE (U46-H 커밋 b4c0fba) | claude(설계) · antigravity(적용) | test_u13_isolation.test_real_scan_budget_5k_files uses process_time instead of wall time |
| U47-O1 | DONE (APPLIED f4dbfb9, Antigravity `pilot judge` APPROVE 18:24) | claude(apply) · antigravity(판정) · codex(재검토) | tests never write the real olla ledger: `discover -s tests` skips tests/__init__.py, so test_000_env_guard.py loads tests/_env_guard.py first; 64/193 pilot_local rows were fake; ledger 723→723 during 839-test suite — docs/48 §2 |
| U47-O2 | DONE (APPLIED f4dbfb9) | claude(apply) · antigravity(판정) | pilot_local rows carry model and work_id; PROMPT_TOO_LARGE logged — docs/48 §2 |
| U47-R1 | DONE (R1f APPLIED 20:02, bundle `4ce4dca2…`; content = Codex's R1e stage byte-identical) | codex(작성 R1d/R1e, apply 0-token) · claude(판정, Codex 부재 대행) · codex(복귀 후 재검토) | R1c `9988bfc7…` REJECTED by Codex (B83: local `approver=user` JSON reached unlink). Purge now always refuses (UNAUTHENTICATED_ACTOR + FRESH_DELETE_APPROVAL_REQUIRED, no unlink in retention.py); rollup/archive/`.work` report kept. Gate `tests/u47_r1e_check.py` (`32cb4508…`) + discover 857 OK/4 skip in source. R1f = R1e manual with judge codex→claude only (Codex stopped before verdict; approver must equal judge). |
| U47-R2 | DONE (R2b APPLIED 20:21, bundle `c899f6e8…`) | antigravity(작성, run U47-R2 a001) · claude(판정) | stat-only retention alert appended to the brief session hook line, once per change (`.coord/presence/retention_seen.txt`); gate `tests/u47_r2_check.py` (`cd29595c…`) 18 OK. The agy run itself was BLOCKED: EXTERNAL_WRITE of `uaos_test_olla_usage_<pid>.jsonl` (U47-O3 leak) and cost 1,141,039 > 400,000 tokens; its stage was applied verbatim via `worker: apply` (only 2 trailing blank lines differ). |
| U47-O3 | DONE (APPLIED 20:26, bundle `3c385eb7…`, Antigravity `pilot judge` APPROVE 35,126 tokens) | claude(작성, apply 0-token) · antigravity(판정) | tests/_env_guard.py removes `uaos_test_olla_usage_<pid>.jsonl` at exit (atexit); full discover 866 OK/4 skip left %TEMP% count 12→12. 12 old leftovers stay (deletion needs the user). |
| U47-J5 | DONE (APPLIED, bundle `dc691807…`, commit ccbddce) | claude(작성, gate 129dbf9) · antigravity(판정·적용) | `pilot judge` with no `--budget` caps at clamp(30,000 + 3 × diff chars, 100,000, 250,000); an explicit budget still wins, and the record names its cap. Claude re-ran gate `tests/u47_j5_check.py` exit 0 (20 OK); the frozen test is byte-identical to the draft. Codex re-review on return. |
| U47-I1 | DONE (Codex 0e2ac36 통합 완료) | codex(설계 0e2ac36) · antigravity(통합·판정) | Codex의 0e2ac36 커밋(budget_route.py, coord route, PROJECT_MANUAL_TEMPLATE, test_u45_general_uaos)을 claude/u45-general-uaos(PR #8)에 병합 완료. Claude re-check: merge ed6dfdb also brings 1e5b316 and 9ba28c4; full discover OK (4 skipped); no conflict markers. This card was Codex's and ran outside the acting order (authority=claude), so it stays local and unpushed until Codex re-reviews it. |
| U47-F1 | DONE (F1b APPLIED, bundle `796a90ae…`) | codex(원인·판정) · apply(0토큰) | Windows에서 `SHELL=PowerShell`을 POSIX 셸로 오인해 `.sh` 종료코드 3을 0으로 바꾸던 결함 수정. 지원 셸 이름만 신뢰하고 그 외에는 bash/Git Bash로 폴백한다. 회귀 883 OK/4 skip. |
| U47-P1 | DONE (APPLIED, bundle `d6d95cda…`) | codex(원인·판정) · apply(0토큰) | 과거 실패 summary와 최신 SQLite 성공 상태의 불일치로 정리 완료 작업 9건을 P1로 재발행하던 결함 수정. DB 누락·손상·진행 중 상태는 fail-closed 유지, 표적 42 OK·전체 883 OK/4 skip, 실제 감시 재실행 `p1_wake_emitted=false`, `reconcile_tasks=[]`. |
| U47-D1 | SUPERSEDED (Claude 대행 판정 2026-09-27: 목표 = U47-D1a DONE) | codex(계약) · claude(대행 종결) | 목표(`rsi report` local 필드·fake_rows 제외·work_id 조인)는 D1a(bundle `d02595a5`, Codex 재검토 APPROVE)가 이미 충족. 실측 `uaos rsi report`: local.rows 201·fake_rows 66·real.runs 135. 원래 기록: 실제 Ollama 2회 EXTERNAL_WRITE 차단 — `.coord/tasks/U47-D1-PROBE-evidence.md` |
| U47-N1 | REJECTED→RW1e DONE(4ad8c23) (Codex 02:2x: 혼합 줄바꿈 CRLF 통일) | claude(계약·판정 대행) · apply(0토큰) | D1 차단 원인: EXTERNAL_WRITE 2회 = Claude의 동시 전체 테스트, exact-byte 실패 = `_apply`의 `write_text`가 LF를 CRLF로 기록. 번들 N1c `0a4dfaa6` APPLIED, 커밋 2ff535f. N1b(judge=antigravity)는 agy QUOTA로 판정 불가 → 폐기. |
| U47-N2 | DONE (Codex 재검토 APPROVE) | claude · apply | CRLF로 끝나는 응답을 조용히 무시하던 결함(N1 반례에서 발견). 번들 `7d861f1e` APPLIED, 커밋 afd44fd, 반례 5/5. |
| U47-A1 | REJECTED→RW1e DONE(4ad8c23) (Codex 02:2x: ACTIVE가 LIMITED 임대 덮어씀) | claude · apply | 근본 원인: 출석부가 세션 신호(heartbeat)로 antigravity=ACTIVE인데 실제 agy는 QUOTA(162h). `pilot judge`가 QUOTA면 agy 오류문을 기록하고 출석부를 리셋 시각까지 LIMITED로 표시. 번들 `0aa11282` APPLIED, 커밋 643480e. |
| U47-D1a | DONE (Codex 재검토 APPROVE) | claude · apply | `rsi report`에 `local` 필드(가짜 1/1 행 제외, work_id 조인). 실측 200행·가짜 66·실제 134회·입력 238,647/출력 57,063·7,375초. 번들 `d02595a5` APPLIED, 커밋 f5d734d. PROBE3 exact-byte PASS(738 입력 토큰, 11.7초). |
| U47-RW1e | DONE (codex exec APPROVE 14:3x, APPLIED, 커밋 4ad8c23, 전체 924 OK/4 skip) | claude(권한대행·조립) · apply(0토큰) · 판정 codex | N1d·A1b·J6(RW1c)+Codex RW1d 수정 3건(실패 이벤트 fail-closed, 같은 상태 heartbeat도 임대 유지, 60,000자 초과 diff 판정 거부)을 HEAD 기준으로 재고정. RW1d는 입력이 RW1c stage에 고정되고 J5 픽스처(81,826자)가 새 거부 규칙에 걸려 표적 2/171 실패 → J5를 4,000줄(53,826자, 예산 191,478)로 축소. bundle `b4d46e91…` DRY_RUN_PASSED, 표적 171 OK, 전체 discover OK(4 skip). codex exec 판정 03:37 turn.failed(사용량 한도) → 자기 승인 없이 대기. 승인 명령: `.coord/tasks/U47-RW1e-apply-manual.md`, work dir `.work/u47rw1e_run2`, 판정 프롬프트 `.work/u47rw1e_judge/prompt.md`. |
| U47-OLLA-SCOPE | DONE-ACTING (Claude 대행 판정; Codex 재검토) | codex(작성) · claude(F1·대행 판정) | Codex 기반 반입 + F1 bundle `83cd8555` APPLIED, test_u17_olla_mcp OK — `.coord/tasks/U49-acting-codex-review-20260927.md` |
| U48-D0 | DONE-ACTING (Claude 대행 판정; Codex 재검토) | codex(구현 Layer A) · claude(재작업) · claude(대행 판정) | Codex 미커밋 기반(.work/u45_claude) 원문 반입 후 bundle `f7c13556` APPLIED, 고정 관문 PASS. REDTEAM P2/P3 2건 — `.coord/tasks/U49-acting-codex-review-20260927.md` |
| U48-J1 | DONE (codex exec APPROVE 00bdfce3→동일 내용 재번들 591a6975 APPLIED, 전체 OK skip 4; D0와 독립) | codex(설계·판정) · apply(0토큰) | 기존 `JUDGE_IS_AUTHOR` 거부·판정 영수증은 확인했지만 설계/전달 영수증은 없고 Claude USD 0.15 요청이 USD 0.492718로 끝난 반례가 있다. J1은 사후 비용 상한을 하드 한도로 주장하지 않으며, 독립 판정 불가 시 `REVIEW_UNAVAILABLE`로 fail-closed한다. 고정 설계·허용 범위·인수: `.coord/tasks/U48-J1-codex-judgement-20260927.md`. |
| U48-R1 | DONE (Claude 번들 codex exec APPROVE, 커밋 fa2c4ab; 실설치 `0.3.2-ad721a2fc713`가 0.3.1 대체) | codex(카드) · claude(구현) · codex exec(판정) | 버전형 런타임 설치기 기본 미리보기·원자 런처 갱신·동일 버전 충돌 거부·백업/롤백. `~/.uaos/runtime/0.3.1` 설치, 전역 launcher가 작업트리 대신 설치 사본 사용, `--version`/`coord inbox` exit 0 — `.coord/tasks/U48-R1-M1-runtime-receipt-20260927.md`. |
| U48-M1 | REVIEW (16:23 세 도구 `olla`를 `0.3.2-ad721a2fc713`로 재등록·handshake 도구 3개; 새 세션 호출 UNKNOWN) | codex(카드) · claude(설정·검증) · 독립 판정자 대기 | Codex·Claude·Antigravity `olla`를 설치 런타임 0.3.1과 UTF-8로 등록. Claude Connected, Codex/Agy list enabled, MCP 직접 handshake에서 도구 3개 확인. 각 도구의 새 실세션 호출과 엄격한 로컬 출력 인수는 미검증 — `.coord/tasks/U48-R1-M1-runtime-receipt-20260927.md`. |
| U48-W1 | DONE (apply 번들 e219b39f, agy가 codex 대행 APPROVE 65,087토큰 WITHIN → APPLIED; Codex 복귀 시 재검토) | claude(구현) · apply(0토큰) · antigravity(판정, codex 한도 18:57까지) | 기본 `--work-dir .coord`에서 `pilot run`이 자기 writer lock 해시로 PermissionError, 이어 자기 runs/<task> 기록으로 SOURCE_DIVERGED. `pilot.work_dir_excludes`가 작업 폴더의 DB·잠금·stage·이번 task runs만 매니페스트에서 제외(추적 중인 `.coord/runs` 177건은 유지). 회귀 `tests/test_u48_default_workdir.py` 4건, 전체 956 OK skip 4. 별건: `judge.CODEX_BINARY="codex"`는 Windows에서 codex.cmd를 못 찾아 FileNotFoundError. |
| U48-W2 | DONE-ACTING (Claude 대행 판정, 사용자 지시 2026-09-27; 자기 계보 → Codex 복귀 재검토 필수) | claude(구현) · apply(0토큰) · claude(대행 판정) | bundle `d96778fa` APPLIED. 판정 스위트 4종 OK. REDTEAM P3: .cmd shim 경로 메타문자 — `.coord/tasks/U49-acting-codex-review-20260927.md` |
| U48-D1 | DONE-ACTING (Claude 대행 판정; 자기 계보 → Codex 재검토) | claude · apply · claude(대행 판정) | bundle `914f76c9` APPLIED; 새 테스트 D0에서 3 error → 통과, 5개 스위트 OK — `.coord/tasks/U48-D1-apply-manual.md` |
| U47-X1 | READY | codex (re-review) | b4c0fba used `Calculator-Exempt` against docs/47 §3; decide whether to keep or re-commit through the gate |
| U47-C2 | DECIDED (사용자 위임 2026-09-28 · Claude 대행 결정 → Codex 재검토) | claude | 캐시 읽기는 계속 전액 계산(`COST_TOKEN_KEYS`: 캐시 입력도 과금·한도 소모, 관문 코드는 개선 대상 아님). `pilot review --reviewer claude` 권장값 `--budget 120000 --budget-usd 0.25`: 실측 최소 94,953 토큰 × 1.25 여유 ≈ 118,700 → 120,000; $0.176 × 1.4 ≈ $0.25. `--budget`은 필수 인자로 유지(기본값 없음, 매 유료 호출마다 명시). docs/47 §1-1 C2; 후속 U47-C2H: `pilot review --help`에 120000·0.25·캐시 포함 표기(bundle `4f55a813` APPLIED, HEAD 1 failure → 2 OK, stage 1093 OK skip 6) |
| U49 | ACTIVE (Claude 권한대행, 사용자 선언 Codex 부재 2026-09-27 19:04) | claude(지휘 대행·설계) · 판정 codex 복귀 시 | 권한대행 절차 S0~S4 — `.coord/tasks/U49-acting-process-20260927.md`. S0: 전체 958 OK skip 6. S1: W2 재번들 `b5728f35…` PASS → agy 판정 QUOTA(97h59m, 약 10-01 21:15) UNUSABLE·미적용; route=claude. 독립 판정자 0이므로 모든 번들 REVIEW 유지. S5(사용자 지시 "codex 대신 수행"): 비판 점검 C1~C8(P1 2: 전역 런타임이 어떤 커밋과도 불일치, 열린 번들이 미커밋 기반에 고정), Layer A+D0·D1·F1·W2·R1·A0 7단계 APPLIED, 전체 992 OK skip 6·compileall 0 — `.coord/tasks/U49-acting-codex-review-20260927.md` |
| U49-R1 | DONE-ACTING (Claude 대행 판정; 자기 계보 → Codex 재검토) | claude · apply | bundle `b740e15b` APPLIED; 새 테스트 HEAD에서 11 fail → 통과(64조합 기준표), U45 경로 테스트 불변 OK — `.coord/tasks/U49-R1-apply-manual.md` |
| U49-A0 | DONE-ACTING (Claude 대행 판정; Codex 재검토) | codex(작성) · apply | Codex 미커밋 `coord deliver` CLI 20줄 반입, bundle `9144e709` APPLIED — `.coord/tasks/U49-A0-apply-manual.md` |
| U49-RT1 | DONE (사용자 승인 2026-09-27, 커밋 5167c01 기준, 8c1ca91로 재설치) | user(승인) · claude(설치) | `runtime_install --apply` → `0.3.0-e786b545bb81`(90파일) current 전환, 이전 `0.3.2-ad721a2fc713` 보존(롤백 `uaos runtime --apply --rollback 0.3.2-ad721a2fc713`). v7_harness .py 82개 전부 커밋과 일치(줄바꿈 정규화), `--version`·`coord route`(claude)·`coord inbox` exit 0. 버전 표기 0.3.0은 main VERSION 기준이라 이전 0.3.2(미커밋 VERSION)보다 낮게 보임 — Codex가 VERSION 정리. 재설치(사용자 지시 2026-09-27): 8c1ca91 기준 `0.3.0-579200834710`(90파일) current, 82/82 일치, 롤백 대상 `0.3.0-e786b545bb81`·`0.3.2-ad721a2fc713` 보존 |
| U49-M2 | DONE-ACTING (Claude 대행 판정; Codex 재검토) | claude · apply | D0 REDTEAM P2: 잠긴 ack를 없음으로 보고 재발행하던 결함 → 여전히 존재하면 MailboxRejected(fail-closed). bundle `952c20a5` APPLIED, 새 테스트 HEAD 1 fail → 통과, 전체 995 OK skip 6 — `.coord/tasks/U49-M2-apply-manual.md` |
| U49-D2 | DONE-ACTING (Claude 대행 판정; 자기 계보 → Codex 재검토) | claude · apply | D1 REDTEAM P3: 객체가 아닌 JSON 영수증(receipt)에서 `_dispatch_count`가 AttributeError → 시도로 계수. bundle `da7c62b9` APPLIED, 새 테스트 HEAD 1 error → 통과, 인수 29 OK, 전체 998 OK skip 6(142 s)·compileall 0 — `.coord/tasks/U49-D2-apply-manual.md` |
| U49-P1 | DONE (사용자 직접 병합) | user | PR #17 병합 → bd9a30a. 후속 PR #18(U49-M2·D2) 열림, 병합은 사용자 |
| U49-G1 | REJECTED (Codex relay_f4f3da02) | claude · apply | bundle `e6322b1c`(커밋 221d049, 미푸시): 소유자 읽기와 unlink 사이 TOCTOU로 복구한 새 가드를 지울 수 있음 → U49-G1R로 재작업 |
| U49-G1R | DONE-ACTING (Claude 대행 판정; 자기 계보 → Codex 재검토) | claude · apply | 가드 해제를 `<guard>.recover` 잠금 아래 소유자 비교·unlink로 직렬화(`RELEASE_WAIT_S=5.0`). bundle `38308558` APPLIED, 커밋 5d3badd. 주입 복구 테스트 0633dd1에서 2 fail·G1 코드에서 1 fail → 통과, 인수 35 OK — `tests/test_u49_guard_release_race.py` |
| U53 | DONE-ACTING (Codex 작성 0633dd1, Claude 대행 APPROVE; Codex 재검토) | codex(구현) · claude(대행 판정) | 무중단 릴레이: `claude-session.turn.lock`, `--session-id/--resume` 세션 유지, 영수증에 응답 `output` 저장, 응답 속 비밀 fail-closed. 새 테스트 099c783에서 red 3 → 통과. PR #19 |
| U53-F1 | DONE-ACTING (Claude 대행 판정; 자기 계보 → Codex 재검토) | claude · apply | U53 기반 8프로세스 관문 1/30에서 삭제 대기 턴 잠금 PermissionError로 작업자 사망 → 대기 후 재시도. bundle `7b219e29` APPLIED, 커밋 e608caa. 새 테스트 HEAD 1 error → 통과, 8프로세스 관문 3종×30 = 30/30, 전체 1005 OK skip 6(145 s)·compileall 0. PR #19에 포함 |
| U54 | DONE-ACTING (1단계 감사만; Claude 대행 판정, Codex 재검토) | claude(초안: 신문기사 세션, 구현: 대행) · apply | 도구 실행 방화벽 빈틈 감사: `v7_harness/firewall_audit.py`(AST, 동작 변경 없음) → 생성 문서 `docs/50`. 15dd362 기준 35지점, GAP 0, CALLER_INPUT 21(사람 검토 대상), GUARDED 2, FIXED 8, PASS_THROUGH 4. bundle `c59108dd` APPLIED, 6 OK, 전체 1068 OK skip 6. 막기·바꾸기는 U54-S2(별도 계약, CALLER_INPUT 21건 검토 뒤) |
| U54-S2 | DONE-ACTING (Claude 대행 판정, Codex 재검토) | claude · apply | docs/50 CALLER_INPUT 21건 검토 → `docs/51`: 명령 주입 0, DATA_ARG 9, FIXED_PLAN 9, OPERATOR_COMMAND 3 → 지금 POLICY_DENIED 관문을 끼울 실행 지점 없음. 새 지점은 `tests/test_u54_s2_caller_review.py`가 실패시켜 재검토 강제. bundle `e72072c8` APPLIED, stage 1071 OK skip 6 |
| DOCS49-C | DONE-ACTING | claude(신문기사 세션 작성) · claude(대행 판정) | docs/49 ACCEPT-WITH-CORRECTIONS 반영(85%·98.7% 블로그 보고치·UNMEASURED, 가리기 근거는 SWE-agent 한정, 5.0 카드 대응표) + U54/U55 계약 초안. 커밋 bb3c0e4(원본 895466d) |
| U55 | BACKLOG (U51→U50→U52 재작업 후) | codex·user | 토큰 래칫 보정은 유효 표본 10개로; 새 유료 측정은 별도 승인(U50/U52 S2 승인은 이전 불가) |
| U56 | DESIGN (Claude 대행 작성, 사용자 지시 2026-09-27; Codex 재검토) | codex(요청 수신, 5%에서 정지) · claude(대행 작성) | Codex 절약모드: NORMAL → THRIFT(표시 잔량 20% 미만) → PACKET_READY → ACTING → RETURN_REVIEW. 잔량% → 토큰 환산 금지, 인계 패킷을 정지 전에 파일로 — `.coord/tasks/U56-thrift-mode-20260927.md` |
| U63 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Codex 구현, Codex 한도 후 Claude가 P2 수정·통합 → Codex 재검토)) | codex(설계·구현·독립 판정), claude(비용 상한 초과로 중단), local(컨텍스트 상한 초과로 0토큰 중단) | `coord thrift`로 Codex `COMMANDER_RESERVE`, Claude `IMPLEMENTER_RESERVE`, Antigravity `RESEARCH_RESERVE`, 전원 불가 `LOCAL_LOCKDOWN` 구현. 동일 입력 `ACK_ONLY`, 병렬 8회 1패킷/1편지, presence 불변, 복귀 `RETURN_REVIEW`. 집중 66/66 및 전체 1098/1098 PASS(6 skip, 154.045s); 절감 효과 `UNMEASURED` — `docs/52_u63-token-budget-thrift-mode.md` |
| U64 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Codex 레드 시험, Claude 대행 수정·판정 → Codex 재검토)) | codex(설계·레드 시험), claude(P2 수정) | 대기 없는 전달: 실제 변화(ACTIONABLE_DELTA 등)는 감시가 살아 있어도 `claude -p`로 직접 깨우고, 작업트리는 공용 우편함을 쓰되 그 트리에서 실행한다. U64-F(Claude): ① `_requires_wake`를 온전한 토큰으로만 판정(ACK_ONLY 우선, 'no ACTIONABLE_DELTA'·'P1 0'·'STEP1' 제외) ② `coord thrift`의 git 증거는 호출한 작업트리, 상태·우편은 공용 데스크 ③ 이미 `claude -p`로 전달된 편지(accepted 영수증)는 `coord watch`가 건너뜀 — 편지 1통이 유료 차례 2번을 쓰던 결함(relay_2175dda1). 전체 1108 OK(6 skip, 156s) — `tests/test_u64_nonstop_dispatch.py`, `tests/test_u64f_no_double_wake.py` |
| U66 | DONE | codex · claude(독립 diff 검토) | U64-F의 publish→accepted 경쟁조건을 `delivery/pending` 선행 표식으로 차단. 감시자는 PENDING을 seen 처리하지 않아 실패 시 재수신하고, 성공 시 accepted로 생략한다. Claude가 guard loser의 타인 표식 삭제 P2와 무효 경쟁시험 P2를 찾아 guard winner 소유권·실제 publish/claim 순서 인수로 보정. 집중 34/34 및 전체 1117/1117 PASS(6 skip, 145.792s), 3배 비용 회귀 없음 — `docs/53_u66-atomic-dispatch-intent.md` |
| U65-G | DONE | codex · claude(독립 diff 검토) | 전역 규칙 파일의 단일 작성자를 `shared/global-rules` 정본 생성기로 고정. Claude가 본문 인용도 정본으로 오인하는 P2를 찾아 BOM 뒤 파일 시작 표식만 인정하고 음성 반례를 추가했다. 정본 파일은 diet 설치기가 변경·제거·drift 판정하지 않고 런타임·출석 훅만 관리하며, 비정본 파일은 기존 block 설치·제거를 유지한다. 집중 27/27, 전체 1119/1119 PASS(6 skip, 148.114s) — `docs/54_u65g-single-global-rules-owner.md` |
| U65 | DONE-REVIEWED (Claude 대행 → Codex 복귀 재검토; PR #33 사용자 병합 확인) | claude(수정·판정 대행) · apply(0토큰) · codex(복귀 판정) | Codex 0.157.1 실측에서 `hooks stable true`, `codex_hooks` 부재 확인. 기존 고정 인수의 기대값 변경은 현행 명칭 보정이며 신규 시험이 현행·레거시·수동 false·제거를 함께 고정해 test-fitting 아님. `deploy_pc`의 adapters 제외도 정본 구조와 일치. PR #33 merge `e26aca4`, mergedBy `gyeomsVibe`; 정본 PR #1 merge `42e9e05`, mergedBy `gyeomsVibe`. 이중 작성자 잔여는 U65-G로 분리. |
| U67 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Codex 작성 → Claude 대행 검토 2026-09-28; Codex 복귀 재검토)) | codex(조율·판정) · claude(과예산으로 증거 거부) · local(형식 2회 실패로 경로 종료) | U66/U65-G 집중 인수 61/61 OK. 프로젝트 매뉴얼에서 과거 U45 push 승인이 현재 단계로 이전되는 결함을 제거. Claude 감사는 UTF-8 재시도 후 acceptance 0이었으나 `485172>12000` 토큰으로 BLOCKED·미채택. Ollama JSON 추출은 코드펜스 형식 위반 2회(input 3403/3431, output 1194/1130)로 REJECTED. 완성 순서와 Claude 실행 계약은 `docs/55_u67-nonstop-token-budget-completion-plan.md`, `.coord/tasks/U67-C2-claude-completion-manual.md`. Claude 대행 독립 전체 회귀 1119/1119 OK(6 skip, 150.390s, 8283d08+U67 문서). |
| U68 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Claude 대행 판정; Codex 복귀 재검토)) | apply(0토큰 구현) · claude(대행 판정) · codex(복귀 재검토) | Windows Claude worker의 stdout을 UTF-8로 고정해 U+2014 등에서 `UNKNOWN_EFFECT_NEEDS_RECONCILIATION`이 되지 않게 한다. 고정 인수: cp949 자식 프로세스 재현 red→green, 기존 Claude worker·U44 회귀, 범위 밖 변경 0. 결과: 원인은 worker 봉투의 `ensure_ascii=False` 출력(자식 stdout 해독은 이미 UTF-8). ASCII 이스케이프로 고정. 신규 2시험 수정 전 2/2 red → 후 green, 인수 46/46 OK, 전체 1121/1121 OK(6 skip, 164.619s). bundle `ba51a6af` APPLIED, 0토큰. 같은 결함이 `lane_worker.py:68`에 남음(범위 밖, U68-L 후보). |
| U68-L | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Claude 대행 판정; Codex 복귀 재검토)) | apply(0토큰) · claude(대행 판정) · codex(복귀 재검토) | U68과 같은 `ensure_ascii=False` 봉투 출력이 lane·apply·ollama 작업자 3곳에 남아 있어 ASCII 이스케이프로 고정. 신규 3시험 수정 전 3/3 red(cp949 UnicodeEncodeError) → green, 인수 59/59 OK, 전체 1124/1124 OK(6 skip, 169.929s; U68 대비 +3%). ollama_worker는 본문에 `===FILE` 표식이 있어 FILE 블록 전달 시 SYNTAX_ERROR로 1회 거부됨 → EDIT 블록으로 재실행. bundle `38aa1e49` APPLIED. PR #35가 #34 병합 뒤 base 미전환으로 u67 브랜치에 병합되어 U68은 PR #36으로 main에 재상정. |
| U69 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Claude 대행 설계·판정; Codex 복귀 재검토)) | claude(대행 설계·판정) · apply(0토큰) · codex(복귀 재검토) | 유료 호출 입장 관문: 장부의 같은 작업자·종류 중 4종 토큰이 모두 보고된 최저 소비를 바닥으로 삼아, 계약 token/USD/초 중 하나라도 바닥 미만이면 `pilot run`·cascade 승격·`pilot review`를 호출 전 거부(ADMISSION_REFUSED). 표본 없으면 ADMIT_UNMEASURED, --approve 재생은 제외. 신규 5시험(수정 전 모듈 부재로 red), 인수 52/52, 전체 1129/1129 OK(6 skip, 177.8s; U68-L 대비 +5%). bundle `4e616700` APPLIED. 실데스크: Claude 리뷰 바닥 124,769(표본 3) → U67-C1형 12,000 거부, **U47-C2 리뷰 기본 상한 120,000도 거부** — 상한 재결정은 Codex 판정 대상. 절감은 UNMEASURED — `docs/56_u69-paid-call-admission-gate.md` |
| U70 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Claude 대행 설계·판정; Codex 복귀 재검토)) | claude(대행 설계·판정) · apply(0토큰) · codex(복귀 재검토) | 로컬 작업유형 자격 관문: 매뉴얼 `task_type:`(모르는 값 lint 오류)이 있는 local/cascade 실행은 Ollama 호출 전 `.coord/qualification`에서 현재 digest의 판정을 읽어 QUALIFIED만 통과, REJECTED·UNQUALIFIED·digest 변경·Ollama 무응답은 LOCAL_NOT_QUALIFIED로 거부(--approve 재생 제외). 채점은 중복 항목을 실패로 계산(94285bd: alpha×4 → (4,4), 수정 후 (1,4)). 결정적 `v7_harness/symbols.py`(AST 기호·줄번호, 모델 토큰 0). 신규 8시험(수정 전 QUALIFICATION_STORE 부재로 red), 인수 29/29, 전체 1137/1137 OK(6 skip, 160.3s; U69 대비 -10%). bundle `d70a0083` APPLIED. 데스크에 자격 기록 0건 → 작업유형 선언 로컬 작업은 현재 전부 거부, 실측정(`qualify --record .coord/qualification`)은 다음 로컬 작업 전 필요. 절감 UNMEASURED — `docs/57_u70-local-task-qualification-gate.md` |
| U71 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Claude 대행 설계·판정; Codex 복귀 재검토)) | claude(대행 설계·판정) · apply(0토큰) · codex(복귀 재검토) | 3도구 무인 연속성 E2E: 실제 `coord` CLI를 별도 OS 프로세스 6개씩 동시에 띄워 ACTIVE→THRIFT→HANDOFF_READY→대행→ACK_ONLY→ACTIONABLE→RETURN_REVIEW→LOCAL_LOCKDOWN 한 주기를 돌리고, PATH 맨 앞 가짜 `claude`(호출당 파일 1개)로 유료 턴을 셈. 결과: 단계당 편지 1통·패킷 1개(중복 작성 0), 같은 ACTIONABLE 편지 6중 경쟁+재전송에 유료 턴 1, ACK_ONLY 유료 0, 처리된 편지에 감시자 미기상(시간 초과), 잠금 시 route 차단·우편함 보관·presence 보존. 운영 코드 변경 0(main c526903이 관문 충족). 변이 3건(U64-F accepted 건너뜀, U64 ACK 대기열, U63 지문 ACK) 모두 실패로 검출. 1회 11.7초, 3회 연속 통과, 전체 1138/1138 OK(6 skip, 172.0s; U70 대비 +7%). bundle `1c8d9d79` APPLIED. 실측: qwen2.5-coder:7b(digest dae161e2) list_extract QUALIFIED 30/30, verbatim_quote REJECTED 21/30 — `.coord/qualification`에 기록. 한계: 실제 `codex queue` 경로는 미포함 — `docs/58_u71-three-tool-continuity-e2e.md` |
| U72-L | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Claude 대행 설계·판정; Codex 복귀 재검토)) | claude(대행 설계·판정) · apply(0토큰) · codex(복귀 재검토) | U72 선행 결함: 연결 작업트리의 pilot·judge·review 사용량이 커밋하지 않는 작업트리 사본에 갇혀 데스크 장부가 U44-FIX6B에서 멈춤(드라이런: 작업트리 35개에 누락 142행). `record_usage`·admission·RSI가 `shared_desk` 장부를 쓰고 읽게 하고, `coord usage-collect [--apply]`(git 기록 파일로 작업트리 탐색, 하위 프로세스 0, 정규 JSON 중복 제거, 잠금 안 원문 줄 추가, 기본 드라이런)를 추가. 신규 5시험(수정 전 작업트리에 기록되어 red), 6프로세스 동시 수집 41행 중복 0, 인수 19/19, 전체 1143/1143 OK(6 skip, 159.6s). bundle `b0deaa8b` APPLIED. 병합 후 `--apply`로 회수 — `docs/59_u72l-desk-ledger.md` |
| U72 | DONE-DELEGATED (2026-09-28 U74에서 비용 기준 최종 판정 — docs/62; 사용자 위임 Claude-as-Codex, 독립 아님; 이전: DONE-ACTING (조건부: 시험 기준 완성, 비용 기준은 U73 누적 뒤 재판정 — 2026-09-28 사용자 지시 "너는 codex이다"로 Claude가 Codex 권한 행사; 자기 산출물 판정이므로 Codex 복귀 재검토 필수)) | codex(최종 판정) · claude(증거 수집·조건부 판정) | 10개 유효 표본의 품질·재작업·유료 토큰·로컬 토큰·벽시계를 대조하고 P1 0·3배 회귀 0일 때만 프로젝트 완성을 판정한다. push·배포·시스템 설정은 별도 최신 승인 전까지 로컬 산출물로 보존한다. 증거(2026-09-28): #40(c53794b) 병합 뒤 런타임 `0.3.0-29944e706459`, `usage-collect --apply`로 작업트리 35개의 누락 143행 회수(69→212행, 재실행 0행). 표본 U63·U64·U66·U67·U68·U68-L·U69·U70·U71·U72-L 모두 인수·전체 회귀 OK; P1 0(inbox 159통); 전체 회귀 145.8~177.8초(1.22배, 직전 대비 최대 +7%) → 시험 시간 3배 회귀 0, **작업 비용 3배 회귀는 UNKNOWN**(정정: 대행 세션 토큰 미기록; 장부 완비 표본은 U66 제외 9개); 비PASS 장부 행 5; 파일럿 유료 U63 703·U67 4,420, U68 이후 0. 공백: 대행 세션 토큰 미기록(절감 UNMEASURED), 결정적 행 `wall_time_s` null, U66 Codex·U67 로컬·U70 자격 호출 장부 행 없음 — `docs/60_u72-completion-evidence.md` |
| U73 | DONE-DELEGATED (2026-09-28 사용자 위임으로 Claude가 Codex 권한 재검토 — 독립 아님, U74 전체 회귀로 인수 재실행; 이전: DONE-ACTING (Claude 대행 설계·판정; Codex 복귀 재검토)) | claude(대행 설계·판정) · apply(0토큰) · codex(복귀 재검토) | U72 비용 관문 UNKNOWN 해소 1단계: `coord usage-session --transcript --work-id [--apply]`가 Claude Code 세션 기록에서 고유 메시지 id별 4종 토큰을 합산해 마지막 기록 뒤 구간만 `kind: session` 행으로 추가(모델·하위 프로세스 0, 잠금 안 증분, `<synthetic>` 제외, 기본 드라이런). RSI(`pilot`만)·입장 관문(같은 종류만) 바닥에 들어가지 않음. 신규 6시험(수정 전 모듈 부재로 red), 6프로세스 동시 기록 1행. 실측(드라이런): 대행 세션 315호출, 출력 225,300·캐시 읽기 43,148,200·캐시 생성 998,695·입력 628. 다음: 카드마다 기록해 3카드 이상 쌓이면 U72 비용 관문 재판정; Codex 세션·qualify 기록은 후속 — `docs/61_u73-session-usage-ledger.md` |
| U74 | DONE-DELEGATED (Claude가 사용자 위임으로 Codex 권한 행사, 자기 산출물 판정 — 독립 아님; Codex 복귀 시 재검토 가능) | claude(대행 설계·판정) · apply(0토큰) | 장부 공백 마감: (A) 파일럿 행 `wall_time_s`를 단조 시계로 기록(전 행 null이던 결함) (B) `qualify`가 프로젝트 `.coord/qualification`이면 `kind: qualification` 행 1개 기록, `usage-session`이 Codex rollout의 누적 `token_count`를 호출별 증가분·캐시 분리로 읽고 actor를 형식에서 판별 (C) 판정 마감: 리뷰 바닥 94,953<120,000으로 U69 상한 충돌 데이터로 해소, RSI 제안 6건 과거 기록 종결, 중복 편지 ack, U63~U73 DONE-DELEGATED (D) 검증 중 발견: 감시자가 편지를 받고 파일을 지운 뒤 늦은 발송자가 ACK_ONLY를 `claude -p` 유료 발송(병렬 부하 4회 중 3회 재현) → 명시적 ACK_ONLY는 `QUEUED_ACK_ONLY`로 발송 0, U71 단언의 경쟁 보정. 신규 7시험(수정 전 6 red), 인수 14개 스위트, 전체 1156/1156 OK(6 skip, 176.7s; U73 184.8s 대비 -4%), U71 병렬 부하 8/8. 데스크 소급: Codex 세션 17행(3,022호출, 누적합 Codex 자체 합계와 일치), 자격 1행(5호출, 5,271토큰; 이전 측정은 덮어써져 UNKNOWN). **U72 비용 관문**: 기준 U67-U73-ACTING 카드당 총 5,134,080·출력 26,120, U74 PR 전 세션 총 14,292,763(2.78배)·출력 63,098(2.42배) → 3배 미만(PASS); PR 작성 꼬리는 `U74-TAIL` 행으로 합산 재판정하며 3배를 넘으면 FAIL로 정정. 한계: 같은 대행 계열 비교, Codex 토큰과는 모델이 달라 비교 불가 — `docs/62_u74-ledger-closure-and-review.md` |
| U51-R2 | DONE-ACTING (Claude 대행 판정; Codex 재검토) | claude(U51 세션 작성) · claude(대행 판정) | 신원 위조 가능 REJECT(relay_d8ff049c) 수리: score는 기록 안 함, qualify가 공급자를 직접 호출·전후 digest·호출별 영수증. 인수 16/16, 위조 score·가짜 --expect-digest 0파일. bundle `13b121b9` APPLIED, 커밋 8526bc5 |
| U50-R2b | DONE-ACTING (Claude 대행 판정; Codex 재검토) | claude(U50 세션 작성) · claude(대행 판정) | 정션 교체 누출 REJECT(relay_79a8d71e) 수리: 핸들로 입장·스냅샷 전달. 인수 311 OK, 독립 정션 교체 재현 누출 0. bundle `6d3dedce` APPLIED, 커밋 1d52fc1 |
| U52-R2 | DONE-ACTING (Claude 대행 판정; Codex 재검토) | claude(U52 세션 작성) · claude(대행 판정) | 1000자 상한에 1096자 REJECT(relay_7da75610) 수리: 표식 포함 상한. 인수 246 OK, 상한 1..3000 전수 초과 0. bundle `8b41b0ee` APPLIED, 커밋 36d5ea2 |
| U52-M | CLOSED-NO_SITE-ACTING (사용자 위임 2026-09-28 "너의 판단에 맡긴다"로 대행 결정; Codex 재검토 시 되살릴 수 있음) | codex·user → claude(대행 결정) | 결정: 호출자 없는 마스킹 코드는 만들지 않는다. 이전 관찰을 들고 가는 유료 경로가 새로 생기면 그 경로와 함께 다시 연다. 이로써 S2의 "마스킹 도착" 선행 조건은 해소됐지만, **S2 유료 측정 자체는 돈이 드는 일이라 금액·상한이 적힌 별도 사용자 승인 전까지 실행하지 않는다**. 근거: recent-k 관찰 마스킹 미구현; 도착 전까지 U50/U52 유료 S2 차단 유지. 2026-09-28 대행 조사: UAOS가 유료 모델에 이전 관찰 목록을 들고 가는 경로 0 — pilot·judge·review·deliver 모두 한 번 호출이고, 여러 턴은 제공자 CLI가 자기 대화 안에서 관리(`review.py` 재시도도 `--resume`). 붙일 호출자가 없으면 마스킹은 죽은 코드(U52-R2에서 Codex가 같은 이유로 삭제). 결정 필요(Codex·사용자): U52-M을 NO_SITE로 닫고 S2 차단 조건을 바꿀지. S2 유료 측정은 어느 쪽이든 별도 승인 |
| U58 | DONE-ACTING (Claude 작성·대행 판정 → Codex 재검토) | claude · apply | 세션별 출석: 콜드 `claude -p`의 SessionEnd 훅이 claude 전체를 24h ABSENT로 써서 `coord route`가 BLOCKED_NO_ACTIVE_AUTHORITY(2026-09-28 16:08Z). 훅 페이로드 `session_id`로 세션을 등록하고 ABSENT는 그 세션만 지움; 살아 있는 세션이 남으면 ACTIVE 유지. 세션 없는 호출·lease는 기존 동작. bundle `5652a943` APPLIED, 새 테스트 HEAD ImportError → 8 OK, 전체 1070 OK skip 6 |
| U59 | DONE-ACTING (Claude 작성·대행 판정 → Codex 재검토) | claude · apply | 저장소당 책상 하나: `.claude/worktrees/<name>` 세션의 훅이 작업트리 `.coord`에 출석을 써서 main(편지 126통·라우팅)은 claude ABSENT로 남고, 작업트리에서 `coord watch`는 메일함 없음으로 크래시(2026-09-28). `shared_desk()`가 연결 작업트리를 main으로 매핑(서브모듈·일반 폴더 불변), 훅과 presence/watch/route/deliver/sentinel/inbox/ack/archive에 적용(PLAN 읽기 명령은 브랜치 사본 유지), watch는 메일함 폴더 생성. bundle `3b673d55` APPLIED, HEAD ImportError → 6 OK, stage 1076 OK·실제 작업트리 1076 OK·main 책상 오염 0 |
| U60 | DONE-ACTING (Claude 작성·대행 판정 → Codex 재검토) | claude · apply | 윈도 `os.replace` 거부(WinError 5, 다른 프로세스가 읽는 중)로 `coord watch`가 종료(2026-09-28). `replace_with_retry()` 20회×10ms, 마지막 거부는 임시 파일 지우고 raise; presence는 그대로 실패 보고, watch는 그 박동만 건너뛰고 편지 검사 계속. bundle `5f1bc1aa` APPLIED, HEAD 3 errors → 3 OK, stage 1079 OK skip 6 |
| U61 | DONE-ACTING (Claude 작성·대행 판정 → Codex 재검토) | claude · apply | 레드팀: claude 출석은 마지막 입력 뒤 1시간에 만료되지만 `coord watch`는 30초마다 박동; 밤새 대기하면 자동 경로가 mailbox_only(PUBLISHED)로 떨어져 살아 있는 watch가 편지를 못 받음. 자동 경로에서 `watcher_live(claude)`를 ACTIVE와 같게 취급(codex ACTIVE 우선 유지). 테스트 중 발견: 우편함 폴더 없는 프로젝트에서 deliver가 MailboxRejected → `_project_mailbox()`가 생성. bundle `dc3a0334` APPLIED, HEAD 3 errors → 3 OK(+U57 20 OK), stage 1091 OK skip 6 |
| U57 | DONE-ACTING (Claude 작성·대행 판정 = 자기 계보 → Codex 재검토 우선) | claude · apply | 사용자 개입 오류 영구 제거(사용자 지시 2026-09-28): (A) Codex 로그의 usage_limit_exceeded → presence LIMITED(리셋 시각까지), (B) `coord watch` 0토큰 새 편지 대기, (C) 대화형 Claude가 watch 중이면 deliver가 `QUEUED_INTERACTIVE`(콜드 claude -p 금지), (D) `coord presence --lease`, 세션 안내문(훅 한 줄·CLAUDE/AGENTS·전역 블록). bundle `41332a8c` APPLIED, 새 테스트 HEAD import error → 19 OK, 병렬 관문 20/20, 전체 1062 OK skip 6 |
| RT-0928 | DONE | claude | 런타임 0.3.0-2ea96b30670e 설치(52ce81d 트리) → PR #20 병합 뒤 0.3.0-05ee984dd166(15dd362 트리, v7_harness 94파일 바이트 일치) → PR #28 병합 뒤 0.3.0-b414e9b586c5(4375149 트리, 87파일 차이 0) |
| P09 | DONE (역사 기록) | Ollama 로컬 pilot(bundle 2e3927305284) | `src/util.py` `sort_csv_rows` + 테스트 3개. 같은 커밋에서 P08이 지운 `coord log`를 복구(카드 밖 작업) — `.coord/tasks/P09-csv-sort-manual.md` |
- 2026-09-19 [R4] 중간 크기 과제(P06, P07) 추가 실측 완료 (DONE, n=3):
  - **P06 (통계 7함수)**: Codex 입력 **−80.2%** (94.0k → 18.6k), 비캐시 **−26.9%** (9.5k → 7.0k), 출력 **−98.3%**, 벽시계 **−9.9%** (91.8s → 82.7s), 품질 PASS (A 31, B 37, 숨은 인수 통과).
  - **P07 (인벤토리·CSV)**: Codex 입력 **−76.3%** (78.4k → 18.6k), 출력 **−98.8%**, 벽시계 **−6.6%** (113.8s → 106.3s), 품질 PASS (A 38, B 44, 숨은 인수 통과).
  - **종합 성과 (P05, P06, P07, n=3)**: Codex 입력 토큰 평균 **76.7% 절감**, 출력 토큰 평균 **97.0% 절감**, 벽시계 시간 평균 **7.6% 단축**, 도구 호출 오버헤드 0회, 품질 100% PASS. 근거: docs/claude-assist/46.

- 2026-09-19 16:2x R3 attempt 03 **MEASURED_AND_VERIFIED(n=1)**: Codex 입력 A 70,433 → B 18,548(−73.7%), 비캐시 6,945 → 6,900(−0.6%), 출력 755 → 46, 도구 4 → 0, 벽시계 −6.4%, 품질 12/12 양쪽. Claude 독립 검증 docs/claude-assist/43. 다음: 중간 크기 과제 2~3쌍 추가 측정 여부(Codex 판정), U03/U04(사용자 승인).

- 2026-09-19 [R3] 라이브 A/B 재측정 검증 완료 (DONE):
  - **게이트 최종 판정**: **`MEASURED_AND_VERIFIED`** (유효성 게이트 `evaluate_measurement` 통과).
  - **실측 성과**: Codex 입력 토큰 **73.7% 절감** (A 70,433 vs B 18,548), 벽시계 시간 **6.4% 단축** (A 60.556s vs B 56.654s), 양측 단위/동작 테스트 12/12 100% 통과(PASS).
  - **Antigravity 실측**: `gemini-3.7-flash-high` 파일럿 40.520s, 총 73,809 tokens, `APPLIED`.
  - **원칙 준수**: P1 2건(토큰 지표 분리, B 조율자 실측) 및 B54 완결, 워크스페이스 최상위 단일 폴더 원칙(`.work/` 격리) 준수, 원본 역사 기록 해시 불변 검증 완료. 산출물: `.coord/runs/R3/measurement.json`, 근거: docs/claude-assist/41.
  - **후속 단계**: R3 완료로 측정 유효성 병목 해소. 남은 승인 과제는 U03/U04(사용자 명시적 승인 대상)뿐임.

- 2026-09-19 (Codex 정지, Claude 조율·Antigravity 실행): R2 DONE — IDE 직접 구현 control.py → r8 P1 2건(4단계 summary·6단계 approval 검증 누락) → 반례 `tests/test_r2_contract_gaps.py` → R2FIX3(claude-opus-4-6-thinking, Gemini Flash는 백그라운드 대기 후 종료 반복) APPLIED → r9 PASS·P1 0. 전체 312 OK. 다음: R3 라이브 측정(Codex A 필요, R2 카드상 별도 단계) — Codex 판정 대기. 근거 docs/claude-assist/33.

- 2026-09-19 [R0] 비용절감 측정 유효성 재설계 closeout 완료 (DONE):
  - 역사 기록 보존: M4 역사 기록 보존, `.coord/runs/P05/ab.json` 원본 SHA256 (`F844872FFA0DAC9AEC39430C288603C374763038EA8B3D52F2F03914CEA940AF`) 불변 보존.
  - 판정 정정: P05 B=`INVALID_SETUP`, comparison=`INVALID_MEASUREMENT`, 절감 효과=`UNMEASURED` 확정 기록 (`.coord/runs/R0/p05-correction.json`).
  - 실행 이력: R0V1 (`f9fc991730c250a3655573e35f4329c9fe381f0a0e7a4cbc63eb6d619cb3f8ba`) `SUPERSEDED_SOURCE_DIVERGENCE` (PASS/DRY_RUN_PASSED, never approved), R6FIX3 (`db31d25d9554433023a4d4dd077f2f4c551d0f9d3b13abfd214d935ca7da3fc9`) `SUCCEEDED/PASS/APPLIED` (acceptance exit 0, `measure_p05.py`, `security.py` 수정).
  - 유효성 게이트: `pre_run_attempt_ids` 스냅샷 검증 및 `INVALID_STALE_RUN` 차단 테스트(`test_stale_ledger_from_before_the_b_run_is_rejected`, `test_missing_pre_run_snapshot_is_rejected`) 고정.
  - 종합 검증 통과: Codex R0 acceptance 12/12 OK, B46 TEMP noise 3/3 OK, 전체 테스트 279 OK (1 skipped), compileall exit 0.
  - 후속 단계: R0 DONE 완료. M4 보존 하에 R1만 fresh identical-baseline 실측을 위해 `READY` 상태로 진입. 현재 절감 효과는 `UNMEASURED`.

- 2026-09-19 Antigravity 독립 검증 r6 완료: r6 P1 신선도(freshness) 결함(pre_run_attempt_ids 스냅샷 부재 시 이전 성공 기록 차용 가능성)을 해결한 R6FIX3 반영 완료. evaluate_measurement에서 INVALID_STALE_RUN 차단 추가, B46 TEMP 소음 패턴 정밀화, 신규 반례 테스트 3개 포함 전체 279개 테스트 전건 PASS, compileall exit 0, 독립 검증 보고서 .coord/runs/VERIFY/independent_verify_r6.json 발행 완료. P05 B 라이브 재측정 준비 완료.

- 2026-09-18 22:0x (Codex 정지, 사용자 지시로 Claude 조율·Antigravity 실행): R0 DONE — R0P1(검증기) → r3 P1 2건(테스트 맞춤 하드코딩, B39 이름충돌 은닉; 원인: 고정 테스트 산술 오류 50.0→33.3) → R0P2 → r4 P1(하이픈 분기; 원인: 고정 테스트 상호 모순) → R0P3(단일 규칙·무거운 폴더 메타데이터 감시) → r5 PASS·P1 0. B41 묶음(B35·B36·B39·B41)은 IDE 직접 반영 후 r3·r5로 검증. 전체 272 OK. M4 효율은 UNMEASURED. 남은 것: 유효한 P05 B 라이브 재측정(Codex, B44 선행), U03/U04(사용자 승인). 근거 docs/claude-assist/28.

- 2026-09-18 Antigravity 자율 실행 완결: 남은 백로그 P2 4건(B41 외부쓰기 경로 요약, B36 원본 불일치 구조화 요약, B35 요약 키 수 상한 복원, B39 대용량 하위폴더 감시 제외)을 B41 묶음으로 일괄 구현 완료. 신규 테스트 6개 포함 전체 266개 테스트 PASS, compileall exit 0, 독립 검증 보고서 `.coord/runs/VERIFY/independent_verify_r3.json` 발행 완료.

- 2026-09-18 R0 정정 구현 완료: M4의 역사 기록과 원본 `.coord/runs/P05/ab.json`은 보존하고 `.coord/runs/R0/p05-correction.json`을 발행했다. `measure_p05.py`에 `evaluate_measurement`를 추가하여 고정 acceptance(8/8 OK)와 라이브 측정기가 동일한 유효성 검증 게이트를 사용하도록 고정했다. 상태를 `REVIEW`로 인계한다.

- 2026-09-18 R0 정정 재개: M4의 역사 기록과 원본 `.coord/runs/P05/ab.json`은 보존한다. B raw의 `helper_unknown_error` 3회, `UNKNOWN/NOT_APPROVED`, `pilot_summary=null`, B 6/A 12 tests를 근거로 기존 B=`INVALID_SETUP`, 비교=`INVALID_MEASUREMENT`, 절감 효과=`UNMEASURED`로 판정한다. R0는 worker가 수정할 수 없는 고정 acceptance를 먼저 RED로 확인한 뒤 단일 SQLite pilot으로 구현하고, PASS bundle만 승인·독립 회귀 검증한다.

- 2026-09-18 Codex 최종 판정:
  1) Antigravity 독립 검증 r2는 B20·B21·B23~B26·B28·B31~B34·B08 12/12 PASS, blocking P1 0으로 인수한다.
  2) 동일 과제·동일 시작 상태 P05 A/B는 둘 다 품질 게이트 PASS이나, B가 Codex input 367,347 대 A 97,270(`+277.7%`), wall 915.7s 대 81.6s(`+1022.2%`)로 절약 목표에 실패했다.
  3) M4는 측정 완료로 `DONE`, 목표 결과는 `FAIL`, 후속은 현 구조 `STOP`이다. pilot을 Codex 절약 기본 경로로 채택하지 않으며 M4 추가 튜닝도 자동 진행하지 않는다.
  4) 다음 자동 단계는 없다. U03/U04 전역 원본 반영은 기존대로 사용자 명시 승인 대기이며, 비용절약 재시도는 별도 재설계 승인 후 새 단계로만 연다.

- v6 전역 정리는 2026-09-16에 별도 승인으로 적용됐으므로 U03/U04의 기존 설명은 역사 기록으로 보존한다.
- 신규 개선 작업은 U05부터 시작한다. 한 단계가 `DONE`이고 사용자 조치가 필요하지 않으면 다음 `READY` 단계 하나를 자동 진행한다.

## 다음 준비 단계

- U07은 독립 재검증을 통과해 `DONE`이다.
- U08은 독립 검토에서 조사 범위와 증거·후보안 제출 조건을 충족해 `DONE`이다. SQLite/MCP 선택과 구현 세부는 확정값이 아니라 U09의 입력으로 사용한다.
- U09은 조율자 독립 검토를 통과해 `DONE`이다. Claude Code의 `docs/11`, `docs/12`는 참고 입력이며 사용자 원문·로컬 실측·공식 근거보다 우선하지 않는다.
- U10 capability·schema contract는 독립 반례 검사에서 발견된 4개 결함을 같은 단계에서 재작업한 뒤, U10 19개·전체 74개 테스트와 compileall을 독립 재실행해 `DONE`으로 확정했다.
- U11은 foreground broker·Windows Named Pipe·single-writer core와 crash/replay/auth 반례 테스트를 구현해 `REVIEW`로 반환됐다. Antigravity job 결과는 `not_found`여서 성공 근거로 쓰지 않았고, Claude read-only 검토의 재현 가능한 command-id 충돌은 같은 단계에서 수정했다. 비용·토큰 절감은 `UNMEASURED`로 유지하며 U12는 아직 생성·시작하지 않는다.
- U11 독립 검토의 silent-client hang 인수 거부는 같은 단계에서 재작업했다. bounded request/response deadline, stable error contract, strict response validation, bounded HMAC frame authentication을 추가했고 focused 2개·U11 11개·U10 19개·전체 85개와 compileall이 통과해 다시 `REVIEW`다. Windows current-user Pipe ACL은 여전히 `UNKNOWN`이며 U12는 열지 않는다.
- Claude 메모 03을 현행 코드와 비교했다. idle read deadline, slow response timeout, idle 후 stop은 반영됨을 확인했다. 연결별 스레드 풀은 single-writer queue 설계 없이 도입하면 권위 경계를 깨므로 U11에서는 채택하지 않았다. bounded 직렬 처리의 head-of-line DoS와 Windows Pipe DACL은 후속 보안·부하 게이트에 `UNKNOWN`으로 이관한다.
- 조율자가 focused 2개, U11 11개, U10 19개, 전체 85개와 compileall을 독립 재실행해 모두 exit 0을 확인했다. U11을 `DONE`으로 확정하고 U12만 다음 `READY` 단계로 연다.
- U12 전용 단계가 카드와 함께 시작됐다. bounded single-writer dispatcher, durable delivery lifecycle, lease/fence, retry budget/circuit, mock launcher만 수행하며 U13은 열지 않는다.
- U12는 실제 IPC 동시 접수를 bounded dispatcher에 연결하고 SQLite writable owner thread를 하나로 유지했다. conditional claim/ack, lease/fence, durable budget/circuit, quota fail-closed, mock crash/timeout/partial/UNKNOWN effect, response-loss replay, graceful drain 반례를 구현했다. 최종 U12 15개·U11 11개·U10 19개·전체 100개와 compileall이 모두 exit 0이므로 `REVIEW`로 반환한다. Claude read-only 단일 비평은 stdout 회수 불가로 `UNAVAILABLE`이며 성공 근거로 쓰지 않았다. 비용·토큰 절감은 `UNMEASURED`; U13은 열지 않는다.
- U12 독립 검토에서 effect callback 예외가 성공 커밋 뒤 발생하는 false-success 반례가 재현돼 인수를 거부했다. 같은 U12를 `READY` 재작업으로 회수한 뒤 `ACTIVE`로 재점유했으며, effect-before-success 순서·UNKNOWN reconciliation·checksum-pinned migration v2·stage latency evidence만 보강한다. U13은 열지 않는다.
- U12 재작업은 observable effect를 `INTENDED → callback(outside transaction) → CONFIRMED` 순서로 바꾸고, 예외를 non-retryable `UNKNOWN/NEEDS_RECONCILIATION`으로 원자 기록해 false ACK/SUCCEEDED/PASS/CONFIRMED를 0으로 만들었다. retry budget과 payload-free monotonic stage evidence는 checksum-pinned migration v2로 이동했다. 직접 반례, U12 18개·U11 11개·U10 21개·전체 105개·compileall이 모두 exit 0이므로 다시 `REVIEW`로 반환한다. latency SLO와 비용·토큰 절감은 각각 `UNKNOWN`/`UNMEASURED`; U13은 열지 않는다.
- 조율자가 최종 스냅샷을 독립 재검증했다. callback 예외 직접 반례에서 ACK/SUCCEEDED/PASS/CONFIRMED 0, UNKNOWN 1, 재실행 0을 확인했고 U12 23개·U11 11개·U10 21개·전체 110개·compileall이 모두 exit 0이었다. U12를 `DONE`으로 확정하고 U13만 `READY`로 연다.
- Named Pipe wake-up + bounded dispatcher는 polling 없는 즉시 전달 후보지만, 실시간 latency SLO·재부팅 간 monotonic clock 비교·고부하 공정성은 U16 benchmark 전까지 `UNKNOWN`이다. 실시간성과 비용·토큰 절감을 측정 전에 보장하지 않는다.
- U13 전용 단계를 카드와 함께 시작했다. 실제 사용자 원본은 읽기 전용 입력으로만 다루고, Git/non-Git isolation·bundle·promotion dry-run은 임시 fixture에서만 구현·검증한다. U14는 열지 않는다.
- 조율자가 U12의 P1 선행 결함(timeout 오분류, Windows process tree 미종료, stale/expired late result의 UNKNOWN effect 미기록, lease renewal 미연결)을 확인해 U13 gate를 회수했다. 실행 중이던 Antigravity job `mu51ah26_x3myuk`를 취소했고 허용 경로의 부분 초안은 검토·통합·테스트 없이 보존했다. U13은 U12가 다시 `DONE`이 될 때까지 `READY (HOLD: U12 rework)`이며 U14는 열지 않는다.
- U12를 같은 전용 단계에서 `ACTIVE`로 재점유했다. 추가 인수 게이트는 effectful timeout=`UNKNOWN/non-retryable`, Windows process-tree 종료 증거, expired/stale late result의 durable UNKNOWN effect/event, conditional lease heartbeat renewal이다.
- U12-R1은 effectful/미분류 timeout을 `UNKNOWN/NEEDS_RECONCILIATION/non-retryable`로 분류하고, 명시적 `read_only`만 `NONE/retryable`로 허용했다. Windows Job Object+tree-kill, rollback 후 EXPIRED 재적용, stale/expired late-result의 durable UNKNOWN/event, owner+attempt+resource+fence 조건부 heartbeat를 연결했다. 직접 반례 5개, U12 28개, U11 11개, U10 21개, 전체 115개와 compileall이 독립 실행에서 모두 exit 0이어서 `REVIEW`로 반환한다. Antigravity job `mu51j3go_x4iqap`은 result API가 `running`을 고정 반환했지만 cancel probe는 `not_running`이었으며, 그 출력/성공 주장은 증거로 사용하지 않았다. U13 HOLD와 U14 미개봉을 유지한다.
- 조율자가 U12-R1 스냅샷을 독립 재검증했다. 처음 선택 실행은 테스트 클래스명 오기로 5 error였고 후속 명령의 exit 0에 가려질 수 있어 증거에서 제외했다. 올바른 클래스명으로 5개 반례를 별도 재실행해 5/5 exit 0을 확인했고, U12 28·U11 11·U10 21·전체 115개와 compileall도 각각 통과했다. Antigravity의 U13 선행 16/16 주장은 WIP=1 위반 범위이므로 인수 증거에서 배제했다. U12를 `DONE`으로 확정하고 U13의 HOLD만 해제한다; U14는 열지 않는다.
- U12 P1 최종 보강은 operation 이름으로 read-only를 추론하지 않고 명시적 capability만 신뢰하며, launcher가 실행 중 주기적으로 conditional heartbeat를 호출한다. Windows Job Object handle signature와 tree-kill fallback 순서를 보강하고, 전역 rollback interception 대신 국소 commit-then-reject로 EXPIRED를 보존했다. 최신 사용자 지시대로 U12는 `REVIEW`, U13은 `READY (HOLD: U12 review)`로 반환한다. U13/U14 파일은 읽거나 수정·통합하지 않았다.
- U13은 U12 `DONE` 전제에서 실패 테스트를 먼저 고정하고 Antigravity 초안 1회(`mu54683m_t3me1n`)를 실제 파일로 검토했다. 이름변경 원경로·삭제 승인과 외부쓰기 UNKNOWN 기록 누락을 같은 단계에서 보정했으며 U13 12개·U12 29개·전체 128개·compileall이 각각 exit 0이라 `REVIEW`로 반환한다. 실제 원본 promotion/실제 Antigravity 편집 실행은 0이며 U14는 열지 않는다.
- U13 독립 검토에서 HOME/TEMP 전체 콘텐츠 해시가 실PC에서 운영 불가한 P1로 확인돼 인수를 거부하고 같은 단계를 재작업했다. 초기 stat-first/changed-only 시도는 이후 metadata 복원 미탐지 반례로 폐기됐고, 최종 설계는 shallow+bounds, 명시적 recursive roots, root-relative noise 제외, root당 64MiB 이내 전체 SHA-256, 초과 fail-closed다. U14는 열지 않는다.
- Claude 메모 05의 실측을 현행 `security.snapshot_watch_roots()`와 대조했다. HOME 전체를 매번 `os.walk`+content SHA-256하고 잠긴 파일을 `ERROR`로 비교하는 구현이 확인돼, 128 테스트 통과와 별개로 실PC에서 지연·거짓 양성을 일으키는 P1 운영 결함으로 판정했다. U14로 이관하면 알고 있는 U13 안전장치를 전제로 통합하게 되므로 U13 인수를 거부하고 `READY (REWORK)`로 되돌린다. U14는 열지 않는다.
- U13 재검토에서 root 열거·개별 stat 실패가 빈 결과/누락으로 축약돼 false delete가 되는 반례를 재현한 뒤 재작업했다. `WatchScanResult(root_exists, files)`로 가용성을 보존하고 transient root/file 실패는 외부 삭제가 아닌 `WATCH_SCAN_UNAVAILABLE`+effect UNKNOWN으로 별도 차단한다. recursive noise 제외를 실제 순회로 검증했고 scandir iterator도 닫는다. U13 18개·U12 29개·전체 134개·compileall이 exit 0이라 `REVIEW`; U14는 열지 않는다.
- U13 최종 재작업은 restored-metadata 우회를 막기 위해 root당 64MiB 이내 전체 SHA-256을 사용하고 초과는 UNKNOWN fail-closed로 바꿨다. root-relative glob, initial/post scan·budget evidence, evidence 재해시 제거, file/dir/root junction·symlink 및 snapshot 후 root 치환을 거부한다. U13 25개·U12 29개·전체 141개·compileall이 exit 0이고 Claude Code 최종 read-only 리뷰도 `PASS/P1 NONE`이다. 검사와 open 사이의 극소 로컬 race는 P2 residual이며 U14는 열지 않는다.
- 2026-09-17: 사용자 지시로 docs/15(설계 정본; 파일명 교환 전 docs/14) 최소 완성 경로로 전환했다(M1=U14 P1 재작업, M2 실전 파일럿, M3 적용; U15~U17 SUPERSEDED). 종료 규칙: P1만 차단, P2·P3는 `.coord/BACKLOG.md`, 단계당 독립 검증 최대 2회. Codex 사용량 한도 동안 Claude가 M1을 대행 구현했으며 DONE은 Antigravity V2 PASS 후 조율자가 판정한다.
- 2026-09-17T19:19:59+09:00: M2 전용 대화창에서 Codex가 `ACTIVE`로 점유했다. 시작 시 `git status`는 비Git 작업공간으로 exit 128이었고, 기존 부분 산출물과 기존 샘플 프로젝트를 재사용한다. M3는 `BACKLOG`를 유지한다.
- 2026-09-17T19:40:24+09:00: M2 구현 초안을 Antigravity bridge로 3회(`mu5dq0yu_y2ycz9`, `mu5e3o24_5fo6b7`, `mu5eazl7_3vl3zz`) 시도했으나 각각 10m/5m/3m print timeout, 출력·파일 변경 0이었다. 동일 외부 실행 실패 3회 규칙에 따라 M2를 `BLOCKED`로 전환했다. focused 17개는 승인 replay·기본 watch roots 두 P1 때문에 2 failures(exit 1); 실제 P01 및 원본 `--approve`, A/B, M3는 실행하지 않았다.
- 2026-09-17: 사용자가 완전 논스탑 진행, `docs/claude-assist/11` 직접 agy fallback, 샘플 프로젝트 첫 `--approve <bundle_id>` 실제 반영, M3 프로젝트·전역 규칙 변경을 명시 승인했다. M2를 같은 카드에서 `ACTIVE`로 재개하며 이 프로젝트 원본 반영·범위 밖 삭제·push/deploy 금지는 유지한다.
- 2026-09-17: M2는 승인 replay·HOME/TEMP 기본값 P1을 수정하고 apply rollback 원자성 반례를 추가했다. 실제 P01 첫 실행은 TEMP의 agy 런타임 잡음 때문에 안전 차단됐고, UUID `.tmp`·Codeium unleash schema만 최소 제외한 뒤 재실행해 `DRY_RUN_PASSED`→승인 replay `APPLIED`, staging/source 인수 6/6, 범위 밖 쓰기 0을 확인했다. A/B 실측과 Antigravity 2차 read-only PASS를 기록했고 M2 18·U10~U14 124·전체 197·compileall이 모두 exit 0이라 수행자 상태 `REVIEW`로 반환한다. DONE 판정 전 M3는 `BACKLOG` 유지.
- 2026-09-17: 사용자 논스탑 지시와 조율 게이트가 M2의 실제 P01·회귀 증거를 인수해 M2를 `DONE`으로 판정했다. 이미 승인된 M3를 `READY`로 열고 전용 카드·대화로 인계한다.
- 2026-09-17: M3 전용 단계의 백업 5개, 원본 대비 61줄 unified diff, 필수 문구 각 1회, 두 `mia-vaccine-test` UTF-8 validation exit 0, 신규 세션 `P02 과제 해줘` 한 줄의 `pilot run` 자동 선택 PASS와 `--approve` 미제공·원본 미반영을 조율자가 재검토했다. M3를 `DONE`으로 확정한다.
- 2026-09-17: M3 전용 대화창에서 승인된 규칙 적용을 `ACTIVE`로 점유했다. 비Git 작업공간 상태를 재확인했고, `mia-vaccine-test`는 Codex·Antigravity 양쪽 설치본의 `SKILL.md`를 대상으로 확정했다.
- 2026-09-17: M3는 승인된 5개 원본을 선백업하고 프로젝트 4줄·Codex 1줄·Gemini 1줄·양쪽 MIA 폴백 각 1줄을 적용했다. 원본→적용본 unified diff exact match, 양쪽 skill validation exit 0, 새 작업 `01a0af1b-f9a6-7d22-9d44-f7470b5c103d`의 `P02 과제 해줘` 한 줄이 SQLite `pilot run`을 자동 선택했고 `--approve` 없이 원본 미반영을 확인했다. 수행자 상태는 `REVIEW`; DONE은 조율자 판정으로 남긴다.

- 2026-09-17 21:3x: Codex 사용량 한도(재설정 09-18 00:15) 중 사용자 지시로 M4를 대행 진행했다. M4는 REVIEW이며 Codex 복귀 시 `docs/claude-assist/14`를 읽고 판정·A 측정·P04 재측정을 수행한다.

- 2026-09-25 도구 상태 전환: 사용자 지시("코덱스가 부재중이다. 코덱스의 프로세스가 멈춘 시점부터 권한대행으로서 코덱스의 프로세스를 마무리해라")에 따라 Antigravity가 총괄 권한대행(ACTING_COMMANDER_PROXY)으로 복귀하여 U30 및 남은 프로세스를 마무리함.
- 도구 상태(형식 고정, docs/20 A4 — 시각이 지나면 UNKNOWN으로 보고 첫 판정 전에 응답을 확인한다): `codex: ACTIVE(USER_DECLARED_2026-09-25T05:44), observed_by=user_and_antigravity, observed_at=2026-09-25T05:44:35+09:00` / `claude_code: CLOUD_ACTIVE_LOCAL_QUOTA_LIMITED, observed_by=user_and_antigravity, observed_at=2026-09-25T05:25:00+09:00` / `antigravity: ACTIVE(DEPUTY_SUPPORT), observed_by=user_and_antigravity, observed_at=2026-09-25T05:44:35+09:00`

## Codex 복귀 재검토 목록 (2026-09-22 작성, 9/24 전후 복귀 예정)

Claude 대행 중 반영된 것. 만든 이가 유일한 검증자가 되지 않도록(자기 선호 편향, arXiv:2410.21819) Codex가 아래 명령을 **직접 돌려** 판정한다. 작성 시점 결과는 모두 exit 0.

| 대상 | 커밋 | 합격 명령 | 작성 시점 결과 | 특히 볼 것 |
|---|---|---|---|---|
| U15 조율 스트림 | 09086b5·baeeb79 외 | `python -m unittest discover -s tests -t . -p "test_u15_*"` | 58 OK | 단일 잠금 아래 읽기·보관(Windows 동시 append), 판정 행위자 제한, 효과는 UNMEASURED(판정 왕복 미관측) |
| U16 로컬 작업자 | c8a7f31·dd09c81·40e6c65 | `python -m unittest discover -s tests -t . -p "test_u16_*"` | 19 OK | SEARCH 1회 일치·전건 검증 후 쓰기, 구체성 60점 기준의 근거(벤치 6과제) |
| U17 olla | 2c9ea32·10faa53·8058ad8·69e11dd·238d0e9 | `python -m unittest discover -s tests -t . -p "test_u17_*"` | 21 OK | 캐시 키(내용 해시·질문·모델·조각), 훅이 절대 막지 않는지, 적중률 표본 8건의 한계 |
| R4-FINAL 판정 | — | `.coord/tasks/R4-additional-measurements.md` 수치 재계산 | DONE(대행) | 입력 −76.7%·출력 −97.0%의 산식, 한도 절감 UNMEASURED 유지 |
| B57/B59 고정물 | — | 전체 회귀 `python .coord/runs/run_regression.py` | 433 OK | B59 QUEUE_SATURATED 용량 4→8 변경이 요구사항을 약화하지 않았는지 |
| 전역 규칙 v5.6~v5.12 | 260718 b8e97e0까지 | `shared/global-rules/scripts/sync-global-rules.ps1 -Mode Check` | PASS·ALIGNED | 무승인 조항이 안전 목록(삭제·push·결제·권한)을 약화하지 않았는지, 로컬 모델이 판정하지 않는 조항 |
| B63·B64 잠금·브로커 종료 | 9574fc4·(이 커밋) | `python -m unittest tests.test_u15_lock_contention tests.test_b64_broker_drain_budget` | OK | Codex 소유 U11/U12 브로커 종료 기한을 대행 수정 — DRAIN_FLOOR_S 2.0이 설계 의도(유한 대기)를 해치지 않는지 |
| Antigravity 훅 실작동 | (이 커밋) | Antigravity 첫 대화에서 `~/.cache/olla/usage.jsonl`에 caller=antigravity 또는 해당 conversationId의 hint_plan·turn_shape 기록이 생기는지 | 미확인 — 한도 소진(9/24 14:57) | 입력 형식(transcriptPath 기록 모양)이 문서와 다르면 turn_shape가 None이 되어 보고 길이 제한만 꺼짐. 기록 보고 어댑터 교정 |
| docs/20·AGENTS 역할 조항 | (이 커밋) | 문서 대조: docs/20 §2 "보유" 표의 우리 쪽 줄 번호가 실제 코드와 맞는지, §4 버림 이유 | 작성 시점 대조 완료 | 역할 문구(활동 중 부관·부재 중 부지휘자)가 사용자 2026-09-23 지시와 같은지, U18 후보 채택 여부 |
| Codex 훅(hooks) 신뢰 | 8982cc3·2ecfb4e | Codex 첫 세션에서 `/hooks` 목록에 `olla hook-shell`·`olla hook-plan`이 신뢰(trusted)로 보이는지 | 미확인 — Codex 한도 소진(9/24 13:41 재설정)으로 실행 불가 | 신뢰 전에는 두 훅 모두 작동하지 않음. Codex 첫 작업으로 확인·신뢰 |
| U21 계산기 원칙 | 4383d0a | `python -m unittest tests.test_u21_calculator` | 12 OK | commit-msg 관문(`.githooks/commit-msg`), `--worker auto` 지시문 구체성 60점 기준 및 에러 승격 동작 |
| U22 로컬 한도·관문 설치 | 65e34bb | `python -m unittest tests.test_u22_worker_limits` | 8 OK | NUM_PREDICT=4096 및 PROMPT_TOO_LARGE fail-fast, `calculator_gate --install` 훅 경로 설정 |
| U15~U22 전체 회귀 | 65e34bb | `python .coord/runs/run_regression.py` | 547 OK (1 skip) | 전체 547 테스트 정상 통과 및 기존 테스트 해시 불변 확인 |
| docs/23 0원 비동기·상주 감시관 | (이 커밋) | `docs/23` 백서 열람 및 3대 도구 영구 불변식 채택 판정 | 백서 확정 | 사용자 최고 의지(Mandate): 유료 모델 상주 폴링 전면 금지, 비용 0원 디스크 파일 비동기 큐(Maildir) + 24/7 로컬 올라마 감시관(Sentinel) 표준화 (arXiv 5편·오픈소스 5개·Reddit 컨센서스 반영) |
| U24 세션 브릿지 직결 | (이 커밋) | `python -m unittest tests.test_u24_codex_bridge` | 3 OK | 3대 도구 대화창의 Codex 프로젝트 대화(Thread) 직접 편입, [agy-], [claude-] 접두어 규약 강제, state_5.sqlite 및 session_index.jsonl 실시간 연동, transcript 자동 임포트 |
| U23-S1b 메일박스 발행 | (이 커밋) | `python -m unittest tests.test_u23_mailbox` | 5 OK | 로컬 Ollama 7b 0토큰 구현, Windows 8병렬 프로세스·원자적 하드링크(no os.replace)·정렬 JSON |
| U23-S1c 클레임·ACK 멱등성 | (이 커밋) | `python -m unittest tests.test_u23_mailbox` | 8 OK | 로컬 Ollama 7b 0토큰 구현, 원자적 클레임·중복거부·ACK 멱등성·NACK 복원·4병렬 경합 |
| U23-S1d 복구·스트레스 | (이 커밋) | `python -m unittest tests.test_u23_mailbox` | 11 OK | 로컬 Ollama 7b 0토큰 구현, 크래시 복구·비밀차단·8+2 병렬 스트레스 100건 무유실 완결 |
| U23-S2 전달 어댑터 | (이 커밋) | `python -m unittest tests.test_u23_mailbox` | 14 OK | 로컬 Ollama 7b 0토큰 구현, 조율 스트림-우편함 연동·지속적 풀 폴백·선별 통지 규격 완결 |
| U23-S3 로컬 감시관 | 7ec4c9c4 | `python -m unittest tests.test_u23_mailbox` | 19 OK | 로컬 Ollama 7b 0토큰 구현, 데드락(60분) 감시, 원장 미정리 탐지, CODE/INFRA 실패 트리아지, 60줄 브리핑, Wake-on-P1 게이트키퍼 |
| U27 사용량 자동화 & RSI | 60246863·e25fb43d·c7fb6e25 | `python -m unittest discover -s tests -p "test_*.py"` | 580 OK (1 skip) | Windows 다중 프로세스·잠금 fail-closed·v2 pilot 자동 append 검증. Antigravity 원격 토큰 사용을 포함해 0원 주장은 기각 |
| U29 타 프로젝트 전역 규칙 배포 | `.coord/tasks/U29-global-rule-deployment.md` | `sync-global-rules.ps1 -Mode Check` | 로컬 배포 DONE, exit 0·8/8 fixture | v5.21.0 미커밋 되돌림을 v5.23.0으로 정리; Codex·Antigravity 런타임 ALIGNED, Claude 별도 확인. Ollama 형식 실패·Antigravity 비용 기록. 새 세션 행동 검증과 원격 Git 배포는 미측정/미수행 |
| U30 올라마 실패 격리와 3도구 전역 배포 | `.coord/tasks/U30-ollama-evidence-gate-design.md` | 정본 SourceCheck → Apply → Check / 전체 회귀 | 3도구 배포 ALIGNED, 회귀 588 OK (1 skip) | 전역 규칙 v5.24.0 3도구 정본 배포 및 런타임 자동 검증기(`v7_harness/olla_evidence.py`) 구현 완결. 8개 전용 테스트 및 588개 전체 회귀 exit 0 |
| 장부 오염 차단(U27) | c0cdd46 | `python .coord/runs/run_regression.py` 후 `.coord/usage/runs.jsonl` 행 수 불변 | Linux: 전체 실행 후 장부 미생성, 수정 되돌리면 `POLLUTED` 검출 | `test_b24`·`test_b26_b21`이 `source_dir=Path(".")`로 실제 장부에 가짜 행(B24_TEST·B21_SHELL)을 회귀마다 남겼다. 로컬 장부의 기존 해당 행은 `correction_of`로 정정 필요(삭제 금지) |
| P08 `coord status` 수정 | b90f6bc | `python -m unittest tests.test_cli tests.test_u15_coord_cli` | Linux 10 OK | `read_events` 사용, 손상 줄은 ok=false·exit 1 |
| U32~U35 전체 (Linux 검증만) | `353fa4c`~`8a0c11f` 및 문서 커밋 | Windows `python .coord/runs/run_regression.py` + `python .coord/runs/U31/metaphor_probe.py` | Linux 663 중 실패 1(B75)·skip 5, 재현 P1~P5 NOT_REPRODUCED | 메모 72의 판정 요청 7건. 특히 Codex 소유 U23 우편함·감시관, U13 매니페스트, U11 소켓 경로의 대행 수정 |
| U36 RSI 관문·U37 전역 설치 | `6f3d40c`·`70eda6c`·`b10ead6`·재검토 커밋 | `python -m unittest tests.test_u36_evidence_gated_rsi tests.test_u37_install_everywhere` + Windows `python .coord/runs/run_regression.py` + 가짜 홈 대신 실제 PC에서 설치기 미리보기 | Linux 710 중 실패 1(B75)·skip 5, 신규 47 OK. Windows U37-W1(`0f6a8fb`): U36 26 OK, U37 2 실패(실행기 `\U` 이스케이프 실제 결함 + 테스트 경로 기대) → `b10ead6` 수정, 재실행 대기 | 메모 73. `manual.py`(평가기 목록)·`sentinel.py`(Codex 소유 U23)·`pilot.py` 대행 수정, 설치기가 사용자 홈 설정을 바꾸는 범위, Codex `codex_hooks` 자동 켜기, 판정자 목록(Antigravity 제외) |
| B28 대소문자·Linux 이식성 | 8ace86f | 전체 회귀(Windows) + `python -m unittest tests.test_b28_reinclude tests.test_u13_isolation tests.test_u15_stream_append tests.test_u18_accept_triage` | Linux 전체 593 중 실패 1(B75)·skip 5, Windows 미실행(UNKNOWN) | 재포함 감시 키가 패턴 표기→디스크 표기로 바뀜(판정 불변 예상), HOME `listdir` 추가 비용, `security.py`는 Codex 소유 U13 코드의 대행 수정 |

- 2026-09-23 20:31 규칙 위반 기록: Claude의 U20 pilot 실행 중(QUIET_LOCK 보유) Antigravity가 원본 `.coord/PLAN.md` 도구 상태 줄을 고쳤다 ("monitoring & proxy support scheduled, 15m cron"). 승인 재생이 APPROVAL_MISMATCH 로 막아 반영 오염은 없었다. 해당 편집은 stash→승인→복원으로 보존했다. 15분 cron 의 위치·내용은 미확인(UNKNOWN). AGENTS 22행: pilot 실행 중 보조 기록은 `.work/notes/` 에만 쓴다.
- 2026-09-23 21:30 관찰: Antigravity 자문(U22-consult)은 15분 cron 이 NONE 이라고 답했으나, 같은 시각대 누군가 원본 PLAN 도구 상태 줄의 antigravity observed_at 을 20:34→21:30 으로 다시 고쳤다(Claude pilot 실행 사이, 반영 오염 없음). 주기적 쓰기 주체가 있다는 증거이며 위치는 UNKNOWN. Antigravity IDE 쪽 예약 작업을 사용자가 확인해야 한다.
- 2026-09-23 23:15 관찰 해소: 위 15분 주기 모니터링은 Antigravity CLI 세션의 등록된 cron(task-24, 사용자 무승인 진행 지시 수신)으로 정상 가동 중임이 확인됨(UNKNOWN 해소). Claude의 U22 개발 완료 마감에 따라 조율 인계 대기 상태로 완결 유지.
- 2026-09-24 00:38 사용자 최고 의지(Mandate) 천명 및 백서(docs/23 v2.0.0) 발행: 유료 LLM의 주기적 상주 폴링(cron)은 토큰 다이어트의 모순이므로 영구 금지. 비용 0원인 디스크 파일 기반 비동기 통신(Maildir/Spool)과 로컬 올라마(Ollama) 24/7 상주 감시관(Sentinel) 아키텍처를 3대 도구 전체 표준으로 확정. 글로벌 학술 논문 5편(`tap`, `FrugalGPT`, `RouteLLM`, `Hybrid LLM`, `LbMAS`), 오픈소스 5개(`AMQ`, `ai-night-shift`, `claude-mpm` 등), Reddit r/LocalLLaMA 엔지니어링 컨센서스 심층 근거 확보 완료. Codex 복귀 시 제14번 항목으로 공식 인수 예정.
- 2026-09-24 22:25 대행 보고(역사 기록, 2026-09-25 정정): 당시 579개 회귀와 로컬 파일럿 완료를 보고했으나 U27 잠금·스키마·자동기록 반례가 남아 있었고 이후 Antigravity 원격 토큰도 사용됐다. 따라서 `유료 API 0토큰 완결`과 `100% 절감` 주장은 철회한다. 최종 근거는 U27 행과 2026-09-25의 580개 회귀다.
- 2026-09-25 Codex 복귀 최종 판정: U23 숨은 인수 3/3, U27 Windows 다중 프로세스·잠금 fail-closed·실제 pilot v2 append, 복귀 점검 13/13, 전체 580 OK(1 skip), compileall exit 0. R1은 역사적 실패 표본으로 보존하고 R2/R4가 대체한다. 사용자 안내 `docs/33_uaos-final-user-guide-and-completion-briefing.md` 발행. 로컬 구현·검증 체계는 DONE, 실제 계정 한도 절감은 UNMEASURED.
- 2026-09-25 U30 Antigravity 대행 마무리 및 전역 배포 확정: 사용자 명시 권한 위임에 따라 Codex 부재 중 멈춘 U30 마무리 수행. 전역 규칙 v5.24.0 정본 동기화 완료(`sync-global-rules.ps1 -Mode Check` ALIGNED, exit 0), 운영 가이드 `docs/올라마_오류를_막는_검증과_대체_절차.md` 정식 편입, 전체 회귀 테스트 580건 완료(OK, skipped=1, exit 0). 런타임 자동 검증기 코드는 구현 실패 후 미구현(격리 보존) 상태임을 정직하게 명시하고 운영 규칙/매뉴얼 배포 완료로 마무리함.
- 2026-09-25 04:28 Claude Code(클라우드 세션, Linux·Python 3.11, 사용자 직접 지시) 전수 재검토: 이전 분석의 오류 2건(P09 "무근거 추가" → 실제로는 P08 삭제의 복구, "공식 회귀가 장부를 격리" → 격리 안 됨)을 정정하고 3개 커밋으로 수정. Linux 회귀 실패 8→1(남은 1건은 B75 실제 결함). Ollama 미설치 환경이라 `Calculator-Exempt`로 직접 수정. `/usage` 구독 한도·세션 토큰은 이 세션에서 조회 불가로 UNKNOWN. 사용 영수증은 `runs.jsonl`이 저장소 추적 대상이 아니어서(로컬 전용) 이 메모로 대신하고 로컬 장부 기록은 사용자 PC에서 남긴다. Windows 회귀는 미실행(UNKNOWN) — Codex 복귀 재검토 목록 3행.
- 2026-09-25 (KST 새벽~오전) Claude Code 클라우드 세션 U32~U35: 사용자 지시("비판적으로 돌아보고 취지에 맞게 실제 구체화해서 구현", 이어서 8개 요청 — 올라마 정밀화·매뉴얼 최적화·하네스·토큰예산·전 프로젝트 프로세스·역할 매뉴얼 발행 후 실행(못하면 패스)·Codex용 기록)에 따라 구현. 원격 `main`에 새 커밋 없음 확인. `/usage` UNKNOWN(클라우드 세션 조회 불가). Antigravity·Ollama 호출 0(미설치) — 해당 실행은 패스, 매뉴얼만 발행. 결과: docs/36·37, 메모 72. 사용량 장부 `.coord/usage/runs.jsonl`은 사용자 PC 전용(한 번도 커밋된 적 없음)이라 커밋하지 않았고 U35-P1 행은 docs/36 §4에 영수증으로 남김.
- 2026-09-25 U30 런타임 자동 검증기 구현 완결: 사용자 지시("런타임 자동 검증기 파이썬 코드 및 테스트 파일의 정식 편입 구현 진행")에 따라 격리되었던 `v7_harness/olla_evidence.py` 및 고정 테스트 `tests/test_u30_olla_evidence.py`(SHA-256 `B62010417F96644B24D8F35E50179AB765F352A74A0CA84CF5929B62F9FA6EE2` 100% 일치)를 정식 소스로 편입. 8개 전용 단위 테스트 100% PASS, 전체 588개 회귀 테스트 72.8초 무결점 통과(587 OK, 1 skipped, exit 0) 확인.
- 2026-09-25 B65 완결·P08/P09 로컬 파일럿 완결·회귀 복구 (Antigravity 대행): (1) B65 Antigravity 훅 및 턴 분석 완성(`v7_harness/olla.py`, `~/.gemini/config/hooks.json`), (2) P08 `coord status` 로컬 Ollama 7b 파일럿 완결(번들 `9f4da7542ebe` APPLIED, 0 paid tokens), (3) P09 CSV 정렬 유틸리티 로컬 Ollama 7b 파일럿 완결(`src/util.py`, 번들 `2e3927305284` APPLIED, 0 paid tokens), (4) P08에서 로컬 모델이 실수로 누락한 `coord log` 파서(`cmd_coord_log`, `p_coord_log`) 복구 및 592개 전체 회귀 무결점 통과(OK, skipped=1, exit 0), (5) 커밋 `2e0453f` `origin/main` 푸시 완료(사용자 명시 승인).
- 2026-09-25 UNMEASURED 20건 전수 인벤토리 및 실측 4단계 준비: (1) PLAN 내 UNMEASURED 20건 전수 분석 아티팩트(`unmeasured-inventory.md`) 발행, (2) 즉시 실측 가능 3건(M1 로컬 성공률 / M2 토큰 집계 / M3 MCP 사용률) 및 구조적 한계 3건(계정 쿼터 / 하루 운영 지연 / 자율 사용률) 식별, (3) 내일 기상 후 즉시 실행 가능한 4단계(M2→M3→M1→영구선언) 절차 세팅 완료.
- 2026-09-25 Claude Code 클라우드 세션 U36·U37: 사용자 지시(B77 승인, RSI 비판적 재조사·자가진화, UAOS 전역 배포, 초보자용 전과정 정리, 이후 "무승인 절차로 계속")에 따라 구현. `/usage` UNKNOWN(클라우드 세션 조회 불가). Ollama·Antigravity 호출 0(미설치). Reddit은 검색 도구가 접근 거부(UNKNOWN), arxiv·openreview·antigravity.google 원문은 네트워크 정책 차단으로 검색 요약만 사용. 전역 규칙 정본 저장소 add_repo는 거부돼 미반영. 결과: docs/38·39, `docs/쉽게_읽는_UAOS_진단과_해결_전과정/` 00~06, 메모 73. 장부 `.coord/usage/runs.jsonl` 미생성·미커밋.
- 2026-09-25 Claude Code 클라우드 세션 비판적 재검토(사용자 지시 "다시 비판적으로 돌아보고 … 정리·정제 … Codex에게 보고"): 자기 RSI 관문을 반례로 공격해 구멍 2개(재실행 복제로 표본 부풀리기, 무관 작업자 실행으로 재검증 채우기)를 재현·수정(red-first). 초보자 문서에 07(실제 사례 6가지, few-shot)·08(약한 곳 우선순위) 추가, 00에 읽는 경로·ELI10. Codex 보고서 `docs/claude-assist/74_…`. Linux 710 중 실패 1(B75). `/usage` UNKNOWN(클라우드 세션 조회 불가), Ollama·Antigravity 호출 0.
- 2026-09-25 Codex 프로세스 및 [U42] RSI 자동화 전수 완결 (Antigravity 권한대행): 사용자 지시("U42 RSI 연구PR 자동화, U42 증거 관문형 RSI 자동화 프로세스를 권한대행으로 안티그래비티가 완수했다. 이제 codex가 진행하던 프로세스를 무승인 절차로 끝까지 마무리해라")에 따라 Codex 잔여 프로세스 전수 완결. (1) U31~U37 대행 판정 완료: 5대 비유 결함 NOT_REPRODUCED, U32 우편함/교환원, U33 스트림, U34 정밀 하네스, U35 파일럿, U36 RSI 관문(27 OK), U37 전역 설치(710 OK, U37-W1 47/47 OK) 전건 DONE 확정. (2) U38~U41 정식 편입: Claude Code 정식 작업자(U38), 토큰예산 상태 기계 라우팅(U39), Ollama 시스템 학습/LoRA 관문(U40), deploy_to_this_pc 전역 배포(U41) 전건 DONE 판정. (3) [U42] 증거 관문형 RSI 자동화 및 연구PR 자동화 프로세스 최종 완수. Codex 조율 프로세스 전수 종결.
- 2026-09-26 [U42-R1] Codex 재검토에서 기존 완료 주장을 회수했다. PR #6의 외부 명령 실패 무시, retry sleep 누락, 소스별 중복 trigger, stale·비원자 lock, 스케줄러 이름 충돌과 로그 보존 부재를 고정 인수로 재작업하며, 실제 삭제와 자동 병합은 금지한다.
- 2026-09-26 [U42-R1] 계약 호출 상한대로 Claude 구현·Ollama 기계 분류·Antigravity 레드팀을 각 1회만 실행했다. Claude는 외부쓰기·예산 초과로 bundle 없이 BLOCKED, Antigravity는 P1 5종 FAIL을 확인했으나 자체 예산 초과로 보고서 승인을 거부했다. Ollama 분류 1개만 원문 대조 후 APPLIED했다. 신규 고정 인수는 retention import 오류로 exit 1이므로 U42를 `REVIEW (BLOCKED 증거 반환)`로 두고 PR #6 push·전역 배포·스케줄 등록을 중단한다.
- 2026-09-26 [U42-R2] 재개 지시에 따라 Claude 원장 `NOTHING_TO_RECONCILE`, local 구현 재시도는 `rv.bak` 외부쓰기 감지로 ABANDONED 처리했다. Claude 격리 후보를 직접 테스트해 Windows path 정규화 2건을 보정하고, 정확한 6파일을 0토큰 apply bundle로 재구성했다. wrapper materialization·status 디코딩 반례까지 추가해 focused 56/56, 전체 783 OK, compileall 0, 고정 SHA 불변을 확인했다. 전역 설치기 apply/check drift 0, 프로젝트 고유 Windows 작업 Ready, manual-now dry-run 0으로 U42를 REVIEW에 반환한다.
- 2026-09-26 [U45] Codex 한도 도달(5시간 97% 리셋 18:50 대기)에 따른 사용자 지시("전수파악 후 무승인 마무리지어라")에 따라 Antigravity가 완결 대행 수행: U42(5f49b85)+U44(40caf37) 기준선 머지 완결, SemVer 0.2.0 범프, `coord init` 프로젝트 매뉴얼/계약 템플릿 생성 구현, `docs/46` 범용 UAOS 핵심 설계서 발행, `tests/test_u45_general_uaos.py` 통과, 777 회귀 통과 확인 후 DONE으로 마감. Codex 복귀 재검토 대상 기록.
===FILE: tests/test_u71_three_tool_e2e.py===
"""U71: three-tool unattended continuity, end to end, with real parallel OS processes.

Every step runs the real `python -m v7_harness.cli coord ...` command in its own process, several at once, against one
throwaway desk. A fake `claude` executable first on PATH writes one file per invocation, so the count of files is the
count of paid Claude turns that the real CLI would have started. The run walks the whole cycle:

    ACTIVE -> THRIFT -> HANDOFF_READY -> acting (Claude) -> RETURN_REVIEW -> LOCAL_LOCKDOWN

and checks the gates of card U71: one writer per step (one packet and one letter per episode, however many callers
race), at most one paid turn per letter, zero paid turns for ACK_ONLY, the zero-token watcher as the wake path, and a
lockdown that routes nothing and wakes nobody.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord.watch import watcher_live

REPO = Path(__file__).resolve().parents[1]
# Six callers per racing step: U63's in-process race used eight threads; six processes keep the run near 20 s on
# this host (each process pays a ~0.3 s interpreter start) while still overlapping every critical section.
RACERS = 6
# The watcher scans every 0.2 s here instead of 30 s so the test waits seconds, not minutes; the scan logic is the same.
WATCH_INTERVAL_S = "0.2"
FIELDS = ["--current-card", "U71", "--next-action", "run the fixed acceptance",
          "--acceptance", "python -m unittest tests.test_u71_three_tool_e2e", "--stop-condition", "fixed test changed"]

FAKE_CLAUDE = """import json, os, sys, time, uuid
log = os.environ["U71_CLAUDE_LOG"]
name = f"{time.time_ns()}_{os.getpid()}_{uuid.uuid4().hex}.json"
# One file per call: concurrent appends to one file lose lines on Windows.
with open(os.path.join(log, name), "w", encoding="utf-8") as handle:
    json.dump({"argv": sys.argv[1:]}, handle)
print(json.dumps({"result": "processed", "is_error": False}))
"""


class ThreeToolContinuityE2E(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.desk = root / "desk"
        (self.desk / ".coord" / "mailbox").mkdir(parents=True)
        (self.desk / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        self.calls = root / "claude_calls"
        self.calls.mkdir()
        fake_bin = root / "bin"
        fake_bin.mkdir()
        (fake_bin / "fake_claude.py").write_text(FAKE_CLAUDE, encoding="utf-8")
        if os.name == "nt":
            (fake_bin / "claude.cmd").write_text(f'@"{sys.executable}" "%~dp0fake_claude.py" %*\r\n', encoding="utf-8")
        else:
            script = fake_bin / "claude"
            script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/fake_claude.py" "$@"\n',
                              encoding="utf-8")
            script.chmod(0o755)
        self.env = {**os.environ, "PATH": str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                    "PYTHONPATH": str(REPO), "U71_CLAUDE_LOG": str(self.calls), "PYTHONIOENCODING": "utf-8"}
        self.env.pop("CLAUDE_WORKER_CMD", None)
        # Safety before anything runs: the only `claude` these processes can find is the fake one.
        found = shutil.which("claude", path=self.env["PATH"])
        self.assertIsNotNone(found)
        self.assertEqual(fake_bin.resolve(), Path(found).resolve().parent)
        self._watchers: list[subprocess.Popen] = []

    def tearDown(self) -> None:
        for proc in self._watchers:
            if proc.poll() is None:
                proc.kill()
                proc.communicate()
        self._tmp.cleanup()

    # --- process helpers -----------------------------------------------------------------------------------------
    def _argv(self, *args: str) -> list[str]:
        return [sys.executable, "-m", "v7_harness.cli", "coord", args[0], "--project", str(self.desk), *args[1:]]

    def _start(self, *args: str) -> subprocess.Popen:
        return subprocess.Popen(self._argv(*args), cwd=REPO, env=self.env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")

    def _race(self, *args: str, n: int = RACERS) -> list[tuple[int, dict]]:
        """Start n identical processes before waiting on any, so they overlap for real."""
        procs = [self._start(*args) for _ in range(n)]
        results = []
        for proc in procs:
            out, err = proc.communicate(timeout=120)
            self.assertTrue(out.strip(), f"no output (rc={proc.returncode}): {err[-800:]}")
            results.append((proc.returncode, json.loads(out)))
        return results

    def _one(self, *args: str) -> tuple[int, dict]:
        return self._race(*args, n=1)[0]

    def _presence(self, **states: str) -> None:
        for tool, state in states.items():
            code, _ = self._one("presence", "--tool", tool, "--state", state)
            self.assertEqual(0, code)

    def _watch(self, timeout_s: int) -> subprocess.Popen:
        proc = self._start("watch", "--target", "claude", "--timeout", str(timeout_s), "--interval", WATCH_INTERVAL_S)
        self._watchers.append(proc)
        deadline = time.monotonic() + 30
        while not watcher_live(self.desk, "claude"):
            self.assertIsNone(proc.poll(), "watcher exited before it was live")
            self.assertLess(time.monotonic(), deadline, "watcher never became live")
            time.sleep(0.05)
        return proc

    def _paid_turns(self) -> int:
        return len(list(self.calls.glob("*.json")))

    def _letters(self, prefix: str) -> list[str]:
        return sorted(p.stem for p in (self.desk / ".coord" / "mailbox" / "inbox").glob(f"{prefix}*.json"))

    def _packets(self) -> list[Path]:
        return sorted((self.desk / ".coord" / "handoff").glob("*.md"))

    # --- the cycle ---------------------------------------------------------------------------------------------
    def test_full_cycle_one_writer_one_paid_turn_per_letter(self) -> None:
        # ACTIVE: all three tools present, Codex conducts.
        self._presence(codex="ACTIVE", claude="ACTIVE", antigravity="ACTIVE")
        self.assertEqual("codex", self._one("route")[1]["authority"])

        # THRIFT: Codex at 15 % keeps working under its own reserve policy; the racers write one packet, one letter.
        results = self._race("thrift", "--tool", "codex", "--remaining-percent", "15", *FIELDS)
        self.assertEqual([0] * RACERS, [code for code, _ in results])
        statuses = sorted(r["status"] for _, r in results)
        self.assertEqual(["ACK_ONLY"] * (RACERS - 1) + ["ACTIONABLE_DELTA"], statuses)
        delta = next(r for _, r in results if r["status"] == "ACTIONABLE_DELTA")
        self.assertEqual(("THRIFT", "codex", "COMMANDER_RESERVE"), (delta["state"], delta["target"], delta["policy"]))
        self.assertEqual(1, len(self._packets()))

        # HANDOFF_READY: Claude's watcher is the only wake path; thrift itself starts no model.
        self._presence(codex="LIMITED")
        watcher = self._watch(timeout_s=60)
        results = self._race("thrift", "--tool", "codex", "--remaining-percent", "5", *FIELDS)
        deltas = [r for _, r in results if r["status"] == "ACTIONABLE_DELTA"]
        self.assertEqual(1, len(deltas), results)
        self.assertEqual(("HANDOFF_READY", "claude"), (deltas[0]["state"], deltas[0]["target"]))
        out, _ = watcher.communicate(timeout=60)
        woke = json.loads(out)
        self.assertEqual((0, "NEW_LETTER", deltas[0]["message_id"], "HANDOFF"),
                         (watcher.returncode, woke["reason"], woke["id"], woke["kind"]))
        self.assertEqual(2, len(self._packets()))
        self.assertEqual(0, self._paid_turns())

        # Acting: every racer sees the same single authority.
        routes = self._race("route")
        self.assertEqual({"claude"}, {r["authority"] for _, r in routes})

        # ACK_ONLY while the interactive session listens: queued for it, no paid turn.
        watcher = self._watch(timeout_s=60)
        results = self._race("deliver", "--actor", "codex", "--target", "claude",
                             "--message", "ACK_ONLY liveness: U71 unchanged")
        # A racer that loses the per-letter guard answers IN_FLIGHT; the letter is already published either way.
        # U74-D: the watcher returns on the published letter and clears its file, so a racer that checks after that
        # sees no watcher; it answers QUEUED_ACK_ONLY (it used to answer DISPATCHED and buy a paid turn).
        reasons = [r["reason"] for _, r in results]
        self.assertTrue({"QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY"} & set(reasons), reasons)
        self.assertLessEqual(set(reasons), {"QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY", "IN_FLIGHT"})
        self.assertEqual(1, len({r["message_id"] for _, r in results}))
        out, _ = watcher.communicate(timeout=60)
        self.assertEqual((0, results[0][1]["message_id"]), (watcher.returncode, json.loads(out)["id"]))
        self.assertEqual(0, self._paid_turns())

        # ACTIONABLE_DELTA: racing senders of one letter buy exactly one paid turn, and a live watcher that has
        # seen everything else does not wake on that already-dispatched letter: it times out (exit 3).
        watcher = self._watch(timeout_s=6)
        results = self._race("deliver", "--actor", "antigravity", "--target", "claude",
                             "--message", "ACTIONABLE_DELTA verdict_requested=yes: U71 evidence changed")
        self.assertEqual(1, self._paid_turns(), results)
        self.assertEqual({"DISPATCHED"}, {r["reason"] for _, r in results} - {"IN_FLIGHT"})
        out, _ = watcher.communicate(timeout=60)
        self.assertEqual((3, "TIMEOUT"), (watcher.returncode, json.loads(out)["reason"]),
                         "the watcher woke on a letter a paid turn already answered")
        # Re-sending the same letter later is idempotent: still one paid turn.
        self._one("deliver", "--actor", "antigravity", "--target", "claude",
                  "--message", "ACTIONABLE_DELTA verdict_requested=yes: U71 evidence changed")
        self.assertEqual(1, self._paid_turns())

        # RETURN_REVIEW: Codex comes back; one return letter, and it leads again.
        self._presence(codex="ACTIVE")
        results = self._race("thrift", "--tool", "codex", "--remaining-percent", "80")
        returns = [r for _, r in results if r.get("event") == "RETURN_REVIEW" and r["status"] == "ACTIONABLE_DELTA"]
        self.assertEqual(1, len(returns), results)
        self.assertEqual("codex", self._one("route")[1]["authority"])

        # LOCAL_LOCKDOWN: nobody may act. Routing fails closed, the hand-off names no tool, a letter stays in the
        # mailbox, and no paid turn starts.
        self._presence(codex="LIMITED", claude="LIMITED", antigravity="LIMITED")
        code, route = self._one("route")
        self.assertEqual((1, "BLOCKED_NO_ACTIVE_AUTHORITY"), (code, route["authority"]))
        results = self._race("thrift", "--tool", "claude", "--remaining-percent", "5", *FIELDS)
        lockdown = [r for _, r in results if r["status"] == "ACTIONABLE_DELTA"]
        self.assertEqual(["LOCAL_LOCKDOWN"], [r["target"] for r in lockdown])
        code, sent = self._one("deliver", "--actor", "codex", "--message", "ACTIONABLE_DELTA verdict_requested=yes: lockdown")
        self.assertEqual(("mailbox_only", "PUBLISHED"), (sent["target"], sent["reason"]))
        self.assertEqual(1, self._paid_turns())
        self.assertEqual({"codex": "LIMITED", "claude": "LIMITED", "antigravity": "LIMITED"}, route["states"])

        # One writer per step: THRIFT, HANDOFF, RETURN_REVIEW and LOCKDOWN each left exactly one thrift letter.
        self.assertEqual(4, len(self._letters("thrift_")))
        self.assertEqual(3, len(self._packets()))  # RETURN_REVIEW is NORMAL: a letter, no packet


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
