```contract
work_id: U96-N
worker: apply
goal: The U63 handoff ladder names its states AMPLE/LOW/HANDOFF_READY, so no state called NORMAL or THRIFT contradicts the token-thrift default mode (U95-T); records saved under the old names still read correctly.
inputs:
- v7_harness/coord/thrift.py sha256=a3c262999c7f2316d6bfc4e65321f0d11755d60a43b98570449a9fc63e2b86ca
- v7_harness/coord/mode.py sha256=40646692fd07f56d8954db6456f7e55127234e42f1c1862f43a91e4c4d4be783
- tests/test_u63_thrift_mode.py sha256=644143e5a8c80c8233a2d3e8f556f981ae1e9378f59c33433f5d1d7167bc010e
- tests/test_u71_three_tool_e2e.py sha256=916e6957d708ccf4a09580e98ab874260d872346a256da1574163794a1366685
- docs/52_u63-token-budget-thrift-mode.md sha256=0af77f37a755666e7995227b308d73272d5ef5fc4097554878bfc7843cde343f
- docs/58_u71-three-tool-continuity-e2e.md sha256=56755c4f44586b9e1d23e3b902157c3f4f9ba2ed2b51b0308e06773594465ace
- .coord/PLAN.md sha256=829353fbd7d85f560733e9577aa93dae23baef3b6b71cf8c391d9fab740a0242
allow:
- v7_harness/coord/thrift.py
- v7_harness/coord/mode.py
- tests/test_u63_thrift_mode.py
- tests/test_u71_three_tool_e2e.py
- tests/test_u96n_ladder_names.py
- docs/52_u63-token-budget-thrift-mode.md
- docs/58_u71-three-tool-continuity-e2e.md
- .coord/PLAN.md
acceptance: python -m unittest tests.test_u96n_ladder_names tests.test_u63_thrift_mode tests.test_u71_three_tool_e2e tests.test_u95t_thrift_mode
forbidden: design changes; edits outside allow; weakening any assertion (existing tests change only the state names); renaming the CLI flag --thrift-at or the stored "thresholds" key; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. Receipt: `.coord/tasks/U96-queue-handoff.md` item 2. U95-T made token-thrift the default mode, yet `coord thrift` still called its no-handoff state `NORMAL` and its reserve state `THRIFT`. A reader of a packet or a letter saw "NORMAL" and read "token-thrift is off". Existing test edits only rename the expected state strings; every assertion keeps its meaning.

===EDIT: v7_harness/coord/thrift.py===
<<<<<<< SEARCH
class ThriftRejected(ValueError): pass
LOCK_STALE_S = 60.0
=======
class ThriftRejected(ValueError): pass
LOCK_STALE_S = 60.0
# U96-N: ladder states. AMPLE = enough quota left, no handoff; LOW = keep working under the tool's reserve policy.
# They were NORMAL/THRIFT until U96-N, which read as "token-thrift is off" beside the default mode (U95-T, mode.py).
AMPLE, LOW, HANDOFF_READY = "AMPLE", "LOW", "HANDOFF_READY"
# Records written before U96-N still hold the old names; map them so an old NORMAL never looks like a return from LOW.
LEGACY_STATES = {"NORMAL": AMPLE, "THRIFT": LOW}
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/thrift.py===
<<<<<<< SEARCH
    state = "NORMAL" if remaining_percent >= thrift_at else ("HANDOFF_READY" if remaining_percent <= handoff_at else "THRIFT")
    fields = tuple(value.strip() if isinstance(value, str) else "" for value in
                   (current_card, next_action, acceptance, stop_condition))
    if state != "NORMAL" and not all(fields):
        raise ThriftRejected("non-NORMAL state requires current card, next action, acceptance, and stop condition")
=======
    state = AMPLE if remaining_percent >= thrift_at else (HANDOFF_READY if remaining_percent <= handoff_at else LOW)
    fields = tuple(value.strip() if isinstance(value, str) else "" for value in
                   (current_card, next_action, acceptance, stop_condition))
    if state != AMPLE and not all(fields):
        raise ThriftRejected("non-AMPLE state requires current card, next action, acceptance, and stop condition")
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/thrift.py===
<<<<<<< SEARCH
        target = tool if state == "THRIFT" else (_successor(tool, desk) if state == "HANDOFF_READY" else tool)
        event = "RETURN_REVIEW" if state == "NORMAL" and previous.get("state") not in (None, "NORMAL") else "HANDOFF"
        packet_path = None; packet_hash = None
        if state != "NORMAL":
=======
        target = tool if state == LOW else (_successor(tool, desk) if state == HANDOFF_READY else tool)
        previous_state = LEGACY_STATES.get(previous.get("state"), previous.get("state"))
        event = "RETURN_REVIEW" if state == AMPLE and previous_state not in (None, AMPLE) else "HANDOFF"
        packet_path = None; packet_hash = None
        if state != AMPLE:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/thrift.py===
<<<<<<< SEARCH
        if state == "NORMAL" and event != "RETURN_REVIEW":
=======
        if state == AMPLE and event != "RETURN_REVIEW":
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/mode.py===
<<<<<<< SEARCH
percentage (its NORMAL/THRIFT/HANDOFF_READY states decide reserves and handoff packets). It runs inside this mode;
its NORMAL state means "no handoff needed", never "token-thrift is off".
=======
percentage (its AMPLE/LOW/HANDOFF_READY states decide reserves and handoff packets; U96-N renamed them from
NORMAL/THRIFT). It runs inside this mode; AMPLE means "no handoff needed", never "token-thrift is off".
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u63_thrift_mode.py===
<<<<<<< SEARCH
        for value,expected in ((100,"NORMAL"),(20,"NORMAL"),(19.99,"THRIFT"),(7.01,"THRIFT"),(7,"HANDOFF_READY"),(0,"HANDOFF_READY")):
=======
        for value,expected in ((100,"AMPLE"),(20,"AMPLE"),(19.99,"LOW"),(7.01,"LOW"),(7,"HANDOFF_READY"),(0,"HANDOFF_READY")):
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u63_thrift_mode.py===
<<<<<<< SEARCH
        self.assertEqual("THRIFT",apply(self.root,tool="codex",remaining_percent=15,**self.fields)["state"])
=======
        self.assertEqual("LOW",apply(self.root,tool="codex",remaining_percent=15,**self.fields)["state"])
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u71_three_tool_e2e.py===
<<<<<<< SEARCH
        self.assertEqual(("THRIFT", "codex", "COMMANDER_RESERVE"), (delta["state"], delta["target"], delta["policy"]))
=======
        self.assertEqual(("LOW", "codex", "COMMANDER_RESERVE"), (delta["state"], delta["target"], delta["policy"]))
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u71_three_tool_e2e.py===
<<<<<<< SEARCH
        self.assertEqual(3, len(self._packets()))  # RETURN_REVIEW is NORMAL: a letter, no packet
=======
        self.assertEqual(3, len(self._packets()))  # RETURN_REVIEW is AMPLE: a letter, no packet
>>>>>>> REPLACE
===END===

===EDIT: docs/52_u63-token-budget-thrift-mode.md===
<<<<<<< SEARCH
`coord thrift`는 관찰한 잔여율을 토큰으로 환산하지 않고 `NORMAL`(20% 이상), `THRIFT`(7% 초과 20% 미만), `HANDOFF_READY`(7% 이하)만 결정한다. 20%와 7%는 대조 측정 전 `UNMEASURED` 정책값이다.
=======
`coord thrift`는 관찰한 잔여율을 토큰으로 환산하지 않고 `AMPLE`(20% 이상), `LOW`(7% 초과 20% 미만), `HANDOFF_READY`(7% 이하)만 결정한다. 20%와 7%는 대조 측정 전 `UNMEASURED` 정책값이다.

상태 이름(U96-N): 예전 이름은 `NORMAL`·`THRIFT`였다. 기본 운영 모드가 토큰예산절약(token-thrift, U95-T)이 된 뒤 `NORMAL`이 "절약 모드 꺼짐"으로 읽혀 `AMPLE`(여유)·`LOW`(부족)로 바꿨다. 예전 이름으로 저장된 기록은 새 이름으로 읽는다. 명령 옵션 `--thrift-at`과 저장 키 `thresholds.thrift`는 호환을 위해 그대로 둔다.
>>>>>>> REPLACE
===END===

===EDIT: docs/58_u71-three-tool-continuity-e2e.md===
<<<<<<< SEARCH
2. **THRIFT**(Codex 15%)
=======
2. **LOW**(Codex 15%)
>>>>>>> REPLACE
===END===

===EDIT: docs/58_u71-three-tool-continuity-e2e.md===
<<<<<<< SEARCH
RETURN_REVIEW는 NORMAL 상태라 편지만 있고 패킷은 없다.
=======
RETURN_REVIEW는 AMPLE 상태라 편지만 있고 패킷은 없다.
>>>>>>> REPLACE
===END===

===EDIT: .coord/PLAN.md===
<<<<<<< SEARCH
`v7_harness/pilot.py`, `tests/test_u96s_source_escape.py` |
=======
`v7_harness/pilot.py`, `tests/test_u96s_source_escape.py` |
| U96-N | REVIEW (Claude 설계, Codex 복귀 시 재검토) | claude(설계) · apply(0토큰) | 영수증: 기본 모드가 토큰예산절약(U95-T)인데 U63 인계 사다리는 여유 상태를 `NORMAL`, 절약 상태를 `THRIFT`로 불러 "절약 꺼짐"으로 읽혔다. 조치: `AMPLE`/`LOW`/`HANDOFF_READY`로 바꾸고 예전 이름으로 저장된 기록은 새 이름으로 읽는다(잘못된 RETURN_REVIEW 방지). — `v7_harness/coord/thrift.py`, `tests/test_u96n_ladder_names.py` |
>>>>>>> REPLACE
===END===

===FILE: tests/test_u96n_ladder_names.py===
"""U96-N: the handoff ladder says AMPLE/LOW/HANDOFF_READY, and old NORMAL/THRIFT records still read correctly."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import presence
from v7_harness.coord.thrift import AMPLE, HANDOFF_READY, LEGACY_STATES, LOW, apply

FIELDS = dict(current_card="U96-N", next_action="rename", acceptance="python -m unittest", stop_condition="test changed")


class LadderNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".coord/mailbox").mkdir(parents=True)
        for tool in presence.TOOLS:
            presence.mark(self.root, tool, "ACTIVE")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _old_record(self, state: str) -> None:
        path = self.root / ".coord/thrift/state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema": "uaos-thrift-v1", "sequence": 1,
                                    "tools": {"codex": {"state": state, "input_fingerprint": "pre-u96n"}}}), encoding="utf-8")

    def test_no_state_is_named_normal_or_thrift(self) -> None:
        states = {apply(self.root / str(v), tool="codex", remaining_percent=v, **FIELDS)["state"]
                  for v in (80, 15, 5) if not (self.root / str(v) / ".coord/mailbox").mkdir(parents=True)}
        self.assertEqual({AMPLE, LOW, HANDOFF_READY}, states)
        self.assertFalse(states & {"NORMAL", "THRIFT"})
        self.assertEqual({"NORMAL": AMPLE, "THRIFT": LOW}, LEGACY_STATES)

    def test_old_thrift_record_returns_for_review(self) -> None:
        self._old_record("THRIFT")
        result = apply(self.root, tool="codex", remaining_percent=80)
        self.assertEqual(("ACTIONABLE_DELTA", "RETURN_REVIEW", AMPLE), (result["status"], result["event"], result["state"]))

    def test_old_normal_record_is_not_a_return(self) -> None:
        self._old_record("NORMAL")
        result = apply(self.root, tool="codex", remaining_percent=80)
        self.assertEqual(("ACK_ONLY", "HANDOFF", AMPLE), (result["status"], result["event"], result["state"]))


if __name__ == "__main__":
    unittest.main()
===END===
