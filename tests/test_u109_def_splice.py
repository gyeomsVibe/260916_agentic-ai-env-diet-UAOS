"""U109: splice whole Python definitions by name, the edit shape a 7B model emits on its own.

U107-B (2026-10-01): qwen2.5-coder:7b wrote nearly correct code as `===EDIT: path===` plus a fenced block of whole
functions instead of SEARCH/REPLACE; the parser dropped it and the cascade paid ~730k Antigravity tokens.
`splice_definitions(current, code)` turns that shape into a file deterministically.
"""

import textwrap
import unittest

from v7_harness.adapters.def_splice import splice_definitions

BASE = textwrap.dedent('''\
    """Module doc."""
    import os

    LIMIT = 3


    def alpha(x):
        return x + 1


    @staticmethod
    def beta():
        return "b"


    class Box:
        def size(self):
            return 1

        def name(self):
            return "box"


    if __name__ == "__main__":
        alpha(1)
''')


class SpliceTests(unittest.TestCase):
    def test_replaces_function_by_name_and_keeps_the_rest(self):
        out = splice_definitions(BASE, "def alpha(x):\n    return x + 2\n")
        self.assertIn("    return x + 2\n", out)
        self.assertNotIn("return x + 1", out)
        self.assertEqual(BASE.replace("x + 1", "x + 2"), out)

    def test_replaces_decorated_function_including_decorator(self):
        out = splice_definitions(BASE, "@staticmethod\ndef beta():\n    return 'c'\n")
        self.assertEqual(1, out.count("@staticmethod"))
        self.assertIn("    return 'c'\n", out)
        self.assertNotIn('return "b"', out)

    def test_replaces_indented_method_at_its_own_indent(self):
        out = splice_definitions(BASE, "    def size(self):\n        return 2\n")
        self.assertIn("    def size(self):\n        return 2\n", out)
        self.assertIn('        return "box"\n', out)
        compile(out, "x.py", "exec")

    def test_new_function_goes_before_main_guard(self):
        out = splice_definitions(BASE, "def gamma():\n    return 3\n")
        self.assertLess(out.index("def gamma"), out.index('if __name__ == "__main__"'))
        self.assertGreater(out.index("def gamma"), out.index("class Box"))
        compile(out, "x.py", "exec")

    def test_constant_replaced_and_new_import_added_once(self):
        out = splice_definitions(BASE, "import re\nimport os\nLIMIT = 5\n")
        self.assertIn("LIMIT = 5\n", out)
        self.assertNotIn("LIMIT = 3", out)
        self.assertEqual(1, out.count("import os\n"))
        self.assertLess(out.index("import re"), out.index("LIMIT = 5"))
        self.assertGreater(out.index("import re"), out.index('"""Module doc."""'))

    def test_new_constant_goes_before_first_definition(self):
        out = splice_definitions(BASE, "WIDTH = 10\n")
        self.assertLess(out.index("WIDTH = 10"), out.index("def alpha"))
        compile(out, "x.py", "exec")

    def test_several_definitions_in_one_block(self):
        out = splice_definitions(BASE, "def alpha(x):\n    return 0\n\n\ndef gamma():\n    return 3\n")
        self.assertIn("    return 0\n", out)
        self.assertIn("def gamma", out)
        compile(out, "x.py", "exec")

    def test_ambiguous_name_is_refused(self):
        src = "class A:\n    def run(self):\n        pass\n\n\nclass B:\n    def run(self):\n        pass\n"
        with self.assertRaisesRegex(ValueError, "SPLICE_AMBIGUOUS:run"):
            splice_definitions(src, "def run(self):\n    return 1\n")

    def test_bad_code_is_refused(self):
        with self.assertRaisesRegex(ValueError, "SPLICE_SYNTAX"):
            splice_definitions(BASE, "def alpha(:\n")

    def test_unsupported_statement_is_refused(self):
        with self.assertRaisesRegex(ValueError, "SPLICE_UNSUPPORTED"):
            splice_definitions(BASE, "print('hi')\n")

    def test_crlf_and_trailing_newline_kept(self):
        out = splice_definitions(BASE, "def alpha(x):\n    return x\n")
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\r", out)


if __name__ == "__main__":
    unittest.main()
