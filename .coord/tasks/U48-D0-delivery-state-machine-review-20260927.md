# U48-D0 — delivery state-machine review (2026-09-27)

Status: REWORK.  This reviews the Claude-provided prototype in the main
checkout: `v7_harness/coord/deliver.py`, `v7_harness/cli.py`, and
`tests/test_u48_deliver.py`.

## Verified baseline

`C:\Python314\python.exe -m unittest tests.test_u48_deliver` ran 9 tests with
exit 0.  `compileall` and `git diff --check` also passed.  This is not a
delivery acceptance result: its tests use a fake subprocess and do not prove a
durable message, receiver acknowledgement, retry, or an actual recipient
session.

## Rejection reasons

1. `deliver()` invokes a target CLI before atomically publishing the message.
   When both desks are absent it returns `ABSENT_ALL` but creates no mailbox
   message, so the fact can be lost.
2. A process exit code of 0 is labelled `SENT`; neither `codex queue` nor the
   parsed Claude text is a recipient ACK bound to the message id and digest.
3. A failed dispatch has no durable attempt number, failure reason, or retry
   state.  The caller's non-zero exit discards the only result unless it adds
   its own ad-hoc logging.
4. The Claude route permits only `Read`, so it cannot acknowledge or execute a
   bounded work contract.  A free-form message is not a task contract.
5. The unit tests do not exercise the required concurrent 8-process
   publish/claim/ack case, no-ACK retention, idempotency, or a real registered
   CLI session.

## Required D0 contract

The corrected `coord deliver` must publish first, under a stable message id
and content digest, and return `PUBLISHED` even if no recipient is active.
Dispatch may then move a claimed message to `DISPATCHED`, but only an explicit
recipient `coord ack --id <id>` receipt creates `ACKED`.  A timeout, missing
CLI, malformed result, or non-zero exit must return the exact same bytes to
the inbox and append a bounded attempt receipt; it must never ask the user to
relay.  Messages without ACK remain recoverable in the inbox.  The receiver
must receive the full, hash-fixed work contract, not merely a path or free-form
summary.

Allowed implementation scope: `v7_harness/coord/deliver.py`,
`v7_harness/cli.py`, `v7_harness/coord/mailbox.py`, and focused U48 tests.
Use `worker: apply` only.  No paid model call, global configuration change,
commit, push, or destructive retention action.

Required gate: a real 8-process test proves one byte-identical message is
published, no ACK is retained, duplicate dispatch does not duplicate delivery,
and an ACK is traceable to the original id/digest.  A separate integration
test may claim `DISPATCH_ACCEPTED` only after a real local recipient CLI is
registered; it cannot call a paid model.
