"""Supplementary native Claude worker journal checks; no provider calls."""
from contextlib import closing, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest import mock

from v7_harness.adapters import claude_worker as cw
from v7_harness import invocation as inv


class ClaudeJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Path(self.tmp.name)
        self.db = self.p / "journal.sqlite3"

    def invoke(self, result=None, error=None, caller="codex", raw=None):
        values = dict(result="done", usage={}, modelUsage={"claude-haiku-5-5": {}}) if result is None else result
        stdout = json.dumps(values).encode() if raw is None else raw
        done = subprocess.CompletedProcess(["native"], 0, stdout=stdout, stderr=b"sensitive diagnostic")
        env = dict(UAOS_INVOCATION_DB=str(self.db), UAOS_CALLER=caller,
                   UAOS_WORK_ID="U229-B2", UAOS_PURPOSE="native metadata probe")
        out = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(cw.subprocess, "run", return_value=done,
                side_effect=error) as run, redirect_stdout(out):
            code = cw.main(["-p", "private prompt", "--add-dir", str(self.p), "--max-budget-usd", ".03",
                            "--model", "claude-haiku-5-5"])
        return code, json.loads(out.getvalue()), run

    def rows(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.row_factory = sqlite3.Row
            return [dict(row) for row in con.execute("SELECT * FROM attempts")]

    def test_all_callers_and_cached_usage_are_durable_and_do_not_claim_oauth(self):
        raw = dict(result="summary", usage=dict(input_tokens=2, cache_read_input_tokens=4,
                   cache_creation_input_tokens=5, output_tokens=3), total_cost_usd=.0012)
        for caller in inv.CALLERS:
            self.assertEqual(0, self.invoke(raw, caller=caller)[0])
        rows = self.rows()
        self.assertEqual(set(inv.CALLERS), {row["caller"] for row in rows})
        self.assertTrue(all(row["input_tokens"] == 11 and row["output_tokens"] == 3 for row in rows))
        self.assertTrue(all(row["model"] == "claude-haiku-5-5" for row in rows))
        self.assertTrue(all(json.loads(row["metadata"])["provider"] == "claude_cli_unverified" for row in rows))
        self.assertNotIn("private prompt", json.dumps(rows))
        self.assertNotIn("summary", json.dumps(rows))
        self.assertEqual(hashlib.sha256(b"private prompt").hexdigest(), rows[0]["input_sha256"])

    def test_timeout_parse_start_provider_and_usage_failures_are_terminal(self):
        probes = ((None, subprocess.TimeoutExpired("native", 1), None, "TIMEOUT"),
                  (None, OSError("secret body"), None, "PROCESS_ERROR"),
                  (None, None, b"invalid", "PARSE_ERROR"),
                  ([], None, None, "RESPONSE_FORMAT"),
                  (dict(is_error=True, subtype="provider secret"), None, None, "PROVIDER_ERROR"),
                  (dict(usage=[1]), None, None, "USAGE_FORMAT"))
        for result, error, raw, expected in probes:
            with self.subTest(expected=expected):
                self.assertEqual(1, self.invoke(result, error, raw=raw)[0])
                row = self.rows()[-1]
                self.assertEqual(("FAILED", expected), (row["outcome"], row["error_class"]))
                self.assertIsNotNone(row["finished_at"])
        self.assertNotIn("secret", json.dumps(self.rows()))
        self.assertNotIn("sensitive diagnostic", json.dumps(self.rows()))

    def test_missing_or_invalid_usage_does_not_invent_zero_counts(self):
        for usage in ({}, {"input_tokens": 2, "output_tokens": 3}, {"input_tokens": -1}):
            self.invoke(dict(usage=usage))
            self.assertIsNone(self.rows()[-1]["input_tokens"])
        self.assertIsNone(self.rows()[-1]["output_tokens"])

    def test_journal_start_failure_prevents_native_subprocess(self):
        with mock.patch.object(inv, "start_attempt", side_effect=sqlite3.OperationalError("private")):
            code, envelope, run = self.invoke()
        self.assertEqual(1, code)
        self.assertEqual("INVOCATION_JOURNAL_START_FAILED", envelope["error"])
        run.assert_not_called()

    def test_journal_terminal_failure_is_not_reported_as_success(self):
        with mock.patch.object(inv, "finish_attempt", side_effect=sqlite3.OperationalError("private")):
            code, envelope, _ = self.invoke()
        self.assertEqual(1, code)
        self.assertEqual("INVOCATION_JOURNAL_TERMINAL_FAILED", envelope["error"])
