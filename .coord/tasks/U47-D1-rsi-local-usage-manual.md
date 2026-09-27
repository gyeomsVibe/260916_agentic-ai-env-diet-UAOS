```contract
work_id: U47-D1a
worker: apply
goal: Fold the local model's pilot_local usage rows (fake 1/1 rows excluded, joined to the pilot ledger by work_id) into `rsi report` and add the frozen test.
inputs:
- v7_harness/rsi.py sha256=0132e8f2f9da62a8a8c23766b727b37882ec6e72029db90589711c9813e69ddd
- v7_harness/cli.py sha256=8bbb119fe9ae4882ef21b5b9539dc6f791a22be6c24224fc9368260fa13ec710
allow:
- v7_harness/rsi.py
- v7_harness/cli.py
- tests/test_u47_d1_local_usage.py
acceptance: python tests/u47_d1_check.py
forbidden: design changes; edits outside allow; editing or deleting other tests; deleting or rewriting usage log rows; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 600
remote_budget_tokens: 0
```

## Instructions for the worker

===FILE: tests/test_u47_d1_local_usage.py===
"""U47-D1 frozen acceptance (written by Claude): `rsi report` folds the local-model usage log in, without fake rows.

docs/48 §2 found 64 of 193 `pilot_local` rows were test leftovers with 1 input and 1 output token. They stay in the
file (never deleted) but must not count as real local work. Real rows are joined to the pilot ledger by work_id so a
local call can be traced to its pilot outcome.
"""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import rsi
from v7_harness.cli import main


def _write(path: Path, rows: list) -> None:
    path.write_text("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows), encoding="utf-8")


class LocalUsageTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log = Path(self._tmp.name) / "usage.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def test_fake_rows_are_counted_not_summed(self):
        _write(self.log, [
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 20.5, "model": "m", "work_id": "A",
             "input_tokens": 700, "output_tokens": 20},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 0.1, "input_tokens": 1, "output_tokens": 1},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 0.1, "input_tokens": 1, "output_tokens": 1},
        ])
        out = rsi.local_usage(self.log, [])
        self.assertEqual(3, out["rows"])
        self.assertEqual(2, out["fake_rows"])
        self.assertEqual(1, out["real"]["runs"])
        self.assertEqual(700, out["real"]["input_tokens"])
        self.assertEqual(20, out["real"]["output_tokens"])
        self.assertEqual(20.5, out["real"]["wall_s"])

    def test_other_events_and_bad_lines_are_ignored_but_counted(self):
        _write(self.log, [
            {"event": "ask", "input_tokens": 50, "output_tokens": 5},
            "not json",
            {"event": "pilot_local", "status": "ERROR", "elapsed_s": 3.0, "model": "m", "work_id": "B"},
        ])
        out = rsi.local_usage(self.log, [])
        self.assertEqual(1, out["rows"])
        self.assertEqual(1, out["unreadable"])
        self.assertEqual(1, out["real"]["runs"])
        self.assertEqual({"ERROR": 1}, out["real"]["by_status"])
        self.assertEqual(0, out["real"]["input_tokens"])

    def test_join_on_work_id(self):
        _write(self.log, [
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 1.0, "model": "m", "work_id": "A",
             "input_tokens": 10, "output_tokens": 2},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 1.0, "model": "m", "work_id": "Z",
             "input_tokens": 10, "output_tokens": 2},
            {"event": "pilot_local", "status": "GENERATED", "elapsed_s": 1.0, "input_tokens": 10, "output_tokens": 2},
        ])
        ledger = [{"kind": "pilot", "work_id": "A", "outcome": "PASS"}]
        out = rsi.local_usage(self.log, ledger)
        self.assertEqual(1, out["joined"])
        self.assertEqual(1, out["unjoined"])
        self.assertEqual(1, out["no_work_id"])
        self.assertEqual({"m": 2, "unknown": 1}, out["real"]["by_model"])

    def test_missing_log_is_reported_not_zero(self):
        out = rsi.local_usage(Path(self._tmp.name) / "absent.jsonl", [])
        self.assertFalse(out["present"])
        self.assertEqual(0, out["rows"])

    def test_note_keeps_cost_honest(self):
        _write(self.log, [])
        self.assertIn("not zero total cost", rsi.local_usage(self.log, [])["note"])

    def test_rsi_report_cli_includes_local(self):
        _write(self.log, [{"event": "pilot_local", "status": "GENERATED", "elapsed_s": 2.0, "model": "m",
                           "work_id": "A", "input_tokens": 9, "output_tokens": 3}])
        buffer = io.StringIO()
        with mock.patch("v7_harness.olla.USAGE_LOG", self.log), contextlib.redirect_stdout(buffer):
            self.assertEqual(0, main(["rsi", "report", "--project", self._tmp.name]))
        local = json.loads(buffer.getvalue())["local"]
        self.assertEqual(1, local["real"]["runs"])
        self.assertEqual(9, local["real"]["input_tokens"])


if __name__ == "__main__":
    unittest.main()
===END===

===EDIT: v7_harness/rsi.py===
<<<<<<< SEARCH
# ---------------------------------------------------------------- propose
=======
def local_usage(usage_log: Path, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """U47-D1: the local model's `pilot_local` rows, without the fake ones, joined to the pilot ledger by work_id.

    A row with exactly 1 input and 1 output token is a test leftover (docs/48 §2: 64 of 193). It stays in the file and
    is counted as `fake_rows`, never summed. Unreadable lines are counted, not silently dropped.
    """
    path = Path(usage_log)
    ledger_ids = {str(row["work_id"]) for row in rows if row.get("work_id")}
    real: dict[str, Any] = {"runs": 0, "input_tokens": 0, "output_tokens": 0, "wall_s": 0.0,
                            "by_status": Counter(), "by_model": Counter()}
    out: dict[str, Any] = {"source": str(path), "present": path.is_file(), "rows": 0, "unreadable": 0,
                           "fake_rows": 0, "joined": 0, "unjoined": 0, "no_work_id": 0}
    lines = path.read_text(encoding="utf-8").splitlines() if out["present"] else []
    for line in lines:
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            out["unreadable"] += 1
            continue
        if not isinstance(rec, dict) or rec.get("event") != "pilot_local":
            continue
        out["rows"] += 1
        tokens_in, tokens_out = rec.get("input_tokens"), rec.get("output_tokens")
        if tokens_in == 1 and tokens_out == 1:
            out["fake_rows"] += 1
            continue
        real["runs"] += 1
        real["input_tokens"] += tokens_in if isinstance(tokens_in, int) and not isinstance(tokens_in, bool) else 0
        real["output_tokens"] += tokens_out if isinstance(tokens_out, int) and not isinstance(tokens_out, bool) else 0
        elapsed = rec.get("elapsed_s")
        real["wall_s"] += float(elapsed) if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool) else 0.0
        real["by_status"][str(rec.get("status") or "unknown")] += 1
        real["by_model"][str(rec.get("model") or "unknown")] += 1
        work_id = rec.get("work_id")
        if not work_id:
            out["no_work_id"] += 1
        elif str(work_id) in ledger_ids:
            out["joined"] += 1
        else:
            out["unjoined"] += 1
    real["wall_s"] = round(real["wall_s"], 1)
    real["by_status"] = dict(real["by_status"])
    real["by_model"] = dict(real["by_model"])
    out["real"] = real
    out["note"] = ("Local tokens use no paid API tokens but are not zero total cost (local inference, wall time, "
                   "electricity); account savings stay UNMEASURED.")
    return out


# ---------------------------------------------------------------- propose
>>>>>>> REPLACE

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    from .rsi import analyze, load_policy, load_rows, open_trials, read_decisions

    project = Path(args.project)
    policy = load_policy(project)
    rows = load_rows(project)
    report = analyze(rows, policy)
=======
    from .olla import USAGE_LOG
    from .rsi import analyze, load_policy, load_rows, local_usage, open_trials, read_decisions

    project = Path(args.project)
    policy = load_policy(project)
    rows = load_rows(project)
    report = analyze(rows, policy)
    # U47-D1: the local model's real work (fake 1/1 rows excluded), joined to the pilot ledger by work_id.
    report["local"] = local_usage(USAGE_LOG, rows)
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
