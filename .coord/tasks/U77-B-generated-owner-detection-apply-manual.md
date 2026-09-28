```contract
work_id: U77-B
worker: apply
goal: Make the UAOS installer recognize actual generated global-rule files whose ownership marker follows the generated title, without accepting quoted markers.
inputs:
- v7_harness/global_install.py sha256=d65f0566d2fb69239e2de6621354286fef68b6a06bba60e5857d97c136228ea3
- tests/test_u77_adaptive_nonstop.py sha256=d3ebd618a11eab343f6b97e25afd668ff2a9a63ca1430fccf49a09a6cd608bbe
- tests/test_u37_install_everywhere.py sha256=c4596292e05327d3b1e2f2c591c70c46f3a6a2207cc6617efb500ef7f0dd25f7
- tests/test_u41_deploy_to_this_pc.py sha256=0b2d0723f08f8f795c5d7cc1cffdf96720ca3529c1ee6561651bd245dda7b050
allow:
- v7_harness/global_install.py
- tests/test_u77_adaptive_nonstop.py
acceptance: python -m unittest tests.test_u77_adaptive_nonstop tests.test_u37_install_everywhere tests.test_u41_deploy_to_this_pc
forbidden: edits outside allow; weakening marker ownership; accepting quoted markers; network; delete; commit; push; PR; merge; deployment
stop: input hash mismatch; source divergence; no changed files; three failures with the same cause
judge: codex
timeout_s: 300
remote_budget_tokens: 0
```

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _with_block(text: str | None, block: str | None) -> str:
=======
def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _is_canon_generated(text: str) -> bool:
    """The generator writes a title, a blank line, then its ownership marker."""
    lines = text.lstrip("\ufeff").splitlines()
    return any(line.startswith(CANON_GENERATED_MARKER) for line in lines[:4])


def _with_block(text: str | None, block: str | None) -> str:
>>>>>>> REPLACE

===EDIT: v7_harness/global_install.py===
<<<<<<< SEARCH
            if current_rules is not None and current_rules.lstrip("\ufeff").startswith(CANON_GENERATED_MARKER):
=======
            if current_rules is not None and _is_canon_generated(current_rules):
>>>>>>> REPLACE

===EDIT: tests/test_u77_adaptive_nonstop.py===
<<<<<<< SEARCH
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
=======
import unittest
from pathlib import Path

from v7_harness import global_install as gi


ROOT = Path(__file__).resolve().parents[1]
>>>>>>> REPLACE

===EDIT: tests/test_u77_adaptive_nonstop.py===
<<<<<<< SEARCH
            self.assertIn(phrase, text)


if __name__ == "__main__":
=======
            self.assertIn(phrase, text)

    def test_actual_generated_header_keeps_single_writer(self):
        generated = (
            "# Codex Global Rules\n\n"
            "<!-- GENERATED from English canonical rules v5.29.0. Edit the source files, not this deployment. -->\n"
            "# Canonical global agent rules\n"
        )
        self.assertTrue(gi._is_canon_generated(generated))
        self.assertTrue(gi._is_canon_generated("\ufeff" + generated))
        self.assertFalse(gi._is_canon_generated(
            "# Personal rules\n- quote: <!-- GENERATED from English canonical rules v5.29.0. -->\n"
        ))


if __name__ == "__main__":
>>>>>>> REPLACE
