"""U47-C2 frozen acceptance (written by Claude): `pilot review --help` names the decided budget and keeps it required.

The decision (docs/47 §1-1 C2) lived only in the docs, so an operator could still pass the 80,000 that failed as
UNUSABLE. The help is where the value is read at the moment of the paid call.
"""

import contextlib
import io
import unittest

from v7_harness.cli import build_parser


def _review_help() -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), self_exit():
        build_parser().parse_args(["pilot", "review", "--help"])
    return " ".join(out.getvalue().split())


@contextlib.contextmanager
def self_exit():
    try:
        yield
    except SystemExit:
        pass


class ReviewBudgetHelpTest(unittest.TestCase):
    def test_help_names_the_decided_values(self):
        text = _review_help()
        self.assertIn("120000", text)
        self.assertIn("0.25", text)
        self.assertIn("cache reads included", text)

    def test_budget_is_still_required(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err), self.assertRaises(SystemExit):
            build_parser().parse_args(["pilot", "review", "--task", "T", "--manual", "m.md"])
        self.assertIn("--budget", err.getvalue())


if __name__ == "__main__":
    unittest.main()
