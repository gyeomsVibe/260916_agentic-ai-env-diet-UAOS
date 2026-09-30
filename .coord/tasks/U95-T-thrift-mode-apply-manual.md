```contract
work_id: U95-T
worker: apply
goal: Make token-thrift the runtime's default operating mode: code reads the mode, every session briefing names it, and in token-thrift a card over its share of the budget keeps the next card closed until it is split.
inputs:
- .coord/PLAN.md sha256=9ad1c619e4b1cbb2340fd12c5967c33ba836c8075452baccd1cb401db5454aaf
- v7_harness/coord/hook_context.py sha256=11b6e1b5af178ce22bd724c8dee91cae0b6133ea72de1b0d7c126fbb08526d60
- v7_harness/coord/card_cost.py sha256=fd40948e675910087c19ed1790937928d642d3e9db8e7548ea4960c8e4726cbe
- tests/test_u76c_card_cost.py sha256=544d2f7a5d0c99dc17c43f2724c837fe3212f1c879a4ce044278bfaa8262f692
allow:
- v7_harness/coord/mode.py
- v7_harness/coord/hook_context.py
- v7_harness/coord/card_cost.py
- tests/test_u95t_thrift_mode.py
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u95t_thrift_mode tests.test_u76c_card_cost tests.test_u95a_antigravity_briefing tests.test_u37_install_everywhere tests.test_u57_desk_signals tests.test_u63_thrift_mode tests.test_u58_session_presence tests.test_u59_shared_desk tests.test_u46_followup_fixes tests.test_u38_cost_gate_and_claude_worker
forbidden: design changes; edits outside allow; editing or weakening existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the EDIT and FILE blocks exactly.

Receipt (윤겸스, 2026-09-30, MIA strategic mode): "UAOS-RSI 운영체제의 기본운영 모드는 토큰예산절약 모드이다", and the
premise that one Claude or Codex conversation drains a 5-hour or weekly limit before one process is done must be the
yardstick. The owner then asked whether writing it in the global rules is enough, or whether UAOS-RSI must implement it
as internal logic. Audit: the rules have said "Token-thrift is default" since v6, but no runtime code reads a mode, the
session briefings never name it, and the per-card cost gate (U76-C) only fails a card at 3x the baseline card average,
so a card could cost up to three average cards and still open the next one.

Design (smallest enforceable piece; the U95-B meter measures the effect):
- `v7_harness/coord/mode.py` is the one place the runtime asks which mode is on. Default token-thrift; only a
  committed `.coord/mode.json` with `set_by: user` and a reason switches to normal (fail-thrift on anything else).
- `card_cost`: in token-thrift a card may spend at most 1.0x the pinned baseline card average (its share). Over the
  share the status stays PASS/FAIL for the 3x regression rule, but `next_card_allowed` is false and the exit code is 1:
  split the card. Normal mode keeps the 3x rule alone.
- The SessionStart briefing (Claude, Codex) and Antigravity's briefing name the mode, so all three tools see it on
  every session at about 20 tokens, with no per-prompt injection (the 09-23 hooks were net negative).
- The module is `mode.py`: `thrift.py` already holds U63's remaining-quota handoff ladder, whose state names
  (NORMAL above 20% remaining) read as if thrift were the exception. Renaming those states changes U63's tests, so it
  is a separate card for Codex review; the docstring here states the relation.
- Rejected: refusing paid workers without a reason in manual lint. Thin headless workers (6-8k first-call context
  against 63-66k in the desktop app) are a thrift lever, and no receipt shows them overused.

===FILE: v7_harness/coord/mode.py===
"""U95-T: token-thrift is UAOS-RSI's default operating mode, read by code and not only written in the rules.

Receipt (윤겸스, 2026-09-30): with today's habits one Claude or Codex conversation drains a 5-hour or weekly limit
before one process, let alone a project, is done. The goal is a much longer workflow on the same budget, and
token-thrift is the default mode. The rules said "Token-thrift is default" since v6, yet no code read a mode, so
nothing changed when a card overspent. This module is the one place the runtime asks which mode is on:

- Token-thrift unless `.coord/mode.json` holds {"mode": "normal", "set_by": "user", "reason": "..."}. A missing,
  unreadable or different file keeps token-thrift (fail-thrift): only 윤겸스's explicit instruction ends it, and the
  file is a reviewed commit, so the switch is visible in history.
- In token-thrift a card may spend at most its share, SHARE_LIMIT times the pinned baseline card average
  (`card_cost`); over it the card is split, not continued. Normal mode keeps only the 3x regression rule.

Not to be confused with `coord thrift` (U63, `thrift.py`): that is a handoff ladder over an observed remaining-quota
percentage (its NORMAL/THRIFT/HANDOFF_READY states decide reserves and handoff packets). It runs inside this mode;
its NORMAL state means "no handoff needed", never "token-thrift is off".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODE_FILE = Path(".coord") / "mode.json"
THRIFT = "token-thrift"
NORMAL = "normal"
# The yardstick as a number: a card may cost what the average pinned baseline card cost (.coord/card_baseline.json).
# It is the line a card must not cross, not the target: the U95 success signal asks for 30% below that average.
SHARE_LIMIT = 1.0
# Said once per session start (Claude, Codex) or conversation (Antigravity): about 20 tokens, never per prompt.
THRIFT_PHRASE = "Mode: token-thrift (default): cut paid calls, tool output and idle gaps."


def current_mode(project: Path | str) -> dict[str, Any]:
    """{"mode", "source"[, "reason"]}; anything but an explicit user switch to normal is token-thrift."""
    path = Path(project) / MODE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"mode": THRIFT, "source": "default"}
    except (OSError, ValueError):
        return {"mode": THRIFT, "source": "unreadable"}
    if not isinstance(data, dict):
        return {"mode": THRIFT, "source": "invalid"}
    reason = data.get("reason")
    if (data.get("mode") == NORMAL and data.get("set_by") == "user" and isinstance(reason, str)
            and reason.strip()):
        return {"mode": NORMAL, "source": MODE_FILE.as_posix(), "reason": reason.strip()}
    return {"mode": THRIFT, "source": MODE_FILE.as_posix() if data.get("mode") == THRIFT else "invalid"}


def mode_phrase(project: Path | str) -> str:
    mode = current_mode(project)
    if mode["mode"] == NORMAL:
        return f"Mode: normal, set by 윤겸스 ({mode['reason'][:80]})."
    return THRIFT_PHRASE


def over_share(project: Path | str, ratios: dict[str, float]) -> list[str]:
    """Metrics whose ratio to the baseline card average exceeds the share; empty outside token-thrift."""
    if current_mode(project)["mode"] != THRIFT:
        return []
    return [metric for metric, ratio in ratios.items() if ratio > SHARE_LIMIT]
===END===

===EDIT: v7_harness/coord/card_cost.py===
<<<<<<< SEARCH
    ratios = {m: round(spent[m] / (base[m] / baseline_cards), 2) for m in METRICS}
    over = [m for m in METRICS if ratios[m] > RATIO_LIMIT]
    return {**result, "status": "FAIL" if over else "PASS", "ratios": ratios, "over_limit": over,
            "next_card_allowed": not over,
            "reason": "over 3x the baseline card average: " + ", ".join(over) if over else None}
=======
    ratios = {m: round(spent[m] / (base[m] / baseline_cards), 2) for m in METRICS}
    over = [m for m in METRICS if ratios[m] > RATIO_LIMIT]
    # U95-T: in token-thrift (the default) a card may spend at most its share of the budget; over it the 3x status is
    # kept, but the next card stays closed until this one is split.
    from .mode import SHARE_LIMIT, THRIFT, current_mode, over_share

    mode = current_mode(project)["mode"]
    beyond = over_share(project, ratios)
    if over:
        reason = "over 3x the baseline card average: " + ", ".join(over)
    elif beyond:
        reason = f"over its share ({SHARE_LIMIT:g}x the baseline card average, token-thrift): split the card: " \
                 + ", ".join(beyond)
    else:
        reason = None
    return {**result, "status": "FAIL" if over else "PASS", "ratios": ratios, "over_limit": over, "mode": mode,
            "share_limit": SHARE_LIMIT if mode == THRIFT else None, "over_share": beyond,
            "next_card_allowed": not over and not beyond, "reason": reason}
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/card_cost.py===
<<<<<<< SEARCH
    # Exit 0 only on PASS against the pinned baseline: FAIL, UNKNOWN and exploratory runs keep the next card closed.
    return 0 if result["status"] == "PASS" and not result.get("exploratory", True) else 1
=======
    # Exit 0 only on PASS against the pinned baseline: FAIL, UNKNOWN and exploratory runs keep the next card closed,
    # and so does a card over its token-thrift share (U95-T).
    allowed = result["status"] == "PASS" and result.get("next_card_allowed", False)
    return 0 if allowed and not result.get("exploratory", True) else 1
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
    return (f"UAOS project {Path(project).name}: inbox {len(inbox)} (P1 {wakes}, RSI reviews {reviews}); desk {desk}. "
            "Read .coord/PLAN.md; `coord inbox` lists what waits. "
=======
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
    from .mode import mode_phrase  # U95-T: every session learns the operating mode from code, not only the rules

    return (f"UAOS project {Path(project).name}: inbox {len(inbox)} (P1 {wakes}, RSI reviews {reviews}); desk {desk}. "
            f"{mode_phrase(project)} "
            "Read .coord/PLAN.md; `coord inbox` lists what waits. "
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
    letters = agy_letters(project)
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
    conversation = str(event.get("conversationId") or "")
    fingerprint = hashlib.sha256("\n".join([conversation, desk, *letters]).encode("utf-8")).hexdigest()
=======
    letters = agy_letters(project)
    desk = ", ".join(f"{tool}={info.get('state')}" for tool, info in presence.items())
    conversation = str(event.get("conversationId") or "")
    from .mode import mode_phrase  # U95-T

    mode = mode_phrase(project)
    fingerprint = hashlib.sha256("\n".join([conversation, desk, mode, *letters]).encode("utf-8")).hexdigest()
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/hook_context.py===
<<<<<<< SEARCH
            "own work. ")
    if letters:
=======
            f"own work. {mode} ")
    if letters:
>>>>>>> REPLACE
===END===

===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
`v7_harness/cost_meter.py`, `tests/test_u95b_cost_meter.py` |
=======
`v7_harness/cost_meter.py`, `tests/test_u95b_cost_meter.py` |
| U95-T | REVIEW (Claude 설계, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 영수증: 윤겸스 지시(2026-09-30) "기본운영 모드는 토큰예산절약 모드", 한 대화에 5시간·1주 한도가 바닥나는 현실이 척도. 규칙에는 v6부터 "Token-thrift is default"가 있었지만 모드를 읽는 코드가 없고, 카드 비용 관문은 기준 카드 평균의 3배에서만 막았음. 조치: `mode.py`가 모드를 판독(기본 절약, `.coord/mode.json`에 set_by user와 이유가 있을 때만 normal), 세션 시작 안내(Claude·Codex·Antigravity)가 모드를 알리고, 절약 모드에서 카드가 기준 평균 1배(몫)를 넘으면 다음 카드를 닫고 분할을 요구. — `v7_harness/coord/mode.py`, `v7_harness/coord/card_cost.py`, `v7_harness/coord/hook_context.py`, `tests/test_u95t_thrift_mode.py` |
>>>>>>> REPLACE
===END===

===FILE: tests/test_u95t_thrift_mode.py===
"""U95-T: token-thrift is the runtime's default mode; a card over its share keeps the next card closed."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from v7_harness.coord import card_cost
from v7_harness.coord.hook_context import agy_line, brief_line
from v7_harness.coord.mode import MODE_FILE, NORMAL, SHARE_LIMIT, THRIFT, current_mode, mode_phrase

DESK = {"codex": {"state": "ABSENT"}, "claude": {"state": "ACTIVE"}, "antigravity": {"state": "ACTIVE"}}


def _row(work_id: str, inp: int, out: int) -> dict:
    return {"work_id": work_id, "kind": "session", "input_tokens": inp, "output_tokens": out}


class ThriftModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "260916_agentic-ai-env-diet"
        (self.root / ".coord" / "usage").mkdir(parents=True)
        (self.root / ".coord" / "PLAN.md").write_text("# plan\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _mode(self, data) -> None:
        text = data if isinstance(data, str) else json.dumps(data)
        (self.root / MODE_FILE).write_text(text, encoding="utf-8")

    def test_default_and_every_invalid_file_is_token_thrift(self) -> None:
        self.assertEqual({"mode": THRIFT, "source": "default"}, current_mode(self.root))
        for data in ("{bad", [1], {"mode": NORMAL}, {"mode": NORMAL, "set_by": "claude", "reason": "x"},
                     {"mode": NORMAL, "set_by": "user", "reason": "  "}, {"mode": "fast", "set_by": "user"}):
            self._mode(data)
            self.assertEqual(THRIFT, current_mode(self.root)["mode"], data)

    def test_only_an_explicit_user_switch_is_normal(self) -> None:
        self._mode({"mode": NORMAL, "set_by": "user", "reason": "one-off deep audit"})
        self.assertEqual({"mode": NORMAL, "source": ".coord/mode.json", "reason": "one-off deep audit"},
                         current_mode(self.root))
        self.assertIn("normal, set by 윤겸스 (one-off deep audit)", mode_phrase(self.root))

    def test_share_is_one_average_card_and_the_3x_rule_stays(self) -> None:
        self.assertEqual(1.0, SHARE_LIMIT)
        self.assertEqual(3.0, card_cost.RATIO_LIMIT)

    def _ledger(self, rows) -> None:
        path = self.root / ".coord" / "usage" / "runs.jsonl"
        path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def test_a_card_over_its_share_is_split_in_thrift_mode_only(self) -> None:
        self._ledger([_row("B", 1000, 100), _row("C", 2000, 200), _row("D", 900, 90)])
        (self.root / ".coord" / "card_baseline.json").write_text(
            json.dumps({"baseline": "B", "baseline_cards": 1}), encoding="utf-8")
        over = card_cost.report(self.root, card="C", baseline="B", baseline_cards=1)
        self.assertEqual(("PASS", THRIFT, False), (over["status"], over["mode"], over["next_card_allowed"]))
        self.assertEqual(["total_tokens", "output_tokens"], over["over_share"])
        self.assertIn("split the card", over["reason"])
        within = card_cost.report(self.root, card="D", baseline="B", baseline_cards=1)
        self.assertEqual(([], True), (within["over_share"], within["next_card_allowed"]))
        with patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(1, card_cost.main(["--project", str(self.root), "--card", "C"]))
            self.assertEqual(0, card_cost.main(["--project", str(self.root), "--card", "D"]))
            self._mode({"mode": NORMAL, "set_by": "user", "reason": "measured A/B"})
            self.assertEqual(0, card_cost.main(["--project", str(self.root), "--card", "C"]))
        normal = card_cost.report(self.root, card="C", baseline="B", baseline_cards=1)
        self.assertEqual((NORMAL, [], True), (normal["mode"], normal["over_share"], normal["next_card_allowed"]))

    def test_the_session_briefing_names_the_mode_without_losing_its_tail(self) -> None:
        line = brief_line(self.root, DESK)
        self.assertIn("Mode: token-thrift (default)", line)
        self.assertTrue(line.endswith("never via the user."), line)
        self._mode({"mode": NORMAL, "set_by": "user", "reason": "measured A/B"})
        self.assertIn("Mode: normal", brief_line(self.root, DESK))

    def test_antigravity_briefing_names_the_mode_and_repeats_when_it_changes(self) -> None:
        event = json.dumps({"invocationNum": 0, "conversationId": "c1"})
        self.assertIn("Mode: token-thrift (default)", agy_line(self.root, DESK, event))
        self.assertEqual("", agy_line(self.root, DESK, event))  # unchanged desk: silent
        self._mode({"mode": NORMAL, "set_by": "user", "reason": "measured A/B"})
        self.assertIn("Mode: normal", agy_line(self.root, DESK, event))


if __name__ == "__main__":
    unittest.main()
===END===
