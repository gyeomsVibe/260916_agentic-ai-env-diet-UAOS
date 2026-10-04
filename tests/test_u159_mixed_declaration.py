"""U159: a user-window declaration still counts when the same prompt also lists other requirements.

Receipt (2026-10-04, Codex relay_89ccebf3): 윤겸스 typed in a Codex thread "이제 부터 여기가 사용자 대상 대화창구이다." followed by
bullet requirements that mention 오류 and 실패. is_declaration() rejected the whole prompt because a repair word appeared
anywhere in it, so the thread was not titled and Codex registered the desk by hand. A declaration is one sentence; a
repair word in a different sentence does not turn it into a repair request.
"""

import unittest

from v7_harness.coord import user_window as uw

# The prompt as the U150 hook recorded it (first two lines; the rest are more requirement bullets).
MIXED = ("이제 부터 여기가 사용자 대상 대화창구이다.\n"
         "- 항상 문제점, 오류 등을 빠짐없이 잘 기록하고, 기록한 데이터 등을 이용해서 우리 RSI 자동 업데이트 (업그레이드) "
         "시스템이 주기적으로 어떤 로직, 프로세스로 자가 업데이트(RSI 업데이트) 되는지 확인하고\n"
         "- 실패한 사례도 기록하라")


class MixedPrompt(unittest.TestCase):
    def test_declaration_followed_by_requirements_that_name_errors_is_a_declaration(self):
        self.assertTrue(uw.is_declaration(MIXED))

    def test_requirement_lines_alone_are_not_a_declaration(self):
        self.assertFalse(uw.is_declaration(MIXED.split("\n", 1)[1]))

    def test_repair_words_in_the_declaring_sentence_still_reject_it(self):
        for text in ("여기가 사용자 대화창구이다 라고 했는데 이름이 안 바뀐다 수정해",
                     "이제부터 여기 대화창구로 쓰는데 오류 나면 고쳐줘\n- 다음 카드 진행"):
            self.assertFalse(uw.is_declaration(text), text)

    def test_designation_and_declaration_must_share_a_sentence(self):
        self.assertFalse(uw.is_declaration("여기 로그를 봐라.\n그 창은 사용자 대화창구이다."))


if __name__ == "__main__":
    unittest.main()
