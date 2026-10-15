"""U198: slicing is the permanent Ollama default for all three tools.
Receipt: 2026-10-15 U197-L1 failed PROMPT_TOO_LARGE (14.5k > 12.3k) and the author went straight to `worker: apply`
with `apply_after`; 윤겸스 had ordered several times to cut Ollama work small like Antigravity slices instead. Re-cut
into ~20-line one-function slices, U197 S1-S6 and S3a-c all passed locally. The remedies, the worker's own refusal
text and the global rule block (installed into Claude Code, Codex and Antigravity) must all say: re-cut first,
apply_after only after a small slice failed twice."""
import unittest
from pathlib import Path

from v7_harness import rsi
from v7_harness.adapters import ollama_worker

ROOT = Path(__file__).resolve().parents[1]
SLICE_CAUSES = ("PROMPT_TOO_LARGE", "NO_FILE_BLOCK", "DICTATION_MISMATCH")


class OllamaSliceDefaultTest(unittest.TestCase):
    def test_remedies_recut_before_apply(self):
        for cause in SLICE_CAUSES:
            _target, action = rsi.REMEDIES[cause]
            self.assertTrue(action.startswith("Re-cut"), (cause, action))
            self.assertIn("worker: local", action, cause)
            self.assertIn("failed twice", action, cause)

    def test_worker_refusal_names_slicing(self):
        source = (ROOT / "v7_harness" / "adapters" / "ollama_worker.py").read_text(encoding="utf-8")
        self.assertIn("re-cut into one-function slices", source)
        self.assertTrue(hasattr(ollama_worker, "preflight"))

    def test_global_rule_block_fixes_slicing_for_all_tools(self):
        block = (ROOT / "uaos_everywhere" / "uaos_global_rule_block.md").read_text(encoding="utf-8")
        self.assertIn("U198", block)
        self.assertIn("잘게 쪼갠", block)
        self.assertIn("apply_after", block)


if __name__ == "__main__":
    unittest.main()
