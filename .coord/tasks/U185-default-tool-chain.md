# U185 — permanent default tool chain, maintained design

Status: design/specification, not installed or verified completion. User requirement: Ollama and Antigravity must be default tools without repeated user reminders. This augments ongoing safety repair; it does not replace U183 or retire existing Antigravity conversations.

## Stage0 evidence and actual gap

Official primary sources: https://docs.ollama.com/api/introduction documents the local server/API separately from cloud credentials; https://code.claude.com/docs/en/hooks documents lifecycle hooks and command-hook inputs; https://docs.python.org/3/library/enum.html documents explicit named values. None proves an installed universal routing gate.

Existing v7_harness/card_pipeline.py already describes Ollama/Antigravity slots and commit/ship audit. Observed operation still allowed a user-facing conductor to launch work before a master card's complete route/receipt existed, or to count a skip/label as the default chain. Prompt reminders and a late audit alone do not enforce dispatch order or exact generation. The user-reported omission is the failure receipt for this card. A fresh Antigravity review succeeded while its UI status was IDLE: inactivity is not inability.

The local drafting tool produced the initial five-heading draft for this design. Its suggestion of "tamper-proof" receipts is rejected: same-account files are not authentication. The design instead pins inputs, reconciles observed execution, and requires an independent non-author judge; it makes no absolute anti-tampering claim.

## Frame and decision

Success: starting a new project/card without any instruction naming tools produces the default route and observed tool receipts, then closes the authorized process through independent gates. Missing, stale or wrong-generation receipts prevent promotion. Non-goals: force pointless calls for exact arithmetic/extraction, weaken evaluators, spend unapproved money, bypass human boundaries, duplicate an existing owner, or claim unknown native hooks as supported.

Alternatives: (A) global prose reminders: cheap, but the reported omission remains possible; reject as the enforcement mechanism. (B) tool-specific duplicated routers: possible but drift and three different bypass paths; reject. (C) one deterministic shared control layer with thin adapters and receipt-gated stages: preferred architecture, pending pinned implementation contracts and independent verification. Rollback: restore the prior reviewed source/runtime pointer and adapter backup; preserve all receipts and user data. No automatic rollback of unrelated work.

## Default state machine — runtime, not a model promise

REGISTERED -> INPUTS_PINNED -> LOCAL_PREP -> LOCAL_CHECKED -> EXECUTED -> AGY_CHECKED -> INDEPENDENT_ACCEPTED -> RELEASE_GATED -> INSTALLED_CHECKED -> LIVE_VERIFIED -> DONE.

1. Before dispatch, register one work/card generation, scope, frozen acceptance, writer, judge, tool/time/token caps and dependency graph. Existing in-flight ownership blocks a duplicate dispatch. Project paths are resolved dynamically, never hard-coded into global routing.
2. Deterministic extraction first; Ollama is the default for eligible mapping, drafts, transformation and mechanical candidates. It receives only bounded pinned inputs, output schema/example and forbidden actions. Codex validates extracted facts and output; Ollama never plans authority or judges acceptance.
3. Antigravity is a default bounded executor for specified work or the required independent reviewer of another author's candidate. A declared IDLE state triggers a bounded capability check, not a waiver. A rejected/capped review never becomes a successful receipt by raising its cap. If Antigravity authored code, its self-review cannot satisfy independent acceptance.
4. Codex conducts and judges; Claude is the deputy/alternate authorized route when Codex is actually unavailable. Tool execution uses the existing CLI/SQLite pilot path, never the retired Bridge. Valid review can proceed without another user "use this tool" instruction.
5. The shared core computes the next legal step, dispatches it once, validates outcome and schedules the next dependency-ready step. Local event/content-hash watchers replace paid polling. User authorization and failed acceptance are typed blockers, not elapsed waits. A genuine unavailable route parks that dependency and takes another safe READY card; it never falsely marks DONE.
6. Commit/ship/merge/install entry points consume the same evaluated route receipt. Missing LOCAL or AGY proof cannot be repaired by prose at the final report. The entry-point check must also run before worker dispatch, not only at commit. UI hooks provide context/capability events; they do not grant authority or replace the shared core.

## Receipt contract and exceptions

Each receipt: schema version, card, generation, stage, actor/actual tool, invocation id, canonical input hashes, candidate/bundle hash, start/end timestamps, outcome, cost/cap, independent judge and evidence path. Unknown measured values remain null/UNKNOWN. A receipt from another card, prior generation or changed input is rejected; a QUEUED/DISPATCHED message is not receiver execution or ACK.

Exceptions are typed, bounded and evidenced: deterministic extraction only when it actually supplies the requested data; LOCAL_UNAVAILABLE or repeated invalid output with exact failure and limited fallback; AGY_QUOTA/UNAVAILABLE with an actual probe/receipt and independent alternate route. UNKNOWN and IDLE are not exemptions. Generic TASK_CLASS prose must not waive an eligible default route. A fallback records why, what was tried, next safe owner and resume trigger; it never silently disables the default permanently.

## Three adapters and Windows

Codex, Claude Code and Antigravity load one canonical route policy and call the same shared preflight/transition functions. Adapters translate supported native lifecycle events only. Unsupported events remain UNKNOWN and require a verified alternate launch path. Exact source, installed adapter hashes and real native hook output must match before universal deployment is claimed.

Windows boot starts the deterministic supervisor/watch infrastructure, not unrestricted paid agents. Registration uses the user's existing action-specific UAC approval only after U183 installed safety passes. Opening any authorized project registers/resumes its own card generation. Preserve the old Antigravity desk and its assigned process. The model is called only for actual scoped work or actionable evidence.

## Frozen acceptance to establish before implementation

- All three tools: a new arbitrary project started without tool names routes eligible preparation to Ollama and candidate execution/review to Antigravity; no project-root hard-coding.
- Missing local call, missing AGY execution/review, wrong-generation receipt, stale candidate/hash, forged status label, reordered stages or self-review: dispatch/promotion refused.
- Deterministic-only extraction, local invalid-output fallback, actual AGY quota, UNKNOWN and IDLE: exact typed outcomes; no cap raise or silent waiver.
- Concurrent duplicate events: one writer and one dispatch; real parallel-process tests, not sequential fixtures.
- Accepted candidate automatically advances its dependency; genuine human/safety/scope boundaries remain unchanged under a timer or tool quorum.
- Cold Windows start, new project enrollment and native hook evidence across all three adapters; boot approval is not operational success.
- Failed/empty outputs, external writes and hidden nonzero exits remain failures. Controlled token/time comparison is required before savings are reported.

Next implementation contracts must name the exact shared entry points after a narrow source survey: card_pipeline plus existing pilot/routing/release gates, with three adapter contracts. Evaluators are frozen by an independent judge first and never worker outputs. U184 is a disjoint small safety proof; U183 lease/boot ownership remains Claude. This design is recorded as the default architecture, but no unimplemented enforcement is claimed as permanently active.

## Executed design verification — v1 is PIVOT, not approved

Installed card_pipeline.audit was directly reproduced with two disposable-root counterexamples. Fixed gate .work/U185_route_receipt_accept.py SHA256 3be0e286c8f9eaf3e8bf5b871a0ac73853118830c1c2f5d9a6460d0da9642b4e: 2 tests,2FAIL,exit1. It accepts old FAILED calls merely because token counts are positive, and accepts a PASS-labeled over-cap review for another bundle/generation. These are actual shared-core refusal gaps, not missing reminders. Existing source audit lines321-358 checks neither order nor these bindings.

Antigravity architecture audit U185-AG1 was attempted with a hashed document, one output path,80000-token/180s contract. It yielded an empty response, no review.json and partial timeout, so it is not design approval. Raw usage input58858 + output5674 + separate cache_read233079 = cache-inclusive297611, over the contract despite the driver's WITHIN label. No cap raise or output adoption. Pilot reconcile returned ABANDONED.

The driver's external path U185_route_receipt_accept.py was created by Codex during the audit's broader watch, not proven to be an Antigravity write. This was a coordinator isolation mistake: preparing a fixed gate inside a watched ancestor while the audit was running. Preserve this attribution and the original receipt; do not report worker misconduct. Future dispatch must freeze ALL test/manifests and resolve the complete watch-root lease before calling any worker; helper locks only inside a nested source are insufficient for ancestor writers.

Actual routing receipt relay_9c302a008fad4de7814ae31af2ae08ad shows U183 execution is waking the stood-down Claude default desk instead of the existing source writer. Current next_card ignores owner_session. A permanent tool chain therefore needs exact destination session/worktree/role binding as well as tool name. Writing an owner_session field alone does not fix a receiver that ignores it. No owner replacement, old-desk exclusion or claim deletion is authorized by this finding.

## Required v2 executable contracts

- RoutePlan v1: card + immutable generation + goal/fixed-acceptance hashes + canonical source manifest + writer session/worktree + non-author judge session + ordered mandatory stages + per-stage caps + all watch roots. No dispatch before validation and a single-owner lease covering those roots.
- Receipt v1: invocation id, stage, provider, actual receiver session, input and output/bundle hashes, terminal outcome, independently validated artifact, start/end sequence, normalized usage semantics including cache, cap and evidence path. Positive tokens alone are usage, not successful work. An unsuccessful local attempt may justify a bounded fallback, never satisfy successful LOCAL_CHECKED.
- preflight(plan, stage, evidence): deterministic ALLOW/BLOCK/UNKNOWN with a typed reason. It must reject stale/unregistered/wrong-order/wrong-bundle/over-cap/self-review and wrong-session evidence before any side effect. A caller cannot waive the requirement with a free-text skip.
- advance(plan, receipt): atomic compare-and-swap on generation/stage/owner; duplicate invocation is idempotent, concurrent writers cannot skip stages. Preserve the original failed evidence when re-planning. Unknown native capability remains UNKNOWN, not a simulated receipt.
- All controlled worker, commit/ship, merge and install entry points consume this same evaluated plan. Existing late-audit PASS is diagnostic only until the new pre-dispatch and pre-promotion bindings are verified; no old PASS label is grandfathered into a new generation.
- Thin adapters translate supported events and actual receiver ACK into the shared contract. Unsupported native pre-tool enforcement must be stated precisely; do not claim a hook can prevent every direct file/tool action. Installed-runtime hashes and real native invocation evidence for all three tools remain separate gates.
- Cost normalization has an explicit provider schema: identify whether input already includes cache, never double-count or omit it, and fail closed when semantics are unknown. The driver's existing cost_gate text is not authoritative. No more paid repetition of U185-AG1; use the independent alternate route and retain the failed receipt.

An independent alternate design review is now scoped to .work/U185_independent_design_review.md only. Before implementation Go it must freeze exact API/endpoint contracts and tests, not merely agree with the prose. Source implementations, tests/evaluators, global settings and U183 ownership remain untouched by this design verification.

## Native adapter contract — primary-source capability, not installed proof

Official fetched references: https://learn.chatgpt.com/docs/hooks ; https://code.claude.com/docs/en/hooks ; https://www.antigravity.google/docs/hooks/ . All document pre-tool events, but their JSON contracts differ. Codex/Claude supported denial uses hookSpecificOutput.permissionDecision=deny; Antigravity uses decision=deny with toolCall/conversationId fields. Never copy one provider's output schema to another. Neither the documents nor an installed script hash prove a native invocation passed.

Codex documentation explicitly states that missing MCP servers/tools and hook errors do not block the operation; malformed/unsupported output is therefore NOT a fail-closed barrier. The controlled pilot/release endpoint must independently require a valid permit even when its notification hook fails. The design does not claim interception of unconfigured native tools or arbitrary same-account edits. Native coverage needs real tests for every supported mutation channel; unsupported or untrusted hook coverage is UNKNOWN, not ALIGNED.

Adapters may deny or report policy decisions but never auto-allow a human-only action, change permission settings, suppress warnings or bypass hook trust. Installing/trusting/updating global hooks is an action-specific deployment boundary, not implied by this design. Bootstrap preparation (bounded read/research/local model calls) must have an explicit stage allowlist so enforcing LOCAL_PREP does not recursively block the very local call it requires. Workers receive only permits for their contract scope; final independent judge and human boundaries stay outside worker authority.

## Independent review disposition

Alternate sidecar .work/U185_independent_design_review.md SHA256 a6b74e7154a921bbe06fb9e64e5d728366337f0b646aa61c63ad1e4bcc4af6e3 independently reproduced both receipt refusal failures, existing21 diagnostic tests green, and the cache-key alias mismatch in evaluate_cost_gate. Its author corrected elapsed time to198s against the180s contract. Therefore its proposed PIVOT is reference data only, not an admissible approval or implementation Go. No retroactive cap increase. Source-checked facts and the original failed tests remain the evidence for Codex's REWORK disposition.

Next bounded work is to freeze the RoutePlan/Receipt/Decision schema, endpoint allowlist and exact receiver/cost fixtures, then obtain a compliant non-author contract verdict. In the interim preserve the invalid receipts, do not retry AG1, do not start implementation on prose alone, and keep the zero-paid watcher for actionable artifacts. U185 is REWORK, not DONE, and all native installed enforcement remains UNKNOWN. Existing U183 ownership and the user's already-approved UAC boundary are not replaced by this design card.

## Resumed concrete schema step — no further duplicate-only waiting

User's renewed no-wait report triggered the next safe design dependency instead of another duplicate-relay response. Ollama generated the fixed field/stage/endpoint draft first; Codex source-checked it and published tasks/U185-contracts.json SHA256 1b3f9ba8e41aeed88c707465e60ff9dc34937f49b7d36a9ee07ce0c3192d1ff6. It adds typed refusals, non-author defaults, cache fixtures, atomic transition keys and explicit limits; it grants no side-effect authority.

Own .work/U185_validate_contract_spec.py SHA256 ef41467292291ad4f7d7d603ae5c9e4bbbe25e0c2391e24a0f9e3de8c95be926: seven checks exit0,0.376s. They verify exact stage order, hash/generation/destination fields, actual endpoint symbols in source, default tools, unusable-evidence exceptions, cache arithmetic and protected boundaries. This is SPECIFICATION VALIDATION ONLY; installed fixed2 refusal failures remain unresolved and runtime enforcement is not claimed.

Reporting correction: repeatedly replying to old relays did not advance unfinished work. Receipt-only traffic must not replace a safe dependency-ready contract step. The root REWORK status stays truthful, with a separate executable refinement/review child so the scheduler does not strand all work behind an invalid prior verdict. No user start command is required to resume that child.
