"""U121: only the Safety human list goes to the user; every other step the tool finishes itself, in all three adapters.

Receipt (2026-10-01, user report): after U120 the conductor listed "revert the uncommitted GEMINI.md polling line" as
`남은 일` for the user, although no human-only boundary applied and the main checkout was writable (Antigravity had
already agreed). The user had Antigravity do it and ordered the rule changed: such work is done directly, without
approval. The same report also showed the U118 adapter sentence ("letters stay UNREAD") is stale after U120.
Fixed acceptance written by the judge (claude) first; no paid call.
"""

import unittest
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[1] / "uaos_everywhere" / "adapters"


class ActNotAsk(unittest.TestCase):
    def text(self, tool):
        return (ADAPTERS / f"{tool}.md").read_text(encoding="utf-8")

    def test_every_adapter_limits_the_user_list_to_the_human_boundary(self):
        for tool in ("claude", "codex", "antigravity"):
            text = self.text(tool)
            self.assertIn("`남은 일`", text, tool)
            self.assertIn("사람 전용 목록", text, tool)
            self.assertIn(".work/backup_", text, tool)
            self.assertIn("U121", text, tool)

    def test_letter_senders_learn_the_u120_auto_reply(self):
        for tool in ("claude", "codex"):
            text = self.text(tool)
            self.assertIn("U120", text, tool)
            self.assertIn("UAOS_AGY_AUTO", text, tool)


if __name__ == "__main__":
    unittest.main()
