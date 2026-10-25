"""Supplementary Ollama embedding journal checks (U229-B2); mocked HTTP, no provider calls."""
from contextlib import closing
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from v7_harness import olla


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class EmbedJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / "journal.sqlite3"

    def run_embed(self, urlopen, caller="codex"):
        env = {"UAOS_INVOCATION_DB": str(self.db), "UAOS_CALLER": caller, "UAOS_WORK_ID": "U229-B2"}
        with mock.patch.dict(os.environ, env), mock.patch.object(olla.urllib.request, "urlopen", urlopen) as call:
            try:
                return olla._embed(["SECRET-RAW-TEXT"]), call
            except Exception as exc:
                return exc, call

    def rows(self):
        with closing(sqlite3.connect(self.db)) as con:
            con.row_factory = sqlite3.Row
            return [dict(r) for r in con.execute("SELECT * FROM attempts")]

    def test_success_records_hash_only(self):
        body = json.dumps({"embeddings": [[0.1]], "prompt_eval_count": 7}).encode()
        out, call = self.run_embed(lambda *a, **k: Resp(body))
        self.assertEqual(out, [[0.1]])
        (row,) = self.rows()
        self.assertEqual((row["outcome"], row["input_tokens"], row["output_tokens"]), ("SUCCEEDED", 7, None))
        self.assertEqual(row["model"], olla.EMBED_MODEL)
        self.assertNotIn("SECRET-RAW-TEXT", json.dumps(row))

    def test_timeout_records_failure_and_propagates(self):
        def boom(*a, **k):
            raise TimeoutError("slow")
        out, _ = self.run_embed(boom)
        self.assertIsInstance(out, TimeoutError)
        (row,) = self.rows()
        self.assertEqual((row["outcome"], row["error_class"]), ("FAILED", "TIMEOUT"))

    def test_all_three_callers(self):
        body = json.dumps({"embeddings": [[1.0]]}).encode()
        for caller in ("claude", "codex", "antigravity"):
            self.run_embed(lambda *a, **k: Resp(body), caller=caller)
        self.assertEqual(sorted(r["caller"] for r in self.rows()), ["antigravity", "claude", "codex"])

    def test_journal_start_failure_prevents_network(self):
        net = mock.Mock()
        with mock.patch("v7_harness.invocation.start_attempt", side_effect=OSError("db down")):
            out, _ = self.run_embed(net)
        self.assertIsInstance(out, OSError)
        net.assert_not_called()


if __name__ == "__main__":
    unittest.main()
