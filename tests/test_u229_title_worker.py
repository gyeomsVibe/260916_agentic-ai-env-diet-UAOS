"""Supplementary native-title adapter probes; existing acceptance stays unchanged."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_title as dt
from v7_harness.coord import user_window as uw


class TitleWorker(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        (self.p / ".coord").mkdir()
        (self.p / ".coord/PLAN.md").write_text("# Temp\n", encoding="utf-8")
        self.prefix = "[261024-1]"
        uw.claim(self.p, "claude", "desk", current=self.prefix)

    def event(self, **values):
        return dict(hook_event_name="UserPromptSubmit", session_id="desk", **values)

    def check(self, **values):
        return dt.reconcile_title(self.p, "claude", "desk", self.event(**values))

    def schedule(self, topic="창구·호출 개선"):
        phases = [{"phase_id": "U229", "state": "ACTIVE"}]
        digest = hashlib.sha256(json.dumps(phases, sort_keys=True, separators=(",", ":"),
                                          ensure_ascii=False).encode()).hexdigest()
        data = {"phases": phases, "desk_title": {"topic": topic, "agreed_by": sorted(dt.TOOLS),
                                                 "schedule_sha256": digest}}
        self.write_schedule(data)
        return data

    def write_schedule(self, data):
        (self.p / ".coord/master_schedule.json").write_text(json.dumps(data), encoding="utf-8")

    def test_missing_consensus_preserves_accepted_suffix(self):
        self.schedule()
        desired = self.check(session_title="old")["title"]
        self.write_schedule({})
        self.assertEqual(desired, self.check(session_title="old")["title"])
        self.assertEqual("CONVERGED", self.check(session_title=desired)["state"])

    def test_relay_and_subagent_do_not_mutate_registry(self):
        registry = self.p / ".coord/presence/user_windows.json"
        before = registry.read_bytes()
        self.assertIsNone(self.check(prompt="[UAOS relay id=x digest=y]")["title"])
        self.assertIsNone(self.check(agent_type="worker")["title"])
        self.assertEqual(before, registry.read_bytes())

    def test_malformed_voters_fail_closed(self):
        data = self.schedule()
        data["desk_title"]["agreed_by"] = [{}, "claude", "antigravity"]
        self.write_schedule(data)
        self.assertEqual(self.prefix, self.check(session_title="old")["title"])

    def test_control_and_bracket_topics_are_rejected(self):
        for topic in ("a\nb", "a\u200bb", "[우회]", " 앞뒤 ", "x" * 17):
            with self.subTest(topic=repr(topic)):
                self.schedule(topic)
                self.assertIsNone(dt._schedule_topic(self.p))

    def test_current_suffix_is_not_stripped_without_consensus(self):
        title = self.prefix + " 이전 합의"
        self.assertEqual("CONVERGED", self.check(session_title=title)["state"])

    def test_one_migration_never_reopens_blocked_budget(self):
        for _ in range(12):
            self.check(session_title="old")
        state = json.loads((self.p / ".coord/presence/user_windows.json").read_text(encoding="utf-8"))
        entry = state["claude"][0]
        self.assertEqual(3, entry["native_emits"])
        self.assertEqual("BLOCKED", entry["title_state"])
        self.assertEqual(dt.ADAPTER_VERSION, entry["adapter_version"])

    def hook(self, event, say="none", post=False):
        cmd = [sys.executable, "-B", "-m", "v7_harness.cli", "coord", "presence", "--project", str(self.p),
               "--tool", "claude", "--state", "ACTIVE", "--from-hook", "--if-uaos", "--say", say, "--delta"]
        if post:
            cmd.append("--post-tool")
        env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", UAOS_CODEX_SESSIONS=str(self.p / "sessions"))
        env.pop("UAOS_WORKER", None)
        run = subprocess.run(cmd, input=json.dumps(dict(event, cwd=str(self.p))), cwd=Path(__file__).parents[1],
                             env=env, text=True, encoding="utf-8", capture_output=True, timeout=20)
        self.assertEqual(0, run.returncode, run.stderr)
        values = []
        for line in run.stdout.splitlines():
            try:
                values.append(json.loads(line))
            except ValueError:
                pass
        return values, run.stdout

    def test_actual_hook_none_emits_native_json_without_model_instruction(self):
        values, stdout = self.hook(self.event(session_title="old"))
        native = [v["hookSpecificOutput"] for v in values if v.get("hookSpecificOutput", {}).get("sessionTitle")]
        self.assertEqual(self.prefix, native[0]["sessionTitle"])
        self.assertEqual("UserPromptSubmit", native[0]["hookEventName"])
        self.assertNotIn("set_session_title", stdout)

    def test_actual_hook_sessionstart_accepts_native_control(self):
        event = dict(hook_event_name="SessionStart", session_id="desk", source="resume", session_title="old")
        values, _ = self.hook(event, say="brief")
        self.assertTrue(any(v.get("hookSpecificOutput", {}).get("sessionTitle") == self.prefix for v in values))

    def test_actual_posttool_hook_never_emits_title(self):
        event = dict(hook_event_name="PostToolUse", session_id="desk", session_title="old")
        values, _ = self.hook(event, post=True)
        self.assertFalse(any("sessionTitle" in v.get("hookSpecificOutput", {}) for v in values))

    def test_real_agy_payload_without_event_name_reconciles_only_existing_desk(self):
        uw.claim(self.p, "antigravity", "agy", current=self.prefix)
        event = dict(artifactDirectoryPath="artifacts", conversationId="agy", initialNumSteps=1,
                     invocationNum=0, modelName="native", transcriptPath="transcript", workspacePaths=[str(self.p)])
        with mock.patch.object(uw, "_current_title", return_value="old"), \
                mock.patch.object(uw, "_instruction", return_value="native rename"):
            got = dt.reconcile_title(self.p, "antigravity", "agy", event)
        self.assertEqual(self.prefix, got["title"])
        self.assertIsNone(dt.reconcile_title(self.p, "antigravity", "foreign", event)["title"])

    def test_handoff_race_inside_registry_lock_refuses_emit(self):
        with mock.patch.object(uw, "desk_role", side_effect=["PRIMARY", "HANDED_OFF"]):
            self.assertIsNone(self.check(session_title="old")["title"])

    def test_parallel_native_attempts_share_one_bounded_budget(self):
        from threading import Barrier

        barrier = Barrier(8)

        def run(_):
            barrier.wait(timeout=5)
            return self.check(session_title="old")

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(run, range(8)))
        self.assertEqual(3, sum(bool(result["title"]) for result in results))
