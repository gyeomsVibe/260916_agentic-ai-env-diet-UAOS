# AI Resource Usage Ledger (AI 자원 사용 원장)

Maintained local metadata collector for Codex, Claude, Antigravity and Ollama.
The ledger records observed resource use; subscription quotas and monetary cost
remain separate. Reasoning tokens are a subset of output and are never added twice.

## Operation

```powershell
python -m v7_harness.usage_accounting collect
python -m v7_harness.usage_accounting report --start 2026-10-01 --end 2026-10-23
python -m v7_harness.usage_accounting report --timezone UTC
python -m v7_harness.usage_accounting snapshot --provider claude --used-percent 100 --window-minutes 10080 --origin user_report
python -m v7_harness.cli usage report
```

The default database is `~/.uaos/usage/ledger.sqlite3`; `--home` and `--db` allow
isolated verification. Data stays local and must not be committed. Snapshot origins
are `observed_ui`, `provider_api`, and `user_report`; no arbitrary text is accepted.
A user report of exhaustion is evidence of that report, not a measured token counter.
Native Codex `rate_limits.primary/secondary` snapshots are captured automatically,
allowlisting percentage, window duration, reset time and original event timestamp.
Their origin is `native_transcript`; unchanged snapshots within each source/pool
are suppressed. They never imply a token/percentage equivalence.
The report includes all-time, last 7 and last 30 calendar days in Asia/Seoul by
default, provider/model/day summaries, unique observed events, sessions, active days,
source statistics, timestamps, parsing failures and coverage. Date bounds are inclusive.

## Sources and boundaries

| Provider | Allowlisted input | Semantics |
| --- | --- | --- |
| Codex | `.codex/sessions/**/*.jsonl`, `.codex/archived_sessions/**/*.jsonl` | Native per-response usage deduplicates by response ID. Older token_count cumulative deltas remain a separate scope; matching adjacent native/last-call views are counted once. Cache read/write partition input. |
| Claude | `.claude/projects/**/*.jsonl` | Assistant message ID; repeated content blocks/late updates use maximum counters. Cache read/write are additional to input. `.claude/sessions` is excluded because it contains credentials. |
| Ollama | `.cache/olla/usage.jsonl` | Actual `ask`, `draft`, `generate`, `inference` token receipts; `pilot_local` requires model, elapsed time and explicit success. Cache/hooks/digest estimates/reviews are separate non-inference rows. |
| Antigravity | Inventory only: `.gemini/{antigravity,antigravity-cli,antigravity-ide}/conversations` DB/PB files | Opaque BLOB schemas do not establish token counts, calls, sessions or active days; these remain UNKNOWN. |

Only metadata is retained. Transcript text, prompts and tool bodies are parsed past
but never stored or printed; credentials, cookies, settings and environment files
are never opened. Session identifiers and report source paths are hashed. Models
and event categories use a restricted metadata label grammar.

Collection uses SQLite transactions with a busy timeout and one writer at a time.
Unchanged files are skipped; appends resume after the last complete JSONL line,
checking the previous tail fingerprint. Rewrites replace that source's contributions.
Deduplication is across source contributions, so moved/copied history stays single.
An initial SHA-256 and subsequent append-chain fingerprints provide provenance;
an append-chain fingerprint is not a SHA-256 of the complete current file.

## Limitations and quality gates

- Local logs are partial evidence. Missing/unsupported provider data is UNKNOWN,
  never a fabricated zero. Cloud history, Antigravity encrypted/opaque payloads,
  billing and provider quota pools are not inferred.
- Tool surfaces and inference providers are distinct. Claude project logs may
  contain Qwen or other local/third-party model labels; these remain in tool/model
  counts but do not prove Anthropic subscription consumption or model host.
  Explicit `<synthetic>` Claude notices are excluded as non-inference rows.
- Calls mean observed usage updates/messages, not provider billable requests.
  Native Codex response IDs distinguish independent identical simultaneous calls.
  Older records without IDs use timestamp/cumulative fingerprints; these can collide.
  Supported parsers with no local events report observed-local calls/sessions/days
  as zero, while global usage and token totals remain UNKNOWN. Opaque Antigravity
  calls/sessions/days are null because no inference parser covers that source.
- Codex counter resets without last-call usage are skipped and counted as errors.
  This intentionally undercounts uncertain reset usage rather than inventing it.
- Legacy Ollama timestamps omit a timezone; Asia/Seoul is an explicit assumption
  counted as `naive_timestamps_kst_assumed`. Model/time fields absent in old rows
  remain UNKNOWN. Historical logs are self-reported receipts, not inference proof.
- Removed historical sources remain in the ledger. A reset/rebuild uses a fresh
  database path; never delete production data automatically.
- Append detection checks the consumed tail. A rewritten prefix plus intact tail
  and later append can evade detection; rebuild from a fresh database if suspected.
- No token percentage conversion, subscription savings, API cost, or recommended
  plan value is calculated here. Those require independent evidence.

Acceptance: `python -m unittest discover -s tests -p 'test_usage_accounting*.py' -v`.
The original 8-test contract was frozen before implementation:
`BF69467C3A122A53A526B201981EF8168CB10FF7F68141AE3AD521B8F7D2C35F`.
Additional source-discovered tests cover legacy Ollama schemas and concurrent CLI
processes. Root conductor performs independent review and installed-runtime checks.
Parser revision 2 forces complete source reparse of older ledger contributions.
A real-use P1 exposed different native-thread and legacy-global cumulative scopes;
these now remain independent. Native per-response counts and IDs avoid re-adding
the historical cumulative offset at every interleaved observation.
Final worker suite: 16 tests pass; original frozen acceptance hash is unchanged.

## Sources and decisions

- [Claude Code usage monitoring](https://code.claude.com/docs/en/monitoring-usage)
- [Ollama generate metadata](https://docs.ollama.com/api/generate)
- [Antigravity plans and separate pools](https://antigravity.google/blog/changes-to-antigravity-plans/)
- [Google AI Ultra usage levels](https://support.google.com/googleone/answer/16286513?hl=en)

Manual records cannot automatically recover existing volume. Provider APIs need
credentials and leave subscription surfaces uncovered. Local allowlisted metadata
plus transactional deduplication was chosen as the smallest reversible proof.
Ollama drafted one normalization function and this operator-note skeleton; both
were independently checked. The normalization draft omitted Claude handling and
integer validation and was rejected. The note incorrectly excluded token storage;
that claim was removed. Local generation does not constitute independent review.
