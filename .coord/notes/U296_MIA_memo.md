# U296 MIA memo — mailbox bottlenecks B5, B6, B11 (2026-11-02)

Receipts: `.coord/notes/BOTTLENECK_RECEIPTS_261102.md` (recursing-moser worktree). Author: Claude (acting conductor, Codex LIMITED). Judge: Antigravity.

## Stage 0 — Evidence (Gate 0 passed: 3 official URLs, quotes below)
- Claude Code hooks reference, https://code.claude.com/docs/en/hooks — common input fields: `session_id` ("Current session identifier"), `transcript_path`, `cwd`, `hook_event_name`; Stop fires "When Claude finishes responding"; exit 2 "Prevents Claude from stopping". Fact: every hook payload names its session, so a per-session watcher/lease key is available from the hook side. Unknown: the Bash tool environment is not documented to carry `session_id` (the CLI therefore takes `--session` explicitly; no env guess).
- Python subprocess docs, https://docs.python.org/3/library/subprocess.html — `DETACHED_PROCESS`: "new process will not inherit its parent's console"; `CREATE_NEW_PROCESS_GROUP`; POSIX `start_new_session`: "setsid() ... in the child". Fact: a detached child outlives the CLI; redirecting std streams to DEVNULL keeps pipes from holding the parent.
- Python os docs, https://docs.python.org/3/library/os.html#os.replace — atomic replace on success (existing `_write_atomic`/`replace_with_retry` already rely on it; reused for the new state file). Page fetch was truncated before the entry; wording not re-quoted (UNKNOWN verbatim, behavior already proven by existing U60 tests).
- Facts from code (receipts): `watch.lock_file` is per tool → `ALREADY_WATCHING`; `_request_hold` emits BLOCKED `U277-STOP-UNGUARDED` per request; sentinel turns every BLOCKED mailbox event into a P1 whose fingerprint includes event ids; `deliver` calls `agy_dispatch.dispatch` synchronously (240 s + 60 s).

## Stage 1-2 — Frame
Problem: three observed failures (B5 ~10 acks/turn, B6 letters in wrong window, B11 caller shell timeout >120 s).
Success signals (deterministic, `tests/test_u296_mailbox_bottlenecks.py`, 12 tests): two sessions hold watchers at once, same session refused; unaddressed letter → main desk only, named letter → that session only; 3 identical STOP_UNGUARDED events → 1 wake, none after ack; child-bound/answered/unknown requests = noise; `--no-wait` deliver never runs the answer in-process.
Non-goals: stop_gate.py emit side (U294 owns), merge/verdict/lease (U295), changing agy answer content or cap logic.
Gate 2: signals are test-checkable → Pass.

## Stage 3-4 — Alternatives (value / feasibility / viability / risk-rollback)
B6: (A) per-(tool,session) lock+lease files and letter eligibility filter in the watcher [chosen: reuses `native_receiver`/`_foreign`, session-less path keeps bytes; rollback = drop `--session`] · (B) one router process fanning letters to per-session sub-mailboxes [new moving part, a crash blocks all sessions] · (C) session from env only [env not documented, UNKNOWN].
B5: (A) consumer-side filter/dedupe in sentinel [chosen; independent of U294's stop_gate edit; rollback = revert one block] · (B) suppress at emit [blocked until U294 merges].
B11: (A) detached child process runs the existing `dispatch` (its lock+replay give idempotence) [chosen; `--wait` and any injected runner keep sync] · (B) in-process thread [dies when the CLI exits] · (C) leave to sentinel backlog drain [adds minutes of latency, new state].
Decision: Go with A/A/A. Rollback: every new parameter defaults to old behavior (`session=""`, `agy_wait=True` in the library).

## Stage 5-8 — Detailed/implementation plan
Files: `v7_harness/coord/{watch,sentinel,deliver,agy_dispatch}.py`, `v7_harness/cli.py`, new test, adapter one-liners. Fixed tests untouched; acceptance = new test file + full suite. Slices <=20 lines per concern: watch keys / watch eligibility / sentinel filter / sentinel set-gate / detached spawn / CLI flags.

## Stage 9-10 — Receipts
See PR body and suite log `.work/u296_suite.log`. Route deviation (recorded honestly): code was written directly with Edit/Write by the Claude session; the pilot/Ollama route is applied at commit by the repo gate (see PR for gate result). One shell heredoc append to `agy_dispatch.py` violated the Edit/Write rule; content verified by `ast.parse` and line endings normalized.
Follow-ups (not in scope): emit-side STOP_UNGUARDED session tag and 1h dedupe after U294 merges; auto-ack of stale `evt_` noise letters.
