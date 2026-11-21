# INCIDENT 2026-10-17: conductor idle until the user pastes a chat (P1, U208 proposal)

Receipt: 윤겸스, 10-17 17:19 KST. The user pasted the Claude desk's briefing into the Codex desk, and only then
did Codex start working. The user called it a fatal operating error that keeps repeating.

## Timeline (verified)

| Time (KST) | Event | Evidence |
|---|---|---|
| 10-17 03:01 | Last dispatched letter to Codex (relay_86867808); Codex runs one turn and ends it | `.coord/mailbox/delivery/attempts/` SENT receipts; rollout 01a1423b task_complete at T18Z |
| 03:01 → 15:01 | 12 h: no dispatch to Codex. Codex has no rollout writes at all from 01:09 to 15:01 | `~/.codex/sessions/2026/10/17` mtimes |
| 04:09, 15:03 | Sentinel publishes transition_unknown and 8 owner_wake letters for Codex-owned phases (U185, U191) | inbox/ack files with actor=sentinel |
| 15:01, 15:03 | Two Claude letters dispatched; Codex runs 2 turns (06Z task_started ×2, task_complete ×2), then ends | rollout 01a1423b |
| 15:03 → 17:19 | 2 h 16 min: Codex idle again. Five open phases are owned by Codex (U185 design, U191 ×2, U196, U180-D5 REVIEW) | master_schedule.json |
| ~17:11 | The Claude desk writes "next plan: Codex leads" and ends its turn | this desk's previous turn |
| 17:19 | User pastes into Codex desk; Codex starts a turn (08Z task_started) | rollout 01a1423b |

Presence showed `codex=ACTIVE` the whole time. `codex.watch.json` had `wakes_session: false`.

## Root cause (one cause, nine earlier fixes missed it)

1. **Nothing autonomous can start a Codex turn except `coord deliver --target codex`.** Every always-on
   alarm (`owner_wake.py:71`, `sentinel.py:500/609/643`, `transition.py:87/133`) only calls `box.publish`,
   which writes a JSON file into the inbox. Codex reads the inbox only when it is already in a turn. A wake
   letter to an idle Codex is therefore a dead letter, by construction.
2. **ACTIVE means "a session exists within its TTL", not "a turn is running".** The authority rule says
   Claude takes over only when Codex is not ACTIVE, so an idle-but-ACTIVE Codex blocks both tools: Codex
   waits for a prompt, and Claude defers to Codex. That is a deadlock, not a wait.
3. **Each turn-based agent ends its turn when its current letter is done.** No agent re-arms the next turn
   for the conductor. The Claude desk did the same thing at 17:11 by ending with "Codex leads next".

## It is a three-tool failure, not a Codex failure (윤겸스 correction, 10-17)

The standing order was: when a wait grows long, each tool finds its own work, consults the other tools, and
keeps the tiki-taka going. All three tools broke it.

- **Claude.** The desk ended at least two turns (17:11 and after the U208 packet) with "next: wait for Codex's
  verdict". During the wait it did not take its own PARKED/ready work, and it did not consult Antigravity.
  "Waiting for a verdict" was treated as a valid stop, although the order makes a long wait a trigger to act.
- **Codex.** It ended each turn after its letter, and it owned 5 open phases.
- **Antigravity.** Presence was last observed 10-16 04:35Z, and 0 dispatches to Antigravity were made in 34 h.
  No tool used the headless agy route (U120) to consult it, so the third voice of the tiki-taka was absent
  and nobody noticed.
- **Shared cause.** Each tool's stop rule says "stop when the next step belongs to someone else". No rule
  says "while you wait, pick the next ready item of yours or open a consultation with a tool that is not
  busy". A wait is therefore an idle state for all three tools at once.
- **Fix direction (add to U208 as part E, for all three adapters).**
  - When a tool would stop because it is waiting on another tool, it must first do one of these:
    1. Take its own next ready or PARKED-review item.
    2. Dispatch a consultation to a tool that has had no dispatch in the last MAX_WAIT_S. For Antigravity this
       is the headless route.
  - Only if neither exists does it stop, behind a zero-paid watcher.
  - Acceptance is measured from the ledger: there is no window above MAX_WAIT_S in which none of the three
    tools has a turn while a ready step exists.

## Second stop and discord, 10-17 ~18:15 KST (윤겸스: "또 멈춰있다, 불협화음, 실시간 동기화")

- **Verdict sent as ACK_ONLY.** Codex sent its U208 STOP verdict (relay_97dcdfe0, relay_3ed59c4e) as
  ACK_ONLY. That is the U188 regression: a verdict did not wake its receiver, and then both tools ended their
  turns.
- **Two truths at once.** The U166 reroute moved U208 to `READY claude` at 09:13:50Z. Codex's verdict says
  STOP and BLOCKED. The schedule and the conductor's verdict disagree, so each desk shows a different state.
- **No turn-end result exchange.** Neither tool is required to send its turn result to the other two tools.
  The tools learn about each other only by chance.

### U209 proposal: real-time sync protocol (for Codex to judge)

- **R1. Result on every state change.** A turn that changes state, records a verdict or creates an artifact
  ends with `coord deliver` to the other two tools, ACTIONABLE with `--delta`.
  - A verdict is always sent with `--verdict`.
  - ACK_ONLY is used only when nothing changed.
- **R2. One state.** `master_schedule.json` is the only state.
  - A verdict updates its phase in the same turn.
  - A U166 reroute never flips a phase whose latest conductor verdict, newer than the stall, is STOP or
    BLOCKED.
- **R3. Three voices.** Antigravity gets the same delta through the headless route (U120).
- **Antigravity audit (relay_3a84bb2e reply).**
  - R1: PASS.
  - R2: REVISE. The phase write and the reroute guard must be an atomic compare-and-swap on the phase
    revision and `updated_at`.
  - R3: REVISE. Sending every delta to the headless route costs too much. Send only verdicts and phase changes.
- **Gate.**
  - Measured from the mailbox: every verdict letter is ACTIONABLE and is dispatched to its receiver.
  - The schedule state equals the latest verdict for every phase.

## Why the same error repeats

U64, U117, U166, U188, U194, U197, U200, U203 and U205 all fixed the **detector** (which letter, which wake
class, which stall timer). None of them added an **actuator** that starts the recipient's turn. Their
acceptance tests prove "a letter with wake_class=ACTIONABLE was published", never "the recipient's
rollout shows a new task_started within N minutes". The gate measured the wrong output, so each fix passed
green while the real-world symptom stayed.

## Fix proposal U208 (for Codex to judge; Claude implements via pilot)

- A. **Actuator**: the sentinel routes every ACTIONABLE alarm for codex/claude/antigravity through the
  existing dispatch path (`deliver` → `_deliver_to_codex` / `_deliver_to_claude` / agy headless), with a
  per-step rate limit (reuse NOTICE_KEEP_S) and the existing paid-call caps. Publish-only stays for ACK_ONLY.
- B. **Liveness = turn progress**: presence for the conductor becomes BUSY / IDLE from the tool's own
  session log (Codex rollout task_started/task_complete, Claude transcript mtime). The authority rule uses
  "ACTIVE and turn within MAX_WAIT_S or BUSY"; an IDLE conductor with ready steps hands authority to the
  deputy for that step.
- C. **End-of-turn rule**: an agent that ends a turn while it, or another tool, owns a READY/REVIEW step must
  dispatch (not publish) one wake to that owner first. This is a hook check (Stop hook) for all three tools.
- D. **Acceptance (fixed, end-to-end)**: with a fake Codex runner, an owner_wake on an idle Codex must yield a
  dispatch receipt and a runner invocation; a real-use check reads the rollout for task_started within
  15 min of a ready step. A test that only asserts the inbox file exists does not count.

Non-goals: no paid polling; no change to the U196 release hold; no weakening of approval policies.
