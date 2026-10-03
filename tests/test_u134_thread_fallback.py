"""U134-D / U134-R F1: A codex `--thread` is used only when its rollout binds it to this project.

Approved specification: U134-R_F1_spec.md (SHA256 285a2bd72ed4f55a745245ea75dd0a6fd7c33676ec5f91eaf7946baf1fa5235c).
Rules under test:
1. Identity is read only from a rollout's first line (readline max 256 KiB), JSON type == 'session_meta'.
   Every present id key (payload.id, payload.session_id) must be non-empty and equal.
2. A requested thread must match UUID shape and rollout filename/payload. Unreadable / oversize / contradictory
   -> THREAD_UNVERIFIED, zero sends.
3. Project identity: canonical cwd must equal a registered checkout ({desk, main, *linked_worktrees} via .git/worktrees/*/gitdir).
   Unregistered cwd -> THREAD_PROJECT_MISMATCH, zero sends.
4. Fallback discovery is bounded: newest 12 rollouts. None -> NO_VERIFIED_THREAD, zero sends.
5. Non-UUID text -> fallback why=not_uuid; UUID without rollout -> fallback why=no_rollout.
6. One send-failure fallback on rc!=0 -> retry once with newest verified thread other than failed one (why=send_failed).
   Timeout / OSError is not retried. Never a third send.
"""

import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver

OLD = "0199aaaa-0000-7000-8000-000000000001"
NEW = "0199bbbb-0000-7000-8000-000000000002"
OTHER = "0199cccc-0000-7000-8000-000000000003"
TWIN = "0199dddd-0000-7000-8000-000000000004"
WT_THREAD = "0199eeee-0000-7000-8000-000000000005"
UNREG_THREAD = "0199ffff-0000-7000-8000-000000000006"


class _Runner:
    def __init__(self, fail_threads=(), timeout_threads=()):
        self.calls = []
        self.fail_threads = set(fail_threads)
        self.timeout_threads = set(timeout_threads)

    def __call__(self, command, **_kw):
        self.calls.append(list(command))
        thread = command[command.index("--thread") + 1] if "--thread" in command else ""
        if thread in self.timeout_threads:
            raise subprocess.TimeoutExpired(command, timeout=60)
        if thread in self.fail_threads:
            return mock.Mock(returncode=1, stdout="", stderr="No active session found")
        return mock.Mock(returncode=0, stdout="", stderr="")

    def threads(self):
        return [c[c.index("--thread") + 1] if "--thread" in c else "" for c in self.calls]


class ThreadFallbackTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        (self.project / ".git").mkdir(parents=True)
        (self.project / ".git" / "worktrees").mkdir(parents=True)

        self.sessions = Path(self._tmp.name) / "codex-sessions"
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(self.sessions)})
        self._env.start()
        self._which = mock.patch("v7_harness.coord.deliver.shutil.which", return_value="codex")
        self._which.start()
        presence.mark(self.project, "codex", "ACTIVE")

    def tearDown(self):
        self._which.stop()
        self._env.stop()
        self._tmp.cleanup()

    def _rollout(self, thread, cwd, age_s, *, raw_content=None, meta_dict=None):
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{thread}.jsonl"
        if raw_content is not None:
            path.write_text(raw_content, encoding="utf-8")
        else:
            meta = meta_dict or {"type": "session_meta", "payload": {"id": thread, "session_id": thread, "cwd": str(cwd)}}
            path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
        moment = time.time() - age_s
        os.utime(path, (moment, moment))
        return path

    def _send(self, thread, message, runner=None):
        runner = runner or _Runner()
        result = deliver(self.project, message=message, actor="claude", target="codex", runner=runner, thread=thread)
        return result, runner

    def _receipt(self, result):
        return json.loads(Path(result.receipt).read_text(encoding="utf-8"))

    def test_a_bogus_thread_resolves_to_the_newest_project_thread(self):
        self._rollout(OLD, self.project, 300)
        self._rollout(NEW, self.project, 10)
        self._rollout(OTHER, Path(self._tmp.name) / "elsewhere", 1)  # newer, but another project
        result, runner = self._send("handoff-20261003", "ACTIONABLE_DELTA bogus thread")
        self.assertEqual("DISPATCHED", result.reason, result)
        self.assertEqual([NEW], runner.threads())
        self.assertEqual({"given": "handoff-20261003", "used": NEW, "why": "not_uuid"},
                         self._receipt(result)["thread_fallback"])

    def test_a_verified_thread_id_is_kept(self):
        self._rollout(OLD, self.project, 300)
        self._rollout(NEW, self.project, 10)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA verified thread")
        self.assertEqual("DISPATCHED", result.reason, result)
        self.assertEqual([OLD], runner.threads())
        self.assertNotIn("thread_fallback", self._receipt(result))

    def test_a_registered_git_worktree_is_accepted(self):
        # Setup real git worktree metadata
        wt_dir = Path(self._tmp.name) / "worktrees" / "external-wt"
        wt_dir.mkdir(parents=True)
        wt_git = wt_dir / ".git"
        admin_entry = self.project / ".git" / "worktrees" / "external-wt"
        admin_entry.mkdir(parents=True)

        # Main -> worktree gitdir
        (admin_entry / "gitdir").write_text(str(wt_git) + "\n", encoding="utf-8")
        # Worktree -> admin back-pointer
        wt_git.write_text(f"gitdir: {admin_entry}\n", encoding="utf-8")

        self._rollout(WT_THREAD, wt_dir, 5)
        result, runner = self._send(WT_THREAD, "ACTIONABLE_DELTA registered worktree thread")
        self.assertEqual("DISPATCHED", result.reason, result)
        self.assertEqual([WT_THREAD], runner.threads())

    def test_an_unregistered_worktree_fails_closed(self):
        # Worktree folder exists under project or temp, but no .git/worktrees/*/gitdir points to it
        unreg_wt = self.project / ".claude" / "worktrees" / "unregistered"
        unreg_wt.mkdir(parents=True)
        self._rollout(UNREG_THREAD, unreg_wt, 5)
        result, runner = self._send(UNREG_THREAD, "ACTIONABLE_DELTA unregistered worktree")
        self.assertEqual("THREAD_PROJECT_MISMATCH", result.reason)
        self.assertEqual([], runner.calls)

    def test_a_wrong_project_uuid_fails_closed(self):
        self._rollout(NEW, self.project, 10)
        self._rollout(OTHER, Path(self._tmp.name) / "elsewhere", 1)
        result, runner = self._send(OTHER, "ACTIONABLE_DELTA wrong project")
        self.assertEqual("THREAD_PROJECT_MISMATCH", result.reason)
        self.assertEqual([], runner.calls)

    def test_a_folder_name_substring_is_not_the_project(self):
        self._rollout(TWIN, Path(self._tmp.name) / "proj2", 1)
        self._rollout(NEW, self.project, 10)
        result, runner = self._send(TWIN, "ACTIONABLE_DELTA substring twin")
        self.assertEqual("THREAD_PROJECT_MISMATCH", result.reason)
        self.assertEqual([], runner.calls)
        result, runner = self._send("handoff", "ACTIONABLE_DELTA substring twin fallback")
        self.assertEqual([NEW], runner.threads())

    def test_a_uuid_without_rollout_falls_back(self):
        self._rollout(NEW, self.project, 10)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA archived thread")
        self.assertEqual("DISPATCHED", result.reason, result)
        self.assertEqual([NEW], runner.threads())
        self.assertEqual({"given": OLD, "used": NEW, "why": "no_rollout"}, self._receipt(result)["thread_fallback"])

    def test_contradictory_payload_ids_fail_closed(self):
        # id != session_id in session_meta
        bad_meta = {"type": "session_meta", "payload": {"id": OLD, "session_id": NEW, "cwd": str(self.project)}}
        self._rollout(OLD, self.project, 10, meta_dict=bad_meta)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA contradictory ids")
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)

    def test_contradictory_filename_uuid_and_payload_fails_closed(self):
        # Filename has OLD, but payload has NEW
        bad_meta = {"type": "session_meta", "payload": {"id": NEW, "session_id": NEW, "cwd": str(self.project)}}
        self._rollout(OLD, self.project, 10, meta_dict=bad_meta)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA contradictory filename and payload")
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)

    def test_oversize_first_line_fails_closed(self):
        # Line exceeding 256 KiB
        oversized = json.dumps({"type": "session_meta", "payload": {"id": OLD, "session_id": OLD, "cwd": str(self.project), "padding": "x" * (260 * 1024)}}) + "\n"
        self._rollout(OLD, self.project, 10, raw_content=oversized)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA oversize line")
        self.assertEqual("THREAD_UNVERIFIED", result.reason)
        self.assertEqual([], runner.calls)

    def test_only_the_session_meta_line_is_read(self):
        day = self.sessions / "2026" / "10" / "03"
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"rollout-2026-10-03T06-00-00-{OTHER}.jsonl"
        meta = {"type": "session_meta", "payload": {"id": OTHER, "cwd": str(Path(self._tmp.name) / "elsewhere")}}
        later = {"type": "response_item", "payload": {"cwd": str(self.project), "text": str(self.project)}}
        path.write_text(json.dumps(meta) + "\n" + json.dumps(later) + "\n", encoding="utf-8")
        result, runner = self._send(OTHER, "ACTIONABLE_DELTA later line")
        self.assertEqual("THREAD_PROJECT_MISMATCH", result.reason)
        self.assertEqual([], runner.calls)

    def test_a_historical_thread_that_fails_to_send_falls_back_once(self):
        self._rollout(OLD, self.project, 3000)
        self._rollout(NEW, self.project, 10)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA dead thread", _Runner(fail_threads={OLD}))
        self.assertEqual("DISPATCHED", result.reason, result)
        self.assertEqual([OLD, NEW], runner.threads())
        self.assertEqual({"given": OLD, "used": NEW, "why": "send_failed"}, self._receipt(result)["thread_fallback"])

    def test_the_send_failure_fallback_is_not_repeated(self):
        self._rollout(OLD, self.project, 3000)
        self._rollout(NEW, self.project, 10)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA both dead", _Runner(fail_threads={OLD, NEW}))
        self.assertNotEqual("DISPATCHED", result.reason)
        self.assertEqual([OLD, NEW], runner.threads())

    def test_a_failing_newest_thread_is_not_retried_on_itself(self):
        self._rollout(NEW, self.project, 10)
        result, runner = self._send(NEW, "ACTIONABLE_DELTA newest dead", _Runner(fail_threads={NEW}))
        self.assertNotEqual("DISPATCHED", result.reason)
        self.assertEqual([NEW], runner.threads())

    def test_timeout_is_not_retried(self):
        self._rollout(OLD, self.project, 3000)
        self._rollout(NEW, self.project, 10)
        result, runner = self._send(OLD, "ACTIONABLE_DELTA timeout thread", _Runner(timeout_threads={OLD}))
        self.assertNotEqual("DISPATCHED", result.reason)
        self.assertTrue(result.reason.startswith("DELIVERY_FAILED:"))
        self.assertEqual([OLD], runner.threads())  # Exactly one send attempt, no fallback

    def test_no_verified_project_thread_fails_closed(self):
        self._rollout(OTHER, Path(self._tmp.name) / "elsewhere", 1)
        result, runner = self._send("t1", "ACTIONABLE_DELTA no project thread")
        self.assertEqual("NO_VERIFIED_THREAD", result.reason)
        self.assertEqual([], runner.calls)


if __name__ == "__main__":
    unittest.main()
