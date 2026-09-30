```contract
work_id: U97-I-R1
worker: apply
goal: `coord inbox` lists only letters that may need action, counts routine pilot RUN notices instead of listing them, and caps each summary; `--all` keeps the full listing.
inputs:
- v7_harness/cli.py sha256=0893f9f43a9f1206ba674e6250b61b1b78a924f07c3bb48635f313cad9e9092c
- .coord/PLAN.md sha256=5a6c655663f375aacc5435bd3400929e7afd47ef2cc26827ab36034d89bce86a
allow:
- v7_harness/cli.py
- tests/test_u97i_inbox_brief.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u97i_inbox_brief tests.test_u32_sentinel_bell tests.test_u48_r1_runtime_install
forbidden: design changes; edits outside allow; editing or weakening existing tests; acking, moving or deleting any letter; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. R1: the first dry run failed because the test never created the mailbox root (MailboxRejected); only the test's setUp changed. Receipt (2026-09-30): the rules have every tool read `coord inbox` at session start. On this project it printed 80,966 bytes for 480 letters; 298 of them were `RUN` notices. The pilot sends those to the tool that ran it, and the prompt hook already relays them. Every later paid call re-reads that output as context.

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_inbox.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_inbox.set_defaults(func=cmd_coord_inbox)
=======
    p_coord_inbox.add_argument("--project", default=".", help="Project root (default: .)")
    p_coord_inbox.add_argument("--all", action="store_true",
                               help="List routine RUN notices too, with full summaries (U97-I)")
    p_coord_inbox.set_defaults(func=cmd_coord_inbox)
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
def cmd_coord_inbox(args: argparse.Namespace) -> int:
    """U32b: list what waits in the voicemail without claiming it."""
    from .coord.mailbox import Mailbox

    mailbox_dir = Path(args.project) / ".coord" / "mailbox"
    if not mailbox_dir.is_dir():
        print(json.dumps({"ok": True, "messages": [], "bad": []}, ensure_ascii=False))
        return 0
    box = Mailbox(mailbox_dir)
    messages = []
    for message_id, payload in box.peek():
        data = payload if isinstance(payload, dict) else {}
        messages.append({
            "id": message_id,
            "kind": data.get("kind") or ("P1" if data.get("p1_alert") else None),
            "step": data.get("step"),
            "summary": data.get("summary") or data.get("wake_reason"),
        })
    print(json.dumps({"ok": True, "messages": messages, "bad": box.list_bad()}, ensure_ascii=False))
    return 0
=======
# U97-I: pilot RUN notices go to the tool that ran the pilot, and the prompt hook already relays them; listing them
# made the start-of-session inbox 80,966 bytes (298 of 480 letters). They are counted, never acked or moved.
INBOX_ROUTINE_KINDS = frozenset({"RUN"})
# 200 characters keep a letter's who/what/verdict; the full text stays in the letter and under `--all`.
INBOX_SUMMARY_LIMIT = 200


def cmd_coord_inbox(args: argparse.Namespace) -> int:
    """U32b: list what waits in the voicemail without claiming it (U97-I: routine RUN notices only counted)."""
    from .coord.mailbox import Mailbox

    mailbox_dir = Path(args.project) / ".coord" / "mailbox"
    if not mailbox_dir.is_dir():
        print(json.dumps({"ok": True, "messages": [], "bad": []}, ensure_ascii=False))
        return 0
    box = Mailbox(mailbox_dir)
    show_all = bool(getattr(args, "all", False))
    messages = []
    routine: dict[str, int] = {}
    for message_id, payload in box.peek():
        data = payload if isinstance(payload, dict) else {}
        kind = data.get("kind") or ("P1" if data.get("p1_alert") else None)
        if kind in INBOX_ROUTINE_KINDS and not show_all:
            routine[kind] = routine.get(kind, 0) + 1
            continue
        summary = data.get("summary") or data.get("wake_reason")
        if not show_all and isinstance(summary, str) and len(summary) > INBOX_SUMMARY_LIMIT:
            summary = summary[:INBOX_SUMMARY_LIMIT] + "…"
        messages.append({"id": message_id, "kind": kind, "step": data.get("step"), "summary": summary})
    result: dict[str, Any] = {"ok": True, "messages": messages, "bad": box.list_bad()}
    if routine:
        result["routine_counted"] = routine  # listed in full with --all
    print(json.dumps(result, ensure_ascii=False))
    return 0
>>>>>>> REPLACE
===END===

===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
`AGENTS.md`, `tests/test_u96d_agents_budget.py` |
=======
`AGENTS.md`, `tests/test_u96d_agents_budget.py` |
| U97-I | REVIEW (Claude 설계, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 영수증: 규칙상 세션마다 읽는 `coord inbox`가 이 프로젝트에서 80,966 B(편지 480통, 그중 파일럿 RUN 알림 298통)를 출력해 이후 모든 유료 호출의 문맥을 키웠다. 조치: RUN 알림은 목록 대신 개수(`routine_counted`)로만 보이고 요약은 200자에서 자른다. `--all`은 전체 목록. 편지는 확인(ack)·이동·삭제하지 않는다. — `v7_harness/cli.py`, `tests/test_u97i_inbox_brief.py` |
>>>>>>> REPLACE
===END===

===FILE: tests/test_u97i_inbox_brief.py===
"""U97-I: the start-of-session inbox lists what may need action and only counts routine RUN notices."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness.cli import INBOX_SUMMARY_LIMIT, main
from v7_harness.coord.mailbox import Mailbox


class InboxBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(self.project / ".coord" / "mailbox")
        for i in range(3):
            self.box.publish(f"evt_run_{i}", {"kind": "RUN", "summary": f"pilot U{i}: SUCCEEDED/PASS/APPLIED"})
        self.box.publish("verdict_req", {"kind": "VERDICT_REQUEST", "summary": "x" * 500})
        self.box.publish("wake_p1", {"p1_alert": True, "wake_reason": "STALE_LOCK"})

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _inbox(self, *extra: str) -> dict:
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(0, main(["coord", "inbox", "--project", str(self.project), *extra]))
        return json.loads(out.getvalue())

    def test_default_counts_run_notices_and_caps_summaries(self) -> None:
        result = self._inbox()
        self.assertEqual({"verdict_req", "wake_p1"}, {m["id"] for m in result["messages"]})
        self.assertEqual({"RUN": 3}, result["routine_counted"])
        verdict = next(m for m in result["messages"] if m["id"] == "verdict_req")
        self.assertEqual(INBOX_SUMMARY_LIMIT + 1, len(verdict["summary"]))

    def test_all_lists_everything_in_full(self) -> None:
        result = self._inbox("--all")
        self.assertEqual(5, len(result["messages"]))
        self.assertNotIn("routine_counted", result)
        verdict = next(m for m in result["messages"] if m["id"] == "verdict_req")
        self.assertEqual("x" * 500, verdict["summary"])

    def test_nothing_is_acked_or_moved(self) -> None:
        before = sorted(p.name for p in (self.project / ".coord" / "mailbox" / "inbox").glob("*.json"))
        self._inbox()
        after = sorted(p.name for p in (self.project / ".coord" / "mailbox" / "inbox").glob("*.json"))
        self.assertEqual(before, after)
        self.assertEqual(5, len(after))


if __name__ == "__main__":
    unittest.main()
===END===
