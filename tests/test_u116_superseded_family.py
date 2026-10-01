"""U116: a BLOCKED step is also cleared by a later PASS of its retry family or of the apply run that replaced it.

Seen 2026-10-01 (wakes wake_4ef34f4c… and wake_b990d00f…, two in one hour): the P1 wake re-listed U106-A2, U107-B,
U109-S, U108-O, U111-B, U113-D, U115-L and U115-L2 although each card had since passed. U88 only knew the `-R<n>` retry
name; the pilot retries since U106 are named `<step><n>` (U113-D → D2 → D3), `<step>-P`/`<step>-agy` (U106-A2 →
U106-A2-P), or are an apply run whose contract manual says `apply_after: <failed work_id>` (U115-L2 → U115-A1, U98-D).
The U88 acceptance (tests/test_u88_p1_superseded.py) stays unchanged: a sibling step such as U86-F1 never clears U86.
Fixed acceptance written by the judge (claude) first.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from v7_harness.coord.mailbox import Mailbox
from v7_harness.coord.sentinel import run_sentinel_cycle

BLOCKED_AT = "2026-10-01T10:00:00+09:00"
BEFORE = datetime.fromisoformat(BLOCKED_AT).timestamp() - 60
AFTER = datetime.fromisoformat(BLOCKED_AT).timestamp() + 60


def _project(directory: str, rows: list[dict], manuals: dict[str, str] | None = None) -> tuple[Path, Mailbox]:
    root = Path(directory)
    (root / ".coord" / "mailbox").mkdir(parents=True)
    ledger = root / ".coord" / "usage" / "runs.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    tasks = root / ".coord" / "tasks"
    tasks.mkdir()
    for work_id, after in (manuals or {}).items():
        (tasks / f"{work_id}-x-apply-manual.md").write_text(
            f"---\nwork_id: {work_id}\nworker: apply\napply_after: {after}\n---\n# manual\n", encoding="utf-8")
    return root, Mailbox(root / ".coord" / "mailbox")


def _pass(work_id: str, ts: float) -> dict:
    return {"kind": "pilot", "work_id": work_id, "outcome": "PASS", "worker": "apply", "ts": ts}


def _blocked(step: str) -> dict:
    return {"kind": "BLOCKED", "step": step, "ts": BLOCKED_AT, "actor": "claude"}


class SupersededFamilyTests(unittest.TestCase):
    def test_numbered_and_suffixed_retries_clear_their_block(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U113-D3", AFTER), _pass("U106-A2-P", AFTER), _pass("U107-B-agy", AFTER)])
            for step in ("U113-D", "U106-A2", "U107-B"):
                box.publish(f"b-{step}", _blocked(step))
            result = run_sentinel_cycle(root, box)
            self.assertFalse(result["p1_wake_emitted"])
            self.assertEqual(["U106-A2", "U107-B", "U113-D"], sorted(result["p1_superseded"]))

    def test_an_apply_after_pass_clears_the_failed_delegate_and_its_family(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U115-A1", AFTER)], manuals={"U115-A1": "U115-L2"})
            box.publish("b-l", _blocked("U115-L"))
            box.publish("b-l2", _blocked("U115-L2"))
            result = run_sentinel_cycle(root, box)
            self.assertFalse(result["p1_wake_emitted"])
            self.assertEqual(["U115-L", "U115-L2"], sorted(result["p1_superseded"]))

    def test_an_earlier_pass_or_another_family_keeps_the_alert(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U113-D3", BEFORE), _pass("U113-P3", AFTER), _pass("U1130-D", AFTER),
                                     _pass("U115-A1", AFTER)])
            box.publish("b-d", _blocked("U113-D"))
            box.publish("b-l", _blocked("U115-L"))  # no manual links U115-A1 to U115-L here
            result = run_sentinel_cycle(root, box)
            self.assertTrue(result["p1_wake_emitted"])
            self.assertEqual([], result["p1_superseded"])

    def test_a_card_level_id_is_not_a_family(self) -> None:
        # U86 must not be read as family "U": a PASS of U87 or U86-F1 never clears it (U88 acceptance).
        with tempfile.TemporaryDirectory() as d:
            root, box = _project(d, [_pass("U87", AFTER), _pass("U86-F1", AFTER)])
            box.publish("b86", _blocked("U86"))
            self.assertTrue(run_sentinel_cycle(root, box)["p1_wake_emitted"])


if __name__ == "__main__":
    unittest.main()
