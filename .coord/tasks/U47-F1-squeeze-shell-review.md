# U47-F1 squeeze shell regression review

- State: REVIEW. Bundle is not approved or applied.
- Root cause: `cmd_squeeze` trusted `os.environ["SHELL"]` without checking the executable type. In Codex on Windows this is PowerShell, which receives a `.sh` file and returns 0 instead of the script's exit 3.
- Baseline reproduction: the existing exit-code test failed with `SHELL=C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` (`3 != 0`, command exit 1) and passed with `SHELL=C:\Program Files\Git\bin\bash.exe` (command exit 0).
- Red-first test: `test_windows_ignores_powershell_shell_and_falls_back_to_git_bash` patches PowerShell into `SHELL`, disables PATH lookup, exposes only the first Git Bash candidate, and failed `3 != 0` before the implementation.
- Contract: `.coord/tasks/U47-F1-squeeze-shell-apply-manual.md`, deterministic `worker: apply`, model input/output tokens 0, allowed source files only `v7_harness/olla.py` and `tests/test_u17_olla.py`.
- Bundle: `3765297c788f1c029800b0caea77be4abda50472d5fedaf6c894c5ab1d90dfa3`; stage changed only `v7_harness/olla.py`. The test was red-first in source and its SHA-256 is byte-identical in stage: `79ba8af8ed10831c773b77f8a4abff852c36b7b868d3a723564e89c47832fa7d`.
- Diff: accept configured shell only when basename is one of `bash`, `sh`, `zsh`, `dash`, or `ksh`; otherwise try `shutil.which("bash")`, then the existing Git Bash candidates on Windows.
- Acceptance: `python -m unittest tests.test_u17_olla.OllaSqueezeTests && python -m unittest discover -s tests -p "test_*.py"` exited 0; full discovery ran 879 tests in 99.988 seconds with 4 skips and no failures/errors.
- Independent stage check: with PowerShell still injected into `SHELL`, the original exit-code test and the new deterministic discovery test both passed (2/2, exit 0).
- Test-fitting review: the implementation does not inspect test names, runners, fixtures, argv, or test-only environment variables; it validates only the configured executable basename.
- Forbidden actions preserved: no deletion, paid/local model call, approval, source promotion, commit, push, or deploy.
