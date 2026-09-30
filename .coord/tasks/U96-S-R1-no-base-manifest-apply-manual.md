```contract
work_id: U96-S-R1
worker: apply
goal: source_escape_paths returns [] when the workspace has no base manifest (mocked or replayed workspaces), so the U96-S check never crashes a run.
inputs:
- v7_harness/pilot.py sha256=371a00b1671c7f4be495c6c0ebbf044c05c3588796b0d6561580a18d47c1a5be
- tests/test_u96s_source_escape.py sha256=ab8a36f8932eb68504d6a04a434f659b7e64c5e87834072f00a29c53c85df694
allow:
- v7_harness/pilot.py
- tests/test_u96s_source_escape.py
acceptance: python -m unittest tests.test_u96s_source_escape tests.test_b41_bundle tests.test_b24_rejected_summary tests.test_b26_b21_features
forbidden: design changes; edits outside allow; editing or weakening existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Apply the blocks below exactly. Receipt: after U96-S, the full suite failed 2 tests (test_b24_rejected_summary, test_b26_b21_features) with `AttributeError: 'NoneType' object has no attribute 'manifest_hash'`: their mocked workspace has `base_manifest=None`.

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
def source_escape_paths(base: DeterministicManifest, source_dir: Path, excludes: list[str]) -> list[str]:
=======
def source_escape_paths(base: DeterministicManifest | None, source_dir: Path, excludes: list[str]) -> list[str]:
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/pilot.py===
<<<<<<< SEARCH
    returns [] here: the dry run and apply still fail closed on the manifest hash.
    """
    try:
=======
    returns [] here: the dry run and apply still fail closed on the manifest hash. A workspace without a base manifest
    (mocked in tests, or replayed) has nothing to compare against and also returns [].
    """
    if base is None:
        return []
    try:
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u96s_source_escape.py===
<<<<<<< SEARCH
        self.assertEqual(source_escape_paths(build_manifest(self.source), self.source, []), [])
=======
        self.assertEqual(source_escape_paths(build_manifest(self.source), self.source, []), [])

    def test_no_base_manifest_names_nothing(self) -> None:
        self.assertEqual(source_escape_paths(None, self.source, []), [])
>>>>>>> REPLACE
===END===
