```contract
work_id: U115-A1
worker: apply
goal: coord deliver --card routes a letter into the card's window, after Ollama runs U115-L (prompt too large) and U115-L2 (output cap, no file) failed
inputs:
- tests/test_u115_card_window_route.py sha256=24082d7d17162bad6cf10e08c674eea8283b169b627125e1eca0ee3aa60a7874
- v7_harness/coord/deliver.py sha256=7c5dcd609aaf9a18f6a37c8f958f2fb3c420339fef1ff3dc0c8b5e2431311c21
- v7_harness/cli.py sha256=9f90a500b4f3404096f69d10df9e2ca8ed05ff34ea83107d23f9adde182060bb
allow:
- v7_harness/coord/deliver.py
- v7_harness/cli.py
acceptance: python -m unittest tests.test_u115_card_window_route tests.test_u113_desk_truth tests.test_u48_deliver tests.test_u48_deliver_d1 tests.test_cli
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
apply_after: U115-L2
timeout_s: 300
remote_budget_tokens: 0
```

## Instructions for the worker

## Instructions for the worker

Card U115: `coord deliver --card U##` dispatches a letter into the window that `.coord/windows/<card>.json` records
for the target tool. The acceptance test `tests/test_u115_card_window_route.py` is in your inputs. Apply exactly the
edits below, one SEARCH/REPLACE per ===EDIT=== section, keeping indentation. Python 3.12, standard library only.
Do not change anything else.

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
def _requires_wake(message: str) -> bool:
=======
def _digest(actor: str, message: str, card: str = "", window: str | None = None) -> str:
    # U115: a card letter's id also covers its card and window, so the same text routed to another window is a new
    # letter instead of a mailbox collision; without a card the id is exactly today's.
    key = actor + "\0" + message + (f"\0{card}\0{window or ''}" if card else "")
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def _requires_wake(message: str) -> bool:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    allowed_tools: tuple[str, ...] = ("Read",),
) -> DeliverResult:
    try:
        with _claude_turn(project_dir, timeout):
            return _deliver_to_claude_locked(
                message, project_dir=project_dir, runner=runner, timeout=timeout, allowed_tools=allowed_tools
            )
=======
    allowed_tools: tuple[str, ...] = ("Read",),
    session: str = "",
) -> DeliverResult:
    try:
        with _claude_turn(project_dir, timeout):
            return _deliver_to_claude_locked(
                message, project_dir=project_dir, runner=runner, timeout=timeout, allowed_tools=allowed_tools,
                session=session,
            )
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    allowed_tools: tuple[str, ...] = ("Read",),
) -> DeliverResult:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return DeliverResult(False, "claude", "CLI_NOT_FOUND", (), "")

    session_path: Path | None = None
    session_id = ""
    resume = False
    if project_dir:
=======
    allowed_tools: tuple[str, ...] = ("Read",),
    session: str = "",
) -> DeliverResult:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return DeliverResult(False, "claude", "CLI_NOT_FOUND", (), "")

    session_path: Path | None = None
    session_id = ""
    resume = False
    if session:  # U115: a card window is an existing session; the default delivery session file is left alone
        session_id, resume = session, True
    elif project_dir:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
def _payload(actor: str, message: str, digest: str, target: str | None) -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    return {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}
=======
def _payload(actor: str, message: str, digest: str, target: str | None, card: str = "",
             window: str | None = None) -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    body = {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}
    if card:  # U115: only a card letter carries these keys, so a letter without --card keeps today's bytes
        body.update(card=card, window=window)
    return body
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    thread: str = "",
    runner: Any = None,
    pending_owner: str | None = None,
) -> DeliverResult:
=======
    thread: str = "",
    runner: Any = None,
    pending_owner: str | None = None,
    card: str = "",
    window: str = "",
) -> DeliverResult:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    # Stable id makes repeated calls with the same sender and bytes idempotent.
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
=======
    # Stable id makes repeated calls with the same sender and bytes idempotent.
    digest = _digest(actor, message, card, window)
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
        if target == "codex":
            if not thread:
=======
        if target == "codex":
            if window:  # U115: the card's own Codex thread replaces the default thread
                thread = window
            if not thread:
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner)
=======
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner, session=window)
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    thread: str = "",
    runner: Any = None,
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.
=======
    thread: str = "",
    runner: Any = None,
    card: str = "",
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    requested_target = target
=======
    digest = _digest(actor, message)
    message_id = "relay_" + digest[:32]
    project = Path(project).resolve()
    box = _project_mailbox(project)
    desk = box.root.parent.parent
    requested_target = target
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    # U66: the intent marker exists before the inbox letter. A racing watcher waits instead of starting a second
=======
    # U115: a card letter goes into the card's window of the resolved target (U114 record). A LIMITED/ABSENT target
    # was resolved to None above, so it gets no window and stays mailbox-only (U113).
    window = None
    if card:
        from v7_harness.coord.windows import window_for
        window = window_for(desk, card, target or "")  # a bad card id raises before anything is published
        digest = _digest(actor, message, card, window)
        message_id = "relay_" + digest[:32]
    # U66: the intent marker exists before the inbox letter. A racing watcher waits instead of starting a second
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
    box.publish(message_id, _payload(actor, message, digest, requested_target))
=======
    box.publish(message_id, _payload(actor, message, digest, requested_target, card, window))
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
                                 thread=thread, runner=runner, pending_owner=pending_owner)
=======
                                 thread=thread, runner=runner, pending_owner=pending_owner,
                                 card=card, window=window or "")
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    p_coord_deliver.add_argument("--thread", default="")
=======
    p_coord_deliver.add_argument("--thread", default="")
    # U115: a card id routes the letter into that card's window (`.coord/windows/<card>.json`, U114).
    p_coord_deliver.add_argument("--card", default="")
>>>>>>> REPLACE
===END===
===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
                     target=args.target, thread=args.thread)
=======
                     target=args.target, thread=args.thread, card=args.card)
>>>>>>> REPLACE
===END===


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
