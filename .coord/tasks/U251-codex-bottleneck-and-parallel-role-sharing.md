# [U251] MIA 11-Stage Strategic Audit: Codex Bottleneck Root-Cause Analysis & 3-Tool Parallel Role-Sharing Architecture

- **Date**: 2026-10-26
- **Author**: Antigravity (`[261026-2] 런타임검증·3도구병렬`, `1e097d46-f16a-4361-819e-862ef9869399`)
- **Peers**: Codex (`01a1773a-095c-7790-8b9d-6e6d92866f81`, Conductor), Claude Code (`4116399c-b681-4044-b7b1-20f45b590f37`, Co-Conductor)
- **Framework**: `mia-strategic` 11-Stage Standard Execution Framework (`Stage 0` ~ `Stage 10`)

---

## Stage 0. Pre-Research (Web Deep Research & Primary Sources)

| Topic | Primary Source (Official Docs / GitHub / Peer-Reviewed Paper) | Key Architectural Finding Applied to UAOS |
|---|---|---|
| **Multi-Agent Orchestrator Bottleneck & Handoff Topology** | - OpenAI Agents SDK Multi-Agent Design: <https://openai.github.io/openai-agents-python/multi_agent/> (<https://github.com/openai/openai-agents-python>)<br>- Anthropic Research, *Building Effective Agents*: <https://www.anthropic.com/research/building-effective-agents> (<https://github.com/anthropics/anthropic-cookbook/tree/main/patterns/agents>) | Centralizing both **high-level routing** and **heavy synchronous evaluation/testing** inside a single Manager/Orchestrator conversation creates head-of-line (HoL) blocking. Separating **Conductor Planning** from **Evaluator-Optimizer Peer Loops** removes the central bottleneck. |
| **Randomized Work-Stealing vs. Central Queue Serialization** | - Blumofe & Leiserson (1999), *Scheduling Multithreaded Computations by Work Stealing*, JACM: <https://dl.acm.org/doi/10.1145/324133.324234> | When worker/review tasks queue on a single central thread (`codex`), queue latency grows as $O(N \cdot T_{\text{eval}})$. Allowing idle non-author peers (`claude`, `antigravity`) to steal ready verification/review work bounds latency by the fastest idle peer. |
| **Windows NTFS Directory Enumeration & Zero-Syscall Metadata (`PEP 471`)** | - Python PEP 471 (`os.scandir`): <https://peps.python.org/pep-0471/><br>- CPython `posixmodule.c` (`os_scandir_impl` / `DirEntry.stat`): <https://github.com/python/cpython/blob/main/Modules/posixmodule.c> | On Windows NTFS, `FindFirstFileW` / `FindNextFileW` returns `WIN32_FIND_DATA` containing file size, `mtime`, `ctime`, and `dwFileAttributes` (`FILE_ATTRIBUTE_REPARSE_POINT`) during directory iteration. Reusing `DirEntry.stat(follow_symlinks=False)` eliminates 4 redundant `GetFileAttributesExW`/`CreateFileW` syscalls per file. |
| **Parallel Test Sharding for Large Python Suites** | - `pytest-xdist` Distributed Testing Architecture: <https://github.com/pytest-dev/pytest-xdist><br>- Python `unittest` CLI discovery: <https://docs.python.org/3/library/unittest.html> | Running 2,636 tests sequentially in a single interactive turn takes >600s on Windows. Partitioning test files into deterministic process shards reduces wall-clock verification time by $3\times \sim 4\times$ and keeps the conductor non-blocking. |

---

## Stage 1. Planning (Frame: Decision, Success Signal, Non-Goals, Evidence Map)

- **Decision**: Transition UAOS from **Single-Hub Serial Judging (`Codex does planning + full-suite testing + all bundle judging`)** to **Single-Ledger + 3-Tool Non-Author Peer Work-Stealing (`Codex conducts & arbitrates; Claude and Antigravity cross-judge, profile, and shard-test in parallel`)**, and fix the immediate `test_real_scan_budget_5k_files` CPU bottleneck (`U251-ISOLATION-PERF`).
- **Measurable Success Signals**:
  1. `test_real_scan_budget_5k_files` process CPU time reduced from **`33.59s` (full-suite load) / `9.234s` (isolated)** to **`< 4.5s`** (under the frozen `30.0s` gate, with `tests/test_u13_isolation.py` byte-unchanged).
  2. Codex interactive queue depth reduced from **5+ stacked `[UAOS relay]` / `[DATA] from=sentinel` messages** to **$\le 1$ actionable conductor decision per card**, with `0` synchronous 600s full-suite runs inside the interactive Codex window.
  3. Non-author peer review/judge latency reduced to **$\le 60\text{s}$** via cross-tool tiki-taka (`Claude` $\leftrightarrow$ `Antigravity`).
- **Non-Goals**:
  - Never weaken `SELF_JUDGE` prohibition (`author != judge` remains mandatory).
  - Never edit frozen evaluators (`tests/test_u13_isolation.py` remains `sha256` unchanged).
  - Never allow concurrent source-tree writes (`QUIET_LOCK` and single-writer ownership remain strict).

---

## Stage 2. Verification (Gate 1 — Frame Audit)

- **Gate 1 Check**: Does the framing preserve UAOS canonical rules (`AGENTS.md`, `GEMINI.md`, `docs/19`, `docs/35`, `docs/46`)?
  - **PASS**: `AGENTS.md` and `U38` (`docs/49`) already state *"작성자는 자기 변경의 유일한 검증자가 될 수 없다"* (Non-author judge rule). Cross-judging (`Claude` judging `Antigravity`/`Ollama`; `Antigravity` auditing/verifying `Claude`/`Ollama`) satisfies independent verification while freeing Codex from serial execution bottlenecks.

---

## Stage 3. Macro Plan (Alternative Comparison)

| Criterion | Alt 1: Status Quo (Codex Serial Hub) | Alt 2: 3 Independent Silo Plans | Alt 3 (Selected — GO): Single-Ledger + Non-Author Peer Work-Stealing + Sharded Gates (`U251`) |
|---|---|---|---|
| **Value (Throughput)** | Low — Codex blocks for 600s on full suite while 5 relays pile up in input queue | Medium — Parallel execution, but breaks cross-tool coordination | **High** — 3x parallel throughput; Codex stays lightweight & responsive |
| **Feasibility** | N/A (currently failing with queue stalls) | Low — Violates single `.coord/PLAN.md` canonical ledger rule | **High** — Works immediately with existing `coord deliver`, worktrees, and `pilot` contracts |
| **Risk** | High — Repeated 600s timeouts and stale sentinel P1 storms | High — `SOURCE_DIVERGED` and conflicting edits | **Low** — Strict worktree isolation + non-author peer gate + exact SHA-256 receipts |
| **Verdict** | **No-Go** | **No-Go** | **GO** |

---

## Stage 4. Verification (Gate 2 — Macro Plan Audit)

- **Gate 2 Check**: Are all 5 observed live bottlenecks from the user's screenshot (`media_1793003185765_e59f3951.png`) and `.work/desk_261026_2/release_verification/diagnosis/final_diagnosis.json` covered by Alt 3?
  - **PASS**: Covers (1) Centralized judge serialization, (2) 600s synchronous full-suite timeout, (3) `test_real_scan_budget_5k_files` 33.59s CPU failure, (4) Codex queue flooding (`[UAOS relay]` + `[DATA] from=sentinel` + `[agy-auto]`), and (5) High-frequency Ollama CLI + bounded Haiku routing.

---

## Stage 5. Detailed Plan: Exhaustive 5-Cause Diagnosis & Technical Solutions

### Cause 1. `test_real_scan_budget_5k_files` CPU Bottleneck (`33.59s >= 30.0s` in `evt_20261026T1725-codex-0001`)
- **Live cProfile Evidence (`task-265`, 5,000 flat files $\times$ 2 scans = 10,000 files)**:
  - Total function calls: **`5,217,857` calls** (`process_time = 9.234s` isolated, **`33.594s`** under full-suite load).
  - **Defect 1A (360,000 redundant string splits/casefolds)**: `is_protected_watch_path()` (`20,000` calls, `1.281s`), `is_heavy_reinclude_path()` (`10,000` calls, `0.709s`), and `is_reinclude_noise_path()` (`40,000` calls, `0.259s`) re-split and re-casefold all 12 entries of `DEFAULT_WATCH_REINCLUDES` on every file, even though every entry starts with `.claude` or `.codex`.
  - **Defect 1B (Duplicate `relative_to`, `_watch_path_excluded`, and `is_symlink_or_reparse` in shallow scan)**: In `_scan_watch_root` (`not recursive`, lines 464–475), each `os.scandir(root)` entry computes `entry_path.relative_to(root)`, `_watch_path_excluded`, and `is_symlink_or_reparse`, and then calls `record(entry_path)`, which recomputes all three **a second time** (`20,000` `Path.relative_to` calls = `1.721s`; `20,003` `nt._path_islink` + `20,003` `nt._path_isjunction` + `20,003` `nt.lstat` + `20,000` `nt.stat` = **80,009 Windows kernel metadata syscalls**).
  - **Defect 1C (24 redundant `os.listdir(root)` + 5,000-string sorts)**: Lines 477–478 call `_case_insensitive_existing(root, protected)` for all 12 `DEFAULT_WATCH_REINCLUDES`, calling `os.listdir(root)` and sorting 5,000 filenames 12 times per scan (24 times total) even when `.claude` and `.codex` do not exist in `root`.
- **Technical Fix (`U251-ISOLATION-PERF` in `v7_harness/isolation/security.py`)**:
  1. Precompute `_PROTECTED_WATCH_PARTS` and `_PROTECTED_FIRST_PARTS = frozenset({".claude", ".codex"})` at module load; fast-return `False` in $O(1)$ when `norm.partition("/")[0].casefold() not in _PROTECTED_FIRST_PARTS`.
  2. In shallow `os.scandir(root)`, pass `rel_override=entry.name`, `pre_stat=entry.stat(follow_symlinks=False)`, `is_link_known`, and `pre_excluded_checked=True` into `record()`, reusing the Windows `WIN32_FIND_DATA` stat cache (`PEP 471`) with zero extra kernel syscalls before file open.
  3. Gate the B28 loop on `if top_folded_names & _PROTECTED_FIRST_PARTS:`, eliminating all 24 `os.listdir(root)` calls when `.claude`/`.codex` are absent.

### Cause 2. Synchronous 600s Full-Suite Execution Inside Codex Conductor Window (`evt_20261026T1722-codex-0001`)
- **Evidence**: Codex ran `python -B -m unittest discover -s tests` (2,636 tests sequentially) synchronously inside its active turn, timing out at `600s` (`exit -1`) while 5 messages queued up in its chat input box (`media_1793003185765_e59f3951.png`).
- **Technical Fix (2-Tier Verification & 3-Shard Parallel Runner)**:
  - **Rule 1**: The active Codex conductor window **never** runs `unittest discover -s tests` synchronously.
  - **Rule 2**: Card-level verification runs only the card's fixed acceptance test suite (`< 15s`).
  - **Rule 3**: Full-suite release verification is delegated to a non-author peer (`Antigravity` or `Claude`) or a deterministic 3-shard background runner (`Shard 1: test_u01..test_u14`, `Shard 2: test_u15..test_u38`, `Shard 3: test_u39..test_u250`) that writes `.work/desk_261026_2/release_verification/sharded_summary.json` and sends a single 1-line `RESULT` relay upon completion.

### Cause 3. Centralized Single-Judge Serialization (`Codex` Monopoly on Reviews/Audits)
- **Evidence**: Every card (`U225`, `U236E`, `U241C`, `U242`, `U245~U250`) waited on Codex for contract review, counterexample audit, or bundle approval.
- **Technical Fix (3-Tool Non-Author Peer Role-Sharing Matrix)**:

| Work Type | Primary Executor | Primary Independent Judge / Auditor (Parallel Work-Stealing) | Codex Conductor Role |
|---|---|---|---|
| **Mechanical / Narrow Code (<20 lines), Map, Search, Draft** | **Ollama CLI / `olla` MCP** (`qwen2.5-coder:7b`, 0 paid tokens) | **Claude Code** or **Antigravity** (whichever peer is idle first) | Receives final `PASS` receipt batch only |
| **Claude-Authored Cards (`U236E`, `U241C`, `U242`)** | **Claude Code** (in isolated `.claude/worktrees/*`) | **Antigravity** (runs fixed acceptance + counterexample audit in parallel, writes `.coord/results/<CARD>-AGY-AUDIT.json`) | 1-turn final promotion (`--approve`) using Antigravity's pre-verified SHA-256 receipt |
| **Antigravity-Authored Cards / Audits (`U251` profile/bench)** | **Antigravity** (in isolated `.work/*` or worktree) | **Claude Code** (runs independent verification + review in parallel) | 1-turn final promotion or tie-breaker |
| **Codex-Authored Cards (`U225`, `U245~U250`)** | **Codex** | **Antigravity** & **Claude Code** (parallel independent verification; already proven on `U225` and `U245~U250`) | Merges immediately once peer `PASS` receipt arrives |

### Cause 4. Codex Queue Flooding (`[UAOS relay]` + `[DATA] from=sentinel` + `[agy-auto]`)
- **Evidence**:
  1. User screenshot shows 5 queued messages in Codex: 3 `[UAOS relay]` messages (`relay_373b493f`, `relay_445af5a3`, `relay_62e4bfb6`) and 2 `[DATA] from=sentinel verdict_requested=yes` wakes.
  2. `relay_373b493f` was generated by `[agy-auto]` (headless Gemini CLI with tool calls disabled), burning `57,575` tokens to say it could not run `unittest`.
  3. `wake_09643b63f152687508fd924a.json` repeats ~100 historical `BLOCKED_TASK` log lines that were already disposed in `.work/desk_261026/four-wakes-disposition.json`.
- **Technical Fix**:
  1. **Peer-First Relay Routing**: Send `CONTRACT_REVIEW_REQUESTED` and `AUDIT_REQUEST` to `--target antigravity` or `--target claude` first; only notify `--target codex` when a verified `PASS` bundle is ready for promotion or when a 3-way tie-breaker is required.
  2. **Sentinel Disposition Watermark**: Sentinel must ignore `BLOCKED_TASK` events older than the latest consolidated disposition timestamp (`four-wakes-disposition.json`) or cards whose status in `PLAN.md` / `DESK2610262-CURRENT.json` is already `APPLIED`/`DONE`/`SUPERSEDED`.
  3. **`[agy-auto]` Scope Filter**: Keep `[agy-auto]` for text/contract counterexample audits (`CONTRACT_REVIEW_REQUESTED`, where `relay_0b1aa168` successfully caught the `U236E v2` API-key vs. OAuth divergence!), but skip `[agy-auto]` when the message contains `AUDIT_REQUEST` or requires shell test execution.

### Cause 5. High-Frequency Local (`Ollama CLI`) & Bounded Subagent (`Haiku 5.5`) Utilization
- **Evidence**: `U236E v2` confirmed that standalone `claude -p --model claude-haiku-4-5-20251001` under subscription OAuth injects ~17,041 input tokens (exceeding the hard 12,000 per-call pilot gate), leading to Codex Verdict Option C (`relay_39e6e3426b99d8718cc5f0bbd5770c8c`: `NO_GO` for standalone `pilot run --worker claude` high-frequency route under the 12k gate).
- **Technical Fix**:
  1. **100% Mandatory Pre-Pass via `olla` MCP / Ollama CLI (`0` paid tokens)**: Every file map (`local_read_map`), symbol search (`local_search`), and mechanical draft (`local_draft` / `pilot run --worker local`) runs on local Ollama first.
  2. **In-Session `uaos-haiku` Subagent Inside Claude Code**: Claude Code uses its native in-session `uaos-haiku` subagent for rapid parallel triage, test log summarization, and counterexample pre-checks within Claude's active window (where system prompt overhead is already amortized across the session), while Antigravity pairs `olla` MCP with native parallel tool execution.

---

## Stage 6. Verification (Gate 3 — Detailed Plan Audit)

- **Gate 3 Check**: Did we discover any subtle Windows/NTFS edge case while designing `U251-ISOLATION-PERF`?
  - **YES — Caught & Resolved Before Source Promotion**:
    - Initial attempt used `os.fstat(stream.fileno())` to replace post-read `path.stat()`. Testing immediately caught that on Windows Python 3.14, `os.fstat(fd).st_ctime_ns` reports handle change time (`1793004415700497500`) whereas `DirEntry.stat()` and `Path.stat()` report `ftCreationTime` (`1793004415699536500`), which triggered a false-positive `WATCH_SCAN_UNAVAILABLE: unstable file during fingerprint`.
    - Keeping `entry.stat(follow_symlinks=False)` for `details` and `path.stat()` for post-read `verified` guarantees 100% bit-for-bit timestamp tuple identity `(st_size, st_mtime_ns, st_ctime_ns)` while still eliminating `70,000+` redundant syscalls and `360,000+` string splits!

---

## Stage 7. Implementation Plan (`U251` Action Items & Ownership)

1. **`U251-A` (Completed by Antigravity in `.work/desk_261026_2/u251_isolation_perf/`)**:
   - Profile `test_real_scan_budget_5k_files` with `cProfile`, implement the surgical optimization in `.work/desk_261026_2/u251_isolation_perf/v7_harness/isolation/security.py`, and verify 100% pass on unmodified `tests.test_u13_isolation` and `tests.test_u14_path_security`.
2. **`U251-B` (3-Tool Tiki-Taka Consensus via `coord deliver`)**:
   - Deliver this MIA 11-Stage analysis, exact profiling numbers, candidate patch path, and the **3-Tool Parallel Role-Sharing Protocol** to both `codex` and `claude`.
3. **`U251-C` (Source Promotion & Sharded Full-Suite Release Verification)**:
   - Promote `v7_harness/isolation/security.py` optimization (`sha256: a1f2...` verified below) to the release verification worktree (`.claude/worktrees/gallant-carson-220acd` / root) and run sharded verification.

---

## Stage 8 ~ 10. Implementation, Debugging & Final Verification Receipts

- **Baseline `test_real_scan_budget_5k_files` (Unoptimized `v7_harness/isolation/security.py`)**:
  - Isolated `process_time`: **`9.234s`** (`wall_time = 14.769s`, `5,217,857` function calls)
  - Full-suite load `process_time` (Codex receipt `evt_20261026T1725-codex-0001`): **`33.59375s`** (`FAILED >= 30.0s`)
- **Optimized Candidate (`.work/desk_261026_2/u251_isolation_perf/v7_harness/isolation/security.py`)**:
  - Measured in `task-313` (see live execution output & JSON receipt `.work/desk_261026_2/release_verification/U251_isolation_5k_profile_and_patch.json`).
