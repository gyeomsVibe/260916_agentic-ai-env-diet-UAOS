"""U277-A9: the request binding stores a credential-free repository identity, or "" (UNKNOWN), never the raw remote.

Fixture values only; no real git or credentials. Codex A8 REVISE: userinfo and query authentication material persisted.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from v7_harness.coord import deliver

MARK = "FIXTURE_ONLY_NOT_A_SECRET"


def _identity(raw: str, returncode: int = 0) -> str:
    with mock.patch.object(deliver.subprocess, "run", return_value=SimpleNamespace(returncode=returncode, stdout=raw)):
        return deliver._repo_url(deliver.Path("."))


class RepoIdentityTest(unittest.TestCase):
    def test_secret_bearing_forms_never_return_the_secret(self):
        for raw in (f"https://fixture-user:{MARK}@example.invalid/team/repo.git",
                    f"https://{MARK}@example.invalid/team/repo.git",
                    f"https://example.invalid/team/repo.git?token={MARK}",
                    f"https://example.invalid/team/repo.git#{MARK}",
                    f"ssh://fixture-user:{MARK}@example.invalid:22/team/repo.git",
                    f"fixture-user:{MARK}@example.invalid:team/repo.git"):
            with self.subTest(raw=raw):
                self.assertNotIn(MARK, _identity(raw))

    def test_safe_forms_keep_host_and_path(self):
        self.assertEqual("example.invalid/team/repo", _identity("https://example.invalid/team/repo.git"))
        self.assertEqual("example.invalid/team/repo",
                         _identity(f"https://fixture-user:{MARK}@Example.Invalid/team/repo.git"))
        self.assertEqual("example.invalid/team/repo", _identity("git@example.invalid:team/repo.git"))
        self.assertEqual("example.invalid/team/repo", _identity("ssh://git@example.invalid/team/repo"))

    def test_same_repo_in_different_forms_binds_the_same(self):
        forms = {_identity("https://example.invalid/team/repo.git"), _identity("git@example.invalid:team/repo.git"),
                 _identity("ssh://git@example.invalid/team/repo.git"), _identity("https://example.invalid/team/repo/")}
        self.assertEqual({"example.invalid/team/repo"}, forms)

    def test_malformed_or_unavailable_is_unknown(self):
        for raw in ("", "   ", "not a url", "https://", "https:///team/repo", "file:///fixture/repo",
                    "D:/fixture/repo", "https://example.invalid", "https://exa mple.invalid/team/repo",
                    "https://example.invalid:notaport/team/repo.git", "https://example.invalid:99999/team/repo.git"):
            with self.subTest(raw=raw):
                self.assertEqual("", _identity(raw))
        self.assertEqual("", _identity("https://example.invalid/team/repo.git", returncode=1))


if __name__ == "__main__":
    unittest.main()
