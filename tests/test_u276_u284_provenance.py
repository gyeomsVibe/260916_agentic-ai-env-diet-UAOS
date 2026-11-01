"""U276 + U284: resolve the true author tool of a historical pilot run and of a commit/PR.

Receipts (2026-11-02 research, .work/u276_u284/RECEIPTS.md):
- U284: PR #171 (codex/u209-r2-release) and PR #160 (codex/u195-pending-opt-in) carry only commits with a
  `Co-Authored-By: Claude` trailer, yet U283 `author_tool` names the author "codex" from the branch prefix, so a
  Claude PASS letter would have counted as an independent peer audit (author == judge).
- U276: 73 of 98 historical `.coord/pilot/runs/*` have no `worker` file, so `_native_records` cannot name their
  author; the broker lease owner is hard-coded "antigravity" (pilot.py) even for apply/claude/ollama runs
  (U44-PROBE worker=claude, lease owner=antigravity), so it is no author evidence.
Rule: every independent signal is collected; one tool -> RESOLVED, several -> CONFLICT, none -> UNKNOWN.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.calculator_gate import audit_errors
from v7_harness.provenance import (
    commit_trailer_tools,
    normalize_tool,
    resolve_commit_author,
    resolve_run_author,
)

CLAUDE_TRAILER = "fix(stall): x\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>\n"


class Normalize(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual("antigravity", normalize_tool("agy"))
        self.assertEqual("antigravity", normalize_tool("Antigravity"))
        self.assertEqual("ollama", normalize_tool("local"))
        self.assertEqual("ollama", normalize_tool("ollama"))
        self.assertEqual("claude", normalize_tool(" claude "))
        self.assertEqual("codex", normalize_tool("codex"))
        for name in ("apply", "custom", "user", "coordinator", "", None):
            self.assertIsNone(normalize_tool(name), name)


class CommitAuthor(unittest.TestCase):
    def test_trailers(self):
        self.assertEqual({"claude"}, commit_trailer_tools([CLAUDE_TRAILER]))
        self.assertEqual({"codex"}, commit_trailer_tools(["feat\n\nAuthor-Tool: codex\n"]))
        self.assertEqual({"antigravity"}, commit_trailer_tools(["feat\n\nAuthor-Tool: agy\n"]))
        self.assertEqual(set(), commit_trailer_tools(["feat: mentions Claude in text only\n"]))
        self.assertEqual(set(), commit_trailer_tools([]))

    def test_prefix_alone_resolves(self):
        self.assertEqual(("claude", "RESOLVED"), resolve_commit_author("claude/u284-x", ["feat\n"]))
        self.assertEqual(("antigravity", "RESOLVED"), resolve_commit_author("agy/u275", ["feat\n"]))

    def test_trailer_agreeing_with_prefix_resolves(self):
        self.assertEqual(("claude", "RESOLVED"), resolve_commit_author("claude/u284", [CLAUDE_TRAILER]))

    def test_receipt_pr171_codex_branch_with_claude_commits_conflicts(self):
        self.assertEqual((None, "CONFLICT"), resolve_commit_author("codex/u209-r2-release", [CLAUDE_TRAILER]))

    def test_unprefixed_branch_uses_trailer(self):
        self.assertEqual(("claude", "RESOLVED"), resolve_commit_author("main", [CLAUDE_TRAILER]))

    def test_no_signal_is_unknown(self):
        self.assertEqual((None, "UNKNOWN"), resolve_commit_author("main", ["feat\n"]))
        self.assertEqual((None, "UNKNOWN"), resolve_commit_author(None, []))


class GateRefusesConflict(unittest.TestCase):
    def test_conflict_author_refuses_every_peer_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            mailbox = Path(tmp) / "mailbox"
            for sub in ("delivery", "ack", "inbox"):
                (mailbox / sub).mkdir(parents=True)
            ledger = mailbox / "delivery" / "agy_auto.jsonl"
            ledger.write_text("", encoding="utf-8")
            for actor in ("claude", "codex", "antigravity"):
                body = {"message_id": f"relay_{actor}", "payload": {"actor": actor, "verdict": "PASS"}}
                (mailbox / "ack" / f"relay_{actor}.json").write_text(json.dumps(body), encoding="utf-8")
                errs = audit_errors(f"feat\n\nAudit: relay_{actor}\n", ["v7_harness/x.py"], ledger, author="CONFLICT")
                self.assertEqual(1, len(errs), actor)
                self.assertIn("CONFLICT", errs[0])


class RunAuthor(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runs = Path(self.tmp.name) / ".coord" / "pilot" / "runs"

    def run_dir(self, task, worker=None, summary=None):
        d = self.runs / task
        d.mkdir(parents=True)
        if worker is not None:
            (d / "worker").write_text(worker, encoding="utf-8")
        if summary is not None:
            (d / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return d

    def test_worker_file_resolves(self):
        d = self.run_dir("U94", worker="ollama\n", summary={"state": "SUCCEEDED"})
        r = resolve_run_author(d, [])
        self.assertEqual(("U94", "ollama", "RESOLVED"), (r["task"], r["author"], r["state"]))
        self.assertIn("worker_file", r["sources"])

    def test_summary_worker_resolves(self):
        d = self.run_dir("U245", summary={"state": "SUCCEEDED", "worker": "local"})
        r = resolve_run_author(d, [])
        self.assertEqual(("ollama", "RESOLVED"), (r["author"], r["state"]))

    def test_ledger_row_by_receipt_path_resolves(self):
        d = self.run_dir("P02", summary={"state": "ABANDONED", "effect_state": "UNKNOWN"})
        rows = [{"kind": "pilot", "worker": "agy", "work_id": "other",
                 "receipt": ".coord\\pilot\\runs\\P02\\summary.json"}]
        r = resolve_run_author(d, rows)
        self.assertEqual(("antigravity", "RESOLVED"), (r["author"], r["state"]))
        self.assertIn("ledger", r["sources"])

    def test_ledger_row_by_work_id_resolves(self):
        d = self.run_dir("U245-L1", summary={"state": "SUCCEEDED"})
        rows = [{"kind": "pilot", "worker": "ollama", "work_id": "U245-L1"}]
        self.assertEqual("ollama", resolve_run_author(d, rows)["author"])

    def test_apply_run_takes_ledger_delegator(self):
        d = self.run_dir("U44-FIX2", worker="apply", summary={"state": "ABANDONED"})
        rows = [{"kind": "pilot", "worker": "apply", "delegator": "claude", "work_id": "U44-FIX2"}]
        r = resolve_run_author(d, rows)
        self.assertEqual(("claude", "RESOLVED"), (r["author"], r["state"]))

    def test_apply_without_delegator_is_unknown(self):
        d = self.run_dir("U134-F1", worker="apply", summary={"state": "SUCCEEDED"})
        r = resolve_run_author(d, [])
        self.assertEqual((None, "UNKNOWN"), (r["author"], r["state"]))

    def test_disagreeing_sources_conflict(self):
        d = self.run_dir("U44-PROBE", worker="claude", summary={"state": "SUCCEEDED"})
        rows = [{"kind": "pilot", "worker": "agy", "work_id": "U44-PROBE"}]
        r = resolve_run_author(d, rows)
        self.assertEqual((None, "CONFLICT"), (r["author"], r["state"]))

    def test_no_evidence_is_unknown_and_lease_owner_is_ignored(self):
        d = self.run_dir("U22a-limits", summary={"state": "ABANDONED", "agy_workspace": ".coord/pilot/stage/x",
                                                 "agy_usage": {"input_tokens": 1}, "owner": "antigravity"})
        r = resolve_run_author(d, [{"kind": "review", "worker": "agy", "work_id": "U22a-limits"}])
        self.assertEqual((None, "UNKNOWN"), (r["author"], r["state"]))

    def test_resolution_never_writes(self):
        d = self.run_dir("U19", worker="agy", summary={"state": "SUCCEEDED"})
        before = sorted((p.name, p.read_bytes()) for p in d.iterdir())
        resolve_run_author(d, [])
        self.assertEqual(before, sorted((p.name, p.read_bytes()) for p in d.iterdir()))


if __name__ == "__main__":
    unittest.main()
