```contract
work_id: U108
worker: cascade
goal: One map-first read gate for all three tools: a file over 300 lines is mapped by the local model (local_read_map / olla digest) before any tool reads more than 60 lines of it (spec below; the fixed test states the rule).
inputs:
- v7_harness/olla.py sha256=ea6f3916257c16c1c9d6ffdd421157ff7671bf3e65dec2c68d06f89e2c7654a2
- v7_harness/global_install.py sha256=7ac63af963cb917c6dc2ae140c4020d7e70dea3b46fc4a5cbde9a60fad102705
- tests/test_u108_map_first.py sha256=2b9bfe3d0f96c53f586bd403c2b784d0ef1324f72c5601cc1ac97e51cf4888ae
allow:
- v7_harness/olla.py
- v7_harness/global_install.py
acceptance: python -m unittest tests.test_u108_map_first tests.test_u103_olla_parity tests.test_u17_olla tests.test_u17_olla_mcp tests.test_u107_plan_hook_install tests.test_u37_install_everywhere tests.test_u45_general_uaos tests.test_u47_d1_local_usage tests.test_u87_uaos_rsi_name tests.test_u90_canon_note tests.test_u91_stale_sentinel_task
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 2400
remote_budget_tokens: 900000
```

## Instructions for the worker

## Spec (edit only `v7_harness/olla.py` and `v7_harness/global_install.py`; the acceptance test `tests/test_u108_map_first.py` is fixed — read its docstring first, it states the rule)

### olla.py — one shared gate used by all three tools

Add next to `DENY_WHOLE_READ_TOKENS`, each with a one-line reason comment:
- `MAP_FIRST_LINES = 300`  # the rule text: "local_read_map before reading any file over 300 lines"
- `FREE_RANGE_LINES = 60`  # enough to confirm what Grep located; the 2026-10-01 slips were 120-line slices
- `RANGE_BUDGET_LINES = 150`  # short ranges may not add up to reading half the file unmapped
- `MAP_FRESH_S = 6 * 3600`  # one working session; an older map may describe other content
- `BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".ipynb"}`

Add `def map_first_deny(path: Path, lines_read: int | None) -> str | None` (`lines_read=None` means the whole file / unknown):
1. Return None unless `path.is_file()`, suffix not in BINARY_SUFFIXES, size <= 5 MB, and its line count
   (`data.count(b"\n")` plus 1 if the data does not end with a newline and is not empty) > MAP_FIRST_LINES.
2. key = `os.path.normcase(str(path.resolve()))`. Read USAGE_LOG (if it exists; only the last 2 MB; skip bad lines).
   Consider rows with `ts` (ISO, `datetime.fromisoformat`) within MAP_FRESH_S of now and normcase(row["file"]) == key.
   If any row has event "digest" -> return None (mapped).
3. n = total lines if lines_read is None else min(lines_read, total). used = sum of `lines` of rows with event
   "range_read" for that file. If n <= FREE_RANGE_LINES and used + n <= RANGE_BUDGET_LINES:
   `log_usage("range_read", file=str(path.resolve()), lines=n)` and return None.
4. If `_pilot_has_gpu()` or not `_server_up()`: `log_usage("map_skip", file=..., reason="gpu" or "down")`, return None.
   (Check these only here, after the cheap checks, so normal reads never wait on the network.)
5. `log_usage("deny_map_first", file=str(path.resolve()), lines=total, lines_read=n)` and return the reason:
   f"{path.name} has {total} lines (over {MAP_FIRST_LINES}): call the local_read_map tool on it first (0 paid tokens; if deferred, first {LOAD_OLLA}; in a shell `olla digest -f <file>`), then read only the lines you need. Without a map you may read {FREE_RANGE_LINES} lines at a time, {RANGE_BUDGET_LINES} per file."

Wire it in:
- `cmd_hook_read` (Claude Read): before everything else that may return, compute lines_read from tool_input:
  `limit` given -> limit; else `offset` given -> total - offset + 1 (pass None and let the function treat it — simplest:
  compute here with the file's line count); neither -> None. If `map_first_deny` returns a reason, print the
  PreToolUse deny JSON (`permissionDecision: "deny"`, `permissionDecisionReason: reason`) and return 0. Keep the
  existing whole-read and hint logic after it unchanged.
- Shell (`olla hook-shell`, used by Claude Bash and Codex Bash), PreToolUse only: add
  `def shell_print_ranges(command: str, cwd: Path) -> list[tuple[Path, int | None]]`: split on `;`, `&&`, `||`; skip
  `cd ...` segments; for each segment split on `|`; the first command's words (shlex, posix=False; unwrap
  powershell/bash wrappers like `shell_read_targets` does) decide what is printed:
  `cat/type/more/bat/less/awk/get-content/gc` -> whole (None); `head` -> `-n N`, `-N`, `--lines N` or 10;
  `tail` -> same, but `-f` -> None; `sed` with `-n` and every script `A,Bp` / `Ap` -> sum of (B-A+1), any other sed -> None;
  `Get-Content` with `-TotalCount/-Head/-First/-Tail/-Last N` -> N. Other commands (grep, rg, findstr, ls, python...) -> skip.
  File args = non-flag words (quotes stripped) that resolve to an existing file (absolute, or relative to cwd).
  If a later pipe stage is `head`/`tail`/`Select-Object -First|-Last N` the count becomes min(count, N); if a later
  stage is `grep/rg/findstr/Select-String/wc` the segment is skipped (filtered output).
  In `shell_read_hint` for PreToolUse: keep `shell_read_deny(paths)` first; if it returns nothing, for each
  (path, n) from `shell_print_ranges` call `map_first_deny(path, n)` and on the first reason return the PreToolUse
  deny JSON string (same shape as `shell_read_deny`).
- `agy_hook` PreToolUse `view_file` (Antigravity): for every view_file call (ranged or not), lines_read =
  EndLine - StartLine + 1 when both are given, else None; if `map_first_deny` gives a reason return
  `{"decision": "deny", "reason": reason}` before the existing whole-view check.
- Add "deny_map_first", "range_read", "map_skip" to the counters dict near line 1146 with 0.

### global_install.py — Claude's Bash gets the shell gate

In the Claude block, when `shutil.which("olla")`, PreToolUse becomes two groups: the existing Read matcher with
OLLA_HOOKS[0] and `{"matcher": "Bash", "hooks": [{"type": "command", "timeout": 10, "command": OLLA_HOOKS[1]}]}`.

Never edit tests. Never touch other files.


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
