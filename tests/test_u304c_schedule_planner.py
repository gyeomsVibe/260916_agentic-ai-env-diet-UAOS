"""U304-C: schedule-time model/effort/helper assignment and the live detailed-schedule driver (fixture-only)."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from v7_harness.coord import schedule_planner as sp
from v7_harness.coord.helper_thinking_router import SUB_PROCESS_STAGES, get_official_tool_lineup

REPO = Path(__file__).resolve().parents[1]

CARD_MD = """# Fixture card

## Cards

| Card | Item | Lane | Author (Claude session) | Judge | Allowed files |
|---|---|---|---|---|---|
| U900-A Scheduler estimator design + router | 3 | ARCH_DESIGN→IMPL_CODE | claude `u900a` | antigravity | `a.py`, `b.py`, `c.py`, `d.py`, `tests/t.py` |
| U900-B Typo fix in readme | 1 | IMPL_CODE | antigravity `u900b` | claude | `README.md` |
| U900-E Cross review | all | VERIFY_AUDIT | — | — | read-only |

## After
not a table line
"""


def _budget(now: float | None = None, *, age_s: float = 60.0, rem5: int = 10_000_000, week: int = 100_000_000,
            week_h: float = 50.0, five_h_min: float = 120.0, **per_tool: dict) -> dict:
    """Fixture budget in the U304-D budget_snapshot shape (generous unless overridden)."""
    now = time.time() if now is None else now
    out = {}
    for tool, plan in (("codex", "plus"), ("claude", "pro"), ("antigravity", "ultra")):
        out[tool] = {"remaining_5h_tokens": rem5, "remaining_week_tokens": week,
                     "reset_5h_at": now + five_h_min * 60, "reset_week_at": now + week_h * 3600,
                     "measured_at": now - age_s, "plan": plan, **per_tool.get(tool, {})}
    return out


def _ledger_rows() -> list[dict]:
    rows = []
    for i, tok in enumerate((1000, 2000, 4000, 8000, 16000, 32000, 64000, 128000)):
        rows.append({"work_id": f"U800-L{i}", "input_tokens": tok, "output_tokens": 0, "wall_time_s": 10.0 + i})
    rows.append({"work_id": "U900-L1", "input_tokens": 60000, "output_tokens": 0})
    rows.append({"work_id": "U900-L2", "input_tokens": 70000, "output_tokens": 0})
    rows.append({"work_id": "U777-skip", "input_tokens": 0, "output_tokens": 0})
    return rows


def _make_desk(root: Path) -> Path:
    coord = root / ".coord"
    (coord / "usage").mkdir(parents=True)
    master = {
        "schedule_id": "FIXTURE",
        "keep_me": {"untouched": True},
        "current_phase_id": "U800",
        "phases": [
            {"phase_id": "U800", "title": "old done", "state": "DONE", "owner_tool": "codex", "lane": "IMPL_CODE"},
            {"phase_id": "U850", "title": "Release merge and runtime reinstall", "state": "READY",
             "owner_tool": "antigravity", "lane": "MERGE_RELEASE"},
        ],
    }
    (coord / "master_schedule.json").write_text(json.dumps(master), encoding="utf-8")
    sub = {
        "schema": "uaos-sub-process-schedule-v1",
        "card_sub_schedules": [{
            "phase_id": "U850", "assigned_executor": "antigravity", "assigned_verifier": "claude",
            "sub_processes": [
                {"sub_id": f"U850:{st}", "step_index": i + 1, "stage_name": st, "state": "DONE" if i == 0 else "ACTIVE" if i == 1 else "PLANNED",
                 "depends_on": [f"U850:{SUB_PROCESS_STAGES[i - 1]}"] if i else []}
                for i, st in enumerate(SUB_PROCESS_STAGES)
            ],
        }],
    }
    (coord / "sub_process_schedule.json").write_text(json.dumps(sub), encoding="utf-8")
    (coord / "usage" / "runs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in _ledger_rows()) + "\nnot json\n", encoding="utf-8")
    (root / "card.md").write_text(CARD_MD, encoding="utf-8")
    return root


class EstimatorTests(unittest.TestCase):
    def test_history_bands_are_measured_quartiles_and_family_median(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            h = sp.load_history(desk, [])
            self.assertEqual(h["rows"], 10)  # zero-token row excluded, bad json skipped
            self.assertEqual(h["band_source"], "measured")
            self.assertEqual(h["by_family"]["U900"]["median_tokens"], 65000)
            e1, e2, e3 = h["band_edges"]
            self.assertTrue(e1 < e2 < e3)

    def test_fallback_bands_with_tiny_ledger(self) -> None:
        h = sp.summarize_history([{"family": "U1", "lane": "", "tokens": 5, "wall_s": None}])
        self.assertEqual(h["band_source"], "fallback")
        self.assertEqual(tuple(h["band_edges"]), tuple(sp.THRESHOLDS["size_bands"]["fallback"]))

    def test_flagship_only_when_importance_and_difficulty_high(self) -> None:
        hist = sp.summarize_history([])
        hi = sp.estimate_step(text="Scheduler architecture estimator router design", stage="SP2_MIA_DESIGN_AUDIT",
                              lane="ARCH_DESIGN", card_id="U1", keypoint=True, history=hist)
        self.assertGreaterEqual(hi["importance"], 2)
        self.assertGreaterEqual(hi["complexity"], 2)
        a = sp.assign_step("claude", hi, card_id="U1")
        self.assertEqual((a["tier"], a["main_model"], a["main_effort"]), ("FLAGSHIP", "claude-opus-5-5", "High"))
        for tool, flag in (("codex", "gpt-6-astra"), ("antigravity", "gemini-4-argon")):
            self.assertEqual(sp.assign_step(tool, hi)["main_model"], flag)

        # Same design burden, not important: High effort on the cheaper main, never the flagship.
        lo_imp = sp.estimate_step(text="Scheduler architecture estimator router design", stage="SP2_MIA_DESIGN_AUDIT",
                                  lane="ARCH_DESIGN", card_id="U1", history=hist)
        self.assertLess(lo_imp["importance"], 2)
        b = sp.assign_step("claude", lo_imp)
        self.assertEqual((b["tier"], b["main_model"], b["main_effort"]), ("STANDARD_HIGH", "claude-sonnet-5-5", "High"))

    def test_mechanical_merge_gets_low_effort(self) -> None:
        est = sp.estimate_step(text="merge the PR", stage="SP5_MERGE_AND_RUNTIME", lane="MERGE_RELEASE",
                               history=sp.summarize_history([]))
        a = sp.assign_step("antigravity", est)
        self.assertEqual((a["tier"], a["main_effort"], a["helper_effort"]), ("MECHANICAL", "Low", "Low"))
        self.assertEqual(a["main_effort_param"], {"thinking_level": "low"})

    def test_exhaustion_demotes_flagship(self) -> None:
        est = sp.estimate_step(text="security gate design architecture", stage="SP2_MIA_DESIGN_AUDIT",
                               lane="ARCH_DESIGN", keypoint=True, history=sp.summarize_history([]))
        a = sp.assign_step("codex", est, exhaustion_risk="IMMINENT_EXHAUSTION")
        self.assertEqual((a["tier"], a["main_model"]), ("STANDARD_HIGH", "gpt-6-sol"))
        self.assertIn("demoted", a["rationale"])

    def test_one_helper_per_tool_and_never_high(self) -> None:
        hist = sp.summarize_history([])
        for tool in ("codex", "claude", "antigravity"):
            helpers, efforts = set(), set()
            for stage in SUB_PROCESS_STAGES:
                for kp in (False, True):
                    est = sp.estimate_step(text="design architecture security", stage=stage, keypoint=kp,
                                           files=6, history=hist)
                    a = sp.assign_step(tool, est)
                    helpers.add(a["helper_model"])
                    efforts.add(a["helper_effort"])
                    self.assertIn(a["main_model"], get_official_tool_lineup(tool)["all_reasoning_models"])
                    self.assertTrue(a["rationale"])
                    self.assertIn("router_baseline", a)
            self.assertEqual(helpers, {get_official_tool_lineup(tool)["primary_helper_model"]})
            self.assertNotIn("High", efforts)

    def test_every_threshold_has_a_reason(self) -> None:
        for name, entry in sp.THRESHOLDS.items():
            self.assertIn("why", entry, name)
            self.assertTrue(entry["why"].strip(), name)

    def test_parse_card_table(self) -> None:
        cards = sp.parse_card_table(CARD_MD)
        self.assertEqual([c["card_id"] for c in cards], ["U900-A", "U900-B", "U900-E"])
        a = cards[0]
        self.assertEqual((a["author"], a["judge"], a["lane"], a["files"]), ("claude", "antigravity", "IMPL_CODE", 5))
        self.assertEqual(cards[2]["author"], "")


def _heavy(keypoint: bool) -> dict:
    est = sp.estimate_step(text="Scheduler architecture estimator router design security gate", stage="SP2_MIA_DESIGN_AUDIT",
                           lane="ARCH_DESIGN", card_id="U1", keypoint=keypoint, history=sp.summarize_history([]))
    est["expected_tokens"] = 10_000
    return est


class BudgetTests(unittest.TestCase):
    def test_fail_closed_without_fresh_budget_and_nothing_written(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            paths = [desk / ".coord" / n for n in ("master_schedule.json", "sub_process_schedule.json")]
            before = [p.read_bytes() for p in paths]
            stale = _budget(age_s=sp.THRESHOLDS["budget_freshness_s"]["value"] + 1)
            partial = _budget()
            del partial["codex"]["remaining_week_tokens"]
            week_passed = _budget(week_h=-1)
            for bad in (None, {}, stale, partial, week_passed):
                for fn in (sp.plan_sub, sp.plan_master):
                    with self.assertRaises(sp.BudgetUnavailable):
                        fn(desk, card_file=desk / "card.md", budget=bad)
            self.assertEqual([p.read_bytes() for p in paths], before)
            self.assertFalse(list(desk.glob(".work/backup_*")))

    def test_paced_allowance_spreads_the_weekly_pool(self) -> None:
        now = 1_000_000.0
        b = _budget(now, rem5=50_000, week=1_000_000, week_h=50)  # 10 windows left -> 100k per window
        a = sp.paced_allowance(sp.validate_budget(b, now=now), now=now)
        self.assertEqual(a["claude"]["paced_tokens"], 50_000)  # 5h remaining binds
        self.assertEqual(a["antigravity"]["flagship_tokens_left"], 25_000)
        self.assertEqual(a["codex"]["flagship_tokens_left"], 5_000)
        refilled = _budget(now, rem5=50_000, week=1_000_000, week_h=50, five_h_min=-1)
        a2 = sp.paced_allowance(sp.validate_budget(refilled, now=now), now=now)
        self.assertEqual(a2["claude"]["paced_tokens"], 100_000)  # 5h reset passed: weekly pace only

    def test_heavy_step_prefers_argon_and_20_dollar_flagship_is_keypoint_only(self) -> None:
        now = 1_000_000.0
        allow = sp.paced_allowance(sp.validate_budget(_budget(now), now=now), now=now)
        a = sp.assign_step("claude", _heavy(False), allowance=allow)
        self.assertEqual((a["tool"], a["main_model"], a["main_effort"], a["rerouted_from"]),
                         ("antigravity", "gemini-4-argon", "High", "claude"))
        k = sp.assign_step("codex", _heavy(True), allowance=allow)
        self.assertEqual((k["tool"], k["main_model"]), ("codex", "gpt-6-astra"))
        # The judge is never the rerouted author: no Argon, High effort on the cheaper own main.
        j = sp.assign_step("claude", _heavy(False), allowance=allow, no_reroute=("antigravity",))
        self.assertEqual((j["tool"], j["tier"], j["main_model"], j["main_effort"]),
                         ("claude", "STANDARD_HIGH", "claude-sonnet-5-5", "High"))
        empty = sp.paced_allowance(sp.validate_budget(_budget(now, rem5=0), now=now), now=now)
        e = sp.assign_step("claude", _heavy(True), allowance=empty)
        self.assertEqual((e["tool"], e["tier"]), ("claude", "STANDARD_HIGH"))
        self.assertIn("withheld", e["rationale"])

    def test_argon_grants_five_times_the_20_dollar_flagship(self) -> None:
        now = 1_000_000.0
        b = _budget(now, rem5=100_000, week=1_000_000, week_h=50)  # paced 100k each tool
        allow = sp.paced_allowance(sp.validate_budget(b, now=now), now=now)
        argon = sum(sp.assign_step("antigravity", _heavy(False), allowance=allow)["tier"] == "FLAGSHIP"
                    for _ in range(20))
        opus = sum(sp.assign_step("claude", _heavy(True), allowance=allow)["main_model"] == "claude-opus-5-5"
                   for _ in range(20))
        self.assertEqual((argon, opus), (5, 1))


class DriverTests(unittest.TestCase):
    def test_plan_sub_writes_driver_assignments_and_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            res = sp.plan_sub(desk, card_file=desk / "card.md", keypoints=["U900-A"], budget=_budget())
            self.assertEqual(set(res["cards"]), {"U850", "U900-A", "U900-B"})  # review-only row has no own steps
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(master["keep_me"], {"untouched": True})
            driver = master["sub_schedule_driver"]
            self.assertEqual(driver["schema"], sp.DRIVER_SCHEMA)
            self.assertEqual(driver["keypoints"], ["U900-A"])
            a_steps = {s["stage"]: s for s in driver["cards"]["U900-A"]["steps"]}
            self.assertEqual(a_steps["SP2_MIA_DESIGN_AUDIT"]["assignment"]["tier"], "FLAGSHIP")
            self.assertEqual(a_steps["SP4_INDEPENDENT_VERIFY"]["acting_tool"], "antigravity")
            self.assertEqual(a_steps["SP5_MERGE_AND_RUNTIME"]["acting_tool"], "antigravity")
            b_steps = {s["stage"]: s for s in driver["cards"]["U900-B"]["steps"]}
            self.assertNotEqual(b_steps["SP2_MIA_DESIGN_AUDIT"]["assignment"]["tier"], "FLAGSHIP")
            self.assertEqual(b_steps["SP5_MERGE_AND_RUNTIME"]["acting_tool"], "codex")  # author never self-merges
            self.assertEqual(a_steps["SP1_RESEARCH_DRAFT"]["state"], "READY")
            # imported capacity card keeps its live states
            u850 = {s["stage"]: s["state"] for s in driver["cards"]["U850"]["steps"]}
            self.assertEqual(u850["SP2_MIA_DESIGN_AUDIT"], "ACTIVE")
            sub = json.loads((desk / ".coord" / "sub_process_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(sub["live_driver"]["cards"].keys(), driver["cards"].keys())
            sp850 = sub["card_sub_schedules"][0]["sub_processes"][1]
            self.assertEqual(sp850["u304c_assignment"]["schema"], sp.ASSIGNMENT_SCHEMA)
            self.assertTrue(list((desk / ".work").glob("backup_*/u304c/master_schedule.json")))

            # Keypoints persist across a re-plan without the flag.
            sp.plan_sub(desk, budget=_budget())
            master2 = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(master2["sub_schedule_driver"]["keypoints"], ["U900-A"])

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            before = (desk / ".coord" / "master_schedule.json").read_bytes()
            sp.plan_sub(desk, card_file=desk / "card.md", dry_run=True, budget=_budget())
            self.assertEqual((desk / ".coord" / "master_schedule.json").read_bytes(), before)

    def test_advance_walks_the_dag_and_syncs_master(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            sp.plan_sub(desk, card_file=desk / "card.md", budget=_budget())
            sp.plan_master(desk, card_file=desk / "card.md", budget=_budget())
            r = sp.advance_sub(desk, card="U900-A")  # nothing ACTIVE: start the first ready step
            self.assertEqual((r["changed"], r["state"]), ("U900-A:SP1_RESEARCH_DRAFT", "ACTIVE"))
            r = sp.advance_sub(desk, card="U900-A")
            self.assertEqual(r["state"], "DONE")
            self.assertEqual(r["opened"], "U900-A:SP2_MIA_DESIGN_AUDIT")
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            phase = next(p for p in master["phases"] if p["phase_id"] == "U900-A")
            self.assertEqual((phase["sub_progress"], phase["current_sub_step"]), ("1/5", "U900-A:SP2_MIA_DESIGN_AUDIT"))
            r = sp.advance_sub(desk, card="U900-A", step="SP2_MIA_DESIGN_AUDIT", to="BLOCKED")
            self.assertIsNone(r["opened"])  # SP3 depends on SP2, so it stays closed
            states = {s["sub_id"]: s["state"] for s in r["steps"]}
            self.assertEqual(states["U900-A:SP3_CODE_EXECUTION"], "PLANNED")
            with self.assertRaises(KeyError):
                sp.advance_sub(desk, card="NOPE")
            with self.assertRaises(ValueError):
                sp.advance_sub(desk, card="U900-A", to="WHATEVER")

    def test_plan_master_assigns_open_phases_and_advance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            res = sp.plan_master(desk, card_file=desk / "card.md", keypoints=["U900-A"], budget=_budget())
            self.assertEqual(res["added_phases"], ["U900-A", "U900-B", "U900-E"])
            ids = [p["phase_id"] for p in res["phases"]]
            self.assertNotIn("U800", ids)  # DONE phases are not re-planned
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            u850 = next(p for p in master["phases"] if p["phase_id"] == "U850")
            self.assertEqual(u850["model_assignment"]["tool"], "antigravity")
            self.assertNotIn("model_assignment", master["phases"][0])
            r = sp.advance_master(desk, phase="U850")
            self.assertEqual((r["from"], r["to"]), ("READY", "ACTIVE"))
            master = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(master["current_phase_id"], "U850")

    def test_parallel_advances_lose_no_update(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            sp.plan_sub(desk, card_file=desk / "card.md", budget=_budget())
            cards = ["U900-A", "U900-B"]

            def walk(card: str) -> None:
                for _ in range(1 + 2 * len(SUB_PROCESS_STAGES)):
                    try:
                        sp.advance_sub(desk, card=card)
                    except KeyError:
                        return

            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(walk, cards))
            driver = json.loads((desk / ".coord" / "master_schedule.json").read_text(encoding="utf-8"))["sub_schedule_driver"]
            for card in cards:
                self.assertEqual({s["state"] for s in driver["cards"][card]["steps"]}, {"DONE"}, card)
            self.assertFalse((desk / ".coord" / "schedule_planner.lock").exists())


class CliTests(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, "-X", "utf8", "-m", "v7_harness.cli", "coord", "schedule", *args],
                              cwd=REPO, capture_output=True, text=True, encoding="utf-8", timeout=120)

    def test_cli_plan_show_advance(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            desk = _make_desk(Path(td))
            bf = desk / "budget.json"
            bf.write_text(json.dumps(_budget(age_s=10_000)), encoding="utf-8")
            before = (desk / ".coord" / "master_schedule.json").read_bytes()
            p = self._run("plan", "--sub", "--project", str(desk), "--card-file", str(desk / "card.md"),
                          "--budget-file", str(bf))
            self.assertEqual(p.returncode, 2)  # stale measured budget: fail closed
            self.assertIn("old", json.loads(p.stdout)["error"])
            self.assertEqual((desk / ".coord" / "master_schedule.json").read_bytes(), before)
            bf.write_text(json.dumps(_budget()), encoding="utf-8")
            p = self._run("plan", "--sub", "--project", str(desk), "--card-file", str(desk / "card.md"),
                          "--budget-file", str(bf))
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn("antigravity", json.loads(p.stdout)["budget"])
            self.assertIn("U900-A", json.loads(p.stdout)["cards"])
            p = self._run("advance", "--sub", "--project", str(desk), "--card", "U900-B")
            self.assertEqual(p.returncode, 0, p.stderr)
            p = self._run("show", "--sub", "--project", str(desk))
            states = [s["state"] for s in json.loads(p.stdout)["cards"]["U900-B"]]
            self.assertEqual(states[0], "ACTIVE")
            p = self._run("advance", "--sub", "--project", str(desk))
            self.assertEqual(p.returncode, 2)
            p = self._run("plan", "--master", "--project", str(desk), "--dry-run", "--budget-file", str(bf))
            self.assertEqual(p.returncode, 0, p.stderr)
            p = self._run("show", "--master", "--project", str(desk))
            self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
