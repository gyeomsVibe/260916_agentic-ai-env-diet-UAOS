"""U304-A fixed acceptance: Flagman (신호수) reads LIVE from a real resident daemon, and the ops-chip panel is open.

Receipt (2026-11-04, 윤겸스 HUD): Flagman showed STOPPED/PID_NOT_RUNNING beside a pulse 11-25 s old. Pulses came
only from short-lived hook processes that stamped their own PID, and the 2026-10-27 daemon was dead with nothing
re-spawning it. These tests spawn a real daemon process; none of them mocks the PID probe.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import v7_harness
from v7_harness.coord import hud_live
from v7_harness.coord.capacity_planner import _flagman_process_info, flagman_liveness, render_html_dashboard
from v7_harness.disjoint_mediator import (
    ensure_independent_flagman_daemon,
    flagman_daemon_meta_file,
    flagman_presence_file,
)

PKG_ROOT = Path(v7_harness.__file__).resolve().parent.parent
DAEMON_INTERVAL_S = 0.5  # fast pulses keep the test short; production uses FLAGMAN_DAEMON_INTERVAL_S = 30
WAIT_S = 30.0  # Python start-up plus the first pulse on a loaded Windows box; the card's gate allows 60 s


def _kill(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows
    except OSError:
        pass


def _wait_for(pred, timeout: float = WAIT_S):
    end = time.time() + timeout
    while time.time() < end:
        got = pred()
        if got:
            return got
        time.sleep(0.2)
    return pred()


def _hook_pulse(root: Path) -> None:
    """A real short-lived process pulses and exits, exactly like a sentinel hook."""
    code = (
        f"import sys; sys.path.insert(0, {str(PKG_ROOT)!r}); from pathlib import Path; "
        "from v7_harness.disjoint_mediator import run_independent_flagman_pulse; "
        f"run_independent_flagman_pulse(Path({str(root)!r}), auto_heal=True)"
    )
    subprocess.run([sys.executable, "-c", code], check=True, timeout=60, cwd=str(root))


class FlagmanDaemonLive(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / ".coord" / "presence").mkdir(parents=True)
        self.pids: list[int] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        for pid in self.pids:
            _kill(pid)
        time.sleep(0.3)
        self.tmp.cleanup()

    def _meta_pid(self) -> int:
        return int(json.loads(flagman_daemon_meta_file(self.root).read_text(encoding="utf-8"))["pid"])

    def _beat(self) -> dict:
        return json.loads(flagman_presence_file(self.root).read_text(encoding="utf-8"))

    def _live(self):
        res = flagman_liveness(self.root, time.time())
        return res if res["state"] == "LIVE" else None

    def _spawn(self) -> int:
        res = ensure_independent_flagman_daemon(self.root, interval_s=DAEMON_INTERVAL_S)
        self.assertEqual("SPAWNED_DETACHED", res["daemon_status"])
        self.pids.append(int(res["pid"]))
        return int(res["pid"])

    def test_real_daemon_reads_live_and_imports_the_ensuring_runtime(self):
        pid = self._spawn()
        self.assertEqual(str(PKG_ROOT), json.loads(flagman_daemon_meta_file(self.root).read_text("utf-8"))["runtime_root"])
        live = _wait_for(self._live)
        self.assertIsNotNone(live, flagman_liveness(self.root, time.time()))
        self.assertEqual("PULSE_FRESH_PID_RUNNING", live["reason"])
        beat = self._beat()
        self.assertEqual((pid, pid, "daemon"), (beat["daemon_pid"], beat["pulse_pid"], beat["pulse_source"]))
        again = ensure_independent_flagman_daemon(self.root, interval_s=DAEMON_INTERVAL_S)
        self.assertEqual(("ALIVE", pid), (again["daemon_status"], again["pid"]))  # no second daemon

    def test_hook_pulse_with_dead_pid_keeps_live(self):
        pid = self._spawn()
        self.assertIsNotNone(_wait_for(self._live))
        _hook_pulse(self.root)
        beat = self._beat()
        if beat["pulse_source"] == "daemon":  # the daemon pulsed again in between; pulse from a hook once more
            _hook_pulse(self.root)
            beat = self._beat()
        self.assertEqual("hook", beat["pulse_source"])
        self.assertNotEqual(pid, beat["pulse_pid"])
        self.assertFalse(_flagman_process_info(int(beat["pulse_pid"]))["alive"])  # the writer is really gone
        self.assertEqual((pid, pid), (beat["pid"], beat["daemon_pid"]))
        self.assertEqual("LIVE", flagman_liveness(self.root, time.time())["state"])

    def test_dead_daemon_reads_stopped_then_hud_refresher_respawns_it(self):
        first = self._spawn()
        self.assertIsNotNone(_wait_for(self._live))
        _kill(first)
        self.assertTrue(_wait_for(lambda: not _flagman_process_info(first)["alive"]))
        _hook_pulse(self.root)  # fresh pulse, dead daemon
        res = flagman_liveness(self.root, time.time())
        self.assertEqual(("STOPPED", "PID_NOT_RUNNING"), (res["state"], res["reason"]))

        respawn = ensure_independent_flagman_daemon(self.root, interval_s=DAEMON_INTERVAL_S)
        self.pids.append(int(respawn["pid"]))
        self.assertEqual("SPAWNED_DETACHED", respawn["daemon_status"])
        self.assertNotEqual(first, respawn["pid"])
        self.assertIsNotNone(_wait_for(self._live))
        self.assertEqual(respawn["pid"], self._beat()["daemon_pid"])

    def test_superseded_daemon_exits_by_itself(self):
        first = self._spawn()
        self.assertIsNotNone(_wait_for(self._live))
        meta = json.loads(flagman_daemon_meta_file(self.root).read_text(encoding="utf-8"))
        meta["pid"] = os.getpid()  # a newer daemon was recorded
        flagman_daemon_meta_file(self.root).write_text(json.dumps(meta), encoding="utf-8")
        self.assertTrue(_wait_for(lambda: not _flagman_process_info(first)["alive"]))

    def test_hook_pulse_without_any_daemon_is_stopped_not_live(self):
        _hook_pulse(self.root)
        beat = self._beat()
        self.assertEqual(("hook", None), (beat["pulse_source"], beat["daemon_pid"]))
        res = flagman_liveness(self.root, time.time())
        self.assertEqual(("STOPPED", "NO_DAEMON"), (res["state"], res["reason"]))


class HudRefresherEnsures(unittest.TestCase):
    def test_serve_ensures_the_daemon_every_cycle(self):
        calls: list[Path] = []
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / ".coord").mkdir()
            res = hud_live.serve(root, open_page=False, sleep=lambda _s: None, max_cycles=2, ensure=calls.append)
        self.assertEqual("STOPPED", res["state"])
        self.assertEqual([root] * 3, calls)  # once before the first render, then once per cycle

    def test_ensure_flagman_reports_instead_of_raising(self):
        res = hud_live.ensure_flagman(Path(tempfile.gettempdir()) / "u304a-no-such-project-dir")
        self.assertFalse(res["ok"])
        self.assertIn("INVALID_ROOT", res["error"])


class OpsChipPanelAlwaysOpen(unittest.TestCase):
    def test_ops_chip_panel_has_no_collapse_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "hud.html"
            render_html_dashboard({}, out)
            html = out.read_text(encoding="utf-8")
        at = html.index("📟 운영 칩 · 대기 상태")
        before = html[:at]
        self.assertEqual(len(re.findall(r"<details\b", before)), before.count("</details>"))  # not inside a <details>
        self.assertNotIn("<summary", before[before.rindex("<") - 1:])
        self.assertIn('id="ops-chip-panel"', before[-400:])
        self.assertIn('id="five-chip-bar"', html[at:at + 400])
        self.assertIn('id="wait-banner"', html[at:at + 600])


if __name__ == "__main__":
    unittest.main()
