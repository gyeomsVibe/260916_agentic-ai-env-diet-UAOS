```contract
work_id: U48-D1
worker: apply
goal: coord deliver records a per-message attempt number; 8 processes delivering 8 letters lose none; un-ACKed letters stay in the inbox with their failure reason.
inputs:
- v7_harness/coord/deliver.py sha256=dfdfed23ef323255196030e78ac89847a52356a14ee14e73cf4628d49ce329a9
allow:
- v7_harness/coord/deliver.py
- tests/test_u48_deliver_d1.py
acceptance: C:/Python314/python.exe -m unittest tests.test_u48_deliver_d1 tests.test_u48_deliver tests.test_u23_mailbox tests.test_u32_mailbox_lossless tests.test_u15_coord_cli
forbidden: design changes; edits outside allow; weakening or deleting existing tests; writing the real home directory; network; model calls; commit/push
stop: two failures with the same cause; input hash mismatch; no output
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Card: PLAN U48-D1. Prepared change .coord/tasks/U48-D1-prep-20260927.md (Claude 17:25) rebased on the applied U48-D0 deliver.py (dfdfed23). Acting judge: Claude under the user's 2026-09-27 order to act for the absent Codex; Codex re-reviews on return.

===FILE: v7_harness/coord/deliver.py===
"""coord deliver: 도구 간 직접 전달기 — 사용자 수동 릴레이 영구 제거.

근본 결함(2026-09-27 사용자 지적):
  사서함(mailbox)에 메시지를 넣은 뒤 사용자에게 "전달해달라"고 부탁하는 것은
  UAOS의 존재 이유를 부정하는 설계 결함이다.

해결:
  수신 도구를 자동 판별하여 직접 전달한다.
  - Codex ACTIVE → `codex queue --thread <session> --message <text>`
  - Claude ACTIVE → `claude -p "<text>" --allowedTools "Read" --output-format json`
  - 둘 다 부재 → 사서함에만 보존(사용자 릴레이 요청 금지)

불변식:
  1. 사용자에게 "전달해달라", "붙여넣기해달라" 등의 릴레이를 요청하지 않는다.
  2. 전달 실패 시 사서함에 보존하고, 실패 사실만 보고한다.
  3. 비밀(secret)은 전달하지 않는다.
"""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from v7_harness.coord.stream import SECRET_PATTERNS
from v7_harness.coord.mailbox import Mailbox


@dataclass(frozen=True)
class DeliverResult:
    delivered: bool
    target: str          # "codex" | "claude" | "mailbox_only"
    reason: str          # SENT | CLI_NOT_FOUND | DELIVERY_FAILED | ABSENT_ALL | ...
    command: tuple[str, ...]
    output: str
    message_id: str = ""
    digest: str = ""
    receipt: str = ""


# ── 비밀 검사 ────────────────────────────────────────────────
def _check_secrets(text: str) -> None:
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            raise ValueError("SECRET_IN_DELIVERY: 비밀이 포함된 메시지는 전달하지 않는다.")


# ── Codex 전달 ───────────────────────────────────────────────
def _deliver_to_codex(
    message: str,
    thread: str,
    *,
    runner: Any = None,
    timeout: int = 60,
) -> DeliverResult:
    codex_bin = shutil.which("codex")
    if not codex_bin:
        return DeliverResult(False, "codex", "CLI_NOT_FOUND", (), "")

    argv = (codex_bin, "queue", "--thread", thread, "--message", message)
    execute = runner or subprocess.run
    try:
        cp = execute(list(argv), capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:{exc}", argv, "")

    if getattr(cp, "returncode", 1) != 0:
        stderr = getattr(cp, "stderr", "") or ""
        return DeliverResult(False, "codex", f"DELIVERY_FAILED:rc={cp.returncode}", argv, stderr[:500])

    return DeliverResult(True, "codex", "SENT", argv, "")


# ── Claude 전달 ──────────────────────────────────────────────
def _deliver_to_claude(
    message: str,
    *,
    project_dir: Path | None = None,
    runner: Any = None,
    timeout: int = 120,
    allowed_tools: tuple[str, ...] = ("Read",),
) -> DeliverResult:
    claude_bin = shutil.which("claude")
    if not claude_bin:
        return DeliverResult(False, "claude", "CLI_NOT_FOUND", (), "")

    argv_list = [
        claude_bin, "-p", message,
        "--output-format", "json",
    ]
    for tool in allowed_tools:
        argv_list.extend(["--allowedTools", tool])

    execute = runner or subprocess.run
    kwargs: dict[str, Any] = dict(capture_output=True, text=True, timeout=timeout)
    if project_dir:
        kwargs["cwd"] = str(project_dir)

    try:
        cp = execute(argv_list, **kwargs)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:{exc}", tuple(argv_list), "")

    rc = getattr(cp, "returncode", 1)
    stdout = getattr(cp, "stdout", "") or ""
    stderr = getattr(cp, "stderr", "") or ""

    if rc != 0:
        return DeliverResult(False, "claude", f"DELIVERY_FAILED:rc={rc}", tuple(argv_list), stderr[:500])

    # Claude CLI JSON 응답에서 result 추출
    result_text = ""
    try:
        data = json.loads(stdout)
        if not isinstance(data, dict) or data.get("is_error") or data.get("type") == "error_max_budget_usd":
            return DeliverResult(False, "claude", "DELIVERY_FAILED:UNUSABLE_RESPONSE", tuple(argv_list), stdout[:500])
        result_text = data.get("result", stdout[:500])
    except (json.JSONDecodeError, AttributeError):
        result_text = stdout[:500]

    return DeliverResult(True, "claude", "SENT", tuple(argv_list), str(result_text)[:2000])


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    """Create one immutable receipt; concurrent attempts get separate names."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


# ── 통합 전달기 ──────────────────────────────────────────────
# Why 300 s: a live dispatcher holds the guard at most for the Claude CLI timeout (120 s) plus receipt writes; 300 s
# gives 2.5x margin so a slow but live dispatcher is never taken for a crashed one.
GUARD_STALE_S = 300.0
# The recovery lock is held only for a stat, a rename and an open (milliseconds); 60 s means its holder crashed.
RECOVER_STALE_S = 60.0
# 50 x 20 ms bounds the claim retry at about 1 s, well above the few ms a concurrent publish holds the file open.
CLAIM_TRIES = 50
CLAIM_SLEEP_S = 0.02


def _payload(actor: str, message: str, digest: str, target: str | None) -> dict[str, Any]:
    """The one published body: the same bytes from every caller, so publish stays idempotent."""
    return {"kind": "HANDOFF", "actor": actor, "message": message, "digest": digest,
            "requested_target": target or "auto"}


def _open_excl(path: Path) -> int | None:
    """Create path exclusively; None if it exists. On Windows a file being unlinked by its holder raises
    PermissionError (delete pending, seen 1 of 50 eight-process runs), so that case is retried, not raised."""
    for _ in range(CLAIM_TRIES):
        try:
            return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return None
        except PermissionError:
            time.sleep(CLAIM_SLEEP_S)
    return None


def _acquire_guard(guard: Path, box: Mailbox, message_id: str, digest: str) -> int | None:
    """Take the per-message dispatch guard, recovering one left by a crashed dispatcher. None means IN_FLIGHT.

    Recovery runs under a second exclusive lock so the age check and the rename cannot interleave with another
    recoverer (otherwise one could rename a guard that another had just re-created). The stale guard is renamed,
    not deleted, and an attempt receipt records the recovery.
    """
    fd = _open_excl(guard)
    if fd is not None:
        return fd
    try:
        if time.time() - guard.stat().st_mtime < GUARD_STALE_S:
            return None
    except OSError:
        pass  # released since (or delete pending on Windows); the exclusive open below decides
    recover = guard.with_name(guard.name + ".recover")
    rfd = _open_excl(recover)
    if rfd is None:
        try:
            if time.time() - recover.stat().st_mtime >= RECOVER_STALE_S:
                os.rename(recover, recover.with_name(f"{recover.name}.stale-{uuid.uuid4().hex}"))
        except OSError:
            pass
        return None  # another recoverer is working now; this caller's message is already published
    os.close(rfd)
    try:
        try:
            age = time.time() - guard.stat().st_mtime
        except OSError:
            age = None
        if age is not None:
            if age < GUARD_STALE_S:
                return None  # a live dispatcher re-created it between our checks
            stale = guard.with_name(f"{guard.name}.stale-{uuid.uuid4().hex}")
            os.rename(guard, stale)
            _write_receipt(box.root / "delivery" / "attempts" / f"{message_id}_{uuid.uuid4().hex}.json",
                           {"message_id": message_id, "digest": digest, "state": "GUARD_RECOVERED",
                            "stale_guard": str(stale), "age_s": round(age, 1), "timestamp_ns": time.time_ns()})
        return _open_excl(guard)
    finally:
        recover.unlink(missing_ok=True)


def _dispatch_count(attempts: Path, message_id: str) -> int:
    """Count earlier dispatch attempts (DISPATCHED or FAILED) for one message; GUARD_RECOVERED receipts do not count.

    Called while holding the claim, so dispatchers of the same id are serialized and the count cannot race. A receipt
    that cannot be read yet (Windows delete-pending) or is not JSON is still counted: it can only be an attempt.
    """
    count = 0
    for path in attempts.glob(f"{message_id}_*.json") if attempts.is_dir() else ():
        try:
            state = json.loads(path.read_text(encoding="utf-8")).get("state")
        except (OSError, ValueError):
            state = None
        if state != "GUARD_RECOVERED":
            count += 1
    return count


def _deliver_unlocked(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
) -> DeliverResult:
    """메시지를 대상 도구에게 직접 전달한다.

    target: "codex" | "claude" | None (자동 판별).
    자동 판별 시 presence를 읽어 ACTIVE인 도구에게 보낸다.
    Codex ACTIVE면 Codex, 아니면 Claude에게 보낸다.

    불변식: 사용자에게 수동 릴레이를 요청하지 않는다.
    """
    _check_secrets(message)
    project = Path(project).resolve()
    box = Mailbox(project / ".coord" / "mailbox")
    # Stable id makes repeated calls with the same sender and bytes idempotent.
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    box.publish(message_id, _payload(actor, message, digest, target))
    ack_file = box.ack_dir / f"{message_id}.json"
    if ack_file.is_file():
        return DeliverResult(True, target or "auto", "ACKED", (), "", message_id, digest, str(ack_file))

    # 자동 판별
    if target is None:
        from v7_harness.coord.presence import read as read_presence
        codex_state = read_presence(project, "codex")["state"]
        if codex_state == "ACTIVE":
            target = "codex"
        else:
            claude_state = read_presence(project, "claude")["state"]
            if claude_state == "ACTIVE":
                target = "claude"
            else:
                # 둘 다 부재: 사서함에만 보존, 사용자 릴레이 요청 금지
                return DeliverResult(False, "mailbox_only", "PUBLISHED", (), "", message_id, digest)

    accepted = box.root / "delivery" / "accepted" / f"{message_id}.json"
    if accepted.is_file():
        return DeliverResult(False, target, "DISPATCHED", (), "", message_id, digest, str(accepted))

    # A same-id caller publishing outside the guard may hold the inbox file open for a moment, and Windows then
    # refuses the claim's rename. Retry briefly instead of reporting IN_FLIGHT with nobody dispatching.
    inbox_file = box.inbox_dir / f"{message_id}.json"
    claim = None
    for _ in range(CLAIM_TRIES):
        claim = box.claim(message_id, "dispatcher")
        if claim is not None or not inbox_file.is_file():
            break
        time.sleep(CLAIM_SLEEP_S)
    if claim is None:
        return DeliverResult(False, target, "IN_FLIGHT", (), "", message_id, digest)

    result: DeliverResult
    try:
        # A contender may have checked before the first sender wrote this
        # receipt, then acquired the claim after the first sender returned it.
        if accepted.is_file():
            return DeliverResult(False, target, "DISPATCHED", (), "", message_id, digest, str(accepted))
        # The claim serializes competing dispatchers. The original is returned
        # to inbox after the attempt; only recipient coord ack may settle it.
        envelope = (f"[UAOS relay id={message_id} digest={digest}]\n{message}\n"
                    f"After processing, run coord ack --id {message_id} for this project. "
                    "The sender keeps this message in the inbox until ACK.")
        if target == "codex":
            if not thread:
                from v7_harness.coord.notify import resolve_thread
                thread = resolve_thread(project)
            result = (_deliver_to_codex(envelope, thread, runner=runner) if thread else
                      DeliverResult(False, "codex", "NO_THREAD", (), ""))
        elif target == "claude":
            prefix = "[안티그래비티에서 온 대화] " if actor.lower() in ("agy", "antigravity") else (
                "[코덱스에서 온 대화] " if actor.lower() == "codex" else "")
            result = _deliver_to_claude(prefix + envelope, project_dir=project, runner=runner)
        else:
            result = DeliverResult(False, str(target), f"UNKNOWN_TARGET:{target}", (), "")

        attempts = box.root / "delivery" / "attempts"
        receipt = {"message_id": message_id, "digest": digest, "target": target,
                   "state": "DISPATCHED" if result.delivered else "FAILED", "reason": result.reason,
                   "attempt": _dispatch_count(attempts, message_id) + 1, "timestamp_ns": time.time_ns()}
        attempt_path = attempts / f"{message_id}_{uuid.uuid4().hex}.json"
        _write_receipt(attempt_path, receipt)
        if result.delivered:
            try:
                _write_receipt(accepted, receipt)
            except FileExistsError:
                pass
            return DeliverResult(False, target, "DISPATCHED", result.command, result.output,
                                 message_id, digest, str(accepted))
        return DeliverResult(False, str(target), result.reason, result.command, result.output,
                             message_id, digest, str(attempt_path))
    finally:
        try:
            box.nack(claim)
        except OSError:
            # A same-id publisher reading the claimed copy can block its unlink on Windows. The bytes are already in
            # the inbox or stay in claimed/ for recover_stale_claims, so nothing is lost; do not fail the dispatch.
            pass


def deliver(
    project: Path,
    *,
    message: str,
    actor: str,
    target: str | None = None,
    thread: str = "",
    runner: Any = None,
) -> DeliverResult:
    """Serialize the complete publish-to-dispatch transaction per message.

    On Windows, another publisher opening a claimed file can prevent NACK
    from unlinking it. This outer guard prevents same-id callers from touching
    mailbox files while the owner is publishing or dispatching.
    """
    _check_secrets(message)
    digest = hashlib.sha256((actor + "\0" + message).encode("utf-8")).hexdigest()
    message_id = "relay_" + digest[:32]
    project = Path(project).resolve()
    box = Mailbox(project / ".coord" / "mailbox")
    # U48-D0 re-review (Claude, 2026-09-27): publish before the guard. A guard left by a crashed dispatcher used to
    # return IN_FLIGHT before any publish, so the message never reached the inbox. Publish is idempotent by id+bytes.
    box.publish(message_id, _payload(actor, message, digest, target))
    guard = box.root / "delivery" / "guards" / f"{message_id}.lock"
    guard.parent.mkdir(parents=True, exist_ok=True)
    fd = _acquire_guard(guard, box, message_id, digest)
    if fd is None:
        return DeliverResult(False, target or "mailbox_only", "IN_FLIGHT", (), "", message_id, digest)
    with os.fdopen(fd, "wb") as handle:
        handle.write(json.dumps({"message_id": message_id, "digest": digest, "actor": actor,
                                 "message": message, "target": target}, ensure_ascii=False).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        return _deliver_unlocked(project, message=message, actor=actor, target=target,
                                 thread=thread, runner=runner)
    finally:
        guard.unlink(missing_ok=True)
===FILE: tests/test_u48_deliver_d1.py===
"""U48-D1: coord deliver keeps un-ACKed and failed letters, records the retry count and failure reason, loses none.

Gate (PLAN U48-D1): 8 parallel processes delivering 8 different letters lose 0; a letter without ACK stays in the
inbox; the failure reason is preserved; each dispatch attempt records its number. Separate from test_u48_deliver.py
so the D0 hash-pinned test file stays unchanged.
"""

from __future__ import annotations

import json
import multiprocessing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v7_harness.coord.deliver import deliver
from v7_harness.coord.mailbox import Mailbox


class _Runner:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.calls = 0
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

    def __call__(self, argv, **kwargs):
        self.calls += 1
        return SimpleNamespace(returncode=self.returncode, stdout=self.stdout, stderr=self.stderr)


def _deliver_distinct(project_text: str, index: int, results) -> None:
    runner = _Runner(0, json.dumps({"result": "accepted", "type": "result"}))
    with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
        outcome = deliver(Path(project_text), message=f"U48-D1 letter {index}", actor="codex", target="claude",
                          runner=runner)
    results.put({"id": outcome.message_id, "reason": outcome.reason, "calls": runner.calls})


def _receipts(project: Path, message_id: str) -> list[dict]:
    attempts = project / ".coord" / "mailbox" / "delivery" / "attempts"
    found = [json.loads(p.read_text(encoding="utf-8")) for p in attempts.glob(f"{message_id}_*.json")]
    return sorted(found, key=lambda receipt: receipt["timestamp_ns"])


class TestD1Retention(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        (self.project / ".coord" / "mailbox").mkdir(parents=True)

    def test_retry_count_and_failure_reason_are_recorded(self):
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            first = deliver(self.project, message="d1 retry", actor="codex", target="claude",
                            runner=_Runner(1, stderr="connection refused"))
            second = deliver(self.project, message="d1 retry", actor="codex", target="claude",
                             runner=_Runner(1, stderr="connection refused"))
            third = deliver(self.project, message="d1 retry", actor="codex", target="claude",
                            runner=_Runner(0, json.dumps({"result": "ok"})))
        receipts = _receipts(self.project, first.message_id)
        self.assertEqual([1, 2, 3], [receipt["attempt"] for receipt in receipts])
        self.assertEqual(["FAILED", "FAILED", "DISPATCHED"], [receipt["state"] for receipt in receipts])
        self.assertTrue(all("DELIVERY_FAILED" in receipt["reason"] for receipt in receipts[:2]), receipts)
        self.assertEqual("DISPATCHED", third.reason)
        self.assertEqual(first.message_id, second.message_id)
        inbox = self.project / ".coord" / "mailbox" / "inbox" / f"{first.message_id}.json"
        self.assertTrue(inbox.is_file())  # dispatched but not ACKed: the letter stays in the inbox

    def test_guard_recovery_receipt_is_not_counted_as_an_attempt(self):
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            first = deliver(self.project, message="d1 guard", actor="codex", target="claude",
                            runner=_Runner(1, stderr="refused"))
        attempts = self.project / ".coord" / "mailbox" / "delivery" / "attempts"
        (attempts / f"{first.message_id}_recovered.json").write_text(
            json.dumps({"message_id": first.message_id, "state": "GUARD_RECOVERED", "timestamp_ns": 0}),
            encoding="utf-8")
        with patch("v7_harness.coord.deliver.shutil.which", return_value="claude"):
            deliver(self.project, message="d1 guard", actor="codex", target="claude", runner=_Runner(1, stderr="x"))
        counted = [r["attempt"] for r in _receipts(self.project, first.message_id) if r["state"] != "GUARD_RECOVERED"]
        self.assertEqual([1, 2], counted)

    def test_eight_processes_eight_letters_lose_none(self):
        ctx = multiprocessing.get_context("spawn")
        results = ctx.Queue()
        workers = [ctx.Process(target=_deliver_distinct, args=(str(self.project), i, results)) for i in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(30)
            self.assertEqual(0, worker.exitcode)
        outcomes = [results.get(timeout=5) for _ in workers]
        ids = {outcome["id"] for outcome in outcomes}
        self.assertEqual(8, len(ids))
        self.assertEqual(["DISPATCHED"] * 8, [outcome["reason"] for outcome in outcomes], outcomes)
        self.assertEqual(8, sum(outcome["calls"] for outcome in outcomes))
        box = Mailbox(self.project / ".coord" / "mailbox")
        self.assertEqual(ids, {path.stem for path in box.inbox_dir.glob("*.json")})  # none lost, none ACKed away
        self.assertEqual([], list(box.ack_dir.glob("*.json")) if box.ack_dir.is_dir() else [])
        for message_id in ids:
            self.assertEqual([1], [r["attempt"] for r in _receipts(self.project, message_id)])


if __name__ == "__main__":
    unittest.main()
===END===

## Output

- Reply with ===FILE blocks only. No explanations. Do not claim success; the acceptance command decides.
