"""U64 red-first counterexamples: a watcher is not an AI wake channel."""
from __future__ import annotations
import json, tempfile, time, unittest
from pathlib import Path
from unittest.mock import patch
from v7_harness.coord.deliver import _requires_wake, deliver
from v7_harness.coord.watch import watch_file

class _Completed:
    returncode = 0
    stdout = json.dumps({"result": "processed", "is_error": False})
    stderr = ""

class NonstopDispatchTest(unittest.TestCase):
    def test_wake_classifier_rejects_ack_and_negated_or_incidental_tokens(self):
        for text in ("ACK_ONLY P1", "inbox 140 (P1 0)", "STEP1 done", "HTTP1", "no ACTIONABLE_DELTA since last"):
            self.assertFalse(_requires_wake(text),text)
        for text in ("ACTIONABLE_DELTA changed evidence", "U63 ACTIONABLE_DELTA", "verdict_requested=yes", "priority=P1"):
            self.assertTrue(_requires_wake(text),text)
    def test_live_watcher_does_not_suppress_actionable_claude_dispatch(self):
        with tempfile.TemporaryDirectory() as folder:
            project=Path(folder); (project/".coord/mailbox").mkdir(parents=True)
            marker=watch_file(project,"claude"); marker.parent.mkdir(parents=True,exist_ok=True)
            marker.write_text(json.dumps({"tool":"claude","token":"t","expires_at":time.time()+300}),encoding="utf-8")
            calls=[]
            def runner(argv,**kwargs): calls.append((argv,kwargs)); return _Completed()
            with patch("v7_harness.coord.deliver.shutil.which",return_value="claude"):
                result=deliver(project,message="ACTIONABLE_DELTA verdict_requested=yes: inspect U64",actor="codex",target="claude",runner=runner)
            self.assertEqual("DISPATCHED",result.reason)
            self.assertEqual(1,len(calls))
            self.assertIn("-p",calls[0][0])

    def test_worktree_shares_mailbox_but_claude_runs_in_worktree(self):
        with tempfile.TemporaryDirectory() as folder:
            main=Path(folder)/"main"; tree=Path(folder)/"tree"
            (main/".git/worktrees/w").mkdir(parents=True); (main/".coord").mkdir(); tree.mkdir()
            (main/".coord/PLAN.md").write_text("# plan\n",encoding="utf-8")
            (tree/".git").write_text(f"gitdir: {(main/'.git/worktrees/w').as_posix()}\n",encoding="utf-8")
            calls=[]
            def runner(argv,**kwargs): calls.append((argv,kwargs)); return _Completed()
            with patch("v7_harness.coord.deliver.shutil.which",return_value="claude"):
                result=deliver(tree,message="ACTIONABLE_DELTA verdict_requested=yes: worktree",actor="codex",target="claude",runner=runner)
            self.assertEqual(str(tree.resolve()),calls[0][1]["cwd"])
            self.assertTrue((main/".coord/mailbox/delivery/accepted"/f"{result.message_id}.json").is_file())
            self.assertFalse((tree/".coord/mailbox/inbox").exists())
            self.assertFalse((tree/".coord/mailbox/delivery/accepted"/f"{result.message_id}.json").exists())

if __name__ == "__main__": unittest.main()
