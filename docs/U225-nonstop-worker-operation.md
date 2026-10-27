# U225 operation contract (maintained)

The conductor owns one machine schedule, one active source writer and one next executable action. Agreement, mailbox publication, a local wake claim and receiver completion are different states. A receiver opens an addressed letter, executes its smallest ready dependency, records evidence and only then ACKs it. If that dependency is unavailable, record BLOCKED and take another ready bounded action; never request another agreement for an already authorized action. A truthy blocker_kind, gate_failed or human marker protects even a READY/PLANNED phase: it is excluded from selection/handoff and checked again inside the claim lock. A READY label cannot erase a recorded safety gate.

## Native continuation

Claude CLI2.1.303 uses a short SessionStart bootstrap and a host-owned Stop asyncRewake listener. A long SessionStart listener blocks its first response. Stop waits without provider calls, scopes events to the current declared desk and holds a kernel lifetime lock. NOTICE, worker sessions, foreign cards and stale messages do not wake it. Exit2 signals an eligible ACTIONABLE event; it is not receiver ACK. Scan windows rearm internally; after24hours or native host cancellation, a new native lifecycle event is required. The state file reports expiry honestly.

Codex continues through its existing native queue. Async hook completion alone does not start a Codex idle turn. Antigravity retains its documented Stop continue/fullyIdle gate; no unsupported asyncRewake setting is installed. Until actual native receipt exists, Antigravity idle wake is UNKNOWN. Never substitute detached shell liveness, a same-desk headless provider call, or a delivered-only receipt for native proof.

## Shared worker planning

All three callers run `uaos coord worker-route --task-file <json>`. Input contains `task` and `availability` objects. The command returns a plan only, with `execution_authorized:false`; existing contract, pilot, single-writer, independent judgment and usage gates still apply.

Example task fields: caller=`codex`/`claude`/`antigravity`, kind=`transform`, input_tokens=1024, output_tokens=256, changed_lines=10, local_failures=0, local_qualified=true, allow_remote=false, timeout_s=30. Availability includes local=true and haiku=false. An unknown paid route never silently becomes available.

Exact count/hash/validate/extract operations use deterministic tools. Qualified bounded transformations, drafts and edits use Ollama first, with at most20changedlines, totalcontext16384, output4096 and a positive timeout. Two same-cause failures end that local route. A failed or unqualified task never earns a higher local call rate merely to increase usage.

Semantic work may use exact `claude-haiku-5-5` through the existing Claude worker only when allow_remote is explicit, availability is verified and positive token/USD/time reservations pass. Group up to ten compatible independent routing items per request; never batch different writer scopes or approval decisions. Tools and independent judgment remain disabled for calculator requests. No paid idle calls or automatic quota retries. Tiny output settings are not a proven totaltoken cap for adaptive thinking. Estimated USD thresholds can overshoot; actual usage is independently checked before admission.

The fixed routing cohort passed Haiku10/10 individually and10/10 in one batch. Batch measured4.885seconds and0.00050305USD list estimate versus23.58seconds and0.0024588USD. This supports batching that task class only. The original Ollama profile passed one of six actual attempts; four further cases were skipped. A new documented qwen3.5:4b think=false/schema profile produced two valid JSON but incorrect labels and stopped, skipping eight cases. Its semantic routing class remains unqualified. Actual account quota savings and broader coding quality are UNMEASURED.

For each cohort retain input hashes, exact model, engine attempts, output-check results, timeout/retry counts, full token usage, elapsed time and list/billed cost distinction. Increase local share only for task classes with ten fixed passing samples and no quality/P1 or3x time/token regression. Receiver-owned native receipts, installed manifest checks and independent acceptance determine completion.

Sources: https://code.claude.com/docs/en/hooks ; https://learn.chatgpt.com/docs/hooks ; https://antigravity.google/docs/hooks ; https://platform.claude.com/docs/en/models/haiku-5-5/overview ; https://code.claude.com/docs/en/cli-reference ; https://code.claude.com/docs/en/env-vars .
