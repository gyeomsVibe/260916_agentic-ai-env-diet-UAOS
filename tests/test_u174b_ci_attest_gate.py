"""U174-B frozen acceptance: `coord merge` also needs a GitHub-signed CI receipt that passed this exact head.

Receipt: Codex decision D1 (.work/u169/codex_gate_decision.md) said a same-account letter, hash or signature is no
trust boundary, so a judge letter alone can be forged by any local tool. U174-A (PR #137) made the uaos-tests
workflow write receipt.json and attest it with actions/attest (Sigstore, GitHub OIDC); run 37276190231 verified with
`gh attestation verify --signer-workflow` exit 0 and a forged file did not. This card makes the merge gate read it.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from v7_harness.coord import merge_route

HEAD = "b" * 40
OTHER = "c" * 40
NOW = 2_000_000_000.0
VERDICT = "relay_" + "2" * 32
REPO = "o/r"
URL = f"https://github.com/{REPO}/pull/7"
WORKFLOW = ".github/workflows/uaos-tests.yml"
DESK = {t: {"state": "ACTIVE"} for t in ("codex", "claude", "antigravity")}


def _receipt(**over):
    data = {"schema": "uaos-ci-receipt-v1", "repo": REPO, "pr": "7", "head": HEAD, "run_id": "901", "exit": 0,
            "summary": "1977 passed, 6 skipped"}
    data.update(over)
    return data


class FakeGh:
    """Answers each gh subcommand from fixed settings; a merger call flips the PR to MERGED."""

    def __init__(self, *, url=URL, api_rc=0, api_err=b"", files=("v7_harness/x.py",), runs=None,
                 receipt=None, verify_rc=0):
        self.url = url
        self.api_rc, self.api_err = api_rc, api_err
        self.files = files
        self.runs = [{"databaseId": 901, "conclusion": "success"}] if runs is None else runs
        self.receipt = _receipt() if receipt is None else receipt
        self.verify_rc = verify_rc
        self.merged = False
        self.calls = []

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        ok = lambda out=b"", rc=0, err=b"": subprocess.CompletedProcess(argv, rc, out, err)  # noqa: E731
        if argv[:3] == ["gh", "pr", "view"]:
            view = {"state": "MERGED" if self.merged else "OPEN", "mergeable": "MERGEABLE", "headRefOid": HEAD,
                    "headRefName": "claude/u174b-x", "url": self.url}
            return ok(json.dumps(view).encode())
        if argv[:2] == ["gh", "api"]:
            return ok(rc=self.api_rc, err=self.api_err)
        if argv[:3] == ["gh", "pr", "diff"]:
            return ok("\n".join(self.files).encode())
        if argv[:3] == ["gh", "run", "list"]:
            return ok(json.dumps(self.runs).encode())
        if argv[:3] == ["gh", "run", "download"]:
            out = Path(argv[argv.index("-D") + 1])
            out.mkdir(parents=True, exist_ok=True)
            (out / "receipt.json").write_text(json.dumps(self.receipt), encoding="utf-8")
            return ok()
        if argv[:3] == ["gh", "attestation", "verify"]:
            return ok(rc=self.verify_rc)
        self.merged = True  # agy / codex merger
        return ok(b"0")

    def tools(self):
        return [a[0] for a in self.calls if a[0] != "gh"]

    def find(self, *prefix):
        return [a for a in self.calls if a[:len(prefix)] == list(prefix)]


class CiAttestGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        folder = self.root / ".coord" / "mailbox" / "inbox"
        folder.mkdir(parents=True)
        (folder / f"{VERDICT}.json").write_text(
            json.dumps({"actor": "antigravity", "message": f"U174-B PASS on head {HEAD}"}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _merge(self, gh):
        return merge_route.merge(self.root, 7, HEAD, VERDICT, runner=gh, now=NOW, desk=DESK)

    def _refused(self, gh, needle):
        row = self._merge(gh)
        self.assertEqual("REFUSED", row["state"], row)
        self.assertIn(needle, row["reason"])
        self.assertEqual([], gh.tools(), "no merger may run without a verified CI receipt")
        return row

    def test_verified_receipt_for_this_head_merges_and_records_the_run(self):
        gh = FakeGh()
        row = self._merge(gh)
        self.assertEqual("MERGED", row["state"], row)
        self.assertEqual("901", row["ci_run"])
        verify = gh.find("gh", "attestation", "verify")[0]
        self.assertEqual(["-R", REPO, "--signer-workflow", f"{REPO}/{WORKFLOW}"], verify[4:])
        self.assertIn(HEAD, gh.find("gh", "run", "list")[0])

    def test_attestation_that_does_not_verify_refuses(self):
        self._refused(FakeGh(verify_rc=1), "attestation")

    def test_no_green_run_for_this_head_refuses(self):
        self._refused(FakeGh(runs=[{"databaseId": 901, "conclusion": "failure"}]), "no green CI run")
        self._refused(FakeGh(runs=[]), "no green CI run")

    def test_receipt_for_another_head_pr_or_a_failed_exit_refuses(self):
        for receipt in (_receipt(head=OTHER), _receipt(pr="8"), _receipt(exit=1), _receipt(repo="o/other")):
            with self.subTest(receipt=receipt):
                self._refused(FakeGh(receipt=receipt), "receipt")

    def test_pr_that_changes_the_ci_workflow_cannot_attest_itself(self):
        self._refused(FakeGh(files=("v7_harness/x.py", WORKFLOW)), "CI workflow")

    def test_repo_without_the_workflow_keeps_the_letter_gate(self):
        gh = FakeGh(api_rc=1, api_err=b"gh: Not Found (HTTP 404)")
        row = self._merge(gh)
        self.assertEqual("MERGED", row["state"], row)
        self.assertEqual("NOT_CONFIGURED", row["ci_run"])
        self.assertEqual([], gh.find("gh", "attestation", "verify"))

    def test_unreadable_workflow_probe_is_unknown_and_refuses(self):
        self._refused(FakeGh(api_rc=1, api_err=b"error connecting to api.github.com"), "gh api")

    def test_non_github_pull_request_url_is_not_configured(self):
        row = self._merge(FakeGh(url="https://x/pull/7"))
        self.assertEqual("MERGED", row["state"], row)
        self.assertEqual("NOT_CONFIGURED", row["ci_run"])

    def test_receipt_is_kept_under_work_as_merge_evidence(self):
        self._merge(FakeGh())
        kept = list((self.root / ".work" / "ci_receipts").glob("*/receipt.json"))
        self.assertEqual(1, len(kept))
        self.assertEqual(HEAD, json.loads(kept[0].read_text(encoding="utf-8"))["head"])


if __name__ == "__main__":
    unittest.main()
