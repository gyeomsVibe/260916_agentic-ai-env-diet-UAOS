"""U237 fixed acceptance: Haiku 5.5 + Ollama 3-tool shared worker pool."""
from pathlib import Path
import unittest


class U237HaikuWorkerPoolTests(unittest.TestCase):
    def setUp(self):
        self.repo_root = Path(__file__).resolve().parents[1]
        self.agent_file = self.repo_root / ".claude" / "agents" / "uaos-haiku-worker.md"

    def task(self, **kw):
        base = dict(
            caller="antigravity",
            kind="edit",
            input_tokens=1200,
            output_tokens=250,
            changed_lines=12,
            local_qualified=True,
            local_failures=0,
            allow_remote=False,
            budget_tokens=4000,
            budget_usd=0.05,
            timeout_s=60,
        )
        base.update(kw)
        return base

    def test_haiku_subagent_manifest_pins_exact_haiku_model(self):
        self.assertTrue(self.agent_file.is_file(), "Missing .claude/agents/uaos-haiku-worker.md")
        text = self.agent_file.read_text(encoding="utf-8")
        self.assertIn("name: uaos-haiku-worker", text)
        self.assertIn("model: claude-haiku-5-5", text)

    def test_select_pool_worker_routes_local_first_with_ollama_coder(self):
        from v7_harness.worker_routing import select_pool_worker

        for caller in ("codex", "claude", "antigravity"):
            with self.subTest(caller=caller):
                res = select_pool_worker(self.task(caller=caller), {"local": True, "haiku": True})
                self.assertEqual(res["status"], "READY")
                self.assertEqual(res["worker"], "local")
                self.assertEqual(res["model"], "qwen2.5-coder:7b")
                self.assertFalse(res["require_exact_model"])

    def test_select_pool_worker_escalates_to_haiku_subagent_after_two_local_failures(self):
        from v7_harness.worker_routing import select_pool_worker

        res = select_pool_worker(
            self.task(local_failures=2, allow_remote=True),
            {"local": True, "haiku": True},
        )
        self.assertEqual(res["status"], "READY")
        self.assertEqual(res["worker"], "claude")
        self.assertEqual(res["model"], "claude-haiku-5-5")
        self.assertEqual(res["subagent"], "uaos-haiku-worker")
        self.assertTrue(res["require_exact_model"])
        self.assertEqual(res["model_pin"], "exact")

    def test_select_pool_worker_blocks_unapproved_escalation(self):
        from v7_harness.worker_routing import select_pool_worker

        res = select_pool_worker(
            self.task(local_failures=2, allow_remote=False),
            {"local": True, "haiku": True},
        )
        self.assertEqual(res["status"], "BLOCKED")
        self.assertIsNone(res["worker"])
        self.assertIsNone(res.get("subagent"))


if __name__ == "__main__":
    unittest.main()
