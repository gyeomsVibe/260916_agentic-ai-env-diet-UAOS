"""U141-A rev 6: a thrift HANDOFF still wakes the successor under the structured CLI default, exactly once.

Receipt: the U141-A3 dev run (2026-10-04). Under `--policy structured` the untagged thrift letter was LEGACY, so a
HANDOFF_READY never woke Claude's watcher (test_u71 timed out). Written by the judge (acting conductor Claude) before
dispatch.
"""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import watch as W
from v7_harness.coord.mailbox import Mailbox


class ThriftLetterWakes(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.project = Path(self._tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)
        self.box = Mailbox(self.project / ".coord" / "mailbox")

    def tearDown(self):
        self._tmp.cleanup()

    def test_thrift_source_tags_its_letter(self):
        source = Path(W.__file__).with_name("thrift.py").read_text(encoding="utf-8")
        self.assertIn('"wake_class":"ACTIONABLE"', source)
        self.assertIn('"requested_target":target', source)

    def test_a_tagged_letter_without_digest_wakes_once(self):
        mid = "thrift_codex_2_0123456789abcdef"
        self.box.publish(mid, {"kind": "HANDOFF", "from": "codex", "to": "claude", "actor": "codex",
                               "requested_target": "claude", "wake_class": "ACTIONABLE",
                               "delta": "HANDOFF codex->claude packet abc"})
        found = W.watch(self.project, ("claude",), timeout_s=0.3, interval_s=0.05, policy="structured")
        self.assertEqual(mid, found and found.get("id"))
        self.assertEqual("ACTIONABLE", found.get("wake_class"))
        digest = hashlib.sha256(mid.encode("utf-8")).hexdigest()
        self.assertEqual(digest, W.letter_digest(mid, {}))
        self.assertTrue(W.pending_wake_path(self.project, "claude", digest).is_file())
        self.assertIsNone(W.watch(self.project, ("claude",), timeout_s=0.3, interval_s=0.05, policy="structured"))


class AgyVerdictLabel(unittest.TestCase):
    """U141-A4 receipt: the real U141-A3 audit reply opened "VERDICT: PASS" (relay_06b6a110) and was tagged NOTICE."""

    def test_labelled_and_bare_verdicts_match(self):
        from v7_harness.coord.agy_dispatch import VERDICT_RE

        for text, token in (("VERDICT: PASS Relay: x", "PASS"), ("**Verdict** - revise: a.py:3", "revise"),
                            ("PASS: matches", "PASS"), ("REWORK", "REWORK")):
            found = VERDICT_RE.match(text)
            self.assertEqual(token, found and found.group(1), text)
        for text in ("Noted, nothing to judge.", "VERDICTS pending", "Passing note"):
            self.assertIsNone(VERDICT_RE.match(text), text)


if __name__ == "__main__":
    unittest.main()
