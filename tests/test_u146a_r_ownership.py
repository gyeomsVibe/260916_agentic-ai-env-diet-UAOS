"""U146a-R: PR112 counterexamples, frozen before the fix (Codex PR110 verdict: "112 must prove session ownership (not
PID-only), missing progress dirs behavior and authority/grant checks").

- Ownership: the Claude Stop hook is a short-lived process, so a claim keyed by its PID is dead the moment the hook
  exits and the next session takes the same card. A claim belongs to the hook input's session_id and lapses only
  after CLAIM_TTL_S without renewal. No session id means no claim and no block.
- Progress: pilot runs live in every pilot dir (`pilot_dirs.discover`, e.g. `.work/<x>/runs`), not only
  `.coord/pilot/runs`; a project without git, runs or schedule never crashes the gate.
- Authority: the push grant is read from the committed `origin/main` blob only. A working-tree edit or a local commit
  that is not on origin/main (anything an agent alone can write) grants nothing.
Processes in the ownership tests are real separate interpreters, like real hook calls.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import next_card as N
from v7_harness.coord import stop_gate as G

REPO = Path(__file__).resolve().parents[1]


def phase(pid, state, owner="claude", deps=()):
    return {"phase_id": pid, "state": state, "owner_tool": owner, "depends_on": list(deps)}


def hook_gate(root: Path, session: str | None) -> dict | None:
    """One Stop-hook call in its own interpreter, which exits right after (as the real hook does)."""
    code = ("import json,sys; from pathlib import Path; from v7_harness.coord import stop_gate as G; "
            "s=sys.argv[2] or None; print(json.dumps(G.gate(Path(sys.argv[1]), 'claude', session=s)))")
    out = subprocess.run([sys.executable, "-c", code, str(root), session or ""], capture_output=True, text=True,
                         cwd=REPO, timeout=60, check=True)
    return json.loads(out.stdout)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()

    def schedule(self, *phases):
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text(json.dumps({"phases": list(phases)}), encoding="utf-8")

    def claim_file(self, card):
        return json.loads((self.root / ".coord" / "next" / "claims" / f"{card}.json").read_text(encoding="utf-8"))


class SessionOwnership(Base):
    def test_hook_claim_survives_the_hook_process(self):
        self.schedule(phase("A", "READY"), phase("B", "READY"))
        first = hook_gate(self.root, "session-1")
        self.assertIn("A", first["reason"])
        self.assertEqual("session-1", self.claim_file("A")["session"])
        # session-1's hook process has exited; another live session must not take A.
        second = hook_gate(self.root, "session-2")
        self.assertIn("B", second["reason"])
        self.assertNotIn("NEXT A", second["reason"])

    def test_same_session_keeps_and_renews_its_claim(self):
        self.schedule(phase("A", "READY"))
        self.assertEqual("A", N.next_step(self.root, "claude", claim=True, session="s1", now=1000.0)["card"])
        again = N.next_step(self.root, "claude", claim=True, session="s1", now=2000.0)
        self.assertEqual(("NEXT", "A"), (again["state"], again["card"]))
        self.assertEqual(2000.0, self.claim_file("A")["at"])

    def test_live_foreign_session_claim_moves_the_reader_on(self):
        self.schedule(phase("A", "READY", owner="all"), phase("B", "READY", owner="all"))
        N.next_step(self.root, "claude", claim=True, session="s1", now=1000.0)
        other = N.next_step(self.root, "codex", claim=True, session="s2", now=1000.0 + N.CLAIM_TTL_S - 1)
        self.assertEqual("B", other["card"])

    def test_claim_older_than_ttl_is_reclaimed(self):
        self.schedule(phase("A", "READY"))
        N.next_step(self.root, "claude", claim=True, session="gone", now=1000.0)
        late = N.next_step(self.root, "claude", claim=True, session="s2", now=1000.0 + N.CLAIM_TTL_S + 1)
        self.assertEqual("A", late["card"])
        self.assertEqual("s2", self.claim_file("A")["session"])

    def test_pid_only_claim_record_is_not_ownership(self):
        # A pre-fix record names only a PID (here this live test process); it holds nothing for a session.
        self.schedule(phase("A", "READY"))
        claims = self.root / ".coord" / "next" / "claims"
        claims.mkdir(parents=True)
        (claims / "A.json").write_text(json.dumps({"pid": os.getpid(), "process_created": 1.0}), encoding="utf-8")
        self.assertEqual("A", N.next_step(self.root, "claude", claim=True, session="s1", now=time.time())["card"])

    def test_claim_without_session_is_refused(self):
        self.schedule(phase("A", "READY"))
        step = N.next_step(self.root, "claude", claim=True)
        self.assertEqual("WAIT", step["state"])
        self.assertFalse((self.root / ".coord" / "next" / "claims" / "A.json").exists())
        self.assertEqual("NEXT", N.next_step(self.root, "claude")["state"])  # a read without claim still names it

    def test_stop_gate_without_session_allows_the_stop(self):
        self.schedule(phase("A", "READY"))
        self.assertIsNone(hook_gate(self.root, None))
        self.assertFalse((self.root / ".coord" / "next" / "claims").exists())


class MissingProgressDirs(Base):
    def test_signature_without_git_runs_or_schedule(self):
        bare = self.root / "bare"
        bare.mkdir()
        signature = G.progress_signature(bare)
        self.assertIsInstance(signature, list)
        self.assertIsNone(signature[0])  # no git HEAD

    def test_gate_works_without_git_or_any_runs_dir(self):
        self.schedule(phase("A", "READY"))
        self.assertEqual("block", G.gate(self.root, "claude", session="s1")["decision"])
        self.assertIsNone(G.gate(self.root, "claude", session="s1"))  # loop guard still releases

    def test_run_under_a_work_pilot_dir_is_progress(self):
        self.schedule(phase("A", "READY"))
        G.gate(self.root, "claude", session="s1")
        self.assertIsNone(G.gate(self.root, "claude", session="s1"))
        run = self.root / ".work" / "u146_pieces" / "runs" / "A-1"
        run.mkdir(parents=True)
        (run / "summary.json").write_text("{}", encoding="utf-8")
        self.assertEqual("block", G.gate(self.root, "claude", session="s1")["decision"])


class GrantAuthority(Base):
    GRANT = {"enabled": True, "branches": ["claude/*"], "never": ["main", "master"], "force": False}

    def git(self, *args):
        return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args], cwd=self.root,
                              check=True, capture_output=True, text=True)

    def write_grant(self, data):
        path = self.root / ".coord" / "grants" / "push.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def setUp(self):
        super().setUp()
        self.git("init", "-q")
        self.git("commit", "-q", "--allow-empty", "-m", "init")

    def publish_on_origin_main(self):
        self.git("add", ".coord/grants/push.json")
        self.git("commit", "-q", "-m", "grant")
        self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def test_uncommitted_grant_is_denied(self):
        self.write_grant(self.GRANT)
        self.assertEqual("DENY", G.push_check(self.root, "claude/x")["decision"])

    def test_local_commit_not_on_origin_main_is_denied(self):
        self.write_grant(self.GRANT)
        self.git("add", ".coord/grants/push.json")
        self.git("commit", "-q", "-m", "self grant")
        self.assertEqual("DENY", G.push_check(self.root, "claude/x")["decision"])

    def test_origin_main_grant_allows_and_working_tree_cannot_widen_it(self):
        self.write_grant(self.GRANT)
        self.publish_on_origin_main()
        self.assertEqual("ALLOW", G.push_check(self.root, "claude/x")["decision"])
        self.write_grant(dict(self.GRANT, branches=["*"], never=[]))  # an agent's uncommitted widening
        self.assertEqual("DENY", G.push_check(self.root, "feature/x")["decision"])
        self.assertEqual("DENY", G.push_check(self.root, "main")["decision"])

    def test_origin_main_disable_wins_over_working_tree_enable(self):
        self.write_grant(dict(self.GRANT, enabled=False))
        self.publish_on_origin_main()
        self.write_grant(self.GRANT)
        self.assertEqual("DENY", G.push_check(self.root, "claude/x")["decision"])


class HookCli(Base):
    def run_cli(self, *args, stdin=""):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, "-m", "v7_harness.cli", *args], input=stdin, capture_output=True,
                              text=True, encoding="utf-8", env=env, cwd=REPO, timeout=120)

    def test_stop_hook_claims_for_the_input_session(self):
        self.schedule(phase("A", "READY"))
        res = self.run_cli("coord", "stop-gate", "--project", str(self.root), "--tool", "claude",
                           stdin=json.dumps({"session_id": "hook-s1", "stop_hook_active": False}))
        self.assertEqual("block", json.loads(res.stdout)["decision"])
        self.assertEqual("hook-s1", self.claim_file("A")["session"])

    def test_stop_hook_without_session_id_prints_nothing(self):
        self.schedule(phase("A", "READY"))
        res = self.run_cli("coord", "stop-gate", "--project", str(self.root), "--tool", "claude", stdin="{}")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual("", res.stdout.strip())

    def test_coord_next_claim_needs_a_session(self):
        self.schedule(phase("A", "READY"))
        res = self.run_cli("coord", "next", "--project", str(self.root), "--tool", "claude", "--claim",
                           "--session", "cli-s1")
        self.assertEqual("NEXT", json.loads(res.stdout)["state"])
        self.assertEqual("cli-s1", self.claim_file("A")["session"])


if __name__ == "__main__":
    unittest.main()
