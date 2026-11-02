"""U294: the Stop hook holds a turn that ends with an approval or choice question to the user."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import stop_gate

ASKING = [
    "정리 끝. 위조 세션 파일을 삭제할까요?",
    "다음으로 진행할까요",
    "이대로 병합하시겠습니까?",
    "검토 후 승인해 주세요.",
    "이 작업을 승인하시겠어요?",
    "권한을 허용하시겠습니까?",
    "원하시면 다음 카드도 하겠습니다.",
    "어떻게 할까요?",
    "Done. Shall I delete the files?",
    "Should I continue with the merge?",
    "Do you want me to push it?",
    "Would you like me to open the PR?",
    "I can do more, want me to?",
    "Please approve the change.",
    "Merge now, approve?",
]
STATEMENTS = [
    "**결과**: U294 완료 — 승인 질문이 막힌다\n- 근거: 테스트 12개 통과",
    "**결과**: 완료\n- **남은 일**: 사용자가 원격 push를 승인해 주세요 라고 적힌 항목은 서술문으로 남긴다",
    "**결과**: 완료\n- **남은 일**: 생성 기록 삭제(사람 전용), 이 동작은 승인 전까지 대기한다",
    "Everything is merged and the suite is green.",
    "",
]


def hold(payload: dict, tool: str = "claude"):
    return stop_gate.approval_ask_hold(payload, tool)


class ApprovalAskHold(unittest.TestCase):
    def test_every_pattern_family_holds(self) -> None:
        for text in ASKING:
            with self.subTest(text=text):
                result = hold({"last_assistant_message": "긴 보고 본문.\n" + text})
                self.assertEqual(result["decision"], "block")
                self.assertIn("U294", result["reason"])

    def test_statements_and_remaining_lines_pass(self) -> None:
        for text in STATEMENTS:
            with self.subTest(text=text):
                self.assertIsNone(hold({"last_assistant_message": text}))

    def test_remaining_line_with_question_mark_still_holds(self) -> None:
        self.assertIsNotNone(hold({"last_assistant_message": "- **남은 일**: 삭제를 승인해 주세요?"}))

    def test_only_the_tail_is_read(self) -> None:
        text = "삭제할까요?\n" + "x" * (stop_gate.ASK_TAIL_CHARS + 50)
        self.assertIsNone(hold({"last_assistant_message": text}))

    def test_stop_hook_active_is_not_held_again(self) -> None:
        self.assertIsNone(hold({"last_assistant_message": "삭제할까요?", "stop_hook_active": True}))

    def test_decision_per_tool(self) -> None:
        payload = {"last_assistant_message": "삭제할까요?"}
        self.assertEqual(hold(payload, "codex")["decision"], "block")
        self.assertEqual(hold(payload, "antigravity")["decision"], "continue")

    def test_transcript_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            rows = [
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "삭제할까요?"}]}},
                {"type": "user", "message": {"role": "user", "content": "응"}},
                {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "x"}]}},
            ]
            path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
            # newest assistant text entry is the question: the tool_use-only row has no text and is skipped
            self.assertIsNotNone(hold({"transcript_path": str(path)}))
            rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Shall I go on?"}]}})
            path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            self.assertIsNotNone(hold({"transcript_path": str(path)}))
            rows.append({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "완료."}]}})
            path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            self.assertIsNone(hold({"transcript_path": str(path)}))

    def test_missing_inputs_do_not_crash(self) -> None:
        for payload in ({}, {"transcript_path": "Z:/no/such.jsonl"}, {"transcript_path": 5}, None, "x",
                        {"last_assistant_message": None}):
            with self.subTest(payload=payload):
                self.assertIsNone(hold(payload))


if __name__ == "__main__":
    unittest.main()
