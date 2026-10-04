"""U157-B: the first error is actionable, a failed dispatch is retried, and the CLI watches a real source.

Receipts (Codex RSI-FULL-20261004 audit, installed 0.3.0-f51c807a29a9, disposable fixtures, exit 0): the first
meaningful error returned ACK_ONLY with 0 triggers (B1); a changed error whose trigger raised was saved as seen and
the retry returned ACK_ONLY with 0 triggers (B2); `rsi watch` passed no fetch/trigger and watched no source.
Contract: .work/u157b/contract_v2.md (v2 after Antigravity REVISE relay_52f836f4). CLI cases run the real CLI in a
subprocess; queue concurrency runs real parallel processes.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import rsi_release

REPO = Path(__file__).resolve().parent.parent
ERRORS = Path(".coord") / "usage" / "user_error_reports.jsonl"
QUEUE = Path(".coord") / "rsi" / "actionable.jsonl"
STATE = Path(".work") / "rsi-scheduler-state.json"
ROW = {"id": "e1", "at": "2026-10-04T20:00:00+09:00", "tool": "codex", "terms": ["lock"], "text": "lock stolen"}
ERRORS_URL = "file:" + ERRORS.as_posix()


def _env() -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _command(project: Path, config: Path | None = None) -> list:
    command = [sys.executable, "-m", "v7_harness.cli", "rsi", "watch", "--project", str(project)]
    return command + (["--config", str(config)] if config else [])


def _result(stdout: str) -> dict:
    """The cycle result is the last JSON object on stdout (scheduler_event lines may come first)."""
    for line in reversed([ln for ln in stdout.splitlines() if ln.strip()]):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and "status" in data:
            return data
    text = stdout.strip()
    start = text.rfind("\n{")
    return json.loads(text[start + 1:] if start >= 0 else text)


def _rows(path: Path) -> list:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _link_dir(link: Path, target: Path) -> bool:
    """A directory junction on Windows (no admin needed), a symlink elsewhere. False when the OS refuses."""
    if os.name == "nt":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        return done.returncode == 0 and link.exists()
    try:
        os.symlink(target, link, target_is_directory=True)
        return True
    except OSError:
        return False


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name).resolve() / "proj"
        (self.project / ".work").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def add_error(self, row=ROW):
        path = self.project / ERRORS
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")

    def watch(self, config: Path | None = None):
        done = subprocess.run(_command(self.project, config), cwd=str(REPO), env=_env(), capture_output=True,
                              text=True, encoding="utf-8", timeout=120)
        return done.returncode, _result(done.stdout), done

    def write_config(self, sources: list) -> Path:
        config = self.project / "watcher.json"
        config.write_text(json.dumps({"max_retries": 1, "sources": sources}), encoding="utf-8")
        return config

    def assert_nothing_written(self):
        self.assertFalse((self.project / STATE).exists())
        self.assertFalse((self.project / QUEUE).exists())

    def cycle(self, trigger, sources=None, **kw):
        config = {"max_retries": kw.pop("max_retries", 1),
                  "sources": sources or [{"url": ERRORS_URL, "first_seen": "actionable"}]}
        return rsi_release.run_scheduler_cycle(
            self.project, config, now=1000.0,
            fetch=kw.pop("fetch", lambda source, timeout: rsi_release.file_source_fetch(self.project, source, timeout)),
            trigger=trigger, **kw)


class CliSource(Base):
    def test_01_first_error_is_actionable_through_the_real_cli(self):
        self.add_error()
        code, result, done = self.watch()
        self.assertEqual(0, code, done.stderr)
        self.assertEqual("ACTIONABLE_DELTA", result["status"])
        rows = _rows(self.project / QUEUE)
        self.assertEqual(1, len(rows))
        self.assertEqual(result["bundle_id"], rows[0]["bundle_id"])

    def test_02_unchanged_rerun_is_ack_only_and_adds_no_row(self):
        self.add_error()
        self.watch()
        code, result, _ = self.watch()
        self.assertEqual((0, "ACK_ONLY"), (code, result["status"]))
        self.assertEqual(1, len(_rows(self.project / QUEUE)))

    def test_03_no_error_file_is_quiet_then_the_first_row_is_actionable(self):
        code, result, _ = self.watch()
        self.assertEqual((0, "ACK_ONLY"), (code, result["status"]))
        self.assertEqual([], _rows(self.project / QUEUE))
        self.add_error()
        code, result, _ = self.watch()
        self.assertEqual((0, "ACTIONABLE_DELTA"), (code, result["status"]))
        self.assertEqual(1, len(_rows(self.project / QUEUE)))

    def test_04_a_source_without_first_seen_keeps_its_baseline(self):
        doc = self.project / "docs" / "guide.md"
        doc.parent.mkdir(parents=True)
        doc.write_text("v1", encoding="utf-8")
        code, result, _ = self.watch(self.write_config([{"url": "file:docs/guide.md"}]))
        self.assertEqual((0, "ACK_ONLY"), (code, result["status"]))
        self.assertEqual([], _rows(self.project / QUEUE))

    def test_05_whitespace_only_first_file_is_not_actionable(self):
        path = self.project / ERRORS
        path.parent.mkdir(parents=True)
        path.write_text("\n  \n", encoding="utf-8")
        code, result, _ = self.watch()
        self.assertEqual((0, "ACK_ONLY"), (code, result["status"]))
        self.assertEqual([], _rows(self.project / QUEUE))
        self.add_error()
        code, result, _ = self.watch()
        self.assertEqual((0, "ACTIONABLE_DELTA"), (code, result["status"]))

    def test_06_escaping_absolute_or_unlisted_paths_fail_closed_and_write_nothing(self):
        outside = self.project.parent / "outside.jsonl"
        outside.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
        (self.project / "v7_harness").mkdir()
        (self.project / "v7_harness" / "x.py").write_text("x = 1\n", encoding="utf-8")
        for url in ("file:../outside.jsonl", "file:" + str(outside), "file:.coord/../../outside.jsonl",
                    "file:v7_harness/x.py", "https://example.invalid/errors"):
            with self.subTest(url=url):
                code, result, _ = self.watch(self.write_config([{"url": url, "first_seen": "actionable"}]))
                self.assertEqual((1, "FAILED"), (code, result["status"]))
                self.assertEqual("fetch", result["failure_receipt"]["stage"])
                self.assertEqual("SourceRefused", result["failure_receipt"]["error"])
                self.assert_nothing_written()

    def test_07_secret_like_files_are_refused(self):
        (self.project / ".coord").mkdir()
        (self.project / ".coord" / ".env").write_text("A=1\n", encoding="utf-8")
        (self.project / "docs").mkdir()
        (self.project / "docs" / "api-key.txt").write_text("k\n", encoding="utf-8")
        for url in ("file:.coord/.env", "file:docs/api-key.txt", "file:.coord/credentials/errors.jsonl"):
            with self.subTest(url=url):
                code, result, _ = self.watch(self.write_config([{"url": url, "first_seen": "actionable"}]))
                self.assertEqual((1, "FAILED", "SourceRefused"),
                                 (code, result["status"], result["failure_receipt"]["error"]))
                self.assert_nothing_written()

    def test_08_a_junction_or_symlink_escape_is_refused(self):
        outside = self.project.parent / "outside_dir"
        outside.mkdir()
        (outside / "errors.jsonl").write_text(json.dumps(ROW) + "\n", encoding="utf-8")
        (self.project / ".coord").mkdir()
        if not _link_dir(self.project / ".coord" / "linked", outside):
            self.skipTest("the OS refused to create a junction/symlink")
        code, result, _ = self.watch(self.write_config([{"url": "file:.coord/linked/errors.jsonl",
                                                         "first_seen": "actionable"}]))
        self.assertEqual((1, "FAILED", "SourceRefused"), (code, result["status"], result["failure_receipt"]["error"]))
        self.assert_nothing_written()

    def test_09_a_corrupt_watcher_config_fails_and_writes_nothing(self):
        config = self.project / "watcher.json"
        config.write_text("{not json", encoding="utf-8")
        self.add_error()
        code, result, _ = self.watch(config)
        self.assertEqual((1, "FAILED"), (code, result["status"]))
        self.assertEqual("config", result["failure_receipt"]["stage"])
        self.assert_nothing_written()

    def test_10_two_parallel_cli_runs_queue_exactly_one_row(self):
        self.add_error()
        processes = [subprocess.Popen(_command(self.project), cwd=str(REPO), env=_env(), stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True, encoding="utf-8") for _ in range(2)]
        statuses = []
        for process in processes:
            out, _ = process.communicate(timeout=120)
            statuses.append(_result(out)["status"])
        self.assertIn("ACTIONABLE_DELTA", statuses)
        self.assertEqual(1, len(_rows(self.project / QUEUE)), statuses)


class Cycle(Base):
    def test_11_a_failed_trigger_is_retried_with_the_same_bundle_and_leaks_no_message(self):
        self.add_error()

        def broken(_bundle):
            raise RuntimeError("dispatch down: secret-value-xyz")

        failed = self.cycle(broken)
        self.assertEqual("FAILED", failed["status"])
        self.assertEqual("trigger", failed["failure_receipt"]["stage"])
        self.assertEqual("RuntimeError", failed["failure_receipt"]["error"])
        self.assertNotIn("secret-value-xyz", json.dumps(failed))
        self.assertFalse((self.project / STATE).exists(), "a failed trigger writes no state")
        seen = []
        retried = self.cycle(lambda bundle: seen.append(bundle) or rsi_release.durable_trigger(self.project, bundle))
        self.assertEqual("ACTIONABLE_DELTA", retried["status"])
        self.assertEqual(failed["failure_receipt"]["bundle_id"], retried["bundle_id"])
        self.assertEqual(retried["bundle_id"], seen[0]["bundle_id"])
        quiet = self.cycle(lambda bundle: self.fail("unchanged cycle must not trigger"))
        self.assertEqual("ACK_ONLY", quiet["status"])
        self.assertEqual(1, len(_rows(self.project / QUEUE)))

    def test_12_a_crash_after_the_append_before_the_state_write_queues_one_row(self):
        self.add_error()
        trigger = lambda bundle: rsi_release.durable_trigger(self.project, bundle)  # noqa: E731
        with mock.patch.object(rsi_release, "_write_state", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.cycle(trigger)
        self.assertEqual(1, len(_rows(self.project / QUEUE)))
        self.assertFalse((self.project / STATE).exists())
        again = self.cycle(trigger)
        self.assertEqual("ACTIONABLE_DELTA", again["status"])
        self.assertEqual(1, len(_rows(self.project / QUEUE)), "the re-dispatch is deduped by bundle_id")
        self.assertEqual("ACK_ONLY", self.cycle(trigger)["status"])

    def test_13_a_corrupt_state_file_fails_closed_without_a_silent_baseline(self):
        self.add_error()
        state = self.project / STATE
        state.write_bytes(b"{torn")
        result = self.cycle(lambda bundle: self.fail("no trigger on corrupt state"))
        self.assertEqual(("FAILED", "state"), (result["status"], result["failure_receipt"]["stage"]))
        self.assertEqual(b"{torn", state.read_bytes())
        self.assertFalse((self.project / QUEUE).exists())

    def test_14_a_refused_source_is_not_retried(self):
        sleeps = []
        result = self.cycle(lambda bundle: None, sources=[{"url": "file:../x.jsonl", "first_seen": "actionable"}],
                            max_retries=3, sleeper=sleeps.append)
        self.assertEqual(("FAILED", "SourceRefused"), (result["status"], result["failure_receipt"]["error"]))
        self.assertEqual([], sleeps)

    def test_15_a_directory_source_fails_without_writing(self):
        (self.project / ".coord" / "usage").mkdir(parents=True)
        result = self.cycle(lambda bundle: None, sources=[{"url": "file:.coord/usage", "first_seen": "actionable"}])
        self.assertEqual(("FAILED", "fetch"), (result["status"], result["failure_receipt"]["stage"]))
        self.assertNotEqual("SourceRefused", result["failure_receipt"]["error"])
        self.assert_nothing_written()

    def test_16_duplicate_config_urls_are_fetched_once(self):
        self.add_error()
        calls = []

        def fetch(source, timeout):
            calls.append(source["url"])
            return rsi_release.file_source_fetch(self.project, source, timeout)

        source = {"url": ERRORS_URL, "first_seen": "actionable"}
        result = self.cycle(lambda bundle: None, sources=[source, dict(source)], fetch=fetch)
        self.assertEqual("ACTIONABLE_DELTA", result["status"])
        self.assertEqual([ERRORS_URL], calls)

    def test_17_bundle_ids_ignore_config_order_and_keep_a_b_a_distinct(self):
        content = {"file:.coord/a.jsonl": "A", "file:.coord/b.jsonl": "B"}

        def fetch(source, timeout):
            return {"url": source["url"], "content_sha256": _sha(content[source["url"]]), "bytes": 1, "blank": False}

        forward = [{"url": u, "first_seen": "actionable"} for u in sorted(content)]
        ids = []
        for order in (forward, list(reversed(forward))):
            with tempfile.TemporaryDirectory() as other:
                root = Path(other)
                (root / ".work").mkdir()
                res = rsi_release.run_scheduler_cycle(root, {"max_retries": 1, "sources": order}, now=1.0,
                                                      fetch=fetch, trigger=lambda bundle: None)
                ids.append(res["bundle_id"])
        self.assertEqual(ids[0], ids[1])

        single = [{"url": "file:.coord/a.jsonl", "first_seen": "actionable"}]
        flips = []
        for value in ("A", "B", "A"):
            content["file:.coord/a.jsonl"] = value
            res = self.cycle(lambda bundle: None, sources=single, fetch=fetch)
            self.assertEqual("ACTIONABLE_DELTA", res["status"])
            flips.append(res["bundle_id"])
        self.assertEqual(3, len(set(flips)), flips)


_CHILD = (
    "import json, sys, time\n"
    "from pathlib import Path\n"
    "from v7_harness import rsi_release\n"
    "go = Path(sys.argv[3])\n"
    "while not go.exists():\n"
    "    time.sleep(0.005)\n"
    "print(rsi_release.durable_trigger(Path(sys.argv[1]), json.loads(sys.argv[2])))\n"
)


class Queue(Base):
    def bundle(self, n: int) -> dict:
        return {"bundle_id": f"{n:064x}", "deltas": [{"url": "file:x", "content_sha256": "c" * 64}], "count": 1}

    def race(self, bundles: list) -> list:
        go = self.project / "go"
        processes = [subprocess.Popen([sys.executable, "-c", _CHILD, str(self.project), json.dumps(b), str(go)],
                                      cwd=str(REPO), env=_env(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True) for b in bundles]
        time.sleep(1.0)
        go.write_text("go", encoding="ascii")
        outs = []
        for process in processes:
            out, err = process.communicate(timeout=120)
            self.assertEqual(0, process.returncode, err)
            outs.append(out.strip())
        return outs

    def test_18_durable_trigger_is_idempotent_per_bundle(self):
        self.assertTrue(rsi_release.durable_trigger(self.project, self.bundle(1)))
        self.assertFalse(rsi_release.durable_trigger(self.project, dict(self.bundle(1))))
        rows = _rows(self.project / QUEUE)
        self.assertEqual([f"{1:064x}"], [row["bundle_id"] for row in rows])

    def test_19_parallel_processes_with_one_bundle_append_one_row(self):
        outs = self.race([self.bundle(7)] * 8)
        self.assertEqual(1, outs.count("True"), outs)
        self.assertEqual(1, len(_rows(self.project / QUEUE)))

    def test_20_parallel_processes_with_distinct_bundles_lose_no_row(self):
        self.race([self.bundle(n) for n in range(8)])
        ids = sorted(row["bundle_id"] for row in _rows(self.project / QUEUE))
        self.assertEqual(sorted(f"{n:064x}" for n in range(8)), ids)

    def test_21_a_torn_tail_is_kept_aside_and_a_corrupt_line_raises(self):
        queue = self.project / QUEUE
        queue.parent.mkdir(parents=True)
        whole = json.dumps({"bundle_id": f"{1:064x}", "ts": 1, "deltas": []}) + "\n"
        queue.write_text(whole + '{"bundle_', encoding="utf-8", newline="")
        self.assertTrue(rsi_release.durable_trigger(self.project, self.bundle(2)))
        self.assertEqual([f"{1:064x}", f"{2:064x}"], [row["bundle_id"] for row in _rows(queue)])
        self.assertIn('{"bundle_', (queue.parent / "actionable.jsonl.torn").read_text(encoding="utf-8"))
        queue.write_text(whole + "not json\n", encoding="utf-8", newline="")
        with self.assertRaises(ValueError):
            rsi_release.durable_trigger(self.project, self.bundle(3))
        self.assertEqual(whole + "not json\n", queue.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
