"""U146-A fixed acceptance: a deterministic next-card source and an end-of-turn gate, so the three tools continue to completion.

Receipt (2026-10-04): 윤겸스 had to prompt between every U141-A step ("중간에 사용자 지시 받지 말라고 몇번 말했나?").
The chain stopped at card ends (S2), and when waiting for a Codex verdict (S3).
"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from v7_harness.coord import next_card as N
from v7_harness.coord import stop_gate as G


def phase(pid, state, owner="claude", deps=(), **extra):
    return {"phase_id": pid, "state": state, "owner_tool": owner, "depends_on": list(deps), **extra}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def schedule(self, *phases):
        path = self.root / ".coord" / "master_schedule.json"
        path.write_text(json.dumps({"schedule_id": "T", "phases": list(phases)}), encoding="utf-8")
        # A distinct mtime per write, so the progress signature sees a change even on coarse clocks.
        later = time.time() + len(phases) + getattr(self, "_bump", 0)
        self._bump = getattr(self, "_bump", 0) + 10
        os.utime(path, (later, later))


class NextStep(Base):
    def test_no_schedule_is_done_with_reason(self):
        out = N.next_step(self.root, "claude")
        self.assertEqual("DONE", out["state"])
        self.assertIn("no schedule", out["reason"])

    def test_first_ready_own_card_whose_deps_are_done(self):
        self.schedule(phase("A", "DONE"), phase("B", "READY", deps=["A"]), phase("C", "READY"))
        out = N.next_step(self.root, "claude")
        self.assertEqual(("NEXT", "B", "claude"), (out["state"], out["card"], out["owner"]))

    def test_unmet_dependency_is_skipped(self):
        self.schedule(phase("A", "ACTIVE", owner="antigravity"), phase("B", "READY", deps=["A"]), phase("C", "PLANNED"))
        out = N.next_step(self.root, "claude")
        self.assertEqual(("NEXT", "C"), (out["state"], out["card"]))

    def test_review_counts_as_done_for_chaining(self):
        # S3: a card waiting for a Codex verdict lets its successor start on a stacked branch.
        self.schedule(phase("A", "REVIEW", waiting_on="codex-verdict"), phase("B", "READY", deps=["A"]))
        self.assertEqual("B", N.next_step(self.root, "claude")["card"])

    def test_owner_all_is_own(self):
        self.schedule(phase("A", "READY", owner="all"))
        self.assertEqual("NEXT", N.next_step(self.root, "codex")["state"])

    def test_other_owner_is_handoff(self):
        self.schedule(phase("A", "READY", owner="antigravity"))
        out = N.next_step(self.root, "claude")
        self.assertEqual(("HANDOFF", "A", "antigravity"), (out["state"], out["card"], out["owner"]))

    def test_own_card_beats_an_earlier_handoff(self):
        self.schedule(phase("A", "READY", owner="antigravity"), phase("B", "READY"))
        self.assertEqual(("NEXT", "B"), (N.next_step(self.root, "claude")["state"], N.next_step(self.root, "claude")["card"]))

    def test_wait_when_only_blocked_or_in_flight_remain(self):
        self.schedule(phase("A", "REVIEW", waiting_on="codex-verdict"), phase("B", "ACTIVE", owner="antigravity"))
        out = N.next_step(self.root, "claude")
        self.assertEqual("WAIT", out["state"])
        self.assertEqual(["A", "B"], out["cards"])

    def test_human_when_only_human_items_remain(self):
        self.schedule(phase("A", "DONE"), phase("B", "HUMAN", human="merge PR #111"))
        out = N.next_step(self.root, "claude")
        self.assertEqual("HUMAN", out["state"])
        self.assertEqual(["merge PR #111"], out["items"])

    def test_all_done(self):
        self.schedule(phase("A", "DONE"), phase("B", "DONE"))
        self.assertEqual("DONE", N.next_step(self.root, "claude")["state"])

    def test_corrupt_schedule_is_wait_not_crash(self):
        (self.root / ".coord" / "master_schedule.json").write_text("{", encoding="utf-8")
        out = N.next_step(self.root, "claude")
        self.assertEqual("WAIT", out["state"])
        self.assertIn("schedule unreadable", out["reason"])


class RedTeam(Base):
    def test_review_stack_deeper_than_three_waits_for_codex(self):
        # R4: one rejected base reworks every child; MAX_REVIEW_STACK = 3 bounds that.
        self.schedule(phase("A", "REVIEW"), phase("B", "REVIEW", deps=["A"]), phase("C", "REVIEW", deps=["B"]),
                      phase("D", "READY", deps=["C"]))
        out = N.next_step(self.root, "claude")
        self.assertEqual("WAIT", out["state"])
        self.assertIn("review stack", out["reason"])

    def test_review_stack_of_two_still_chains(self):
        self.schedule(phase("A", "REVIEW"), phase("B", "REVIEW", deps=["A"]), phase("C", "READY", deps=["B"]))
        self.assertEqual("C", N.next_step(self.root, "claude")["card"])

    def test_claim_is_exclusive_and_skips_to_the_next_candidate(self):
        # R3: two sessions read the same NEXT; only one may run it.
        self.schedule(phase("A", "READY", owner="all"), phase("B", "READY", owner="all"))
        # U146a-R: ownership is the session id, not a PID (the Stop hook process exits right after each call).
        first = N.next_step(self.root, "claude", claim=True, session="s1")
        self.assertEqual(("NEXT", "A", True), (first["state"], first["card"], first["claimed"]))
        claim = json.loads((self.root / ".coord" / "next" / "claims" / "A.json").read_text(encoding="utf-8"))
        self.assertEqual("s1", claim["session"])
        # A live foreign session's claim moves the reader on.
        other = N.next_step(self.root, "codex", claim=True, session="s2")
        self.assertEqual("B", other["card"])

    def test_dead_claim_is_reclaimed(self):
        # U146a-R: a claim not renewed within CLAIM_TTL_S belongs to a gone session.
        self.schedule(phase("A", "READY"))
        claims = self.root / ".coord" / "next" / "claims"
        claims.mkdir(parents=True)
        (claims / "A.json").write_text(json.dumps({"session": "gone", "at": time.time() - N.CLAIM_TTL_S - 60}),
                                       encoding="utf-8")
        self.assertEqual("A", N.next_step(self.root, "claude", claim=True, session="s1")["card"])

    def test_schedule_is_read_from_the_main_checkout_of_a_worktree(self):
        # R5: worktrees must agree on one schedule.
        main = self.root / "main"
        main.mkdir()
        git = lambda *a, cwd=main: subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True)
        git("init", "-q")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
        git("worktree", "add", "-q", str(self.root / "wt"))
        (main / ".coord").mkdir()
        (main / ".coord" / "master_schedule.json").write_text(json.dumps({"phases": [phase("A", "READY")]}), encoding="utf-8")
        self.assertEqual("A", N.next_step(self.root / "wt", "claude")["card"])


class PushCheck(Base):
    def grant(self, **over):
        data = {"enabled": True, "branches": ["claude/*", "codex/*", "agy/*"], "never": ["main", "master"],
                "force": False, "merge": False}
        data.update(over)
        path = self.root / ".coord" / "grants"
        path.mkdir(parents=True, exist_ok=True)
        (path / "push.json").write_text(json.dumps(data), encoding="utf-8")
        # U146a-R: only the grant committed on origin/main counts, so the helper publishes it there.
        git = lambda *a: subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *a], cwd=self.root,
                                        check=True, capture_output=True)
        if not (self.root / ".git").exists():
            git("init", "-q")
        git("add", ".coord/grants/push.json")
        git("commit", "-q", "--allow-empty", "-m", "grant")
        git("update-ref", "refs/remotes/origin/main", "HEAD")

    def test_deny_by_default_without_a_grant(self):
        self.assertEqual("DENY", G.push_check(self.root, "claude/u146a")["decision"])

    def test_feature_branch_is_allowed(self):
        self.grant()
        self.assertEqual("ALLOW", G.push_check(self.root, "claude/u146a")["decision"])

    def test_main_force_disabled_and_foreign_branches_are_denied(self):
        self.grant()
        for branch, force in (("main", False), ("master", False), ("claude/x", True), ("feature/x", False)):
            self.assertEqual("DENY", G.push_check(self.root, branch, force=force)["decision"], branch)
        self.grant(enabled=False)
        self.assertEqual("DENY", G.push_check(self.root, "claude/x")["decision"])

    def test_corrupt_grant_denies(self):
        self.grant()
        (self.root / ".coord" / "grants" / "push.json").write_text("{", encoding="utf-8")
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "corrupt"],
                       cwd=self.root, check=True, capture_output=True)
        subprocess.run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=self.root, check=True)
        self.assertEqual("DENY", G.push_check(self.root, "claude/x")["decision"])


class StopGate(Base):
    def test_blocks_when_own_next_card_exists(self):
        self.schedule(phase("A", "READY"))
        out = G.gate(self.root, "claude", session="s1")
        self.assertEqual("block", out["decision"])
        self.assertIn("A", out["reason"])

    def test_allows_stop_on_wait_human_done_handoff(self):
        for phases in ([phase("A", "ACTIVE", owner="codex")],
                       [phase("A", "HUMAN", human="push")],
                       [phase("A", "DONE")],
                       [phase("A", "READY", owner="antigravity")]):
            self.schedule(*phases)
            self.assertIsNone(G.gate(self.root, "claude", session="s1"), phases)

    def test_loop_guard_releases_after_one_block_without_progress(self):
        # Antigravity audit relay_5d1e13d0 [HIGH]: each block is a full-context paid turn, so allow one re-entry only.
        self.schedule(phase("A", "READY"))
        decisions = [G.gate(self.root, "claude", session="s1") for _ in range(2)]
        self.assertEqual("block", decisions[0]["decision"])
        self.assertIsNone(decisions[1])
        log = (self.root / ".coord" / "log" / "stop_gate.jsonl").read_text(encoding="utf-8")
        self.assertIn('"kind": "BLOCKED"', log)
        self.assertIn('"card": "A"', log)

    def test_progress_resets_the_guard(self):
        self.schedule(phase("A", "READY"))
        G.gate(self.root, "claude", session="s1")
        # A ledger row alone is not progress (the audit's spin case: a pilot failing repeatedly).
        usage = self.root / ".coord" / "usage"
        usage.mkdir()
        (usage / "ledger.jsonl").write_text("{}\n", encoding="utf-8")
        self.assertIsNone(G.gate(self.root, "claude", session="s1"))
        # A new pilot run is verified advancement and resets the guard.
        run = self.root / ".coord" / "pilot" / "runs" / "A-1"
        run.mkdir(parents=True)
        (run / "summary.json").write_text("{}", encoding="utf-8")
        later = time.time() + 1000
        os.utime(run / "summary.json", (later, later))
        self.assertEqual("block", G.gate(self.root, "claude", session="s1")["decision"])

    def test_guard_is_per_tool(self):
        self.schedule(phase("A", "READY", owner="all"))
        G.gate(self.root, "claude", session="s1")
        # U146a-R: s1's claim is live, so codex reaches the same card A only once that claim lapses; claude's spent
        # guard on A must not release codex's first block.
        late = time.time() + N.CLAIM_TTL_S + 1
        self.assertEqual("block", G.gate(self.root, "codex", session="s2", now=late)["decision"])


class DefaultProcedure(unittest.TestCase):
    """R1: the nonstop chain is the UAOS-RSI default only together with its enforcement, in every tool's text."""

    ROOT = Path(__file__).resolve().parents[1]

    def test_portable_block_and_all_adapters_name_the_enforced_chain(self):
        block = (self.ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        for phrase in ("uaos coord next", "--claim", "coord push-check", "같은 턴"):
            self.assertIn(phrase, block)
        for tool in ("claude", "codex", "antigravity"):
            text = (self.ROOT / "uaos_everywhere" / "adapters" / f"{tool}.md").read_text(encoding="utf-8")
            self.assertIn("coord next", text, tool)
        self.assertIn("coord stop-gate", (self.ROOT / "uaos_everywhere" / "adapters" / "claude.md").read_text(encoding="utf-8"))

    def test_the_human_list_keeps_merge_and_names_the_grant(self):
        block = (self.ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        last = [line for line in block.splitlines() if line.startswith("- 멈추고 사용자에게 물을 것")][0]
        for word in ("삭제", "병합", "배포", "결제", "계정"):
            self.assertIn(word, last)
        self.assertIn(".coord/grants/push.json", last)

    def test_project_hook_runs_the_stop_gate(self):
        settings = json.loads((self.ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
        commands = [h["command"] for entry in settings["hooks"]["Stop"] for h in entry["hooks"]]
        self.assertTrue(any("coord stop-gate" in c and "--tool claude" in c for c in commands), commands)


class Cli(Base):
    def run_cli(self, *args, stdin=""):
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, "-m", "v7_harness.cli", *args], input=stdin, capture_output=True,
                              text=True, encoding="utf-8", env=env, cwd=Path(__file__).resolve().parents[1], timeout=120)

    def test_coord_next_prints_json(self):
        self.schedule(phase("A", "READY"))
        res = self.run_cli("coord", "next", "--project", str(self.root), "--tool", "claude")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual("NEXT", json.loads(res.stdout)["state"])

    def test_stop_gate_hook_reads_stdin_and_prints_block(self):
        self.schedule(phase("A", "READY"))
        hook_input = json.dumps({"session_id": "s1", "stop_hook_active": False, "cwd": str(self.root)})
        res = self.run_cli("coord", "stop-gate", "--project", str(self.root), "--tool", "claude", stdin=hook_input)
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual("block", json.loads(res.stdout)["decision"])

    def test_stop_gate_prints_nothing_when_stop_is_allowed(self):
        self.schedule(phase("A", "DONE"))
        res = self.run_cli("coord", "stop-gate", "--project", str(self.root), "--tool", "claude", stdin="{}")
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual("", res.stdout.strip())

    def test_push_check_cli_exit_codes(self):
        res = self.run_cli("coord", "push-check", "--project", str(self.root), "--branch", "claude/x")
        self.assertEqual(3, res.returncode)
        self.assertEqual("DENY", json.loads(res.stdout)["decision"])

    def test_stop_gate_never_fails_the_session_on_bad_input(self):
        res = self.run_cli("coord", "stop-gate", "--project", str(self.root / "missing"), "--tool", "claude", stdin="not json")
        self.assertEqual(0, res.returncode, res.stderr)


if __name__ == "__main__":
    unittest.main()
