# U184 — false wait routing, maintained evidence card

Observed installed stall.py _phase_waits accepts terminal DONE with stale waiting_on. It matches the substring merge in a negative safety note and turns it into merger work. scan's timer/quorum transition replaces the original BLOCKED/HUMAN state and note with READY. The live Codex structured watcher exited STALLED_WAIT for U180S-BOOT despite its failed U183 safety gate and already-approved UAC. Do not treat this timer output as authority to merge or register a task.

Root cause: dependency availability, authorization and failed acceptance are represented as free text and conflated with elapsed waiting. A timer is not acceptance. Python's official enum reference provides explicit named values as a design option, not proof of a completed repair: https://docs.python.org/3/library/enum.html . Compare typed blocker metadata, conservative state-preserving reroute, and keyword-only heuristics before design approval; no production code changed here.

Frozen regression: C:/Users/Kimyoongyeom/.codex/worktrees/u180-shared-recovery/260916_agentic-ai-env-diet/.work/U184_stall_accept.py. Pass command: python <gate> <candidate-root>. Tests cover terminal-state precedence, safety-failure exclusion and a real scan quorum preserving a scope boundary byte-for-byte. All mutations are in this test's disposable temporary directory. No production schedule is used by the reproducer.

Order: U183 writer Claude remains priority and sole shared-source owner. This is a follow-on card, not a parallel implementation assignment. Human scope boundaries and failed acceptance cannot be waived by route consensus. Preserve internal next-work dispatch for genuine reviewed dependencies. No remote push, install, legacy termination, permission change or deployment is authorized by this card.

2026-10-11 continuation: installed gate3 FAIL (test exit1), SHA256 0b4998996057572db5e61d97f8ee29ae4f4ab7cdb80a93eeae5e5039a943d0db. A real hook quorum then rewrote both boot safety and Lotto scope phases to READY and erased the gate notes. Codex restored boot to REWORK (no waiting_on, approval remains valid) and Lotto scope to HUMAN with an explicit authorization boundary. This contains the live false dispatch; it is not completion. U183 design is still REVISE, not a new PASS.

MIA small reversible proof: compare keyword-only routing (rejected: negative text becomes permission), blanket no-reroute (rejected: genuine internal wait stalls), and typed blockers plus terminal-state precedence (Go for this narrow proof). Local U184-L1 is confined to stall.py only, at most eight changed lines; no lease/boot writes or shared writer takeover. Fixed3 plus unchanged U166 tests must pass; independent review and installed acceptance are still required before release.

Local drafting attempt was rejected: it invented a form-validation story unrelated to the supplied evidence. The maintained card uses only deterministic source inspection and the independent reproduction.

## Ollama-first and Antigravity receipts

Ollama U184-L1 was called first with a pinned narrow contract: input4768/output343 local tokens. It invented an extra no-waiting_on guard, so fixed3 passed but unchanged U16624 had1error. Rejected; no evaluator changed. After that failed delegate, deterministic five-line A1 bundle70a7a4647ef5feb789703da50ec3e3737ade1add17b53f7e5585ac47c15c0133 passed both gates. Independent sidecar reran3+24, exits0, exact candidate SHA256 2e28683c85ef2a56c94efb03d270461466105aa23f9ae04c484ec5dbd5966f57.

Antigravity was actually invoked through pilot review on this exact bundle, not treated as unavailable from IDLE alone. Review conversation197f973f-e0cf-40e5-a2e8-6ee4376f01af returned advisory PASS; total27487 tokens within80000 cap,32s. Evidence is own .coord/pilot/runs/U184-A1/review_agy.json. No cap raise or rejected-output adoption. Codex still owns final evidence judgment. Full stage regression is running; neither installed success nor boot repair is claimed.

Superseding final candidate receipt: full stage2049 tests354.316s OK(skip6),exit0. Official exact A1 bundle promotion is APPLIED in the isolated Codex checkout; own source fixed3 was rerun after apply,exit0, matching SHA256 2e28683c85ef2a56c94efb03d270461466105aa23f9ae04c484ec5dbd5966f57. No installed runtime, remote merge or boot success is claimed. Release must integrate only this five-line repair onto current main, preserve U179 changes and add the pinned maintained regression; do not release this old checkout's superseded lease/CLI files.
