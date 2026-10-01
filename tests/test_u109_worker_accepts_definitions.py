"""U109-W: the Ollama worker applies the edit shape its 7B model emits on its own.

U107-B's reply was `===EDIT: path===` plus a fenced block of whole functions; `_apply` matched nothing and the run
was thrown away. A fenced block after `===EDIT:` on a .py file now replaces definitions by name (def_splice).
"""

import tempfile
import unittest
from pathlib import Path

from v7_harness.adapters import ollama_worker

SOURCE = "import os\n\n\ndef alpha():\n    return 1\n\n\ndef beta():\n    return 2\n"


class FencedDefinitionEditTests(unittest.TestCase):
    def _apply(self, reply: str, name: str = "pkg/m.py", content: str = SOURCE) -> tuple[list[str], str]:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pkg").mkdir()
            (root / name).write_text(content, encoding="utf-8")
            written = ollama_worker._apply(reply, root, task="change `alpha`")
            return written, (root / name).read_text(encoding="utf-8")

    def test_fenced_function_after_edit_header_replaces_it_by_name(self):
        reply = "===EDIT: pkg/m.py===\n```python\ndef alpha():\n    return 10\n```\n"
        written, text = self._apply(reply)
        self.assertEqual(["pkg/m.py"], written)
        self.assertIn("    return 10\n", text)
        self.assertIn("def beta():\n    return 2\n", text)

    def test_unfenced_search_replace_still_works(self):
        reply = "===EDIT: pkg/m.py===\n<<<<<<< SEARCH\n    return 2\n=======\n    return 20\n>>>>>>> REPLACE\n"
        _written, text = self._apply(reply)
        self.assertIn("return 20", text)

    def test_fenced_block_on_a_non_python_file_is_not_spliced(self):
        with self.assertRaises(ValueError):
            self._apply("===EDIT: pkg/n.md===\n```python\ndef alpha():\n    pass\n```\n", "pkg/n.md", "# doc\n")

    def test_edit_rules_offer_the_definition_shape(self):
        self.assertIn("```python", ollama_worker.EDIT_RULES)
        self.assertIn("same name", ollama_worker.EDIT_RULES)


if __name__ == "__main__":
    unittest.main()
