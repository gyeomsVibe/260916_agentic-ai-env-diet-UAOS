"""U100-P: read the date in Codex's weekly reset message.

Receipt (2026-09-28 rollout, found in the U100 audit): Codex printed "try again at Oct 4th, 2026 2:35 AM". The
parser only knew "try again at 2:35 AM", fell back to one hour, and Antigravity wrote a 4-day ABSENT lease by hand
that ended 12 h after the real reset. Fixed acceptance written by the judge (claude) before the fix.
"""

from __future__ import annotations

import unittest
from datetime import datetime

from v7_harness.coord.presence import UNPARSED_RESET_S, _reset_at

COMPLETED = datetime(2026, 9, 28, 20, 0).timestamp()


class DatedResetTests(unittest.TestCase):
    def test_dated_weekly_reset_is_read(self) -> None:
        message = "You've hit your usage limit. ... or try again at Oct 4th, 2026 2:35 AM."
        self.assertEqual(datetime(2026, 10, 4, 2, 35).timestamp(), _reset_at(message, COMPLETED))

    def test_other_ordinal_suffixes_and_pm(self) -> None:
        for day, suffix in ((1, "st"), (2, "nd"), (3, "rd"), (21, "st")):
            message = f"try again at Nov {day}{suffix}, 2026 1:05 PM."
            self.assertEqual(datetime(2026, 11, day, 13, 5).timestamp(), _reset_at(message, COMPLETED))

    def test_clock_only_message_still_rolls_to_next_day(self) -> None:
        self.assertEqual(datetime(2026, 9, 29, 1, 35).timestamp(), _reset_at("try again at 1:35 AM.", COMPLETED))

    def test_unreadable_date_falls_back_to_one_hour(self) -> None:
        self.assertEqual(COMPLETED + UNPARSED_RESET_S, _reset_at("try again at Foo 4th, 2026 2:35 AM.", COMPLETED))


if __name__ == "__main__":
    unittest.main()
