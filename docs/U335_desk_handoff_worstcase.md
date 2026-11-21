# U335 user-desk handoff: worst-case table

Code: `v7_harness/coord/desk_handoff.py`, CLI `coord desk-handoff --action detect|run|check|ack|status --tool <tool>`.
Deadlines (real time): notice attempt ≤ 10 s (`ACK_DEADLINE_S`), card reply ≤ 120 s (`REPLY_DEADLINE_S`), never block.
Lease 900 s (`LEASE_S`): long enough for one long dispatch turn, short enough that a dead desk frees the role.

| Failure | What happens | Reason code / evidence |
| --- | --- | --- |
| Two new desks at once | Both read epoch N, both call takeover(expected_epoch=N) under one OS file lock; the first writes N+1, the second sees N+1 ≠ N and loses. | `DESK_TAKEOVER_LOST`; tests `test_concurrent_double_takeover_one_winner` (3x2 real processes), `test_concurrent_threads_one_winner` |
| Old desk mid-dispatch | The takeover does not wait for it. Its next dispatch calls `check_dispatch` and is refused; a dispatch already sent is covered by the manifest (cards keep their state) and the card window's notice. | `DESK_SUPERSEDED`; `test_old_desk_dispatch_refused` |
| New desk dies right after takeover | Manifest and conductor record are already on disk. Lease expires after 900 s: nobody dispatches (`DESK_LEASE_EXPIRED`), and any desk, the old one included, may reclaim with epoch+1 (recovery, not a silent revert). | `test_dead_new_desk_lease_expires_and_old_can_reclaim` |
| Card session offline | Send fails or times out in ≤ 10 s, is recorded (`SEND_FAILED`, `ACK_TIMEOUT`, `NO_TRANSPORT`), other cards proceed in parallel. After 120 s without two signals the card is `UNCONFIRMED`; the manifest and letter stay for its return. | `test_slow_and_broken_transport_do_not_block` |
| Duplicate notices | Notice id = hash(handoff, card, tool) is claimed under lock before sending; a repeat run or two runners skip it. A duplicate reply counts as one signal. | `DUPLICATE_SKIPPED`; `test_every_card_notified_exactly_once`, `test_ack_needs_second_signal_and_never_blocks` |
| Desk on another tool | Takeover with `states` follows codex > claude > antigravity; a lower tool is refused while a higher one is ACTIVE; all UNKNOWN is refused. | `CROSS_TOOL_NOT_AUTHORITY`, `AUTHORITY_UNKNOWN`; `test_cross_tool_follows_authority_order` |
| Corrupt conductor record | Read raises; never overwritten as if empty. | `DESK_RECORD_CORRUPT`; `test_corrupt_conductor_record_fails_closed` |
| Lock held by a live process | Wait ≤ 10 s, then refuse. | `DESK_LOCK_BUSY` |

Known limits: Claude card sessions are notified through app session messaging, which a shell call cannot do; the CLI leaves
those notices as `NO_TRANSPORT` and the conductor sends them from the manifest (`.coord/handoff/<id>.json`). Dispatch
paths call `check_dispatch` explicitly; wiring it into every existing dispatch entry is a follow-up so U327–U334 files stay untouched.
The ledger is `.coord/desk_ledger.jsonl` until U332's ledger merges.
