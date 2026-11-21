"""U331 gates: companion cards + card navigation map (no network, no paid calls, temp dirs only)."""
from __future__ import annotations

import json
import multiprocessing
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from v7_harness.coord import card_nav, presence

NOW = 1_800_000_000.0


def _active(project: Path, *tools: str, now: float = NOW) -> None:
    for tool in tools:
        presence.mark(project, tool, "ACTIVE", now=now, ttl_s=600)


def _primary(project: Path, cid: str = "U329", nature: str = "implementation", now: float = NOW, **kw) -> None:
    card_nav.write_card(project, cid, "claude", title="Council", nature=nature, lane="IMPL_CODE", state="RUNNING",
                        stage=9, progress=40, now=now, **kw)


def _nav_worker(args: tuple[str, str, int]) -> None:
    project, tool, n = args
    for i in range(n):
        card_nav.write_card(Path(project), f"P{tool[:2].upper()}", tool, state="RUNNING", progress=i, title="x",
                            nature="implementation")


def _alloc_worker(args: tuple[str, str, str]) -> str:
    project, tool, requested = args
    try:
        return card_nav.allocate_card_id(Path(project), owner=tool, requested=requested, branch=f"{tool}/b")
    except card_nav.DuplicateCardId:
        return "DUP"


class CompanionNavTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.p = Path(self._tmp.name)

    def test_companion_created_per_active_tool_with_roles(self) -> None:
        _active(self.p, "codex", "claude", "antigravity")
        _primary(self.p)
        opened = card_nav.open_companions(self.p, "U329", now=NOW)
        ids = {c["id"] for c in opened}
        self.assertEqual({"U329.codex", "U329.agy"}, ids)
        lanes = {c["lane"] for c in opened}
        self.assertEqual({"VERIFY_AUDIT", "ARCH_DESIGN"}, lanes)
        for c in opened:
            self.assertEqual([], c["owned_files"])  # never edits primary files
            self.assertEqual("U329", c["primary"])
        self.assertEqual(["U329.agy", "U329.codex"], card_nav.read_card(self.p, "U329")["companions"])
        self.assertEqual([], card_nav.open_companions(self.p, "U329", now=NOW))  # idempotent
        self.assertEqual([], card_nav.open_companions(self.p, "U329.agy", now=NOW))  # no companion of a companion

    def test_cap_three_then_queue_then_promote(self) -> None:
        _active(self.p, "claude", "antigravity")
        for n in range(10):
            _primary(self.p, f"U{400 + n}")
            card_nav.open_companions(self.p, f"U{400 + n}", now=NOW)
        agy = [c for c in card_nav.list_cards(self.p) if (c.get("owner") or {}).get("tool") == "antigravity"]
        self.assertEqual(3, sum(c["state"] == "READY" for c in agy))
        self.assertEqual(7, sum(c["state"] == "QUEUED" for c in agy))
        card_nav.close_companions(self.p, "U400", "primary done", now=NOW)
        agy = [c for c in card_nav.list_cards(self.p) if (c.get("owner") or {}).get("tool") == "antigravity"]
        self.assertEqual(3, sum(c["state"] == "READY" for c in agy))
        self.assertEqual(6, sum(c["state"] == "QUEUED" for c in agy))

    def test_no_companion_for_stale_limited_absent_tools(self) -> None:
        presence.mark(self.p, "codex", "ACTIVE", now=NOW - 300, ttl_s=900)  # heartbeat 300 s old -> stale
        presence.mark(self.p, "antigravity", "LIMITED", now=NOW, ttl_s=600)
        _primary(self.p)
        self.assertEqual([], card_nav.open_companions(self.p, "U329", now=NOW))
        # a tool with no presence file at all is UNKNOWN -> also none
        self.assertEqual([], [c for c in card_nav.list_cards(self.p) if c.get("nature") == "companion"])

    def test_auto_close_with_result_and_refresh_on_replan(self) -> None:
        _active(self.p, "codex", "antigravity")
        _primary(self.p)
        card_nav.open_companions(self.p, "U329", now=NOW)
        touched = card_nav.refresh_companions(self.p, "U329", now=NOW + 5, next_action="re-audit new plan")
        self.assertEqual(2, len(touched))
        c = card_nav.read_card(self.p, "U329.agy")
        self.assertEqual(1, c["plan_rev"])
        self.assertEqual("re-audit new plan", c["next_action"]["agy"])
        closed = card_nav.finish_primary(self.p, "U329", "claude", "merged\nPR ok", now=NOW + 9)
        self.assertEqual(2, len(closed))
        done = card_nav.read_card(self.p, "U329.codex")
        self.assertEqual("DONE", done["state"])
        self.assertEqual("merged PR ok", done["result"])  # one line
        self.assertEqual("DONE", card_nav.read_card(self.p, "U329")["state"])

    def test_owner_only_write(self) -> None:
        _primary(self.p)
        with self.assertRaises(card_nav.NavRejected):
            card_nav.write_card(self.p, "U329", "codex", state="DONE")

    def test_parallel_three_process_nav_updates_no_lost_lines(self) -> None:
        n = 25
        tools = ("claude", "codex", "antigravity")
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(3) as pool:
            pool.map(_nav_worker, [(str(self.p), t, n) for t in tools])
        for t in tools:
            card = card_nav.read_card(self.p, f"P{t[:2].upper()}")
            self.assertEqual(n - 1, card["progress"])  # last write won, file never torn
        lines = (card_nav.nav_dir(self.p) / "events.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(3 * n, len(lines))
        for line in lines:
            json.loads(line)
        doc = card_nav.regenerate_map(self.p)
        self.assertEqual(3, len(doc["cards"]))
        self.assertTrue((card_nav.nav_dir(self.p) / "card_map.json").is_file())

    def test_stale_signal_is_unknown_not_actionable(self) -> None:
        _primary(self.p, now=NOW)
        card = card_nav.read_card(self.p, "U329")
        self.assertEqual("RUNNING", card_nav.effective_state(card, NOW + 60))
        self.assertEqual("UNKNOWN", card_nav.effective_state(card, NOW + 61))
        self.assertFalse(card_nav.is_actionable(card, NOW + 61))
        doc = card_nav.regenerate_map(self.p, now=NOW + 61)
        self.assertEqual("UNKNOWN", doc["cards"][0]["effective_state"])
        self.assertFalse(doc["cards"][0]["actionable"])
        lines, _ = card_nav.hook_lines(self.p, "claude", now=NOW + 61)
        self.assertIn("UNKNOWN", lines[0])
        self.assertIn("not actionable", lines[0])

    def test_concurrent_id_allocation_distinct_and_duplicate_rejected(self) -> None:
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(2) as pool:
            got = pool.map(_alloc_worker, [(str(self.p), "claude", ""), (str(self.p), "antigravity", "")])
        self.assertEqual(2, len(set(got)))
        self.assertNotIn("DUP", got)
        # evidence case: two tools both claim U327 -> the second is rejected
        with ctx.Pool(2) as pool:
            got = pool.map(_alloc_worker, [(str(self.p), "claude", "U327"), (str(self.p), "antigravity", "U327")])
        self.assertEqual(["DUP", "U327"], sorted(got))
        # same owner+branch asking again is idempotent
        self.assertEqual("U327", card_nav.allocate_card_id(self.p, owner=got[0] == "DUP" and "antigravity" or "claude",
                                                           requested="U327", branch=("antigravity" if got[0] == "DUP" else "claude") + "/b"))

    def test_allocation_floor_from_plan_md(self) -> None:
        (self.p / ".coord").mkdir()
        (self.p / ".coord" / "PLAN.md").write_text("| U326 | x |\n| U330 | y |", encoding="utf-8")
        self.assertEqual("U331", card_nav.allocate_card_id(self.p, owner="claude"))
        self.assertEqual("U332", card_nav.allocate_card_id(self.p, owner="codex"))

    def test_file_and_scope_overlap_warning(self) -> None:
        card_nav.write_card(self.p, "U1", "claude", nature="implementation", owned_files=["a.py", "b.py"], scope="router", state="RUNNING", now=NOW)
        card_nav.write_card(self.p, "U2", "antigravity", nature="implementation", owned_files=["b.py"], scope="router", state="RUNNING", now=NOW)
        card_nav.write_card(self.p, "U3", "codex", nature="design", owned_files=["c.py"], scope="router", state="RUNNING", now=NOW)
        kinds = {(w["kind"], tuple(w["cards"])) for w in card_nav.regenerate_map(self.p, now=NOW)["overlaps"]}
        self.assertIn(("FILE_OVERLAP", ("U1", "U2")), kinds)
        self.assertIn(("NATURE_SCOPE_OVERLAP", ("U1", "U2")), kinds)
        self.assertEqual(2, len(kinds))  # U3 differs in nature and shares no file

    def test_companion_never_overlaps_its_primary(self) -> None:
        _active(self.p, "antigravity")
        _primary(self.p, owned_files=["x.py"], scope="s")
        card_nav.open_companions(self.p, "U329", now=NOW)
        self.assertEqual([], card_nav.regenerate_map(self.p, now=NOW)["overlaps"])

    def test_hook_line_format_per_tool_and_delta_only(self) -> None:
        _active(self.p, "claude", "antigravity")
        _primary(self.p)
        card_nav.open_companions(self.p, "U329", now=NOW)
        lines, seen = card_nav.hook_lines(self.p, "agy", now=NOW)
        self.assertEqual(1, len(lines))
        self.assertTrue(lines[0].startswith("nav: U329 RUNNING(claude) -> you(agy) U329.agy: "), lines[0])
        self.assertTrue(lines[0].endswith(", due 120s"), lines[0])
        # unchanged -> no repeat, even though the due countdown moved
        again, _ = card_nav.hook_lines(self.p, "agy", now=NOW + 10, seen=seen)
        self.assertEqual([], again)
        # the owner sees its own card, not the companion
        own, _ = card_nav.hook_lines(self.p, "claude", now=NOW)
        self.assertEqual(1, len(own))
        self.assertTrue(own[0].startswith("nav: U329 RUNNING(you)"), own[0])
        # a tool with no stake gets nothing
        self.assertEqual([], card_nav.hook_lines(self.p, "codex", now=NOW)[0])

    def test_desk_delta_carries_nav_line(self) -> None:
        from v7_harness.coord import desk_delta

        _active(self.p, "claude", "antigravity", now=time.time())
        _primary(self.p, now=time.time())
        card_nav.open_companions(self.p, "U329")
        text = desk_delta.delta_text(self.p, "antigravity")
        self.assertIn("nav: U329 RUNNING(claude) -> you(agy) U329.agy", text)
        self.assertNotIn("nav: U329", desk_delta.delta_text(self.p, "antigravity"))  # shown once

    def test_cards_over_the_line_cap_are_not_marked_seen(self) -> None:
        """AGY review: a card cut by MAX_HOOK_LINES must fire on the next prompt, not vanish."""
        for n in range(card_nav.MAX_HOOK_LINES + 2):
            _primary(self.p, f"U4{n:02d}", now=NOW)
        lines, seen = card_nav.hook_lines(self.p, "claude", now=NOW)
        self.assertEqual(card_nav.MAX_HOOK_LINES, len(lines))
        self.assertEqual(card_nav.MAX_HOOK_LINES, len(seen))
        more, seen2 = card_nav.hook_lines(self.p, "claude", now=NOW, seen=seen)
        self.assertEqual(2, len(more))
        self.assertEqual(card_nav.MAX_HOOK_LINES + 2, len(seen2))

    def test_nav_delta_is_not_lost_when_the_hook_is_full(self) -> None:
        """AGY review: a delta cut by MAX_LINES must not advance the cursor, or the notice is gone for good."""
        from v7_harness.coord import desk_delta

        _active(self.p, "claude", "antigravity", now=time.time())
        _primary(self.p, now=time.time())
        card_nav.open_companions(self.p, "U329")
        with mock.patch.object(desk_delta, "MAX_LINES", 0):
            self.assertNotIn("nav: U329", desk_delta.delta_text(self.p, "antigravity"))
        self.assertIn("nav: U329 RUNNING(claude) -> you(agy) U329.agy", desk_delta.delta_text(self.p, "antigravity"))


class ProvisioningCompanionErrors(unittest.TestCase):
    """AGY review: expected failures are recorded; programming errors are not swallowed into ok:True."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Path(self._tmp.name) / "proj"
        (self.p / ".coord").mkdir(parents=True)
        (self.p / ".coord" / "PLAN.md").write_text("# plan", encoding="utf-8")
        self._env = mock.patch.dict("os.environ", {presence.CODEX_SESSIONS_ENV: self._tmp.name})
        self._env.start()
        for tool in ("claude", "antigravity"):
            presence.mark(self.p, tool, "ACTIVE", ttl_s=3600)
        presence.mark(self.p, "codex", "LIMITED", ttl_s=3600, lease=True, lease_source="manual")
        _primary(self.p, now=time.time())

    def tearDown(self) -> None:
        self._env.stop()
        self._tmp.cleanup()

    def test_oserror_is_recorded_not_swallowed(self) -> None:
        from v7_harness.coord import process_lanes

        with mock.patch.object(card_nav, "open_companions", side_effect=OSError("disk")):
            res = process_lanes.open_or_reuse_card_parallel_windows(self.p, ["U329"])
        self.assertTrue(res["ok"])
        self.assertIn("OSError", res["cards"]["U329"]["companions_error"])

    def test_card_id_rejected_by_the_nav_map_is_recorded_not_raised(self) -> None:
        from v7_harness.coord import process_lanes

        with mock.patch.object(card_nav, "read_card", side_effect=card_nav.NavRejected("bad id")):
            res = process_lanes.open_or_reuse_card_parallel_windows(self.p, ["U329"])
        self.assertTrue(res["ok"])
        self.assertIn("NavRejected", res["cards"]["U329"]["companions_error"])

    def test_programming_error_propagates(self) -> None:
        from v7_harness.coord import process_lanes

        with mock.patch.object(card_nav, "open_companions", side_effect=NameError("bug")):
            with self.assertRaises(NameError):
                process_lanes.open_or_reuse_card_parallel_windows(self.p, ["U329"])


if __name__ == "__main__":
    unittest.main()
