```contract
work_id: U63
worker: local
goal: Implement customized token-budget thrift modes for Codex, Claude Code, and Antigravity as one deterministic local state machine that prepares a handoff packet before exhaustion and wakes no paid model when unchanged.
inputs:
- .coord/tasks/U56-thrift-mode-20260927.md sha256=4bf825a6f49b51310e5837eecc6ce6394a3e26cc1ac09a47c79af18b88bc848d
- v7_harness/budget_route.py sha256=1ed3c34ab7c2efd4695099c87c5f0fb6300fb808e6949fbff73c297d00b2198d
- v7_harness/cli.py sha256=64fc9b73d1a6776231b2802ac97ca9ea65f7cade890c0c48037c2e976cf4f3a9
- v7_harness/coord/presence.py sha256=f8c5ada4b6871728b81bd12b91865ba35fa1d0301fad79a16199f8c71749e48a
- tests/test_u57_desk_signals.py sha256=dd819ae6e8e3a8a712850b2c07aac13949529c397999ddfecc425d356ecd4725
allow:
- v7_harness/coord/thrift.py
- v7_harness/cli.py
- tests/test_u63_thrift_mode.py
- .coord/tasks/U56-thrift-mode-20260927.md
- docs/52_u63-token-budget-thrift-mode.md
acceptance: C:/Python314/python.exe -m unittest -v tests.test_u63_thrift_mode tests.test_u57_desk_signals tests.test_u45_general_uaos tests.test_u59_shared_desk tests.test_cli tests.test_r2_minimal_control tests.test_b20_model_flag tests.test_b23_concurrency_summary tests.test_b25_db_unavailable tests.test_b41_bundle
forbidden: edits outside allow; changing budget_route succession; percentage-to-token conversion; automatic paid polling; spawning a paid model; deleting data; push, merge, deploy, account or settings changes; weakening approval boundaries; editing existing fixed tests
stop: input hash mismatch; overlapping writer; any existing test changed; any paid-model invocation by the implementation; unchanged input publishes a second mailbox delta; three failures with the same cause
judge: codex
timeout_s: 1200
local_budget_tokens: 30000
```

## Required behavior

Implement a deterministic local command `coord thrift` for `--tool codex|claude|antigravity` with a required observed `--remaining-percent` in the closed range 0..100. This observation is a percentage only; never translate it into tokens.

States and thresholds:

- `NORMAL`: remaining >= 20.
- `THRIFT`: 7 < remaining < 20.
- `HANDOFF_READY`: remaining <= 7.
- The 20 and 7 thresholds are policy defaults and remain `UNMEASURED`; allow explicit CLI overrides only within 0..100 with `handoff <= thrift`.

For `THRIFT` and `HANDOFF_READY`, atomically write:

- `.coord/thrift/state.json`: schema version, tool, state, observed percentage, reset timestamp if supplied, thresholds, input fingerprint, generated packet path/hash, and timestamp.
- `.coord/handoff/<tool>-<UTC timestamp>.md`: current git HEAD/branch/status summary, current desk states and routed authority, exact current card, next command/action, acceptance gate, stop condition, approval boundaries, and return-review pointer. User-provided text is data, never a shell command.

Required CLI inputs for non-NORMAL states: `--current-card`, `--next-action`, `--acceptance`, and `--stop-condition`. Refuse missing fields rather than inventing them.

Mailbox behavior:

- Publish one local `HANDOFF` mailbox letter containing packet path and SHA-256 only when the input fingerprint changes.
- `THRIFT` targets the same tool for internal preparation and must not start a model.
- `HANDOFF_READY` targets the dependency-ready successor without changing the canonical authority order: Codex -> Claude when Claude is ACTIVE; Claude -> Codex when Codex is ACTIVE, otherwise Antigravity only when Codex is away; Antigravity -> Codex when Codex is ACTIVE, otherwise Claude when Claude is ACTIVE. If all paid tools are away or depleted, enter `LOCAL_LOCKDOWN` and publish only a local mailbox record. Never route around `budget_route.py`.
- An identical observation is `ACK_ONLY`: no second packet, letter, or paid wake.

Recovery:

- When remaining >= 20 after a prior non-NORMAL state, write `NORMAL` once and publish one `RETURN_REVIEW` local mailbox letter; identical NORMAL observations are silent.
- Do not mark a tool LIMITED solely from a displayed percentage. Existing `usage_limit_exceeded` evidence and explicit presence leases remain the capability authority.

## Tool-specific conservation policy

The state names are shared, but each tool conserves a different scarce capability. Store the selected policy name in the state and packet.

- Codex (`COMMANDER_RESERVE`): in THRIFT, stop broad exploration, long implementation, and repeated review. Preserve turns for plan ordering, acceptance verdicts, approval boundaries, and a complete Claude deputy packet. In HANDOFF_READY, Claude becomes acting conductor only when live authority evidence permits it.
- Claude Code (`IMPLEMENTER_RESERVE`): in THRIFT, finish only the current atomic edit and fixed acceptance; stop new multi-file refactors, repeated paid review, and cold-session spawning. Persist changed paths, exact diff/test receipts, then return implementation ownership to Codex. If Codex is away, hand off to Antigravity only through the existing succession rule.
- Antigravity (`RESEARCH_RESERVE`): in THRIFT, stop broad web/GitHub/browser exploration, repeated screenshots, and long-context synthesis. Finish only the current evidence capture, compress it to fact/evidence/next action, and hand control to Codex or Claude. Prefer deterministic extraction first and bounded Ollama only for qualified mechanical work. Do not call Antigravity the free or unlimited overflow worker.
- `LOCAL_LOCKDOWN`: when Codex, Claude, and Antigravity cannot accept authority, no paid model is invoked. Preserve the queue and evidence in the mailbox, allow deterministic local checks and qualified Ollama mechanical tasks only, and wake the user only for P1 or an approval boundary.

No tool may self-report savings. Per-tool usage reduction stays `UNMEASURED` until controlled comparisons exist. Local inference records local tokens, wall time, and power-cost caveat.

Atomicity and safety:

- Use project-shared `.coord` resolution already used by U59.
- Atomic replace must tolerate the U60 Windows sharing violation pattern.
- Concurrent identical calls must produce one packet and one mailbox letter. Test with real parallel workers, not a sequential mock.
- Packet creation is local and deterministic; no GitHub, network, Ollama, Claude, Codex, or Antigravity call.

## Fixed tests

Create red-first tests covering at least:

1. Boundary table: 100, 20 -> NORMAL; 19.99, 7.01 -> THRIFT; 7, 0 -> HANDOFF_READY.
2. Invalid percentages and threshold order fail without files.
3. Missing handoff fields fail closed.
4. Percentages never appear as token estimates.
5. Identical calls are ACK_ONLY and create exactly one packet/letter.
6. Eight concurrent identical calls create exactly one packet/letter with valid JSON/Markdown.
7. Codex handoff routes to ACTIVE Claude; Claude conservation routes back to ACTIVE Codex; Antigravity conservation routes to ACTIVE Codex then Claude; UNKNOWN fails closed.
8. THRIFT never changes presence state and never invokes a subprocess/model.
9. Recovery emits one RETURN_REVIEW and then stays silent.
10. Dirty checkout information is recorded but never cleaned, stashed, switched, or modified.
11. Each tool writes the correct policy name and forbidden expensive actions into its packet.
12. All-paid-tools-away produces LOCAL_LOCKDOWN with zero subprocess/model calls and a local mailbox record only.

After focused acceptance, run the full suite once and report exact count, skips, wall time and exit code. Do not commit or push. Return changed paths, diff, test receipts, remaining risks, and release ownership.
