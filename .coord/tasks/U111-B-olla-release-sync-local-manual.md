```contract
work_id: U111-B
worker: local
goal: The installer keeps the olla release (the copy the olla launcher runs) equal to the repo: --check reports drift, --apply copies with per-path backups; only for the real home
inputs:
- v7_harness/global_install.py sha256=bd67bc03bc382c1e7f30e7d176b78554cd8ce47ac294f78aebd8ab6ce90d0514
- tests/test_u111_olla_release_sync.py sha256=901f859e3417ed50a5a8247637f3af17ef17e19c01339f17ac5f6d376c6cbb32
allow:
- v7_harness/global_install.py
acceptance: python -m unittest tests.test_u111_olla_release_sync tests.test_u37_install_everywhere tests.test_u103_olla_parity tests.test_u107_plan_hook_install tests.test_u108_map_first tests.test_u91_stale_sentinel_task tests.test_u45_general_uaos
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 1200
remote_budget_tokens: 0
```

## Instructions for the worker

Edit only v7_harness/global_install.py with exact SEARCH/REPLACE blocks (the lines to find are around `extra_rules`,
`backed_up` and `enable_codex_hooks`). Make these four changes; each one is required.

1. Add a new function right above the line "def plan(home: Path, python: str, *, repo: Path = REPO_ROOT, rules: bool = True, extra_rules: tuple[Path, ...] = (),":

    # U111: `olla` on PATH runs a copied release (PYTHONPATH=<release>); after the PR #81 merge it still ran old code
    # (51 stale files, 2026-10-01). The installer owns that copy like its other files.
    OLLA_RELEASE_RE = re.compile(r'PYTHONPATH="?([^";%$]+)')


    def olla_release_dir(which: Callable[[str], str | None] = shutil.which) -> Path | None:
        """The folder the `olla` launcher puts first on PYTHONPATH, when it holds a v7_harness copy."""
        found = which("olla")
        match = OLLA_RELEASE_RE.search(_read(Path(found)) or "") if found else None
        root = Path(match.group(1).strip()) if match else None
        return root if root is not None and (root / "v7_harness").is_dir() else None


2. In the signature of plan, the line
         enable_codex_hooks: bool = True, uninstall: bool = False) -> list[Change]:
   becomes
         enable_codex_hooks: bool = True, uninstall: bool = False, olla_release: Path | None = None) -> list[Change]:
   and right before the "return changes" that ends plan (after the `extra_rules` loop) add:

    if olla_release is not None and not uninstall:
        source = Path(repo) / "v7_harness"
        for src in sorted(source.rglob("*.py")):
            if "__pycache__" in src.parts:
                continue
            dest = Path(olla_release) / "v7_harness" / src.relative_to(source)
            change = _text_change("olla release", dest, _read(dest), src.read_text(encoding="utf-8"))
            if change.action != "UNCHANGED":
                changes.append(change)

3. In apply, the line
            relative = change.path.relative_to(home) if change.path.is_relative_to(home) else Path(change.path.name)
   becomes (U111: two release files named __init__.py must not share one backup)
            relative = (change.path.relative_to(home) if change.path.is_relative_to(home)
                        else change.path.relative_to(change.path.anchor))

4. In main, the line
                   enable_codex_hooks=not args.no_codex_feature, uninstall=args.uninstall)
   becomes
                   enable_codex_hooks=not args.no_codex_feature, uninstall=args.uninstall,
                   # U111, like U91: the release belongs to this PC's real user; a test or staging --home never touches it.
                   olla_release=olla_release_dir() if Path(args.home).resolve() == Path.home().resolve() else None)

Do not edit tests. Do not change anything else.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
