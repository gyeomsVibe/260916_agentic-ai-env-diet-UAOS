import tempfile
import unittest
from pathlib import Path

from v7_harness.evidence_ledger import EvidenceLedger, verify_report_citations


class TestU245EvidenceCitationGate(unittest.TestCase):
    def test_rejects_report_missing_primary_sources(self):
        res = verify_report_citations("단순 텍스트 요약 보고서입니다. 링크 없음.")
        self.assertEqual(res["verdict"], "FAILED")
        self.assertEqual(res["error"], "MISSING_PRIMARY_SOURCE")
        self.assertIn("github_repository_url", res["missing"])

    def test_accepts_report_with_article_and_github_links(self):
        text = (
            "근거 기사: https://zdnet.co.kr/view/?no=20261019165618 "
            "공식 저장소: https://github.com/morluto/rea"
        )
        res = verify_report_citations(text)
        self.assertEqual(res["verdict"], "PASS")
        self.assertEqual(len(res["github_urls"]), 1)
        self.assertEqual(len(res["article_urls"]), 1)

    def test_epistemic_tiers_and_unknown_resolution_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = EvidenceLedger(Path(tmp))
            inferred = ledger.record_evidence(
                kind="call_path",
                claim="Candidate helper match",
                tier="INFERRED",
                source_url="https://github.com/morluto/rea",
            )
            observed = ledger.record_evidence(
                kind="oracle_diff",
                claim="3205 x86 cases matched byte-for-byte",
                tier="OBSERVED",
                source_url="https://github.com/N0zoM1z0/dx-ball",
            )
            unk = ledger.record_unknown(
                question="Does pan helper clamp negative x?",
                authority_needed="x86 binary oracle",
                supporting_ids=[inferred["evidence_id"]],
            )
            # Inferred evidence cannot resolve an unknown
            bad = ledger.update_unknown(
                unknown_id=unk["unknown_id"],
                expected_revision=1,
                resolved_by_evidence_id=inferred["evidence_id"],
            )
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["error"], "UNVERIFIED_RESOLUTION")

            # Stale revision is rejected
            stale = ledger.update_unknown(
                unknown_id=unk["unknown_id"],
                expected_revision=99,
                resolved_by_evidence_id=observed["evidence_id"],
            )
            self.assertFalse(stale["ok"])
            self.assertEqual(stale["error"], "STALE_REVISION")

            # Observed evidence resolves the unknown cleanly
            good = ledger.update_unknown(
                unknown_id=unk["unknown_id"],
                expected_revision=1,
                resolved_by_evidence_id=observed["evidence_id"],
            )
            self.assertTrue(good["ok"])
            self.assertEqual(good["unknown"]["state"], "RESOLVED")


if __name__ == "__main__":
    unittest.main()
