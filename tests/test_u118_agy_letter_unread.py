"""U118: a letter that asks Antigravity to act says it stays unread until a user turn, and names the headless route.

Receipt (2026-10-01, user report): the conductor sent the R-U115-U116 review manual to Antigravity with
`coord deliver --target antigravity`, got `ok: true, reason: PUBLISHED`, and reported "the verdict letter has not
arrived yet" as a next step. No CLI wakes Antigravity (U95-A), so the letter sat unread until the user pasted it into
Antigravity by hand, which the rules forbid (U103: the user must not have to paste). The headless route already
existed: `pilot review --reviewer agy`. Now a real delta to Antigravity keeps PUBLISHED (the mailbox and its hooks are
unchanged) but its output says UNREAD and names that route; ACK_ONLY letters stay silent.
Fixed acceptance written by the judge (claude) first; no paid call.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness.coord import presence
from v7_harness.coord.deliver import deliver


class AgyLetterUnread(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name) / "proj"
        (self.project / ".coord").mkdir(parents=True)
        (self.project / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")
        sessions = Path(self._tmp.name) / "codex-sessions"
        sessions.mkdir()
        self._env = mock.patch.dict(os.environ, {presence.CODEX_SESSIONS_ENV: str(sessions)})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _runner(self, *_a, **_kw):
        raise AssertionError("no CLI may run for an Antigravity letter")

    def test_a_verdict_request_names_the_headless_route(self):
        result = deliver(self.project, message="[review manual] verdict_requested=yes ACTIONABLE_DELTA",
                         actor="claude", target="antigravity", runner=self._runner)
        self.assertEqual("PUBLISHED", result.reason)
        self.assertIn("UNREAD", result.output)
        self.assertIn("pilot review --reviewer agy", result.output)

    def test_an_ack_only_letter_stays_silent(self):
        result = deliver(self.project, message="liveness ACK_ONLY", actor="claude", target="antigravity",
                         runner=self._runner)
        self.assertEqual("PUBLISHED", result.reason)
        self.assertEqual("", result.output)


if __name__ == "__main__":
    unittest.main()
