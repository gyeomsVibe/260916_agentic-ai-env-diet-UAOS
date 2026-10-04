"""Antigravity CLI (agy) real-process launcher integrated with Windows Job Objects and headless JSON protocol."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from v7_harness.adapters.agy import AgyOutcome, AgyRequest, build_agy_command, parse_agy_result
from v7_harness.adapters.long_prompt import ARGV_PROMPT_CHARS, FILE_MARKER, WINDOWS_ARGV_LIMIT, command_line_chars
from v7_harness.contracts.execution import WorkerDecision
from v7_harness.execution.launcher import (
    _assign_process_to_job,
    _cleanup_job,
    _create_win_job,
    _terminate_process_tree,
)


def fit_command_line(argv: list[str], prefix_len: int, prompt_path: Path, *,
                     windows: bool = os.name == "nt") -> tuple[list[str], str]:
    """(argv, error) that fits the command line (U44 W6). argv[prefix_len] is "-p" and the prompt follows it.

    Our Python adapters (*_worker.py) take the prompt as a file past ARGV_PROMPT_CHARS. The real agy binary has no
    documented prompt file, so on Windows an agy line past the limit is refused before it starts.
    """
    if command_line_chars(argv) <= ARGV_PROMPT_CHARS or argv[prefix_len:prefix_len + 1] != ["-p"]:
        return argv, ""
    if any(str(part).endswith("_worker.py") for part in argv[:prefix_len]):
        prompt_path.write_text(argv[prefix_len + 1], encoding="utf-8")
        return argv[:prefix_len + 1] + [FILE_MARKER + str(prompt_path.resolve())] + argv[prefix_len + 2:], ""
    chars = command_line_chars(argv)
    if windows and chars >= WINDOWS_ARGV_LIMIT:
        return argv, (f"PROMPT_TOO_LONG_FOR_ARGV: the agy command line is {chars} characters, Windows allows "
                      f"{WINDOWS_ARGV_LIMIT - 1}; shorten the contract or use a Python worker")
    return argv, ""


class AgyProcessLauncher:
    """Execute real headless agy CLI process inside Windows Job Object with durable timeout and heartbeat."""

    def __init__(self, *, agy_command: list[str], request: AgyRequest, runs_dir: Path) -> None:
        self.agy_command = list(agy_command)
        self.request = request
        self.runs_dir = Path(runs_dir)
        self.last_outcome: AgyOutcome | None = None
        self.raw_paths: tuple[Path, Path] | None = None

    def launch(
        self,
        *,
        attempt_id: str,
        acceptance_hash: str,
        command_id: str = "c1",
        mode: str = "success",
        timeout_sec: float | None = None,
        on_wait_hook: Callable[[], None] | None = None,
        worker_capability: str | None = None,
        heartbeat: Callable[[], bool] | None = None,
        heartbeat_interval_sec: float = 0.25,
        **kwargs: Any,
    ) -> WorkerDecision:
        # Build command replacing the initial executable with agy_command list
        built = build_agy_command(self.request)
        argv = list(self.agy_command) + built[1:]

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        json_path = self.runs_dir / f"{attempt_id}.json"
        err_path = self.runs_dir / f"{attempt_id}.err"
        argv, too_long = fit_command_line(argv, len(self.agy_command), self.runs_dir / f"{attempt_id}.prompt.md")
        if too_long:
            # Nothing started, so nothing changed: effect NONE, not a reconciliation case.
            json_path.write_bytes(b"")
            err_path.write_bytes(too_long.encode("utf-8"))
            self.raw_paths = (json_path, err_path)
            return WorkerDecision(successful=False, result_status="ERROR", effect_state="NONE", retryable=False,
                                  error_class="PROMPT_TOO_LONG_FOR_ARGV")

        # Launcher timeout: request.print_timeout_s + 60 seconds
        timeout = float(timeout_sec) if timeout_sec is not None else float(self.request.print_timeout_s + 60)

        job = _create_win_job()
        # U146-B (agy audit relay_3e404354): a headless worker is not a session; UAOS_WORKER keeps its global hooks
        # (presence, the nonstop Stop gate) from writing a heartbeat or holding it on a new card.
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name != "nt",
            env={**os.environ, "UAOS_WORKER": "1"},
        )
        if job and not _assign_process_to_job(job, proc):
            _cleanup_job(job)
            job = None

        if on_wait_hook is not None:
            on_wait_hook()

        if heartbeat_interval_sec <= 0:
            raise ValueError("INVALID_HEARTBEAT_INTERVAL")

        deadline = time.monotonic() + timeout
        stdout = b""
        stderr = b""
        timed_out = False
        heartbeat_failed = False

        try:
            while True:
                if heartbeat is not None and not heartbeat():
                    heartbeat_failed = True
                    if _terminate_process_tree(job, proc):
                        job = None
                    try:
                        stdout, stderr = proc.communicate(timeout=1.0)
                    except Exception:
                        pass
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    timed_out = True
                    if _terminate_process_tree(job, proc):
                        job = None
                    try:
                        stdout, stderr = proc.communicate(timeout=1.0)
                    except Exception:
                        pass
                    break
                try:
                    stdout, stderr = proc.communicate(timeout=min(heartbeat_interval_sec, remaining))
                    break
                except subprocess.TimeoutExpired:
                    continue
        finally:
            _cleanup_job(job)

        # Save raw evidence
        json_path.write_bytes(stdout if stdout is not None else b"")
        err_path.write_bytes(stderr if stderr is not None else b"")
        self.raw_paths = (json_path, err_path)

        if heartbeat_failed:
            return WorkerDecision(
                successful=False,
                result_status="NEEDS_RECONCILIATION",
                effect_state="UNKNOWN",
                retryable=False,
                error_class="LEASE_HEARTBEAT_FAILED",
            )

        if timed_out:
            return WorkerDecision(
                successful=False,
                result_status="NEEDS_RECONCILIATION",
                effect_state="UNKNOWN",
                retryable=False,
                error_class="TIMEOUT",
            )

        outcome = parse_agy_result(stdout=stdout, stderr=stderr, exit_code=proc.returncode)
        self.last_outcome = outcome

        if outcome.successful:
            return WorkerDecision(
                successful=True,
                result_status="SUCCEEDED",
                effect_state="CONFIRMED",
                retryable=False,
                error_class="NONE",
            )
        else:
            return WorkerDecision(
                successful=False,
                result_status="NEEDS_RECONCILIATION",
                effect_state="UNKNOWN",
                retryable=False,
                error_class=outcome.error_class,
            )
