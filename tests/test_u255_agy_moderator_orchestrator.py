"""U255: Acceptance and concurrency tests for Antigravity Moderator & Ollama/Haiku Orchestrator."""

from __future__ import annotations

import json
import multiprocessing as mp
import tempfile
import types
import unittest
from pathlib import Path

from v7_harness.coord.agy_moderator import (
    MAX_HAIKU_PREFLIGHT_TOKENS,
    AntigravityModerator,
    PersonalAssistantOrchestrator,
)


def _concurrent_vote_worker(root_str: str, proposal_id: str, voter: str, barrier: object, queue: object) -> None:
    mod = AntigravityModerator(Path(root_str))
    desk = {
        "antigravity": {"state": "ACTIVE"},
        "claude": {"state": "ACTIVE"},
        "codex": {"state": "ACTIVE"},
    }
    barrier.wait(10)
    res = mod.mediate_consensus(
        proposal_id=proposal_id,
        author_tool="claude",
        voter_tool=voter,
        vote="AGREE",
        evidence_summary=f"verified by {voter}",
        desk=desk,
    )
    queue.put(res)


class TestU255AgyModeratorOrchestrator(unittest.TestCase):
    def test_1_review_verdict_assigned_and_woken_excluding_author(self) -> None:
        """Unassigned REVIEW phase gets an ACTIVE non-author judge and emits an ACTIONABLE wake."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coord = root / ".coord"
            coord.mkdir(parents=True)
            (coord / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "schedule_id": "U255-S1",
                        "phases": [
                            {
                                "phase_id": "U254",
                                "state": "REVIEW",
                                "owner_tool": "claude",
                                "author_tool": "claude",
                                "depends_on": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            desk = {
                "codex": {"state": "LIMITED"},
                "claude": {"state": "ACTIVE"},
                "antigravity": {"state": "ACTIVE"},
            }
            mod = AntigravityModerator(root, stall_threshold_s=60.0)
            out = mod.detect_and_intervene_stalls(desk=desk, now=1000.0)
            self.assertTrue(out["ok"])
            self.assertEqual(len(out["interventions"]), 1)
            self.assertEqual(out["interventions"][0]["judge"], "antigravity")
            saved = json.loads((coord / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["phases"][0]["reviewer"], "antigravity")
            self.assertEqual(saved["phases"][0]["waiting_on"], "antigravity-verdict")

    def test_2_quota_limit_triggers_failover_and_ollama_manual_generation(self) -> None:
        """When Codex hits LIMITED, Moderator reassigns its READY phase and drafts a failover manual via Ollama CLI."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coord = root / ".coord"
            coord.mkdir(parents=True)
            (coord / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "schedule_id": "U255-S2",
                        "phases": [
                            {
                                "phase_id": "U255-P1",
                                "title": "Quota Failover Task",
                                "state": "READY",
                                "owner_tool": "codex",
                                "allowed_files": ["v7_harness/coord/agy_moderator.py"],
                                "acceptance_cmd": "python -m unittest tests.test_u255_agy_moderator_orchestrator",
                                "depends_on": [],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            def fake_runner(argv: list[str], **kwargs: object) -> object:
                return types.SimpleNamespace(
                    returncode=0,
                    stdout="Execute U255-P1 via local worker and verify with independent judge.\n",
                    stderr="",
                )

            assistant = PersonalAssistantOrchestrator(root, runner=fake_runner)
            mod = AntigravityModerator(root, assistant=assistant)
            desk = {
                "codex": {"state": "LIMITED"},
                "claude": {"state": "ACTIVE"},
                "antigravity": {"state": "ACTIVE"},
            }
            res = mod.detect_and_handle_quota_limits(desk=desk, now=2000.0)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["replanned"]), 1)
            self.assertEqual(len(res["manuals_generated"]), 1)
            m_info = res["manuals_generated"][0]
            self.assertEqual(m_info["assistant_used"], "ollama")
            self.assertNotEqual(m_info["new_owner"], m_info["judge"])
            manual_text = Path(m_info["manual_path"]).read_text(encoding="utf-8")
            self.assertIn("```contract", manual_text)
            self.assertIn("work_id: U255-P1", manual_text)
            self.assertIn("https://github.com/langchain-ai/langgraph-supervisor-py", manual_text)

    def test_3_ollama_failure_falls_back_to_haiku_5_5_and_journals_both(self) -> None:
        """When Ollama CLI fails, PersonalAssistantOrchestrator falls back to Haiku 5.5 CLI and journals both."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls: list[list[str]] = []

            def fake_runner(argv: list[str], **kwargs: object) -> object:
                calls.append(list(argv))
                if "ollama" in str(argv[0]).lower():
                    return types.SimpleNamespace(returncode=1, stdout="", stderr="ollama server busy")
                return types.SimpleNamespace(
                    returncode=0,
                    stdout=json.dumps({"result": "Haiku 5.5 failover summary line."}),
                    stderr="",
                )

            assistant = PersonalAssistantOrchestrator(root, runner=fake_runner)
            info = assistant.draft_failover_manual(
                phase={"phase_id": "U255-H1", "title": "Haiku Fallback"},
                new_owner="antigravity",
                judge_tool="claude",
                unavailable_tool="codex",
            )
            self.assertEqual(info["assistant_used"], "haiku")
            rows = [
                json.loads(line)
                for line in (root / ".coord" / "usage" / "runs.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["worker"], "ollama")
            self.assertEqual(rows[0]["outcome"], "FAILED")
            self.assertEqual(rows[1]["worker"], "haiku")
            self.assertEqual(rows[1]["outcome"], "PASS")

    def test_4_haiku_preflight_blocks_above_12000_tokens(self) -> None:
        """Haiku 5.5 calls exceeding 12,000 estimated tokens fail closed before invoking the provider."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            called = False

            def fake_runner(argv: list[str], **kwargs: object) -> object:
                nonlocal called
                called = True
                return types.SimpleNamespace(returncode=0, stdout="{}", stderr="")

            assistant = PersonalAssistantOrchestrator(root, runner=fake_runner)
            huge_prompt = "X" * (MAX_HAIKU_PREFLIGHT_TOKENS * 4)
            res = assistant.call_haiku_cli(work_id="U255-OVERCAP", prompt=huge_prompt)
            self.assertFalse(res["ok"])
            self.assertEqual(res["error"], "PREFLIGHT_TOKEN_CAP_EXCEEDED")
            self.assertFalse(called)

    def test_5_consensus_forbids_self_approval_and_adopts_on_peer_quorum(self) -> None:
        """Author cannot self-approve; consensus reaches ADOPTED when all ACTIVE non-author peers agree."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mod = AntigravityModerator(root)
            desk = {
                "antigravity": {"state": "ACTIVE"},
                "claude": {"state": "ACTIVE"},
                "codex": {"state": "LIMITED"},
            }
            self_vote = mod.mediate_consensus(
                proposal_id="U255-PROP",
                author_tool="antigravity",
                voter_tool="antigravity",
                vote="AGREE",
                desk=desk,
            )
            self.assertFalse(self_vote["ok"])
            self.assertEqual(self_vote["error"], "SELF_APPROVAL_FORBIDDEN")

            peer_vote = mod.mediate_consensus(
                proposal_id="U255-PROP",
                author_tool="antigravity",
                voter_tool="claude",
                vote="AGREE",
                evidence_summary="38/38 tests pass",
                desk=desk,
            )
            self.assertTrue(peer_vote["ok"])
            self.assertEqual(peer_vote["proposal"]["state"], "ADOPTED")
            self.assertEqual(peer_vote["proposal"]["agreed_by"], ["antigravity", "claude"])

    def test_6_concurrent_two_process_consensus_votes_preserved(self) -> None:
        """Two real OS processes voting concurrently on a proposal preserve both votes and adopt cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ctx = mp.get_context("spawn")
            barrier, queue = ctx.Barrier(2), ctx.Queue()
            procs = [
                ctx.Process(
                    target=_concurrent_vote_worker,
                    args=(str(root), "U255-CONC", voter, barrier, queue),
                )
                for voter in ("antigravity", "codex")
            ]
            for p in procs:
                p.start()
            for p in procs:
                p.join(15)
            results = [queue.get(timeout=5) for _ in procs]
            self.assertTrue(all(r.get("ok") for r in results))
            ledger = json.loads((root / ".coord" / "moderator" / "consensus_ledger.json").read_text(encoding="utf-8"))
            prop = ledger["proposals"]["U255-CONC"]
            self.assertEqual(set(prop["votes"].keys()), {"antigravity", "codex"})
            self.assertEqual(prop["state"], "ADOPTED")

    def test_7_codex_bottleneck_review_and_ready_assist_relieved(self) -> None:
        """When Codex is bottlenecked with ACTIVE work + REVIEW queue + READY queue, Moderator offloads to Claude/Antigravity."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coord = root / ".coord"
            coord.mkdir(parents=True)
            (coord / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "schedule_id": "U255-BOTTLENECK",
                        "phases": [
                            {
                                "phase_id": "U250-ACT",
                                "state": "ACTIVE",
                                "owner_tool": "codex",
                                "allowed_files": ["v7_harness/a.py"],
                                "depends_on": [],
                            },
                            {
                                "phase_id": "U251-REV",
                                "state": "REVIEW",
                                "owner_tool": "antigravity",
                                "author_tool": "antigravity",
                                "reviewer": "codex",
                                "waiting_on": "codex-verdict",
                                "depends_on": [],
                            },
                            {
                                "phase_id": "U252-RDY",
                                "state": "READY",
                                "owner_tool": "codex",
                                "allowed_files": ["v7_harness/b.py"],
                                "depends_on": [],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            desk = {
                "codex": {"state": "ACTIVE"},
                "claude": {"state": "ACTIVE"},
                "antigravity": {"state": "ACTIVE"},
            }
            mod = AntigravityModerator(root)
            res = mod.detect_and_relieve_bottlenecks(desk=desk, now=3000.0)
            self.assertTrue(res["ok"])
            self.assertEqual(len(res["relieved"]), 2)
            kinds = {r["phase_id"]: r for r in res["relieved"]}
            self.assertEqual(kinds["U251-REV"]["kind"], "REVIEW_BOTTLENECK_RELIEVED")
            self.assertEqual(kinds["U251-REV"]["to_tool"], "claude")
            self.assertEqual(kinds["U252-RDY"]["kind"], "WORKLOAD_ASSIST_DISPATCHED")
            self.assertIn(kinds["U252-RDY"]["to_tool"], ("antigravity", "claude"))

    def test_8_broken_bridge_cut_lan_and_stale_quiet_lock_repaired(self) -> None:
        """Repairman/Caretaker clears dead-PID QUIET_LOCK, reconnects dependency-DONE BLOCKED bridge, and re-splices cut LAN relay."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            coord = root / ".coord"
            (coord / "mailbox" / "inbox").mkdir(parents=True)
            (root / ".work").mkdir(parents=True)
            (root / ".work" / "QUIET_LOCK").write_text(
                json.dumps({"owner": "codex", "pid": 99999999, "started_at": 100.0}),
                encoding="utf-8",
            )
            (coord / "master_schedule.json").write_text(
                json.dumps(
                    {
                        "schedule_id": "U255-REPAIR",
                        "phases": [
                            {"phase_id": "U1", "state": "DONE", "owner_tool": "codex", "depends_on": []},
                            {
                                "phase_id": "U2",
                                "state": "BLOCKED",
                                "blocker_kind": "DEPENDENCY",
                                "owner_tool": "claude",
                                "depends_on": ["U1"],
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (coord / "mailbox" / "inbox" / "relay_cutlan01.json").write_text(
                json.dumps(
                    {
                        "message_id": "relay_cutlan01",
                        "created_at": 500.0,
                        "payload": {
                            "kind": "HANDOFF",
                            "actor": "claude",
                            "requested_target": "codex",
                            "card": "U2",
                            "wake_class": "ACTIONABLE",
                            "message": "un-acked stranded relay",
                        },
                    }
                ),
                encoding="utf-8",
            )
            desk = {
                "codex": {"state": "ACTIVE"},
                "claude": {"state": "ACTIVE"},
                "antigravity": {"state": "ACTIVE"},
            }
            mod = AntigravityModerator(root)
            out = mod.repair_broken_bridges_and_lan(desk=desk, now=1000.0)
            self.assertTrue(out["ok"])
            repair_kinds = {r["kind"] for r in out["repairs"]}
            self.assertEqual(
                repair_kinds,
                {"STALE_QUIET_LOCK_CLEARED", "BROKEN_BRIDGE_RECONNECTED", "LAN_CABLE_RECONNECTED"},
            )
            self.assertFalse((root / ".work" / "QUIET_LOCK").exists())
            sched = json.loads((coord / "master_schedule.json").read_text(encoding="utf-8"))
            self.assertEqual(sched["phases"][1]["state"], "READY")


if __name__ == "__main__":
    unittest.main()
