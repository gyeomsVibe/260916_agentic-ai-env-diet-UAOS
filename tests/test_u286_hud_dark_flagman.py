"""U286: the HUD is readable (dark theme, larger text) and shows whether Flagman is really alive.

Receipt (2026-10-29, 윤겸스): the light-themed HUD used 11px text, and it showed Flagman as ACTIVE
from a stale `state` field while the daemon was dead. Liveness comes from the age of the
heartbeat file `.coord/presence/flagman.json` (pulse every 30 s; over 90 s = three missed pulses).
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord.capacity_planner import (
    _flagman_process_info,
    flagman_liveness,
    render_contextual_hud_widget,
    render_html_dashboard,
)


class FlagmanLiveness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.beat = self.root / ".coord" / "presence" / "flagman.json"

    def write(self, text: str) -> None:
        self.beat.parent.mkdir(parents=True, exist_ok=True)
        self.beat.write_text(text, encoding="utf-8")  # always a fresh mtime: mtime must not decide anything

    def beat_doc(self, age_s: float, now: float, state: str = "ACTIVE", pid: int = 4242) -> None:
        self.write(json.dumps({"schema": "uaos-independent-flagman-entity-v3", "state": state,
                               "updated_at": str(now - age_s), "pid": str(pid)}))

    @staticmethod
    def running(created: float, exe: str = r"C:\Python314\pythonw.exe"):
        return lambda pid: {"alive": True, "created": created, "exe": exe}

    def test_fresh_pulse_and_running_python_pid_is_live(self):
        now = time.time()
        self.beat_doc(10, now)
        live = flagman_liveness(self.root, now, probe=self.running(now - 600))
        self.assertEqual("LIVE", live["state"])
        self.assertEqual(10, live["age_s"])

    def test_stale_pulse_is_stopped_despite_active_state(self):
        now = time.time()
        self.beat_doc(91, now)
        self.assertEqual("STOPPED", flagman_liveness(self.root, now, probe=self.running(now - 600))["state"])

    def test_missing_heartbeat_is_missing(self):
        self.assertEqual("MISSING", flagman_liveness(self.root, time.time())["state"])

    # Codex black-box probes (2026-10-29): every one of these read LIVE from the old mtime-only rule.
    def test_fresh_non_json_file_is_unknown_not_live(self):
        self.write("not-json")
        self.assertEqual("UNKNOWN", flagman_liveness(self.root, time.time())["state"])

    def test_fresh_self_reported_stopped_is_stopped(self):
        now = time.time()
        self.beat_doc(1, now, state="STOPPED", pid=2147483000)
        res = flagman_liveness(self.root, now, probe=self.running(now - 600))
        self.assertEqual(("STOPPED", "SELF_REPORTED_STOPPED"), (res["state"], res["reason"]))

    def test_fresh_active_pulse_with_dead_pid_is_stopped(self):
        now = time.time()
        self.beat_doc(1, now)
        res = flagman_liveness(self.root, now, probe=lambda pid: {"alive": False, "created": None, "exe": ""})
        self.assertEqual(("STOPPED", "PID_NOT_RUNNING"), (res["state"], res["reason"]))

    def test_pid_reused_by_a_newer_process_is_stopped(self):
        now = time.time()
        self.beat_doc(30, now)
        self.assertEqual("PID_REUSED_AFTER_PULSE", flagman_liveness(self.root, now, probe=self.running(now - 5))["reason"])

    def test_pid_owned_by_non_python_process_is_stopped(self):
        now = time.time()
        self.beat_doc(5, now)
        res = flagman_liveness(self.root, now, probe=self.running(now - 600, r"C:\Windows\notepad.exe"))
        self.assertEqual("PID_NOT_PYTHON", res["reason"])

    def test_wrong_schema_and_unverifiable_pid_are_unknown(self):
        now = time.time()
        self.write(json.dumps({"state": "ACTIVE", "updated_at": str(now), "pid": "4242"}))
        self.assertEqual("UNKNOWN", flagman_liveness(self.root, now)["state"])
        self.beat_doc(1, now)
        self.assertEqual("PID_UNVERIFIABLE", flagman_liveness(self.root, now, probe=lambda pid: None)["reason"])

    def test_real_probe_sees_this_test_process(self):
        info = _flagman_process_info(os.getpid())
        self.assertTrue(info and info["alive"])
        self.assertIn("python", Path(info["exe"]).name.lower() if info["exe"] else "python")

    def test_hud_line_names_flagman_state(self):
        for state, word in (("LIVE", "가동"), ("STOPPED", "정지"), ("MISSING", "없음"), ("UNKNOWN", "미확인")):
            hud = render_contextual_hud_widget({"compact_head": {}, "flagman_liveness": {"state": state, "age_s": 5}})
            self.assertIn(f"신호수:{word}", hud)
            self.assertLessEqual(len(hud), 200)


class DarkReadableHtml(unittest.TestCase):
    def test_dark_theme_and_larger_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hud.html"
            render_html_dashboard({"flagman_liveness": {"state": "LIVE", "age_s": 3}}, out)
            html = out.read_text(encoding="utf-8")
        self.assertIn("color-scheme: dark", html)
        self.assertIn("--background:", html)
        self.assertIn("--foreground:", html)
        self.assertIn("font-size: 18px", html)
        self.assertNotIn("text-[11px]", html)
        self.assertNotIn("text-[10px]", html)
        self.assertNotIn("bg-transparent", html)
        self.assertIn('id="flagman-badge"', html)
        # bars were invisible: their fill used --primary, which the standalone page never defined
        self.assertIn("--primary:", html)
        # budget board replaced the donut: per tool 5 h and weekly used/total/left/% and when a blocked tool returns
        self.assertNotIn('id="donut-box"', html)
        self.assertIn('id="budget-board"', html)
        self.assertIn('id="budget-headline"', html)
        self.assertIn("리셋 시각 미수집", html)  # no captured reset time is said, never guessed
        self.assertIn('querySelectorAll(".countdown")', html)
        # v3: calm lanes, no glow or flash (WCAG 2.3.1), budget cards open the lane detail, budget beside schedule
        self.assertNotIn("shadowBlur", html)
        self.assertIn("window.uaosSelectTool", html)
        self.assertIn("xl:grid-cols-2", html)
        self.assertIn("no-motion", html)  # in-page switch; OS reduced-motion froze the HUD
        # flow map overhaul: full-width canvas with particles plus a click-to-open detail panel per tool
        self.assertIn('id="flow-canvas"', html)
        self.assertIn('id="flow-detail"', html)
        self.assertIn("function renderFlow()", html)
        # schedule plans open as an accordion with the master-schedule detail
        self.assertIn("acc-item", html)
        # facts only: ledger fields are labelled as ledger, planner output as plan, unmeasured cost as unmeasured
        self.assertIn("장부 상태", html)
        self.assertIn("실행 증거가 아님", html)
        self.assertIn("계획기 제안(장부 아님)", html)
        self.assertIn('"미측정"', html)


if __name__ == "__main__":
    unittest.main()
