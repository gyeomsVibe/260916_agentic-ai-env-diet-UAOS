"""U350: desk director state (`.coord/presence/director_state.json`) under Charter Article 18.

C27: a `(?:보좌|AS)-` title never becomes PRIMARY_DIRECTOR and its authority is 0.
C28: cleanup respects a live QUIET_LOCK and fails closed when the `.work/backup_<date>/` copy fails.
C29: an aide launch carries UAOS_WORKER=1, max_turns <= 6, no paid 429 retry, cost UNMEASURED.
Art. 18: subcommanders act only in their own tool domain; upward rollups are at most 15 lines.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import desk_director as dd


class _Project(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class AssistantTitleTest(_Project):
    def test_assistant_title_regex(self) -> None:
        for title in ("[261122-1] 보좌-레이더", "AS-radar watch", "[AS-1] aide"):
            self.assertTrue(dd.is_assistant_title(title), title)
        for title in ("[261122-1] UAOS 지휘", "BASIS review", "as-lowercase", "보좌 without dash"):
            self.assertFalse(dd.is_assistant_title(title), title)
        self.assertTrue(dd.is_assistant_title("ALIAS-room"))  # literal regex: a false positive fails closed

    def test_assistant_cannot_claim_primary(self) -> None:
        result = dd.claim_primary(self.project, tool="claude", title="[261122-2] 보좌-감시", now=1.0)
        self.assertFalse(result["ok"])
        self.assertEqual("ASSISTANT_TITLE", result["reason"])
        self.assertIsNone(dd.load_state(self.project).get("primary"))
        self.assertFalse((self.project / dd.STATE_REL).exists())

    def test_assistant_cannot_replace_existing_primary(self) -> None:
        self.assertTrue(dd.claim_primary(self.project, tool="codex", title="[261122-1] 지휘", now=1.0)["ok"])
        self.assertFalse(dd.claim_primary(self.project, tool="claude", title="AS-takeover", now=2.0)["ok"])
        self.assertEqual("codex", dd.load_state(self.project)["primary"]["tool"])

    def test_assistant_authority_is_zero(self) -> None:
        self.assertEqual(0, dd.authority_of("보좌-x", role=dd.PRIMARY))
        self.assertEqual(0, dd.authority_of("AS-x", role=dd.SUBCOMMANDER))
        self.assertGreater(dd.authority_of("[261122-1] 지휘", role=dd.PRIMARY), 0)

    def test_peer_authority_zero_until_user_input(self) -> None:
        dd.claim_primary(self.project, tool="codex", title="[261122-1] 지휘", now=1.0)
        aide = dd.register_aide(self.project, title="보좌-레이더", tool="claude", now=2.0)
        self.assertTrue(aide["ok"])
        state = dd.load_state(self.project)
        self.assertEqual(0, state["aides"]["보좌-레이더"]["authority"])
        self.assertEqual(dd.AIDE, state["aides"]["보좌-레이더"]["role"])

    def test_aide_requires_assistant_title(self) -> None:
        self.assertFalse(dd.register_aide(self.project, title="[261122-3] 일반", tool="claude", now=1.0)["ok"])

    def test_primary_claim_writes_state(self) -> None:
        result = dd.claim_primary(self.project, tool="codex", title="[261122-1] 지휘", now=5.0)
        self.assertTrue(result["ok"])
        doc = json.loads((self.project / dd.STATE_REL).read_text(encoding="utf-8"))
        self.assertEqual(dd.PRIMARY, doc["primary"]["role"])
        self.assertEqual(5.0, doc["primary"]["at"])


class DomainAndRollupTest(_Project):
    def test_domain_scope_enforced(self) -> None:
        self.assertTrue(dd.can_act(actor_tool="claude", role=dd.SUBCOMMANDER, target_domain="claude"))
        self.assertFalse(dd.can_act(actor_tool="claude", role=dd.SUBCOMMANDER, target_domain="codex"))
        self.assertTrue(dd.can_act(actor_tool="codex", role=dd.PRIMARY, target_domain="antigravity"))
        self.assertFalse(dd.can_act(actor_tool="claude", role=dd.AIDE, target_domain="claude"))

    def test_rollup_max_15_lines(self) -> None:
        text = dd.rollup_summary([f"line {i}" for i in range(40)])
        lines = text.splitlines()
        self.assertEqual(dd.ROLLUP_MAX_LINES, 15)
        self.assertEqual(15, len(lines))
        self.assertIn("+26", lines[-1])
        self.assertEqual("line 0", lines[0])

    def test_rollup_short_is_unchanged_and_multiline_split(self) -> None:
        self.assertEqual("a\nb", dd.rollup_summary(["a", "b"]))
        self.assertEqual(15, len(dd.rollup_summary(["x\ny"] * 10).splitlines()))
        self.assertEqual("", dd.rollup_summary([]))


class QuietLockAndBackupTest(_Project):
    def _stale_aide(self) -> None:
        dd.claim_primary(self.project, tool="codex", title="[261122-1] 지휘", now=1.0)
        dd.register_aide(self.project, title="AS-old", tool="claude", now=1.0)

    def _quiet_lock(self, pid: int, started: float) -> None:
        path = self.project / ".work" / "QUIET_LOCK"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": pid, "started_at": started}), encoding="utf-8")

    def test_live_quiet_lock_blocks_cleanup(self) -> None:
        self._stale_aide()
        now = time.time()
        self._quiet_lock(os.getpid(), now - 10)
        self.assertTrue(dd.quiet_lock_live(self.project, now=now))
        result = dd.cleanup_stale(self.project, max_age_s=1.0, now=now)
        self.assertFalse(result["ok"])
        self.assertEqual("QUIET_LOCK_LIVE", result["reason"])
        self.assertIn("AS-old", dd.load_state(self.project)["aides"])

    def test_old_or_dead_quiet_lock_is_not_live(self) -> None:
        now = time.time()
        self._quiet_lock(os.getpid(), now - 3601)
        self.assertFalse(dd.quiet_lock_live(self.project, now=now))
        self._quiet_lock(0, now)
        self.assertFalse(dd.quiet_lock_live(self.project, now=now))
        self.assertFalse(dd.quiet_lock_live(Path(self.project / "nowhere"), now=now))

    def test_cleanup_backs_up_then_removes_stale(self) -> None:
        self._stale_aide()
        result = dd.cleanup_stale(self.project, max_age_s=10.0, now=100.0, date="261122")
        self.assertTrue(result["ok"])
        self.assertEqual(["AS-old"], result["removed"])
        backup = self.project / ".work" / "backup_261122" / "director_state.json"
        self.assertIn("AS-old", json.loads(backup.read_text(encoding="utf-8"))["aides"])
        self.assertNotIn("AS-old", dd.load_state(self.project)["aides"])

    def test_backup_failure_fails_closed(self) -> None:
        self._stale_aide()
        before = (self.project / dd.STATE_REL).read_bytes()
        with mock.patch.object(dd.shutil, "copy2", side_effect=OSError("disk full")):
            result = dd.cleanup_stale(self.project, max_age_s=10.0, now=100.0, date="261122")
        self.assertFalse(result["ok"])
        self.assertEqual("BACKUP_FAILED", result["reason"])
        self.assertEqual(before, (self.project / dd.STATE_REL).read_bytes())

    def test_nothing_stale_needs_no_backup(self) -> None:
        self._stale_aide()
        result = dd.cleanup_stale(self.project, max_age_s=1000.0, now=100.0, date="261122")
        self.assertTrue(result["ok"])
        self.assertEqual([], result["removed"])
        self.assertFalse((self.project / ".work" / "backup_261122").exists())


class AideLaunchTest(unittest.TestCase):
    def test_launch_spec_barriers(self) -> None:
        spec = dd.aide_launch_spec()
        self.assertEqual("1", spec["env"]["UAOS_WORKER"])
        self.assertLessEqual(spec["max_turns"], 6)
        self.assertFalse(spec["retry_on_429"])
        self.assertEqual("UNMEASURED", spec["cost"])

    def test_max_turns_over_cap_rejected(self) -> None:
        with self.assertRaises(ValueError):
            dd.aide_launch_spec(max_turns=7)
        with self.assertRaises(ValueError):
            dd.aide_launch_spec(max_turns=0)
        self.assertEqual(3, dd.aide_launch_spec(max_turns=3)["max_turns"])

    def test_rate_limit_falls_back_without_retry(self) -> None:
        decision = dd.on_rate_limit(429, attempt=1)
        self.assertEqual("FALLBACK_TIER_0A", decision["action"])
        self.assertFalse(decision["retry"])
        self.assertEqual("UNMEASURED", decision["cost"])
        self.assertFalse(dd.on_rate_limit(429, attempt=5)["retry"])
        self.assertEqual("CONTINUE", dd.on_rate_limit(200, attempt=1)["action"])


if __name__ == "__main__":
    unittest.main()
