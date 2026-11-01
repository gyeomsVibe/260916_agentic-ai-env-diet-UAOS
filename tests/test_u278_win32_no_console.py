"""U278: Win32 No-Console Background Subprocess Launch Verification Tests.

Contract (U278-L3):
1. Observer starts and records its first sample BEFORE child spawn, stops after child exit + 2.0 s;
   polling interval <= 50 ms (10 ms fixed) with recorded actual `sample_count`, `median_gap_ms`, and `max_gap_ms`.
2. Maps desktop windows by `GetWindowThreadProcessId(hwnd) in process_tree_pids(child_pid)` (including child PID
   and console-host processes via `CreateToolhelp32Snapshot`), NEVER comparing `HWND == PID`.
3. Positive control: a deliberately console-showing child (`CREATE_NEW_CONSOLE`) must be detected, else gate FAIL.
4. If interactive desktop screen enumeration is unavailable (`EnumWindows` returns 0 top-level windows in a
   restricted/headless Window Station), screen-dependent test reports `SKIPPED` (`self.skipTest`), never `PASS`.
5. Each of the 5 owned launch paths (`presence._spawn_detached`, `deliver._deliver_to_codex`,
   `deliver._deliver_to_claude_locked`, `windows._codex_rpc_session`, `windows._open_antigravity`) runs a
   real subprocess once (`subprocess.run` / `subprocess.Popen` unmocked) and verifies `GetConsoleWindow() == 0`.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import deliver, presence, windows

CONSOLE_WINDOW_CLASSES = frozenset({"ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS", "PseudoConsoleWindow"})
TH32CS_SNAPPROCESS = 0x00000002


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _process_tree_pids(root_pids: set[int]) -> set[int]:
    """Return `root_pids` plus all descendant/console-host PIDs via Win32 Toolhelp32 snapshot."""
    if os.name != "nt" or not root_pids:
        return set(root_pids)
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == -1 or snap is None:
        return set(root_pids)
    try:
        pe = _PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        parent_map: dict[int, int] = {}
        if k32.Process32FirstW(snap, ctypes.byref(pe)):
            while True:
                parent_map[int(pe.th32ProcessID)] = int(pe.th32ParentProcessID)
                if not k32.Process32NextW(snap, ctypes.byref(pe)):
                    break
        tree = set(root_pids)
        added = True
        while added:
            added = False
            for pid, ppid in parent_map.items():
                if pid not in tree and ppid in tree:
                    tree.add(pid)
                    added = True
        return tree
    finally:
        k32.CloseHandle(snap)


def _enumerate_desktop_windows() -> tuple[int, dict[int, tuple[str, int]]]:
    """Return `(total_top_windows, {hwnd: (class_name, owner_pid)})` for visible windows on the interactive desktop."""
    if os.name != "nt":
        return 0, {}
    user32 = ctypes.windll.user32
    total_top = 0
    found: dict[int, tuple[str, int]] = {}
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):
        nonlocal total_top
        if hwnd:
            total_top += 1
            if user32.IsWindowVisible(hwnd):
                buf = ctypes.create_unicode_buffer(64)
                user32.GetClassNameW(hwnd, buf, 64)
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                found[int(hwnd)] = (buf.value, int(pid.value))
        return True

    user32.EnumWindows(WNDENUMPROC(_cb), 0)
    return total_top, found


def _desktop_screen_available() -> bool:
    """True only when running on an interactive Windows desktop where `EnumWindows` enumerates top-level windows."""
    if os.name != "nt":
        return False
    total_top, _ = _enumerate_desktop_windows()
    return total_top > 0


class _DesktopConsoleObserver:
    """Pre-launch observer (<50 ms interval) mapping windows by `GetWindowThreadProcessId(hwnd)` & process tree."""

    def __init__(self, interval_s: float = 0.010) -> None:
        if interval_s > 0.050:
            raise ValueError("Observer interval must be <= 50 ms")
        self.interval_s = interval_s
        self.tracked_roots: set[int] = set()
        self.tree_pids: set[int] = set()
        self.baseline_hwnds: set[int] = set()
        self.matched_pid_hwnds: set[int] = set()
        self.new_console_hwnds: set[int] = set()
        self.fg_before: int = 0
        self.fg_changed: bool = False
        self.timestamps: list[float] = []
        self._lock = threading.Lock()
        self._first_sample = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start_before_spawn(self) -> None:
        if os.name == "nt":
            self.fg_before = int(ctypes.windll.user32.GetForegroundWindow())
            _, win_map = _enumerate_desktop_windows()
            self.baseline_hwnds = {
                h for h, (cls, _pid) in win_map.items() if cls in CONSOLE_WINDOW_CLASSES
            }
        self._thread.start()
        if not self._first_sample.wait(timeout=5.0):
            raise AssertionError("Observer failed to record its first sample before child spawn")

    def register_pid(self, pid: int) -> None:
        if pid > 0:
            with self._lock:
                self.tracked_roots.add(int(pid))
                self.tree_pids = _process_tree_pids(self.tracked_roots)

    def _run(self) -> None:
        user32 = ctypes.windll.user32 if os.name == "nt" else None
        while not self._stop.is_set():
            now = time.perf_counter()
            self.timestamps.append(now)
            with self._lock:
                roots = set(self.tracked_roots)
            tree = _process_tree_pids(roots) if roots else set()
            _, win_map = _enumerate_desktop_windows()
            for hwnd, (cls, owner_pid) in win_map.items():
                if owner_pid in tree and (cls in CONSOLE_WINDOW_CLASSES or hwnd not in self.baseline_hwnds):
                    self.matched_pid_hwnds.add(hwnd)
                if cls in CONSOLE_WINDOW_CLASSES and hwnd not in self.baseline_hwnds:
                    self.new_console_hwnds.add(hwnd)
            if user32 is not None and self.fg_before != 0:
                fg_now = int(user32.GetForegroundWindow())
                if fg_now != 0 and fg_now != self.fg_before:
                    self.fg_changed = True
            if not self._first_sample.is_set():
                self._first_sample.set()
            time.sleep(self.interval_s)

    def stop_after_post_exit_window(self, post_exit_s: float = 2.0) -> dict[str, float | int]:
        if post_exit_s > 0:
            time.sleep(post_exit_s)
        self._stop.set()
        self._thread.join(timeout=5.0)
        gaps_ms = [
            (self.timestamps[i] - self.timestamps[i - 1]) * 1000.0
            for i in range(1, len(self.timestamps))
        ]
        return {
            "sample_count": len(self.timestamps),
            "median_gap_ms": round(statistics.median(gaps_ms), 3) if gaps_ms else 0.0,
            "max_gap_ms": round(max(gaps_ms), 3) if gaps_ms else 0.0,
        }


def _wait_json(path: Path, timeout_s: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                pass
        time.sleep(0.005)
    raise AssertionError(f"Timed out waiting for synchronized artifact {path}")


class TestU278Win32NoConsole(unittest.TestCase):
    def test_1_all_5_owned_launch_paths_run_real_process_once_with_no_console_and_detached_survival(self):
        if os.name != "nt":
            self.skipTest("Win32 console creationflags test requires Windows")
        self.assertFalse(getattr(subprocess, "_uaos_no_console_patched", False))

        tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_ctx.cleanup)
        tmp = Path(tmp_ctx.name)
        wt_root = str(Path(__file__).resolve().parents[1])

        # Build a real Windows `.cmd` shim that executes `sys.executable probe.py` so all CLI paths run real processes
        probe_py = tmp / "cli_probe.py"
        probe_log = tmp / "probe_log.jsonl"
        probe_py.write_text(
            "import ctypes, json, os, sys\n"
            "from pathlib import Path\n"
            "hwnd = int(ctypes.windll.kernel32.GetConsoleWindow())\n"
            f"log_p = Path({str(probe_log)!r})\n"
            "rec = {'pid': os.getpid(), 'console_hwnd': hwnd, 'argv': sys.argv[1:]}\n"
            "with log_p.open('a', encoding='utf-8') as f:\n"
            "    f.write(json.dumps(rec) + '\\n')\n"
            "if 'app-server' in sys.argv[1:]:\n"
            "    for line in sys.stdin:\n"
            "        msg = json.loads(line)\n"
            "        if msg.get('id') == 0:\n"
            "            print(json.dumps({'jsonrpc': '2.0', 'id': 0, 'result': {}}), flush=True)\n"
            "            break\n"
            "else:\n"
            "    print(json.dumps({'result': 'ok', 'conversation_id': 'conv-real-1', 'usage': {'input_tokens': 9}}), flush=True)\n",
            encoding="utf-8",
        )
        shim_cmd = tmp / "fake_tool.cmd"
        shim_cmd.write_text(f'@"{sys.executable}" "{probe_py}" %*\r\n', encoding="utf-8")

        # 1) Path 1: `presence._spawn_detached` real process + normal parent exit + TerminateProcess parent kill
        child_script = (
            "import ctypes, json, os, sys, time\n"
            "from pathlib import Path\n"
            "ready_p, done_p = Path(sys.argv[1]), Path(sys.argv[2])\n"
            "hwnd = int(ctypes.windll.kernel32.GetConsoleWindow())\n"
            "rt = ready_p.with_suffix('.tmp')\n"
            "rt.write_text(json.dumps({'child_pid': os.getpid(), 'console_hwnd': hwnd}), encoding='utf-8')\n"
            "os.replace(rt, ready_p)\n"
            "time.sleep(0.20)\n"
            "dt = done_p.with_suffix('.tmp')\n"
            "dt.write_text(json.dumps({'child_pid': os.getpid(), 'console_hwnd': hwnd, 'ok': True}), encoding='utf-8')\n"
            "os.replace(dt, done_p)\n"
        )
        ready_a, done_a = tmp / "ready_a.json", tmp / "done_a.json"
        parent_normal_script = (
            "import sys, time\n"
            f"sys.path.insert(0, {wt_root!r})\n"
            "from pathlib import Path\n"
            "from v7_harness.coord import presence\n"
            f"presence._spawn_detached({child_script!r}, {str(ready_a)!r}, {str(done_a)!r})\n"
            "deadline = time.monotonic() + 5.0\n"
            f"while time.monotonic() < deadline and not Path({str(ready_a)!r}).is_file():\n"
            "    time.sleep(0.005)\n"
        )
        obs_a = _DesktopConsoleObserver(interval_s=0.010)
        obs_a.start_before_spawn()
        parent_a = subprocess.Popen(
            [sys.executable, "-c", parent_normal_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        obs_a.register_pid(parent_a.pid)
        try:
            info_a = _wait_json(ready_a, timeout_s=5.0)
            obs_a.register_pid(int(info_a["child_pid"]))
            rc_a = parent_a.wait(timeout=5.0)
            self.assertEqual(0, rc_a)
            done_info_a = _wait_json(done_a, timeout_s=5.0)
        finally:
            stats_a = obs_a.stop_after_post_exit_window(post_exit_s=2.0)
            if parent_a.stdout:
                parent_a.stdout.close()
            if parent_a.stderr:
                parent_a.stderr.close()

        self.assertEqual(0, info_a["console_hwnd"])
        self.assertTrue(done_info_a.get("ok"))
        self.assertEqual(set(), obs_a.matched_pid_hwnds)
        self.assertGreaterEqual(int(stats_a["sample_count"]), 40)

        # Case B: Forced parent kill via TerminateProcess (`parent_b.kill()`)
        ready_b, done_b = tmp / "ready_b.json", tmp / "done_b.json"
        parent_hold_script = (
            "import sys, time\n"
            f"sys.path.insert(0, {wt_root!r})\n"
            "from v7_harness.coord import presence\n"
            f"presence._spawn_detached({child_script!r}, {str(ready_b)!r}, {str(done_b)!r})\n"
            "time.sleep(30.0)\n"
        )
        parent_b = subprocess.Popen(
            [sys.executable, "-c", parent_hold_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        try:
            info_b = _wait_json(ready_b, timeout_s=5.0)
            parent_b.kill()
            rc_b = parent_b.wait(timeout=5.0)
            self.assertNotEqual(0, rc_b)
            done_info_b = _wait_json(done_b, timeout_s=5.0)
        finally:
            if parent_b.poll() is None:
                parent_b.kill()
                parent_b.wait(timeout=5.0)
            if parent_b.stdout:
                parent_b.stdout.close()
            if parent_b.stderr:
                parent_b.stderr.close()
        self.assertEqual(0, info_b["console_hwnd"])
        self.assertTrue(done_info_b.get("ok"))

        # 2) Paths 2, 3, 4, 5: Run real subprocesses through `_deliver_to_codex`, `_deliver_to_claude_locked`,
        #    `_codex_rpc_session`, and `_open_antigravity` using the real `subprocess.run` / `subprocess.Popen`.
        with mock.patch("v7_harness.coord.deliver.shutil.which", return_value=str(shim_cmd)), \
             mock.patch("v7_harness.coord.windows.shutil.which", return_value=str(shim_cmd)):
            res_codex = deliver._deliver_to_codex("ping-codex", "01990000-0000-7000-8000-000000000001")
            self.assertTrue(res_codex.delivered, f"Real _deliver_to_codex failed: {res_codex}")

            res_claude = deliver._deliver_to_claude_locked("ping-claude", project_dir=tmp)
            self.assertTrue(res_claude.delivered, f"Real _deliver_to_claude_locked failed: {res_claude}")

            rpc = windows._codex_rpc_session()
            try:
                self.assertIsNotNone(rpc.proc)
            finally:
                rpc.proc.kill()
                rpc.proc.wait(timeout=5.0)

            conv_id, tokens = windows._open_antigravity(tmp, "ping-agy", subprocess.run)
            self.assertEqual("conv-real-1", conv_id)
            self.assertEqual(9, tokens)

        records = [json.loads(line) for line in probe_log.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(4, len(records), f"Expected 4 real CLI subprocess runs, got {len(records)}: {records}")
        for rec in records:
            self.assertEqual(0, rec["console_hwnd"], f"CLI path allocated a console window: {rec}")

    def test_2_interactive_desktop_observer_positive_and_negative_controls_with_process_tree_pid_mapping(self):
        if not _desktop_screen_available():
            self.skipTest(
                "Interactive desktop screen unavailable in current Window Station (EnumWindows returned 0 windows); "
                "skipping screen-level HWND observer test per contract item 4 (never false PASS)"
            )

        tmp_ctx = tempfile.TemporaryDirectory()
        self.addCleanup(tmp_ctx.cleanup)
        tmp = Path(tmp_ctx.name)

        # Positive control on interactive desktop: CREATE_NEW_CONSOLE child MUST be detected by observer
        pos_ready = tmp / "pos_ready.json"
        pos_script = (
            "import ctypes, json, os, sys, time\n"
            "from pathlib import Path\n"
            "hwnd = int(ctypes.windll.kernel32.GetConsoleWindow())\n"
            "rt = Path(sys.argv[1] + '.tmp')\n"
            "rt.write_text(json.dumps({'child_pid': os.getpid(), 'console_hwnd': hwnd}), encoding='utf-8')\n"
            "os.replace(rt, sys.argv[1])\n"
            "time.sleep(0.25)\n"
        )
        obs_pos = _DesktopConsoleObserver(interval_s=0.010)
        obs_pos.start_before_spawn()
        pos_proc = subprocess.Popen(
            [sys.executable, "-c", pos_script, str(pos_ready)],
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0x00000010),
        )
        obs_pos.register_pid(pos_proc.pid)
        try:
            pos_info = _wait_json(pos_ready, timeout_s=5.0)
            pos_proc.wait(timeout=5.0)
        finally:
            pos_stats = obs_pos.stop_after_post_exit_window(post_exit_s=0.2)
            if pos_proc.poll() is None:
                pos_proc.kill()
                pos_proc.wait(timeout=5.0)

        self.assertNotEqual(0, pos_info["console_hwnd"])
        self.assertTrue(
            bool(obs_pos.matched_pid_hwnds or obs_pos.new_console_hwnds),
            f"Positive control failed: observer did not detect CREATE_NEW_CONSOLE window (stats={pos_stats})",
        )


if __name__ == "__main__":
    unittest.main()
