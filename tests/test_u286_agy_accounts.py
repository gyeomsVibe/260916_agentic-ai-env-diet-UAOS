"""U286 v4: Antigravity per-account resets come from the 429 log and sign-in markers, never from a guess.

Receipt (2026-10-29, 윤겸스): the HUD's Antigravity budget was ledger tokens against a reference cap while the user
rotates one subscription and four free accounts. The log lines below copy the real `language_server.log` shape.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v7_harness.coord.agy_accounts import antigravity_accounts, parse_log

KST = timezone(timedelta(hours=9))
PREFIX = "ERROR: logging before google.Init: "
LOG = "\n".join([
    PREFIX + "I1029 05:45:00.138082       1 server.go:1798] Starting language server process with pid 25592",
    PREFIX + "E1029 06:26:24.100000  9 errorreport.go:224] generating and executing: RESOURCE_EXHAUSTED (code 429): "
             "Individual quota reached. Please upgrade your subscription to increase your limits. Resets in 124h14m54s.",
    PREFIX + "I1029 06:26:51.000000  9 x.go:1] [AuthProvider] SetEnableBusinessLogin called with enable: true",
    PREFIX + "E1029 06:59:41.000000  9 errorreport.go:224] RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 167h27m42s.",
    PREFIX + "E1029 07:05:43.000000  9 errorreport.go:224] RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 167h58m35s.",
    PREFIX + "I1029 08:04:12.000000  9 x.go:1] [AuthProvider] SetEnableBusinessLogin called with enable: true",
    PREFIX + "E1029 08:13:33.000000  9 errorreport.go:224] RESOURCE_EXHAUSTED (code 429): Individual quota reached. Resets in 167h51m18s.",
])
MTIME = datetime(2026, 10, 29, 8, 20, tzinfo=KST)


class ParseLog(unittest.TestCase):
    def test_reset_is_log_time_plus_duration_in_its_sign_in_session(self):
        events, newest = parse_log(LOG, MTIME)
        self.assertEqual("2026-10-29T08:04:12+09:00", newest)
        self.assertEqual(4, len(events))
        self.assertEqual("2026-11-03T10:41:18+09:00", events[0]["resets_at"])  # 06:26:24 + 124h14m54s
        self.assertEqual("2026-10-29T05:45:00+09:00", events[0]["session"])  # before any marker: the log's own start
        # one session's resets drift 37 minutes, yet they stay one session (the reset-time clustering split them)
        self.assertEqual({"2026-10-29T06:26:51+09:00"}, {e["session"] for e in events[1:3]})

    def test_december_line_read_in_january_is_last_year(self):
        line = PREFIX + "E1231 23:00:00.000000 1 e.go:1] RESOURCE_EXHAUSTED (code 429): x. Resets in 2h."
        events, _ = parse_log(line, datetime(2027, 1, 1, 1, 0, tzinfo=KST))
        self.assertEqual("2027-01-01T01:00:00+09:00", events[0]["resets_at"])

    def test_no_429_line_means_no_wait(self):
        self.assertEqual([], parse_log(PREFIX + "I1029 05:45:00.0 1 s.go:1] started", MTIME)[0])


class AccountView(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root, self.appdata = Path(tmp.name) / "proj", Path(tmp.name) / "appdata"
        (self.root / ".coord" / "accounts").mkdir(parents=True)
        (self.root / ".coord" / "accounts" / "antigravity_accounts.json").write_text(json.dumps({"accounts": [
            {"email": "sub@example.com", "kind": "subscription", "plan": "Ultra", "weekly_reset_date": "2026-11-01"},
            {"email": "free1@example.com", "kind": "free", "plan": "무료"},
        ]}), encoding="utf-8")
        logs = self.appdata / "Antigravity" / "logs"
        logs.mkdir(parents=True)
        log = logs / "language_server.log"
        log.write_text(LOG, encoding="utf-8")
        os.utime(log, (MTIME.timestamp(), MTIME.timestamp()))
        (self.appdata / "Antigravity" / "app_storage.json").write_text(
            json.dumps({"jetski.onboarding.lastLoginUsername": "free1@example.com"}), encoding="utf-8")

    def view(self, **kw):
        return antigravity_accounts(self.root, now=datetime(2026, 10, 29, 9, 0, tzinfo=KST), appdata=self.appdata, **kw)

    def test_only_the_newest_session_is_tied_to_the_signed_in_account(self):
        v = self.view()
        free1 = next(a for a in v["accounts"] if a["email"] == "free1@example.com")
        self.assertTrue(free1["signed_in"] and free1["blocked"])
        self.assertEqual("2026-11-05T08:04:51+09:00", free1["resets_at"])
        self.assertIn("로그인", free1["reset_source"])
        self.assertEqual(2, len(v["unassigned_waits"]))  # older sessions stay unidentified, never guessed
        sub = next(a for a in v["accounts"] if a["kind"] == "subscription")
        self.assertFalse(sub["blocked"])
        self.assertEqual(("2026-11-01", "사용자 제공"), (sub["weekly_reset_date"], sub["weekly_reset_source"]))

    def test_waits_survive_a_log_restart_once_persisted(self):
        self.view(persist=True)
        (self.appdata / "Antigravity" / "logs" / "language_server.log").write_text("", encoding="utf-8")
        v = self.view()
        self.assertTrue(next(a for a in v["accounts"] if a["email"] == "free1@example.com")["blocked"])
        self.assertEqual(2, len(v["unassigned_waits"]))

    def test_passed_resets_and_dates_drop_out(self):
        v = antigravity_accounts(self.root, now=datetime(2026, 11, 6, tzinfo=KST), appdata=self.appdata)
        self.assertEqual([], v["unassigned_waits"])
        self.assertFalse(any(a["blocked"] for a in v["accounts"]))
        self.assertIsNone(v["accounts"][0]["weekly_reset_date"])

    def test_missing_sources_say_so(self):
        v = antigravity_accounts(self.root / "none", appdata=self.root / "none")
        self.assertEqual(([], False, False, None), (v["accounts"], v["registry_present"], v["log_present"], v["signed_in"]))


if __name__ == "__main__":
    unittest.main()
