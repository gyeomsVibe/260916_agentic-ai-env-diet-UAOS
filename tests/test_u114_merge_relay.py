import unittest
from unittest import mock
from pathlib import Path
from v7_harness.coord import merge_relay


class MergeRelayTests(unittest.TestCase):
    def test_get_open_prs_parses_json(self):
        sample = '[{"number": 84, "title": "U113", "mergeable": "MERGEABLE"}]'
        with mock.patch("subprocess.run") as m_run:
            m_run.return_value = mock.Mock(returncode=0, stdout=sample)
            prs = merge_relay.get_open_prs(Path("."))
            self.assertEqual(len(prs), 1)
            self.assertEqual(prs[0]["number"], 84)

    def test_notify_claude_merged_calls_deliver(self):
        with mock.patch("v7_harness.coord.deliver.deliver") as m_deliver:
            m_deliver.return_value = mock.Mock(delivered=True)
            res = merge_relay.notify_claude_merged(84, "claude/u113-desk-and-windows")
            self.assertTrue(res)
            self.assertIn("PR #84", m_deliver.call_args[1]["message"])


if __name__ == "__main__":
    unittest.main()
