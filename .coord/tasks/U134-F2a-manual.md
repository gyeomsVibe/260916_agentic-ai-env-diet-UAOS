```contract
work_id: U134-F2a
worker: apply
goal: per-letter OS-locked queue claim with scoped crash recovery in deliver.dispatch_queued (Codex relay_4e5ed6c2)
inputs:
- v7_harness/coord/deliver.py sha256=6cceeb12322f1718b20afed256685518433e71cbbfc53303e806d1784ed7b5e0
- tests/test_u134_f2_queue_claim.py sha256=891b0b502a02193270e143a61f7774a56fb5dbc2b88cc7ae545e63b0a14286e6
- tests/test_u134_dispatch_on_active.py sha256=f0f27169af71185282a66d447b8633b77c1d5878ffa2007f19e326b085ec697d
allow:
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u134_f2_queue_claim tests.test_u134_dispatch_on_active tests.test_u134_thread_fallback tests.test_u134_judge_counterexamples tests.test_u134_f1b_cwd tests.test_u113_desk_truth tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread tests.test_u120_agy_auto_reply tests.test_u127_agy_card_window tests.test_u48_deliver tests.test_u48_deliver_d1 tests.test_u49_dispatch_count tests.test_u49_guard_release_race tests.test_u49_mailbox_locked_ack
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
apply_after: U134-F2
remote_budget_tokens: 0
judge: codex
timeout_s: 1800
```

## Work Order U134-F2a (judge salvage of the U134-F2 agy candidate; acting conductor Claude, Codex LIMITED)

Receipt: U134-F2 agy run FAILED EXTERNAL_WRITE: the worker wrote main deliver.py (b499c67e) instead of its stage.
That candidate passed the fixed acceptance (17 modules OK in .work/wt_eval). The judge rejected it for two
unrequested deletions (extra orphan .taking files, and extra or all claims of the message). This EDIT keeps the
candidate's queue section byte for byte, except that those deletions are removed. Instructions for F2 are unchanged.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
def queued_letters(project: Path, tool: str) -> list[Path]:
    """U134-B: letters waiting for `tool`, oldest name first; a missing queue is empty (the hook's cheap check)."""
    folder = _queue_dir(project, tool)
    return sorted(folder.glob("relay_*.json")) if folder.is_dir() else []


def dispatch_queued(project: Path, tool: str, *, runner: Any = None) -> list[dict[str, str]]:
    """U134-B: send each letter queued for `tool` once.

    A heartbeat takes a letter by renaming it (atomic; a racing heartbeat gets OSError and skips it), so two
    heartbeats in parallel send it once. The send reuses `_deliver_unlocked` with the queued message id (an empty
    window digests like the None the queue was written with), so the accepted and ack receipts keep it idempotent.
    An unsettled send goes back to the queue; after the last try it is parked as `<message_id>.failed`.
    """
    # Reasons that end a queued letter's trip: sent, already acknowledged, or held for the interactive session.
    settled = ("DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY")
    # One try per hook kind (SessionStart, UserPromptSubmit, PostToolUse) before parking: a letter that keeps failing
    # (no thread, CLI error) must not fire `codex queue` on every heartbeat forever.
    tries = 3
    project = Path(project).resolve()
    desk = _project_mailbox(project).root.parent.parent
    sent: list[dict[str, str]] = []
    for marker in queued_letters(project, tool):
        taking = marker.with_name(f"{marker.stem}.{uuid.uuid4().hex}.taking")
        try:
            os.rename(marker, taking)
        except OSError:
            continue
        try:
            letter = json.loads(taking.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            os.replace(taking, marker.with_suffix(".failed"))
            continue
        card = str(letter.get("card") or "")
        thread = str(letter.get("thread") or "")
        if card:
            from v7_harness.coord.windows import window_for
            thread = window_for(desk, card, tool) or thread  # U115: the card's own window of the now-ACTIVE tool
        result = _deliver_unlocked(project, message=str(letter.get("message") or ""),
                                   actor=str(letter.get("actor") or ""), target=tool, thread=thread,
                                   runner=runner, card=card, window="")
        sent.append({"message_id": str(letter.get("message_id") or marker.stem), "reason": result.reason})
        if result.reason in settled:
            taking.unlink(missing_ok=True)
            continue
        letter["attempts"] = int(letter.get("attempts") or 0) + 1
        taking.write_text(json.dumps(letter, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        os.replace(taking, marker if letter["attempts"] < tries else marker.with_suffix(".failed"))
    return sent

=======
def _park_failed(source_file: Path, message_id: str, queue_dir: Path) -> Path:
    """U134-F2: park a corrupt or exceeded-retries letter as .failed without overwriting existing evidence."""
    target = queue_dir / f"{message_id}.failed"
    # Decision: never overwrite existing .failed evidence; use unique hex suffix if default name is taken
    if target.exists():
        target = queue_dir / f"{message_id}.{uuid.uuid4().hex}.failed"
    os.replace(source_file, target)
    return target


def queued_letters(project: Path, tool: str) -> list[Path]:
    """U134-B: letters waiting for `tool`, oldest name first; a missing queue is empty (the hook's cheap check).
    U134-F2: collect letter ids from both <id>.json markers and orphan <id>.<hex>.taking files, each id once."""
    folder = _queue_dir(project, tool)
    if not folder.is_dir():
        return []
    ids: set[str] = set()
    for p in folder.iterdir():
        if not p.is_file():
            continue
        if p.name.endswith(".json"):
            ids.add(p.stem)
        elif p.name.endswith(".taking"):
            # Decision: <id>.<hex>.taking -> extract <id> (first segment before the dot)
            ids.add(p.name.split(".")[0])
    # Decision: build list of marker paths so each id is processed once, in name order
    return [folder / f"{letter_id}.json" for letter_id in sorted(ids)]


def dispatch_queued(project: Path, tool: str, *, runner: Any = None) -> list[dict[str, str]]:
    """U134-B/F2: send each letter queued for `tool` once under a per-letter OS lock with scoped crash recovery.

    Documented risk: a crash after the remote send but before the accepted receipt can duplicate one send.

    A heartbeat takes each letter under a per-letter non-blocking OS lock (<id>.lock), held across the rename,
    send, and settle. A live owner keeps the lock even if paused, preventing stolen letters. If an orphan .taking
    exists under the lock, the previous owner is dead, so it is recovered along with any claimed mailbox entry.
    An unsettled send goes back to the queue without incrementing attempts if IN_FLIGHT, or increments attempts
    and parks as .failed after 3 tries.
    """
    # Reasons that end a queued letter's trip: sent, already acknowledged, or held for the interactive session.
    settled = ("DISPATCHED", "ACKED", "QUEUED_INTERACTIVE", "QUEUED_ACK_ONLY")
    # One try per hook kind (SessionStart, UserPromptSubmit, PostToolUse) before parking: a letter that keeps failing
    # (no thread, CLI error) must not fire `codex queue` on every heartbeat forever.
    # 3: max retries per hook kind before parking to failed
    tries = 3
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    folder = _queue_dir(project, tool)
    sent: list[dict[str, str]] = []

    for marker in queued_letters(project, tool):
        message_id = marker.stem
        lock_file = folder / f"{message_id}.lock"
        # Decision: per-letter OS lock. Open <message_id>.lock and take a non-blocking lock.
        # Decision: never unlink .lock file; the OS automatically releases locks on process exit/termination.
        try:
            fd = os.open(lock_file, os.O_CREAT | os.O_RDWR)
        except OSError:
            continue

        locked = False
        try:
            if not _try_lock(fd):
                # Decision: busy lock means a live owner has it (even if paused); skip to next letter.
                continue
            locked = True

            # Decision: letter claim and orphan recovery under the per-letter lock.
            taking_files = sorted(folder.glob(f"{message_id}.*.taking"))
            is_orphan = False
            taking: Path
            if taking_files:
                # Decision: holding the lock while an orphan .taking exists proves its owner is dead. Adopt it.
                is_orphan = True
                # Judge fix (U134-F2a): adopt the oldest orphan only and delete nothing; the contract forbids deletion.
                taking = taking_files[0]
            elif marker.is_file():
                taking = marker.with_name(f"{message_id}.{uuid.uuid4().hex}.taking")
                try:
                    os.rename(marker, taking)
                except OSError:
                    continue
            else:
                # Neither taking nor marker exists; already settled or removed
                continue

            if is_orphan:
                # Decision: scoped mailbox recovery for THIS message id: if claimed and inbox is absent, move back to inbox.
                # Do not call box.recover_stale_claims or touch any other message id.
                claims = sorted(box.claimed_dir.glob(f"{message_id}_*.json"))
                if claims:
                    inbox_file = box.inbox_dir / f"{message_id}.json"
                    # Judge fix (U134-F2a): only move one claim back, never delete a claim (another holder may own it).
                    if not inbox_file.is_file():
                        os.replace(claims[0], inbox_file)
                # Decision: write an attempt receipt with state QUEUE_CLAIM_RECOVERED under delivery/attempts/
                attempts_dir = box.root / "delivery" / "attempts"
                attempts_dir.mkdir(parents=True, exist_ok=True)
                _write_receipt(
                    attempts_dir / f"{message_id}_{uuid.uuid4().hex}.json",
                    {
                        "message_id": message_id,
                        "state": "QUEUE_CLAIM_RECOVERED",
                        "timestamp_ns": time.time_ns(),
                    },
                )

            # Decision: read letter from taking file; handle corrupt markers without overwriting evidence
            try:
                letter = json.loads(taking.read_text(encoding="utf-8"))
                if not isinstance(letter, dict):
                    raise ValueError("letter is not a json object")
            except (OSError, ValueError):
                _park_failed(taking, message_id, folder)
                continue

            card = str(letter.get("card") or "")
            thread = str(letter.get("thread") or "")
            if card:
                from v7_harness.coord.windows import window_for
                thread = window_for(desk, card, tool) or thread  # U115: card's own window of the now-ACTIVE tool

            message = str(letter.get("message") or "")
            actor = str(letter.get("actor") or "")
            digest = _digest(actor, message, card, "")

            # Decision: acquire per-message dispatch guard following U83 age rule (_acquire_guard, GUARD_STALE_S)
            guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
            guard.parent.mkdir(parents=True, exist_ok=True)
            guard_fd = _acquire_guard(guard, box, message_id, digest)
            if guard_fd is None:
                # Decision: guard is still young held by another active/recent dispatcher -> IN_FLIGHT
                result = DeliverResult(False, tool, "IN_FLIGHT", (), "", message_id, digest)
            else:
                guard_owner = uuid.uuid4().hex
                with os.fdopen(guard_fd, "wb") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "message_id": message_id,
                                "digest": digest,
                                "actor": actor,
                                "message": message,
                                "target": tool,
                                "owner": guard_owner,
                            },
                            ensure_ascii=False,
                        ).encode("utf-8")
                    )
                    handle.flush()
                    os.fsync(handle.fileno())

                pending_owner = None
                if tool == "claude" and _requires_wake(message):
                    pending = box.root / "delivery" / "pending" / f"{message_id}.json"
                    pending.parent.mkdir(parents=True, exist_ok=True)
                    pending.write_text(
                        json.dumps(
                            {
                                "message_id": message_id,
                                "target": "claude",
                                "state": "PENDING",
                                "owner": guard_owner,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        encoding="utf-8",
                    )
                    pending_owner = guard_owner

                try:
                    result = _deliver_unlocked(
                        project,
                        message=message,
                        actor=actor,
                        target=tool,
                        thread=thread,
                        runner=runner,
                        pending_owner=pending_owner,
                        card=card,
                        window="",
                    )
                finally:
                    _release_guard(guard, guard_owner)

            sent.append({"message_id": str(letter.get("message_id") or message_id), "reason": result.reason})

            # Decision: settle logic
            if result.reason in settled:
                taking.unlink(missing_ok=True)
                continue

            if result.reason == "IN_FLIGHT":
                # Decision: guard is still young; return letter to <message_id>.json without adding an attempt
                os.replace(taking, folder / f"{message_id}.json")
                continue

            # Decision: any other unsettled result adds one attempt and parks after tries (3) attempts
            letter["attempts"] = int(letter.get("attempts") or 0) + 1
            taking.write_text(json.dumps(letter, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            if letter["attempts"] < tries:
                os.replace(taking, folder / f"{message_id}.json")
            else:
                _park_failed(taking, message_id, folder)
        finally:
            if locked:
                try:
                    _unlock(fd)
                except OSError:
                    pass
            try:
                os.close(fd)
            except OSError:
                pass

    return sent

>>>>>>> REPLACE
