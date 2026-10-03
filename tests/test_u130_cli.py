"""U130: `uaos card new|claim|skip|audit`, `coord window` refusing a manual without the four stage slots, and
`rsi ship` refusing a card whose `card audit` fails."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import card_pipeline, cli


def run(argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(argv)
    return code, out.getvalue()


class CardCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _ledger(self, rows):
        path = self.root / ".coord" / "usage" / "runs.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_card_new_writes_the_template_once(self):
        code, out = run(["card", "new", "--project", str(self.root), "--card", "U900", "--title", "Demo"])
        self.assertEqual(code, 0)
        manual = self.root / ".work" / "cards" / "U900_manual.md"
        self.assertEqual(card_pipeline.missing_slots(manual.read_text(encoding="utf-8")), [])
        self.assertTrue(json.loads(out)["created"])
        code, out = run(["card", "new", "--project", str(self.root), "--card", "U900", "--title", "Other"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["created"])

    def test_card_new_refuses_a_bad_id(self):
        code, _ = run(["card", "new", "--project", str(self.root), "--card", "../U1", "--title", "x"])
        self.assertEqual(code, 2)

    def test_card_audit_exit_code_follows_the_evidence(self):
        code, out = run(["card", "audit", "--project", str(self.root), "--card", "U900"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["missing"], ["ollama", "agy"])
        self._ledger([{"work_id": "U900-L1", "worker": "local", "input_tokens": 10},
                      {"work_id": "U900-R1", "worker": "agy", "input_tokens": 10}])
        code, out = run(["card", "audit", "--project", str(self.root), "--card", "U900"])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(out)["ok"])

    def test_card_audit_reads_reviews_in_the_project_run_dirs(self):
        self._ledger([{"work_id": "U900-L1", "worker": "local", "input_tokens": 10}])
        review = self.root / ".coord" / "runs" / "U900-L1" / "review_agy.json"
        review.parent.mkdir(parents=True)
        review.write_text(json.dumps({"verdict": "PASS"}), encoding="utf-8")
        code, _ = run(["card", "audit", "--project", str(self.root), "--card", "U900"])
        self.assertEqual(code, 0)

    def test_card_skip_refuses_short_task_class_evidence(self):
        code, out = run(["card", "skip", "--project", str(self.root), "--card", "U900", "--slot", "agy",
                         "--reason", "TASK_CLASS", "--evidence", "short"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"], "EVIDENCE_TOO_SHORT")

    def test_card_skip_records_a_valid_row(self):
        code, _ = run(["card", "skip", "--project", str(self.root), "--card", "U900", "--slot", "agy",
                       "--reason", "TASK_CLASS", "--evidence", "a one-line doc typo has nothing to audit"])
        self.assertEqual(code, 0)
        rows = card_pipeline._jsonl(card_pipeline._ledger(self.root))
        self.assertEqual(rows[-1]["skip_reason"], "TASK_CLASS")

    def test_card_claim_imports_this_session_calls(self):
        run(["card", "new", "--project", str(self.root), "--card", "U900", "--title", "Demo"])
        log = self.root / "usage.jsonl"
        log.write_text(json.dumps({"ts": "2999-01-01T00:00:00", "event": "ask", "session": "s1",
                                   "input_tokens": 50, "output_tokens": 5}) + "\n", encoding="utf-8")
        with mock.patch("time.time", return_value=32503680000.0 + 10):  # 3000-01-01: after the call's ts
            code, out = run(["card", "claim", "--project", str(self.root), "--card", "U900", "--session", "s1",
                             "--olla-log", str(log)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["claimed"], 1)

    def test_card_claim_needs_an_opened_card(self):
        code, out = run(["card", "claim", "--project", str(self.root), "--card", "U900", "--session", "s1",
                         "--olla-log", str(self.root / "none.jsonl")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["error"], "CARD_NOT_OPENED")


class WindowSlotTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _window(self, text):
        prompt = self.root / "manual.md"
        prompt.write_text(text, encoding="utf-8")
        with mock.patch("v7_harness.coord.windows.open_window", return_value={"id": "w1"}) as opened:
            code, out = run(["coord", "window", "--project", str(self.root), "--card", "U900", "--tool", "codex",
                             "--title", "t", "--prompt-file", str(prompt)])
        return code, out, opened

    def test_free_form_manual_is_refused(self):
        code, out, opened = self._window("# U900\n\nJust do it.\n")
        self.assertEqual(code, 2)
        opened.assert_not_called()
        self.assertIn("Stage 1 Research", json.loads(out)["missing_slots"])

    def test_template_manual_opens_the_window(self):
        code, _, opened = self._window(card_pipeline.TEMPLATE.format(card="U900", title="t"))
        self.assertEqual(code, 0)
        opened.assert_called_once()


class ShipAuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "approval.json").write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _ship(self, packet):
        (self.root / "packet.json").write_text(json.dumps(packet), encoding="utf-8")
        with mock.patch("v7_harness.rsi_release.ship_release", return_value={"status": "DRY_RUN"}) as shipped:
            code, out = run(["rsi", "ship", "--project", str(self.root), "--packet", str(self.root / "packet.json"),
                             "--approval", str(self.root / "approval.json")])
        return code, out, shipped

    def test_unaudited_card_is_not_shipped(self):
        code, out, shipped = self._ship({"work_id": "U900-rsi", "changed_files": ["v7_harness/x.py"]})
        self.assertEqual(code, 1)
        shipped.assert_not_called()
        self.assertIn("CARD_AUDIT", out)

    def test_packet_without_a_card_is_not_shipped(self):
        code, out, shipped = self._ship({"work_id": "release", "changed_files": []})
        self.assertEqual(code, 1)
        shipped.assert_not_called()
        self.assertIn("CARD_AUDIT", out)

    def test_audited_card_ships(self):
        path = self.root / ".coord" / "usage" / "runs.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"work_id": "U900-L1", "worker": "local", "input_tokens": 10}) + "\n"
                        + json.dumps({"work_id": "U900-R1", "worker": "agy", "input_tokens": 10}) + "\n",
                        encoding="utf-8")
        code, _, shipped = self._ship({"work_id": "U900-rsi", "card": "U900", "changed_files": []})
        self.assertEqual(code, 0)
        shipped.assert_called_once()


if __name__ == "__main__":
    unittest.main()
