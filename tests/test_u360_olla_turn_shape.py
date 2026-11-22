"""U360: olla.turn_shape must start a new turn at Antigravity autonomous wake boundaries.

Receipt: a live Antigravity transcript.jsonl logged `narration_blocks: 21/22` on compliant 4-line turns,
because only USER_INPUT / USER_EXPLICIT reset the turn, so every earlier autonomous wake turn
(SYSTEM_MESSAGE or CHECKPOINT with source == "SYSTEM") was counted as mid-turn narration.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness import olla

REPORT = "**결과**: 완료\n- 근거: 테스트 통과\n- 위험: 없음\n- 다음: 없음"


def _user(text: str = "과제 해줘") -> dict:
    return {"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": text}


def _model(content: str, tool_calls: list | None = None) -> dict:
    row = {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": content}
    if tool_calls is not None:
        row["tool_calls"] = tool_calls
    return row


def _system(kind: str, source: str | None = "SYSTEM") -> dict:
    row = {"type": kind, "content": "wake"}
    if source is not None:
        row["source"] = source
    return row


def _generic() -> dict:
    return {"source": "SYSTEM", "type": "GENERIC", "content": "tool output"}


class TurnShapeAutonomousWakeTests(unittest.TestCase):
    def _write(self, rows: list[dict]) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "transcript.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
        return path

    def test_a_multi_wake_compliant_turns_have_no_narration(self) -> None:
        path = self._write([
            _user(),
            _model(REPORT),
            _system("SYSTEM_MESSAGE"),
            _model("", tool_calls=[{"name": "run_command"}]),
            _generic(),
            _model(REPORT),
            _system("SYSTEM_MESSAGE"),
            _model(REPORT),
        ])
        shape = olla.turn_shape(path)
        self.assertEqual(0, shape["narration_blocks"])
        self.assertEqual(4, shape["final_lines"])

    def test_b_checkpoint_boundary_starts_new_turn(self) -> None:
        path = self._write([_user(), _model(REPORT), _system("CHECKPOINT"), _model(REPORT)])
        self.assertEqual(0, olla.turn_shape(path)["narration_blocks"])

    def test_c_real_narration_inside_wake_turn_is_counted(self) -> None:
        path = self._write([
            _system("SYSTEM_MESSAGE"),
            _model("중간 설명", tool_calls=[{"name": "run_command"}]),
            _generic(),
            _model("최종 보고"),
        ])
        shape = olla.turn_shape(path)
        self.assertEqual(1, shape["narration_blocks"])
        self.assertEqual(len("최종 보고"), shape["final_chars"])

    def test_d_error_and_non_system_messages_do_not_reset(self) -> None:
        path = self._write([
            _user(),
            _model("중간 설명", tool_calls=[{"name": "run_command"}]),
            _system("ERROR_MESSAGE"),
            _model(REPORT),
        ])
        self.assertEqual(1, olla.turn_shape(path)["narration_blocks"])
        for source in ("OTHER", None):
            with self.subTest(source=source):
                path = self._write([
                    _user(),
                    _model("중간 설명"),
                    _system("SYSTEM_MESSAGE", source=source),
                    _model(REPORT),
                ])
                self.assertEqual(1, olla.turn_shape(path)["narration_blocks"])

    def test_e_existing_formats_unchanged(self) -> None:
        agy = self._write([_user(), _model("중간 설명"), _model("**결과**: 완료\n- 과정: A -> B\n- 근거: 테스트 통과")])
        self.assertEqual(1, olla.turn_shape(agy)["narration_blocks"])
        self.assertEqual(3, olla.turn_shape(agy)["final_lines"])
        claude = self._write([
            {"type": "user", "message": {"content": "이전 지시"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "옛 보고"}]}},
            {"type": "user", "message": {"content": "새 지시"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "진행 설명"}, {"type": "tool_use"}]}},
            {"type": "user", "message": {"content": [{"type": "tool_result"}]}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "결과 1\n결과 2"}]}},
        ])
        self.assertEqual({"narration_blocks": 1, "final_lines": 2, "final_chars": 9, "nested_lines": 0},
                         olla.turn_shape(claude))
        msg = lambda t: {"type": "response_item",
                         "payload": {"type": "message", "role": "assistant", "content": [{"text": t}]}}
        codex = self._write([{"type": "event_msg", "payload": {"type": "task_started"}}, msg("a"), msg("b"), msg("끝")])
        self.assertEqual(2, olla.turn_shape(codex)["narration_blocks"])


if __name__ == "__main__":
    unittest.main()
