"""U145: a promoted file keeps the source folder's inherited ACL instead of a private 0o700 DACL.

Receipt (2026-10-03): 15 promoted tracked files had a protected DACL that granted only SYSTEM, Administrators and
OWNER RIGHTS. Cause: since Python 3.13, `tempfile.mkdtemp` gives the transaction folder a 0o700 DACL, and
`os.replace` carries that DACL into source. Sandboxed Codex lost read access to those files.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from v7_harness.isolation import NonGitStagingAdapter
from v7_harness.isolation.promotion import apply_promotion


def _acl(path: Path) -> str:
    # icacls marks inherited ACEs with "(I)". A protected private DACL has none.
    return subprocess.run(["icacls", str(path)], capture_output=True, text=True, check=True).stdout


@unittest.skipUnless(sys.platform == "win32", "Windows DACL behaviour")
class PromotionAclTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        # TemporaryDirectory is itself 0o700 on 3.13+. Reset it so it inherits, like a user workspace folder.
        subprocess.run(["icacls", self.temp.name, "/reset", "/Q"], capture_output=True, check=True)
        self.root = Path(self.temp.name) / "ws"
        self.root.mkdir()
        self.source = self.root / "src"
        self.source.mkdir()
        (self.source / "a.py").write_text("x = 1\n", encoding="utf-8")
        self.workspace = NonGitStagingAdapter().create_staging(self.source, self.root / "stage")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_promoted_file_inherits_the_source_acl(self) -> None:
        self.assertIn("(I)", _acl(self.source / "a.py"), "precondition: the source file inherits ACEs")
        (self.workspace.staging_dir / "a.py").write_text("x = 2\n", encoding="utf-8")
        (self.workspace.staging_dir / "new.py").write_text("z = 1\n", encoding="utf-8")
        bundle = self.workspace.create_patch_bundle()
        apply_promotion(source_dir=self.source, staging_dir=self.workspace.staging_dir,
                        patch_bundle=bundle, approve_bundle_id=bundle.bundle_id)
        self.assertEqual("x = 2\n", (self.source / "a.py").read_text(encoding="utf-8"))
        for name in ("a.py", "new.py"):
            self.assertIn("(I)", _acl(self.source / name), f"{name} lost its inherited ACL")

    def test_no_transaction_folder_is_left_beside_source(self) -> None:
        (self.workspace.staging_dir / "a.py").write_text("x = 3\n", encoding="utf-8")
        bundle = self.workspace.create_patch_bundle()
        apply_promotion(source_dir=self.source, staging_dir=self.workspace.staging_dir,
                        patch_bundle=bundle, approve_bundle_id=bundle.bundle_id)
        self.assertEqual([], [p.name for p in self.root.iterdir() if ".promotion-" in p.name])


if __name__ == "__main__":
    unittest.main()
