"""U130: the default card pipeline puts Ollama and Antigravity into every card, enforced by the runtime.

A card manual comes from one template with four stage slots; `card audit` passes only with a real Ollama call and an
Antigravity audit or review in the ledger, or a verified skip row; the commit gate runs the audit on new code."""

import datetime
import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import card_pipeline as cp


def _olla_ts(epoch: float) -> str:
    return datetime.datetime.fromtimestamp(epoch).isoformat(timespec="seconds")


def _rows(desk: Path) -> list[dict]:
    path = desk / ".coord" / "usage" / "runs.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


class TemplateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_manual_has_all_slots_and_default_workers(self):
        out = cp.new_manual(self.desk, "U900", "Demo card", now=1000.0)
        text = Path(out["manual"]).read_text(encoding="utf-8")
        self.assertTrue(out["created"])
        self.assertEqual(cp.missing_slots(text), [])
        self.assertIn("U900", text)
        self.assertIn("Demo card", text)
        for word in ("Ollama", "Antigravity", "local_draft", "worker: local", "pilot review --reviewer agy"):
            self.assertIn(word, text)
        record = json.loads((self.desk / ".coord" / "cards" / "U900.json").read_text(encoding="utf-8"))
        self.assertEqual(record["started_at"], 1000.0)

    def test_new_manual_never_overwrites(self):
        cp.new_manual(self.desk, "U900", "Demo", now=1000.0)
        manual = self.desk / ".work" / "cards" / "U900_manual.md"
        manual.write_text("mine", encoding="utf-8")
        out = cp.new_manual(self.desk, "U900", "Other", now=2000.0)
        self.assertFalse(out["created"])
        self.assertEqual(manual.read_text(encoding="utf-8"), "mine")
        self.assertEqual(out["started_at"], 1000.0)

    def test_bad_card_id_refused(self):
        for bad in ("../U1", "u130", "U", "U12/x"):
            with self.assertRaises(ValueError):
                cp.new_manual(self.desk, bad, "t")

    def test_missing_slots_names_each_gap(self):
        self.assertEqual(len(cp.missing_slots("free-form manual")), 4)
        text = cp.TEMPLATE.format(card="U1", title="t").replace("## Stage 3", "## Step 3")
        self.assertEqual(cp.missing_slots(text), ["Stage 3 Execute"])
        no_workers = "\n".join(line for line in cp.TEMPLATE.format(card="U1", title="t").splitlines()
                               if not (line.startswith("Workers:") and "agy" in line and "review" in line.lower()))
        self.assertTrue(any(gap.endswith("Workers line") for gap in cp.missing_slots(no_workers)))

    def test_a_later_workers_line_does_not_fill_an_earlier_stage(self):
        text = "## Stage 1 - Research\n\n## Stage 2 - MIA\nWorkers: a\n## Stage 3 - Execute\nWorkers: b\n" \
               "## Stage 4 - Verify\nWorkers: c\n"
        self.assertEqual(cp.missing_slots(text), ["Stage 1 Research: Workers line"])

    def test_probe_targets_the_local_tags_endpoint(self):
        self.assertEqual(cp.OLLAMA_TAGS, "http://127.0.0.1:11434/api/tags")
        self.assertTrue(cp.TEMPLATE.startswith("# {card} contract manual"))

    def test_broken_records_read_as_missing(self):
        (self.desk / ".coord" / "cards").mkdir(parents=True)
        (self.desk / ".coord" / "cards" / "U903.json").write_text("{}", encoding="utf-8")
        (self.desk / ".coord" / "windows").mkdir(parents=True)
        (self.desk / ".coord" / "windows" / "U903.json").write_text('{"tools": []}', encoding="utf-8")
        self.assertIsNone(cp.started_at(self.desk, "U903"))
        self.assertFalse(cp.audit(self.desk, "U903")["ok"])


class CardOfTest(unittest.TestCase):
    def test_message_line_wins_over_branch(self):
        self.assertEqual(cp.card_of("fix: x\n\nCard: U131\n", "claude/u130-default"), "U131")

    def test_branch_fallback_and_none(self):
        self.assertEqual(cp.card_of("fix: x", "claude/u130-default-card-pipeline"), "U130")
        self.assertEqual(cp.card_of("fix: x", "codex/u98-d-lint"), "U98")
        self.assertIsNone(cp.card_of("fix: x", "main"))
        self.assertIsNone(cp.card_of("fix: x", "claude/ecstatic-hermann-93a9d5"))


class ClaimTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)
        self.log = self.desk / "olla_usage.jsonl"
        self.start = 1_790_000_000.0
        cp.new_manual(self.desk, "U900", "Demo", now=self.start)

    def tearDown(self):
        self.tmp.cleanup()

    def _log(self, rows):
        _write_jsonl(self.log, rows)

    def test_claims_only_real_calls_of_the_session_inside_the_card_window(self):
        s = self.start
        self._log([
            {"ts": _olla_ts(s + 10), "event": "ask", "session": "A", "caller": "claude", "input_tokens": 500,
             "output_tokens": 50},
            {"ts": _olla_ts(s + 20), "event": "digest", "session": "A", "caller": "claude", "cached": False,
             "paid_tokens_if_read": 9000, "paid_tokens_digest": 300},
            {"ts": _olla_ts(s + 30), "event": "digest", "session": "A", "cached": True, "paid_tokens_if_read": 9000},
            {"ts": _olla_ts(s + 40), "event": "hint_plan", "session": "A"},
            {"ts": _olla_ts(s + 50), "event": "ask", "session": "B", "input_tokens": 700, "output_tokens": 70},
            {"ts": _olla_ts(s - 100), "event": "ask", "session": "A", "input_tokens": 900, "output_tokens": 9},
            {"ts": _olla_ts(s + 60), "event": "ask", "session": "A", "input_tokens": 0, "output_tokens": 0},
        ])
        out = cp.claim(self.desk, "U900", "A", self.log, now=s + 1000)
        self.assertEqual(out, {"ok": True, "card": "U900", "claimed": 2})
        rows = _rows(self.desk)
        self.assertEqual([r["work_id"] for r in rows], ["U900-olla-1", "U900-olla-2"])
        self.assertEqual([r["input_tokens"] for r in rows], [500, 9000])
        self.assertTrue(all(r["worker"] == "ollama" and r["kind"] == "olla_mcp" for r in rows))

    def test_a_call_is_claimed_once_across_cards(self):
        cp.new_manual(self.desk, "U901", "Other", now=self.start)
        self._log([{"ts": _olla_ts(self.start + 5), "event": "ask", "session": "A", "input_tokens": 5,
                    "output_tokens": 1}])
        self.assertEqual(cp.claim(self.desk, "U900", "A", self.log, now=self.start + 9)["claimed"], 1)
        self.assertEqual(cp.claim(self.desk, "U901", "A", self.log, now=self.start + 9)["claimed"], 0)
        self.assertEqual(cp.claim(self.desk, "U900", "A", self.log, now=self.start + 9)["claimed"], 0)
        self.assertEqual(len(_rows(self.desk)), 1)

    def test_card_not_opened(self):
        out = cp.claim(self.desk, "U999", "A", self.log, now=self.start)
        self.assertEqual(out, {"ok": False, "card": "U999", "error": "CARD_NOT_OPENED"})

    def test_window_record_opens_a_card(self):
        win = self.desk / ".coord" / "windows" / "U902.json"
        win.parent.mkdir(parents=True, exist_ok=True)
        win.write_text(json.dumps({"card": "U902", "tools": {"antigravity": {"id": "c1", "opened_at": 50.0}}}),
                       encoding="utf-8")
        self.assertEqual(cp.started_at(self.desk, "U902"), 50.0)


class SkipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_ollama_down_needs_a_failed_probe(self):
        out = cp.skip(self.desk, "U900", "ollama", "OLLAMA_DOWN", "probe", probe=lambda: True)
        self.assertEqual(out["error"], "OLLAMA_UP")
        out = cp.skip(self.desk, "U900", "ollama", "OLLAMA_DOWN", "probe", probe=lambda: False)
        self.assertTrue(out["ok"])
        row = _rows(self.desk)[-1]
        self.assertEqual((row["work_id"], row["kind"], row["skip_reason"]), ("U900-skip-ollama", "card_skip",
                                                                            "OLLAMA_DOWN"))

    def test_agy_limited_needs_the_desk(self):
        out = cp.skip(self.desk, "U900", "agy", "AGY_LIMITED", "desk", agy_state=lambda: "IDLE")
        self.assertEqual(out["error"], "AGY_AVAILABLE")
        self.assertTrue(cp.skip(self.desk, "U900", "agy", "AGY_LIMITED", "desk", agy_state=lambda: "LIMITED")["ok"])

    def test_reason_slot_and_evidence_checks(self):
        self.assertEqual(cp.skip(self.desk, "U900", "x", "TASK_CLASS", "e" * 30)["error"], "BAD_SLOT")
        self.assertEqual(cp.skip(self.desk, "U900", "agy", "LAZY", "e" * 30)["error"], "BAD_REASON")
        self.assertEqual(cp.skip(self.desk, "U900", "agy", "OLLAMA_DOWN", "e" * 30)["error"], "BAD_REASON")
        self.assertEqual(cp.skip(self.desk, "U900", "ollama", "TASK_CLASS", "   ")["error"], "NO_EVIDENCE")
        self.assertEqual(cp.skip(self.desk, "U900", "ollama", "TASK_CLASS", "too short")["error"],
                         "EVIDENCE_TOO_SHORT")
        self.assertEqual(_rows(self.desk), [])


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.desk = Path(self.tmp.name)
        self.ledger = self.desk / ".coord" / "usage" / "runs.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def _ledger(self, rows):
        _write_jsonl(self.ledger, rows)

    def test_empty_card_fails_with_both_slots_missing(self):
        out = cp.audit(self.desk, "U900")
        self.assertFalse(out["ok"])
        self.assertEqual(out["missing"], ["ollama", "agy"])

    def test_real_ollama_row_and_agy_conversation_reply_pass(self):
        self._ledger([{"work_id": "U900-L1", "worker": "local", "input_tokens": 3000, "outcome": "REWORK"},
                      {"work_id": "U9000-L1", "worker": "agy", "input_tokens": 3000}])
        win = self.desk / ".coord" / "windows" / "U900.json"
        win.parent.mkdir(parents=True, exist_ok=True)
        win.write_text(json.dumps({"card": "U900", "tools": {"antigravity": {"id": "conv-1", "opened_at": 1.0}}}),
                       encoding="utf-8")
        auto = self.desk / ".coord" / "mailbox" / "delivery" / "agy_auto.jsonl"
        _write_jsonl(auto, [{"state": "FAILED", "conversation_id": "conv-1", "reply_id": "relay_00"},
                            {"state": "ANSWERED", "conversation_id": "conv-1", "reply_id": "relay_ab"}])
        out = cp.audit(self.desk, "U900")
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["missing"], [])
        self.assertTrue(any("relay_ab" in item for item in out["agy"]))

    def test_zero_token_ollama_row_and_other_cards_do_not_count(self):
        self._ledger([{"work_id": "U900-L1", "worker": "local", "input_tokens": 0},
                      {"work_id": "U9001-L1", "worker": "ollama", "input_tokens": 50},
                      {"work_id": "U900-L2", "worker": "agy", "input_tokens": 10}])
        out = cp.audit(self.desk, "U900")
        self.assertEqual(out["missing"], ["ollama"])

    def test_agy_review_file_needs_a_terminal_verdict(self):
        self._ledger([{"work_id": "U900-L1", "worker": "ollama", "input_tokens": 10}])
        run = self.desk / ".coord" / "runs" / "U900-L1"
        run.mkdir(parents=True)
        (run / "review_agy.json").write_text(json.dumps({"verdict": "PENDING"}), encoding="utf-8")
        self.assertEqual(cp.audit(self.desk, "U900", run_dirs=[self.desk / ".coord"])["missing"], ["agy"])
        (run / "review_agy.json").write_text(json.dumps({"verdict": "REVISE"}), encoding="utf-8")
        self.assertTrue(cp.audit(self.desk, "U900", run_dirs=[self.desk / ".coord"])["ok"])

    def test_skip_rows_count_but_task_class_not_for_code(self):
        cp.skip(self.desk, "U900", "ollama", "TASK_CLASS", "web search only; Ollama cannot browse")
        cp.skip(self.desk, "U900", "agy", "AGY_LIMITED", "desk LIMITED", agy_state=lambda: "ABSENT")
        self.assertTrue(cp.audit(self.desk, "U900")["ok"])
        self.assertTrue(cp.audit(self.desk, "U900", code_paths=["docs/x.md"])["ok"])
        out = cp.audit(self.desk, "U900", code_paths=["v7_harness/x.py"])
        self.assertEqual(out["missing"], ["ollama"])


if __name__ == "__main__":
    unittest.main()
