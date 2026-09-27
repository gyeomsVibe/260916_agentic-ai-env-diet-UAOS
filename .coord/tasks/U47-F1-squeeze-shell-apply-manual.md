```contract
work_id: U47-F1
worker: apply
goal: Make cmd_squeeze execute .sh scripts only through a POSIX shell: ignore PowerShell/cmd in SHELL on Windows, fall back deterministically to Git Bash, and preserve the script exit code.
inputs:
- v7_harness/olla.py sha256=5e7d7f551a667de662aedbb06d066c605eb4931c1b2ab020c874f37ea222efb5
- tests/test_u17_olla.py sha256=79ba8af8ed10831c773b77f8a4abff852c36b7b868d3a723564e89c47832fa7d
allow:
- v7_harness/olla.py
- tests/test_u17_olla.py
acceptance: python -m unittest tests.test_u17_olla.OllaSqueezeTests && python -m unittest discover -s tests -p "test_*.py"
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: codex
timeout_s: 1800
remote_budget_tokens: 0
```

## Instructions for the worker

===EDIT: v7_harness/olla.py===
<<<<<<< SEARCH
def cmd_squeeze(args: argparse.Namespace) -> int:
    script = Path(args.script)
    bash_path = os.environ.get("SHELL") or shutil.which("bash")
    if not bash_path and sys.platform == "win32":
=======
def cmd_squeeze(args: argparse.Namespace) -> int:
    script = Path(args.script)
    configured_shell = os.environ.get("SHELL")
    posix_shells = {"bash", "sh", "zsh", "dash", "ksh"}
    bash_path = (configured_shell if configured_shell and Path(configured_shell).stem.lower() in posix_shells
                 else shutil.which("bash"))
    if not bash_path and sys.platform == "win32":
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
