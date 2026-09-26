"""U42-R1 frozen acceptance for fail-closed shipping, scheduling, locking, and retention."""

from __future__ import annotations

import hashlib
import json
import multiprocessing
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness import retention, rsi_release

HEAD = "a" * 40
BRANCH = "codex/u42-rsi-research-pr"


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _packet() -> dict:
    snapshot = "fixed"
    receipt = {"exit_code": 0, "passed": 1, "fixed_sha256": _sha("gate"), "runner": "antigravity"}
    return {
        "schema": "uaos-rsi-release-v1", "work_id": "U42", "title": "R1", "summary": "hardening",
        "author": "claude", "verifier": "antigravity", "judge": "codex", "change_type": "fix",
        "base_branch": "main", "branch": BRANCH, "version_file": "uaos_everywhere/VERSION",
        "update_documents": ["README.md"], "changed_files": ["v7_harness/rsi_release.py"],
        "sources": [{"url": "https://example.test", "snapshot": snapshot,
                     "snapshot_sha256": _sha(snapshot)}],
        "acceptance": dict(receipt), "holdout": dict(receipt), "red_team": dict(receipt),
        "usage": {"remote_budget_tokens": 100, "actual_tokens": 10, "wall_seconds": 1, "failures": []},
    }


def _approval() -> dict:
    text = "approved"
    return {
        "work_id": "U42", "approval_text": text, "approval_sha256": _sha(text),
        "allowed_actions": list(rsi_release.REQUIRED_APPROVAL_ACTIONS), "forbidden_actions": ["auto_merge"],
    }


def _scheduler_process(root: str, start, output) -> None:
    start.wait(10)

    def fetch(source, timeout):
        time.sleep(0.2)
        return {"url": source["url"], "version": "1", "etag": "e", "last_modified": "d",
                "content_sha256": _sha("same")}

    result = rsi_release.run_scheduler_cycle(
        Path(root), {"sources": [{"url": "https://example.test"}], "max_retries": 1,
                     "timeout_seconds": 2, "lock_ttl_seconds": 60},
        fetch=fetch, trigger=lambda _: None, now=time.time(),
    )
    output.put(result["status"])


class ShippingFailClosedTests(unittest.TestCase):
    def _runner(self, fail: tuple[str, ...] | None = None, remote: str = HEAD):
        calls = []

        def run(command, **kwargs):
            calls.append(list(command))
            prefix = tuple(command[:len(fail)]) if fail else ()
            if fail and prefix == fail:
                return subprocess.CompletedProcess(command, 9, "", "boom")
            if command[:2] == ["git", "status"]:
                out = " M v7_harness/rsi_release.py\n"
            elif command[:3] == ["git", "rev-parse", "HEAD"]:
                out = HEAD + "\n"
            elif command[:2] == ["git", "ls-remote"]:
                out = (remote + f"\trefs/heads/{BRANCH}\n") if remote else ""
            elif command[:3] == ["gh", "pr", "view"]:
                out = '{"url":"https://github.com/o/r/pull/6","state":"OPEN"}'
            else:
                out = "ok\n"
            return subprocess.CompletedProcess(command, 0, out, "")

        return run, calls

    def test_every_external_step_failure_names_the_step_and_never_ships(self) -> None:
        stages = {
            ("git", "status"): "git status", ("git", "fetch"): "git fetch",
            ("git", "add"): "git add", ("git", "commit"): "git commit",
            ("git", "rev-parse"): "git rev-parse HEAD", ("git", "push"): "git push",
            ("git", "ls-remote"): "git ls-remote", ("gh", "pr", "create"): "gh pr create",
            ("gh", "pr", "view"): "gh pr view",
        }
        for prefix, label in stages.items():
            with self.subTest(stage=label):
                runner, _ = self._runner(prefix)
                with self.assertRaisesRegex(rsi_release.ReleaseRefused, label):
                    rsi_release.ship_release(Path("."), _packet(), _approval(), execute=True, run=runner)

    def test_push_failure_cannot_return_shipped(self) -> None:
        runner, _ = self._runner(("git", "push"))
        with self.assertRaises(rsi_release.ReleaseRefused):
            rsi_release.ship_release(Path("."), _packet(), _approval(), execute=True, run=runner)

    def test_remote_sha_must_exist_and_equal_local_head(self) -> None:
        for remote in ("", "b" * 40):
            runner, _ = self._runner(remote=remote)
            with self.assertRaisesRegex(rsi_release.ReleaseRefused, "REMOTE_SHA"):
                rsi_release.ship_release(Path("."), _packet(), _approval(), execute=True, run=runner)


class SchedulerHardeningTests(unittest.TestCase):
    def _config(self) -> dict:
        return {"interval_seconds": 86400, "timeout_seconds": 15, "max_retries": 3,
                "backoff_base_seconds": 60, "lock_ttl_seconds": 600,
                "sources": [{"url": "https://a.test"}, {"url": "https://b.test"}]}

    def _obs(self, url: str, content: str) -> dict:
        return {"url": url, "version": content, "etag": content, "last_modified": content,
                "content_sha256": _sha(content)}

    def test_retry_sleeper_is_called_between_attempts_only(self) -> None:
        sleeps = []
        attempts = []

        def fail(source, timeout):
            attempts.append(source["url"])
            raise OSError("offline")

        with tempfile.TemporaryDirectory() as d:
            result = rsi_release.run_scheduler_cycle(Path(d), self._config(), fetch=fail, trigger=lambda _: None,
                                                     sleeper=sleeps.append, now=1000)
        self.assertEqual("FAILED", result["status"])
        self.assertEqual(3, len(attempts))
        self.assertEqual([60, 120], sleeps)
        self.assertEqual([60, 120, 240], result["backoff_seconds"])
        self.assertEqual(1240, result["next_run_at"])

    def test_two_changed_sources_are_collected_then_triggered_once(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            prior = {url: self._obs(url, "old") for url in ("https://a.test", "https://b.test")}
            state = root / ".work" / "rsi-scheduler-state.json"
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps(prior), encoding="utf-8")
            calls = []
            result = rsi_release.run_scheduler_cycle(
                root, self._config(), fetch=lambda source, _: self._obs(source["url"], "new"),
                trigger=calls.append, now=1000,
            )
            self.assertEqual("ACTIONABLE_DELTA", result["status"])
            self.assertEqual(1, len(calls))
            self.assertEqual(2, len(calls[0]["deltas"]))

    def test_stale_lock_recovers_but_live_lock_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            lock = root / ".work" / "rsi-scheduler.lock"
            lock.parent.mkdir(parents=True)
            lock.write_text(json.dumps({"pid": 111, "started_at": 900}), encoding="utf-8")
            records = []
            blocked = rsi_release.run_scheduler_cycle(root, self._config(), fetch=lambda *_: {}, trigger=lambda _: None,
                                                      pid_alive=lambda pid: True, record=records.append, now=1000)
            self.assertEqual("LOCKED", blocked["status"])
            recovered = rsi_release.run_scheduler_cycle(
                root, self._config(), fetch=lambda source, _: self._obs(source["url"], "new"),
                trigger=lambda _: None, pid_alive=lambda pid: False, record=records.append, now=1000,
            )
            self.assertEqual("ACK_ONLY", recovered["status"])
            self.assertTrue(any(r.get("event") == "STALE_LOCK_RECOVERED" for r in records), records)

    def test_atomic_lock_allows_exactly_one_process_owner(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            ctx = multiprocessing.get_context("spawn")
            start = ctx.Event()
            output = ctx.Queue()
            processes = [ctx.Process(target=_scheduler_process, args=(d, start, output)) for _ in range(4)]
            for process in processes:
                process.start()
            start.set()
            for process in processes:
                process.join(15)
                self.assertEqual(0, process.exitcode)
            statuses = [output.get(timeout=3) for _ in processes]
            self.assertEqual(1, sum(status != "LOCKED" for status in statuses), statuses)

    def test_task_name_is_project_unique_and_manual_now_runs_from_project(self) -> None:
        calls = []

        def run(command, **kwargs):
            calls.append((list(command), kwargs))
            return subprocess.CompletedProcess(command, 0, "SUCCESS", "")

        one = rsi_release.windows_schedule(Path(r"C:\Work\One"), r"C:\Python\python.exe", action="install")
        two = rsi_release.windows_schedule(Path(r"C:\Work\Two"), r"C:\Python\python.exe", action="install")
        self.assertNotEqual(one["task_name"], two["task_name"])
        self.assertIn("C:\\Work\\One", one["wrapper_text"])
        result = rsi_release.windows_schedule(Path(r"C:\Work\One"), r"C:\Python\python.exe",
                                              action="manual-now", apply=True, run=run)
        self.assertTrue(result["ok"])
        self.assertEqual(Path(r"C:\Work\One"), calls[0][1]["cwd"])


class RetentionPlanTests(unittest.TestCase):
    def _file(self, root: Path, rel: str, text: str, age_days: int, now: float) -> Path:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        stamp = now - age_days * 86400
        os.utime(path, (stamp, stamp))
        return path

    def test_plan_is_hash_manifest_only_and_protects_failures_approvals_and_active_runs(self) -> None:
        now = 2_000_000_000.0
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            old_ok = self._file(root, ".coord/pilot/runs/old/summary.json", '{"status":"PASS"}', 90, now)
            old_fail = self._file(root, ".coord/pilot/runs/fail/summary.json", '{"status":"FAILED","p1":true}', 90, now)
            approval = self._file(root, ".coord/approvals/U42.json", '{"approval":true}', 400, now)
            active = self._file(root, ".coord/pilot/runs/active/summary.json", '{"status":"ACTIVE"}', 90, now)
            policy = retention.default_policy()
            plan = retention.plan_retention(root, policy, now=now)
            by_path = {item["path"]: item for item in plan["items"]}
            self.assertEqual("ARCHIVE_CANDIDATE", by_path[old_ok.relative_to(root).as_posix()]["action"])
            self.assertEqual("PROTECT", by_path[old_fail.relative_to(root).as_posix()]["action"])
            self.assertEqual("PROTECT", by_path[approval.relative_to(root).as_posix()]["action"])
            self.assertEqual("ACTIVE_EXCLUDE", by_path[active.relative_to(root).as_posix()]["action"])
            self.assertEqual(64, len(plan["manifest_sha256"]))
            self.assertIn("archive_path", by_path[old_ok.relative_to(root).as_posix()])

    def test_retention_defaults_to_dry_run_and_never_deletes(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            target = self._file(root, ".work/logs/old.log", "old", 365, 2_000_000_000.0)
            plan = retention.plan_retention(root, retention.default_policy(), now=2_000_000_000.0)
            result = retention.apply_retention(root, plan)
            self.assertEqual("DRY_RUN", result["status"])
            self.assertTrue(target.exists())
            with self.assertRaisesRegex(retention.RetentionRefused, "FRESH_DELETE_APPROVAL_REQUIRED"):
                retention.apply_retention(root, plan, execute_delete=True)
            self.assertTrue(target.exists())

    def test_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            policy = retention.default_policy()
            policy["zones"].append({"path": "../outside", "retention_days": 1, "max_count": 1, "max_bytes": 1})
            with self.assertRaisesRegex(retention.RetentionRefused, "PATH_ESCAPE"):
                retention.plan_retention(root, policy, now=1)


if __name__ == "__main__":
    unittest.main()
