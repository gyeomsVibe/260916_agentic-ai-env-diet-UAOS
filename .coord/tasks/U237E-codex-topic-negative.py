"""Independent U237D topic gate; no provider calls or source writes."""
import sys
import unittest
from pathlib import Path

source = Path(sys.argv.pop(1)).resolve()
sys.path.insert(0, str(source))
from v7_harness.coord.user_window import _topic_from_text


class TopicEvidence(unittest.TestCase):
    declaration = "이제부터 이 대화창이 사용자 대상 대화창구이다.\n"

    def test_url_alone_is_not_a_topic(self):
        self.assertIsNone(_topic_from_text(self.declaration + "https://example.com"))

    def test_file_path_alone_is_not_a_topic(self):
        self.assertIsNone(_topic_from_text(self.declaration + "C:/Work/report.md"))

    def test_real_topic_remains_available(self):
        self.assertEqual("통신 오류 복구", _topic_from_text(self.declaration + "통신 오류 복구"))


if __name__ == "__main__":
    unittest.main()
