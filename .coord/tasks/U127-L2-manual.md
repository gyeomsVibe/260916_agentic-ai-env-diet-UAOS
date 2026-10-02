```contract
work_id: U127-L2
worker: apply
apply_after: U127-L1
goal: card letters to Antigravity resume the card's conversation (cap 70,000, broken window retries fresh once); windows.py records it safely under parallel writers (U127)
inputs:
- .work/u127_apply.md sha256=4bd2782402d2b9a37248241a38e8e239962f951f007ec34a839ecf643b57ae98
allow:
- v7_harness/coord/windows.py
- v7_harness/coord/agy_dispatch.py
- v7_harness/coord/deliver.py
acceptance: python -m unittest tests.test_u127_agy_card_window tests.test_u120_agy_auto_reply tests.test_u114_windows tests.test_u115_card_window_route tests.test_u115_claude_full_session tests.test_u113_desk_truth tests.test_u117_watch_wakes_session tests.test_u118_agy_letter_unread tests.test_u48_deliver tests.test_u48_deliver_d1 tests.test_u49_dispatch_count
forbidden: design changes; edits outside allow; editing or deleting tests; network; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

# Work order: U127 exact apply (after the failed Ollama run U127-L1): card windows record + one Antigravity conversation per card

- Target files: `v7_harness/coord/windows.py`, `v7_harness/coord/agy_dispatch.py`, `v7_harness/coord/deliver.py`

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
def window_for(project: Path, card: str, tool: str) -> str | None:
    return _load(_record_path(project, card)).get("tools", {}).get(tool, {}).get("id")
=======
def window_for(project: Path, card: str, tool: str) -> str | None:
    return _load(_record_path(project, card)).get("tools", {}).get(tool, {}).get("id")


def window_entry(project: Path, card: str, tool: str) -> dict[str, Any]:
    """U127: the card's window entry for one tool ({} when there is none)."""
    return dict(_load(_record_path(project, card)).get("tools", {}).get(tool) or {})


def record_window(project: Path, card: str, tool: str, window_id: str, *, now: float | None = None,
                  **extra: Any) -> dict[str, Any]:
    """U127: write one tool's window for a card and keep the other tools' windows (the U114 record format)."""
    path = _record_path(project, card)
    record = _load(path)
    entry = {"id": window_id, "opened_at": time.time() if now is None else now, **extra}
    old = record.get("tools", {}).get(tool) or {}
    if old.get("id") == window_id and "opened_at" in old:
        entry["opened_at"] = old["opened_at"]
    record = {"card": card, "title": record.get("title") or f"[{card}]", "tools": {**record.get("tools", {}), tool: entry}}
    path.parent.mkdir(parents=True, exist_ok=True)
    # U127-A audit: each writer has its own temp file, so two letters for one card never swap a half-written record.
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        _retry(lambda: tmp.replace(path))
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise
    return entry
>>>>>>> REPLACE

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
=======
def _retry(op: Callable[[], Any]) -> Any:
    """U127: Windows refuses to open or replace a record while a parallel writer swaps it; retry with back-off."""
    for attempt in range(RECORD_TRIES):
        try:
            return op()
        except PermissionError:
            if attempt == RECORD_TRIES - 1:
                raise
            time.sleep(0.01 * (attempt + 1))


def _load(path: Path) -> dict[str, Any]:
    return _retry(lambda: json.loads(path.read_text(encoding="utf-8"))) if path.is_file() else {}
>>>>>>> REPLACE

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
import subprocess
import time
=======
import subprocess
import threading
import time
>>>>>>> REPLACE

===EDIT: v7_harness/coord/windows.py===
<<<<<<< SEARCH
CLAUDE_TIMEOUT_S = 120
=======
CLAUDE_TIMEOUT_S = 120
# U127: a record read or replace retries with 10 ms, 20 ms, ... back-off (about 2 s over 20 tries) while a parallel
# writer swaps it; the parallel test (8 threads x 10 writes) hit PermissionError on the first try without it.
RECORD_TRIES = 20
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
MAX_REPLY_CHARS = 1500
=======
MAX_REPLY_CHARS = 1500
# U127: a resumed turn re-reads the conversation (probe: 53,072 input tokens against about 25,000 fresh, +28,000 a
# turn). Past this the card starts fresh, so the next turn still fits the 100,000 review budget (U127-A audit).
RESUME_MAX_INPUT = 70_000
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
             timeout_s: int = 240, now: float | None = None) -> dict[str, Any]:
=======
             timeout_s: int = 240, now: float | None = None, card: str = "") -> dict[str, Any]:
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
    argv = build_agy_command(AgyRequest(task_id="agy-auto", title=message_id, prompt=prompt, workspace=box, isolation_mode="staging", print_timeout_s=timeout_s))
    done = runner(argv, cwd=str(box), env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True, timeout=timeout_s + 60)
    outcome = parse_agy_result(stdout=done.stdout or b"", stderr=done.stderr or b"", exit_code=done.returncode)
=======
    conversation = None
    if card:  # U127: one Antigravity conversation per card (the U114 window record)
        from v7_harness.coord.windows import window_entry
        entry = window_entry(project, card, "antigravity")
        if entry.get("id") and int(entry.get("last_input_tokens") or 0) < RESUME_MAX_INPUT:
            conversation = str(entry["id"])
    for resume in ([conversation, None] if conversation else [None]):  # U127-A: a broken window retries fresh once
        argv = build_agy_command(AgyRequest(task_id="agy-auto", title=message_id, prompt=prompt, workspace=box, isolation_mode="staging", print_timeout_s=timeout_s, conversation_id=resume))
        done = runner(argv, cwd=str(box), env={**os.environ, "UAOS_WORKER": "1"}, capture_output=True, timeout=timeout_s + 60)
        outcome = parse_agy_result(stdout=done.stdout or b"", stderr=done.stderr or b"", exit_code=done.returncode)
        if outcome.successful:
            break
>>>>>>> REPLACE

===EDIT: v7_harness/coord/agy_dispatch.py===
<<<<<<< SEARCH
    row = {"ts": now, "message_id": message_id, "state": "ANSWERED", "reply_id": sent.message_id, "usage": dict(outcome.usage), "conversation_id": outcome.conversation_id}
=======
    if card and outcome.conversation_id:
        from v7_harness.coord.windows import record_window
        record_window(project, card, "antigravity", str(outcome.conversation_id), now=now,
                      last_input_tokens=int(outcome.usage.get("input_tokens", 0)))
    row = {"ts": now, "message_id": message_id, "state": "ANSWERED", "reply_id": sent.message_id, "usage": dict(outcome.usage), "conversation_id": outcome.conversation_id}
>>>>>>> REPLACE

===EDIT: v7_harness/coord/deliver.py===
<<<<<<< SEARCH
            row = dispatch(desk, message_id=message_id, actor=actor, message=message, runner=runner or subprocess.run)
=======
            row = dispatch(desk, message_id=message_id, actor=actor, message=message, runner=runner or subprocess.run,
                           card=card)
>>>>>>> REPLACE


## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
