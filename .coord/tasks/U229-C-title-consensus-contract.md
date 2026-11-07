# U229-C — consensus writer and stable schedule identity

Maintained contract; canonical card ID **U234** (earlier descriptive alias U229-C is not accepted by `card new`). Codex conductor, Claude sole implementer, Antigravity independent verifier. Existing U229 remains the parent. B2 frozen source is immutable; this child addresses the newly reproduced title blocker before further policy deployment. Use U234 for pilot/audit/window records; the contract's existing path and the pinned acceptance hash stay unchanged.

## MIA 0–4: evidence, frame, alternatives, decision

- Receipt: relay_daa07cf4aca458bf065981c783f01bf8 and native TITLE_STATUS_INVESTIGATION.md. Installed reader has no automated writer; whole-phase hashing invalidates votes on state changes. Root independently read the 136-line reader and observed the same mismatch during 7f5ace08 -> 1be225ac updates.
- Sources read before this decision: https://docs.python.org/3/library/sqlite3.html (explicit transactions), https://docs.python.org/3/library/os.html#os.replace (file replacement). These mechanisms need local concurrent tests; documentation alone proves no application-level atomicity.
- Goal: three genuine tool votes produce a short suffix on all existing native title adapters, without metadata churn invalidating agreement. Title remains display metadata, never authority.
- Alternatives: manual master editing fails automation; rewriting the shared master under a title-only lock risks lost unrelated scheduler writes; dedicated transactional consensus state avoids that cross-writer mutation.
- Decision: GO for a minimal dedicated SQLite store under the canonical shared project's `.coord/`, plus semantic schedule identity. No new server, model loop or master rewrite. This replaces the earlier full-phase hash assumption; do not transfer old mailbox votes silently.

## MIA 5–8: fixed interface and ownership

Input baseline is installed `0.3.0-cbd2208ef625`, package digest `cbd2208ef62553f03261556dd4f83754273c914b35914fd5cacb14d6aa62b257`. Create a new owned isolated source under Claude `.work/U229-C-title-consensus`; never mutate B1/B2 frozen trees, staged B2 branch or shared dirty checkout. Preserve all runtime features when root prepares installation. For eventual source release apply only this card's narrow hunks; never replace the full CLI from another baseline.

Allowed source files: `v7_harness/coord/title_consensus.py` (new), `v7_harness/coord/desk_title.py`, and additive `v7_harness/cli.py` command wiring. Supplementary worker tests allowed. Root acceptance file is not editable by workers.

APIs fixed for independent acceptance:

```python
schedule_digest(project: Path) -> str
cast_vote(project: Path, tool: str, topic: str, expected_hash: str) -> dict
```

- Implement in `coord/title_consensus.py`. Resolve the shared project root consistently. Semantic hash is SHA256 of UTF-8 compact JSON of the ordered list `[{"phase_id": id, "title": phase.get("title", "")}, ...]`, sorted object keys, ensure_ascii=False. Require nonempty phase list and unique nonempty string phase IDs; malformed input fails closed. State/owner/timestamps/receipts must not enter this hash. Reordering/ID/title changes invalidate it.
- Add CLI `coord title-vote --project ROOT --tool TOOL --topic TOPIC --schedule-sha256 HASH`. Optional read-only `--status` may expose the current semantic hash; no implicit votes. Each native tool casts its own vote. Labels are attribution, not authenticated release/approval authority. Never fabricate other tools' votes or reinterpret old raw-phase hashes.
- Topic: 1–16 Unicode code points, no leading/trailing whitespace, control characters or square brackets. Unknown tool, bad topic, corrupt schedule or mismatched expected hash raises a bounded validation error before vote mutation.
- Dedicated SQLite transactions serialize vote updates and quorum acceptance. One current vote per tool per semantic round; duplicate caller cannot create quorum. Only all three tools agreeing on the same topic and semantic hash establishes a new accepted topic. Conflict/partial topic update keeps the last approved topic; no new suffix before quorum.
- Reader `desk_title._schedule_topic(project)` reads fresh accepted dedicated state and validates current semantic digest. Preserve validated legacy master `desk_title` behavior only when no dedicated store exists. Corrupt dedicated state fails closed. Do not create a DB merely by reading. Do not rewrite master_schedule.json, user-desk identity, prefix, ownership or native emit budgets.
- Existing `_desired_title` keeps a previously accepted suffix when a new semantic round is pending. No direct app/session database writes or fake hook events. Native confirmation and desktop visibility remain separate.

## MIA 9–10: gates, limits, release

Root acceptance path: `170e/.work/U229/consensus-acceptance/test_u229_consensus_acceptance.py`, SHA256 `50f6e3dd5203f74c9d645dfb802a66e5a70e2546ff429dfb5c4cb93280dbaf29`. Run with the isolated source as cwd and the absolute acceptance directory passed to unittest discovery; merely setting PYTHONPATH from a different checkout can import that checkout first. Confirm the imported package path. Then run unchanged title and invocation regression tests. Required five cases: 3 votes -> suffix; 2 votes/duplicate caller -> no quorum; state-only change preserves hash/topic; topic/semantic change needs fresh votes; three synchronized real OS processes cannot lose a vote. Assert master bytes unchanged by voting. No test weakening, fixture-specific branches or evaluator edits.

Use deterministic extraction first. Ollama only useful <=20-line/skeleton slices with actual input/output/usage receipts; no manufactured failed attempt or unrelated title-run provenance. Preserve normal pilot/card/audit commit gates. No additional EVAL benchmark calls. Design/file work bounded to 15 minutes; stop after two same-cause failures. Report one frozen manifest/diff, exact commands/exits and unresolved facts; no worker install/push/merge. Root judges and installs only reviewed exact deltas, preserving current features. Antigravity reviews the non-author source and reruns fixed gates; quorum and production native display require real subsequent tool votes/readback.
