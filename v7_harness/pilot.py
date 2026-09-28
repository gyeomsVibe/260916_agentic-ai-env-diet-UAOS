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


def _worker_error(path: Path) -> str | None:
    """The `error` of a worker's JSON envelope (U81), or None when it is missing or unreadable."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    error = data.get("error") if isinstance(data, dict) else None
    return error if isinstance(error, str) and error else None


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
            # U81: the engine reports a worker refusal as UNKNOWN_EFFECT_NEEDS_RECONCILIATION; keep the worker's own
            # reason (e.g. UNREQUESTED_DELETION) so rsi does not blame the Ollama service for a deterministic refusal.
            worker_error = _worker_error(raw_stdout)
            if worker_error and worker_error not in detail:
                detail = f"{detail}; worker: {worker_error}"
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
