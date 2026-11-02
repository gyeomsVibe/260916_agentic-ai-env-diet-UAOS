```contract
work_id: U296-L1b
worker: local
goal: Add --session and --wait options to coord watch/deliver in cli.py per the spec
inputs:
- v7_harness/cli.py sha256=950246a4b96b3cc44074eeb6e5435a4ccfb1ad5933ca9ba7d1baea1c142828fb
allow:
- v7_harness/cli.py
acceptance: python -c "import subprocess,sys;o=subprocess.run([sys.executable,'-m','v7_harness.cli','coord','deliver','--help'],capture_output=True,text=True).stdout;sys.exit(0 if '--wait' in o and '--session' in o else 1)"
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: antigravity
timeout_s: 180
remote_budget_tokens: 0
```

## Instructions for the worker

Edit v7_harness/cli.py only.
1. In the argparse setup of `coord watch`, add an optional `--session` string argument (default None). When calling watch(), pass requester_session=getattr(args, "session", None) or None.
2. In the argparse setup of `coord deliver`, add an optional `--session` string argument (default "") and a `--wait` store_true flag. The deliver call's thread value becomes `args.thread or getattr(args, "session", "")`.
3. Pass agy_wait=bool(args.wait) to deliver() only when args has attribute wait.
Keep every other line unchanged.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
