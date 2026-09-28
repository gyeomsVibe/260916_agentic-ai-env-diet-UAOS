"""U68-L: every pilot worker prints its envelope so a cp949 stdout cannot lose it.

U68 fixed the Claude worker after U67-C1 lost its envelope to UnicodeEncodeError on U+2014. The lane, apply and local
Ollama workers printed their envelopes the same way (`ensure_ascii=False`). Each test swaps stdout for a cp949 text
stream, drives the worker to an envelope that holds U+2014, and reads the bytes back as ASCII JSON.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import unittest
from contextlib import nullcontext
from unittest import mock

from v7_harness.adapters import apply_worker, lane_worker, ollama_worker

DASH = "—"


def _cp949_run(fn) -> tuple[int, dict]:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp949", newline="\n")
    with mock.patch.object(sys, "stdout", stream):
        rc = fn()
        stream.flush()
    return rc, json.loads(raw.getvalue().decode("ascii"))


class WorkerEnvelopeCp949Tests(unittest.TestCase):
    def test_lane_worker(self) -> None:
        done = subprocess.CompletedProcess([], 0, stdout=json.dumps({"result": f"done {DASH}", "num_turns": 2},
                                                                    ensure_ascii=False).encode("utf-8"), stderr=b"")
        with mock.patch("v7_harness.adapters.gpu_priority.pilot_holds", lambda t: nullcontext()), \
                mock.patch.object(lane_worker.subprocess, "run", return_value=done):
            rc, env = _cp949_run(lambda: lane_worker.main(["-p", "x", "--add-dir", ".", "--print-timeout", "5s"]))
        self.assertEqual((0, "SUCCESS", f"done {DASH}"), (rc, env["status"], env["response"]))

    def test_apply_worker(self) -> None:
        with mock.patch.object(ollama_worker, "dictated_paths", return_value=["a.txt"]), \
                mock.patch.object(ollama_worker, "_apply", return_value=[f"a{DASH}b.txt"]):
            rc, env = _cp949_run(lambda: apply_worker.main(["-p", "x", "--add-dir", "."]))
        self.assertEqual((0, "SUCCESS", f"wrote: a{DASH}b.txt"), (rc, env["status"], env["response"]))

    def test_ollama_worker(self) -> None:
        with mock.patch("v7_harness.adapters.gpu_priority.pilot_holds", lambda t: nullcontext()), \
                mock.patch.object(ollama_worker, "_log"), \
                mock.patch.object(ollama_worker, "_generate", side_effect=OSError(f"down {DASH}")):
            rc, env = _cp949_run(lambda: ollama_worker.main(["-p", "x", "--add-dir", ".", "--print-timeout", "5s"]))
        self.assertEqual((1, "ERROR"), (rc, env["status"]))
        self.assertIn(f"down {DASH}", env["error"])


if __name__ == "__main__":
    unittest.main()
