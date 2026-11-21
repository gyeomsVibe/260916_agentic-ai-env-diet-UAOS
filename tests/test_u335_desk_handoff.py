"""U335 fixed acceptance: automatic user-desk handoff. No network, no paid calls."""

from __future__ import annotations

import json
import subprocess
import threading
import sys
import textwrap
import time
import uuid
from pathlib import Path

import pytest

from v7_harness.coord import desk_handoff as dh

OLD = "11111111-1111-4111-8111-111111111111"
NEW = "22222222-2222-4222-8222-222222222222"
NEW2 = "33333333-3333-4333-8333-333333333333"


def _register(project: Path, tool: str, thread: str) -> None:
    path = project / ".coord" / "presence" / f"user_desk_{tool}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"thread": thread, "at": time.time(), "source": "test"}), encoding="utf-8")


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    coord = tmp_path / ".coord"
    (coord / "cards").mkdir(parents=True)
    (coord / "PLAN.md").write_text("- U327 model router\n- U329 council\n", encoding="utf-8")
    (coord / "cards" / "U327.json").write_text(json.dumps({"card": "U327", "title": "model router"}), encoding="utf-8")
    wins = {"cards": {
        "U327": {"card": "U327", "title": "[U327] router", "tools": {
            "claude": {"window_id": "w-claude-327", "state": "ACTIVE", "native_id": "local_aaa"},
            "codex": {"window_id": "w-codex-327", "state": "ACTIVE"}}},
        "U329": {"card": "U329", "title": "[U329] council", "tools": {
            "claude": {"window_id": "w-claude-329", "state": "ACTIVE"},
            "antigravity": {"window_id": "w-agy-329", "state": "CLOSED"}}}}}
    (coord / "windows.json").write_text(json.dumps(wins), encoding="utf-8")
    return tmp_path


class Recorder:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []

    def session(self, s: dict, text: str) -> bool:
        self.sent.append(("session", s["card"], s["tool"]))
        return True

    def letter(self, s: dict, text: str) -> bool:
        self.sent.append(("letter", s["card"], s["tool"]))
        return True


def test_detect_manifest_single_conductor(project: Path) -> None:
    _register(project, "claude", OLD)
    first = dh.run_handoff(project, "claude")
    assert first["ok"] and first["epoch"] == 1 and first["from_desk"] == ""
    assert dh.detect_new_desk(project, "claude")["due"] is False  # same desk again: nothing to do
    _register(project, "claude", NEW)
    found = dh.detect_new_desk(project, "claude")
    assert found["due"] and found["old_desk"] == OLD and found["new_desk"] == NEW
    won = dh.run_handoff(project, "claude")
    assert won["ok"] and won["epoch"] == 2 and won["from_desk"] == OLD
    manifest = json.loads(Path(won["manifest"]).read_text(encoding="utf-8"))
    assert [c["card"] for c in manifest["cards"]] == ["U327", "U329"]
    tools = {(c["card"], s["tool"]) for c in manifest["cards"] for s in c["sessions"]}
    assert tools == {("U327", "claude"), ("U327", "codex"), ("U329", "claude")}  # CLOSED agy window excluded
    assert dh.conductor(project, "claude")["desk"] == NEW
    ledger = [json.loads(x) for x in dh.ledger_path(project).read_text(encoding="utf-8").splitlines()]
    assert [r["event"] for r in ledger if r["event"] == "TAKEOVER"] == ["TAKEOVER", "TAKEOVER"]


def test_manifest_is_deterministic(project: Path) -> None:
    a = dh.build_manifest(project, tool="claude", old_desk=OLD, new_desk=NEW, epoch=2, now=1.0)
    b = dh.build_manifest(project, tool="claude", old_desk=OLD, new_desk=NEW, epoch=2, now=1.0)
    assert a == b


def test_old_desk_dispatch_refused(project: Path) -> None:
    assert dh.check_dispatch(project, "claude", OLD)["ok"]  # no handoff recorded yet
    _register(project, "claude", OLD)
    dh.run_handoff(project, "claude")
    assert dh.check_dispatch(project, "claude", OLD)["ok"]
    _register(project, "claude", NEW)
    dh.run_handoff(project, "claude")
    refused = dh.check_dispatch(project, "claude", OLD)
    assert refused == {"ok": False, "reason": "DESK_SUPERSEDED", "conductor": NEW, "epoch": 2}
    assert dh.check_dispatch(project, "claude", NEW)["ok"]
    assert dh.renew_lease(project, "claude", OLD, 1)["reason"] == "DESK_SUPERSEDED"


def test_every_card_notified_exactly_once(project: Path) -> None:
    _register(project, "claude", NEW)
    rec = Recorder()
    out = dh.run_handoff(project, "claude", send_session=rec.session, send_letter=rec.letter)
    assert sorted(rec.sent) == [("letter", "U327", "codex"), ("session", "U327", "claude"), ("session", "U329", "claude")]
    assert set(out["notified"].values()) == {"SENT"}
    again = dh.notify_all(project, out["handoff_id"], send_session=rec.session, send_letter=rec.letter)
    assert set(again["results"].values()) == {"DUPLICATE_SKIPPED"}
    assert len(rec.sent) == 3  # duplicate notices never re-sent


def test_ack_needs_second_signal_and_never_blocks(project: Path) -> None:
    _register(project, "claude", NEW)
    rec = Recorder()
    out = dh.run_handoff(project, "claude", send_session=rec.session, send_letter=rec.letter)
    hid = out["handoff_id"]
    assert dh.record_ack(project, hid, "U327", "claude", "reply")["acked"] is False
    assert dh.record_ack(project, hid, "U327", "claude", "reply")["acked"] is False  # duplicate reply is not a 2nd signal
    assert dh.record_ack(project, hid, "U327", "claude", "window_active")["acked"] is True
    now = time.time()
    states = dh.ack_summary(project, hid, now=now)["states"]
    assert states["U327:claude"] == "ACKED" and states["U329:claude"] == "PENDING"
    late = dh.ack_summary(project, hid, now=now + dh.REPLY_DEADLINE_S + 1)["states"]
    assert late["U329:claude"] == "UNCONFIRMED"


def test_slow_and_broken_transport_do_not_block(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dh, "ACK_DEADLINE_S", 0.2)
    _register(project, "claude", NEW)

    release = threading.Event()

    def slow(s: dict, text: str) -> bool:
        release.wait(timeout=5)  # released at the end, so no thread outlives the test
        return True

    def broken(s: dict, text: str) -> bool:
        raise RuntimeError("boom")

    started = time.monotonic()
    out = dh.run_handoff(project, "claude", send_session=slow, send_letter=broken)
    assert time.monotonic() - started < 1.5
    release.set()
    assert out["notified"]["U327:claude"] == "ACK_TIMEOUT"
    assert out["notified"]["U329:claude"] == "ACK_TIMEOUT"  # every card was attempted, no early loop abort
    assert out["notified"]["U327:codex"] == "SEND_ERROR_RuntimeError"


def test_concurrent_double_takeover_one_winner(project: Path) -> None:
    """Two real processes race with the same observed epoch; exactly one wins."""
    script = textwrap.dedent("""
        import sys, json
        from pathlib import Path
        from v7_harness.coord import desk_handoff as dh
        project, desk = Path(sys.argv[1]), sys.argv[2]
        print(json.dumps(dh.takeover(project, "claude", desk, expected_epoch=0)))
    """)
    repo = Path(__file__).resolve().parents[1]
    procs = [subprocess.Popen([sys.executable, "-c", script, str(project), desk], cwd=repo, stdout=subprocess.PIPE,
                              stdin=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True) for desk in (NEW, NEW2) for _ in range(3)]
    outs = [(p.communicate(timeout=60)[0], p) for p in procs]
    assert all(p.returncode == 0 for _, p in outs)
    results = [json.loads(out.strip().splitlines()[-1]) for out, _ in outs]
    winners = [r for r in results if r["ok"]]
    assert len(winners) == 1, results
    assert all(r["reason"] == "DESK_TAKEOVER_LOST" for r in results if not r["ok"])
    cond = dh.conductor(project, "claude")
    assert cond["epoch"] == 1 and cond["desk"] in (NEW, NEW2)


def test_concurrent_threads_one_winner(project: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda i: dh.takeover(project, "claude", f"{uuid.uuid4()}", expected_epoch=0), range(8)))
    assert sum(r["ok"] for r in results) == 1
    assert dh.conductor(project, "claude")["epoch"] == 1


def test_dead_new_desk_lease_expires_and_old_can_reclaim(project: Path) -> None:
    t0 = 1000.0
    dh.takeover(project, "claude", OLD, now=t0)
    dh.takeover(project, "claude", NEW, expected_epoch=1, now=t0 + 1)
    later = t0 + 1 + dh.LEASE_S + 1
    assert dh.check_dispatch(project, "claude", NEW, now=later)["reason"] == "DESK_LEASE_EXPIRED"
    assert dh.check_dispatch(project, "claude", OLD, now=later)["reason"] == "DESK_SUPERSEDED"
    back = dh.takeover(project, "claude", OLD, expected_epoch=2, now=later)
    assert back["ok"] and back["epoch"] == 3


def test_cross_tool_follows_authority_order(project: Path) -> None:
    states = {"codex": "ACTIVE", "claude": "ACTIVE", "antigravity": "ACTIVE"}
    assert dh.authority(states) == "codex"
    assert dh.takeover(project, "claude", NEW, states=states)["reason"] == "CROSS_TOOL_NOT_AUTHORITY"
    assert dh.takeover(project, "codex", NEW, states=states)["ok"]
    unknown = {"codex": "UNKNOWN", "claude": "UNKNOWN", "antigravity": "UNKNOWN"}
    assert dh.takeover(project, "claude", NEW, states=unknown)["reason"] == "AUTHORITY_UNKNOWN"
    away = {"codex": "LIMITED", "claude": "ABSENT", "antigravity": "ACTIVE"}
    assert dh.takeover(project, "antigravity", NEW2, states=away)["ok"]


def test_corrupt_conductor_record_fails_closed(project: Path) -> None:
    path = project / ".coord" / "presence" / "desk_conductor_claude.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        dh.conductor(project, "claude")


def test_audit_revise_fixes(project: Path) -> None:
    # (1) an UNKNOWN higher tool blocks a lower tool: fail closed
    assert dh.authority({"codex": "UNKNOWN", "claude": "ACTIVE", "antigravity": "ABSENT"}) == ""
    assert dh.authority({"codex": "LIMITED", "claude": "ACTIVE"}) == "claude"
    assert dh.takeover(project, "claude", NEW, states={"codex": "UNKNOWN", "claude": "ACTIVE"})["reason"] == "AUTHORITY_UNKNOWN"
    # (2) the send cap is covered by test_slow_and_broken_transport_do_not_block
    # (3) no transport claims nothing, so a later run with a transport still sends
    _register(project, "claude", NEW)
    first = dh.run_handoff(project, "claude")
    assert set(first["notified"].values()) == {"NO_TRANSPORT"}
    rec = Recorder()
    later = dh.notify_all(project, first["handoff_id"], send_session=rec.session, send_letter=rec.letter)
    assert set(later["results"].values()) == {"SENT"} and len(rec.sent) == 3
    # (4) blank or case/space variants of one signal never make two signals
    hid = first["handoff_id"]
    assert dh.record_ack(project, hid, "U327", "claude", "")["reason"] == "SIGNAL_INVALID"
    assert dh.record_ack(project, hid, "U327", "claude", "reply")["acked"] is False
    assert dh.record_ack(project, hid, "U327", "claude", " Reply ")["acked"] is False
    # renew_lease with epoch 0 is refused
    assert dh.renew_lease(project, "claude", NEW, 0)["ok"] is False


def test_stranded_sending_row_is_reclaimed(project: Path) -> None:
    _register(project, "claude", NEW)
    out = dh.run_handoff(project, "claude")
    hid = out["handoff_id"]
    nid = dh.notice_id(hid, "U327", "claude")
    # a crashed runner left a SENDING claim 5 minutes ago; a fresh claim (just now) must stay protected
    dh._write_json(dh._acks_path(project, hid), {
        nid: {"card": "U327", "tool": "claude", "window_id": "w", "status": "SENDING", "signals": [], "sent_at": time.time() - (2 * dh.ACK_DEADLINE_S + 2)},
        dh.notice_id(hid, "U329", "claude"): {"card": "U329", "tool": "claude", "window_id": "w", "status": "SENDING",
                                              "signals": [], "sent_at": time.time() - dh.ACK_DEADLINE_S}})  # live send, inside the cutoff
    rec = Recorder()
    res = dh.notify_all(project, hid, send_session=rec.session, send_letter=rec.letter)["results"]
    assert res["U327:claude"] == "SENT" and res["U329:claude"] == "DUPLICATE_SKIPPED"
    assert ("session", "U327", "claude") in rec.sent and ("session", "U329", "claude") not in rec.sent
    again = dh.notify_all(project, hid, send_session=rec.session, send_letter=rec.letter)["results"]
    assert again["U327:claude"] == "DUPLICATE_SKIPPED"  # the reclaimed row persisted as SENT


def test_injected_clock_does_not_reclaim_live_claim_and_busy_ledger_is_tolerated(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _register(project, "claude", NEW)
    hid = dh.run_handoff(project, "claude")["handoff_id"]
    nid = dh.notice_id(hid, "U327", "claude")
    base = 1000.0  # injected clock far from wall time: a live claim stamped with it must not look 'old'
    dh._write_json(dh._acks_path(project, hid), {nid: {"card": "U327", "tool": "claude", "window_id": "w",
                                                       "status": "SENDING", "signals": [], "sent_at": base}})
    rec = Recorder()
    res = dh.notify_all(project, hid, send_session=rec.session, send_letter=rec.letter, now=base + 1)["results"]
    assert res["U327:claude"] == "DUPLICATE_SKIPPED" and ("session", "U327", "claude") not in rec.sent
    res = dh.notify_all(project, hid, send_session=rec.session, send_letter=rec.letter,
                        now=base + 2 * dh.ACK_DEADLINE_S + 1)["results"]
    assert res["U327:claude"] == "SENT"

    def busy(*a, **k):
        raise TimeoutError("DESK_LOCK_BUSY")

    monkeypatch.setattr(dh, "append_ledger", busy)
    out = dh.notify_all(project, hid, send_session=rec.session, send_letter=rec.letter)
    assert out["ok"] is True and out["ledger_ok"] is False


def _cli(project: Path, *args: str) -> tuple[int, dict]:
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "desk-handoff", "--project", str(project), *args],
                          cwd=repo, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8", timeout=60)
    return proc.returncode, json.loads(proc.stdout)


def test_cli_detect_run_check_ack(project: Path) -> None:
    _register(project, "claude", NEW)
    code, out = _cli(project, "--tool", "claude", "--action", "detect")
    assert code == 0 and out["due"] is True and out["new_desk"] == NEW
    code, out = _cli(project, "--tool", "claude", "--action", "run")
    assert code == 0 and out["reason"] == "TAKEN_OVER" and out["epoch"] == 1
    assert out["notified"] and set(out["notified"].values()) <= {"NO_TRANSPORT", "SENT", "SEND_FAILED"}
    code, out = _cli(project, "--tool", "claude", "--action", "check", "--desk", OLD)
    assert code == 1 and out["reason"] == "DESK_SUPERSEDED"
    code, out = _cli(project, "--tool", "claude", "--action", "check", "--desk", NEW)
    assert code == 0 and out["reason"] == "CONDUCTOR"
    code, out = _cli(project, "--tool", "claude", "--action", "status")
    assert code == 0 and out["conductor"]["desk"] == NEW
    code, out = _cli(project, "--tool", "claude", "--action", "run")  # same desk again: nothing to do
    assert code == 0 and out["reason"] == "SAME_DESK"


def test_cli_status_reports_corrupt_record_instead_of_crashing(project: Path) -> None:
    path = project / ".coord" / "presence" / "desk_conductor_claude.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}", encoding="utf-8")  # an existing but empty record is corruption, not 'no handoff'
    code, out = _cli(project, "--tool", "claude", "--action", "status")
    assert code == 1 and out["reason"] == "DESK_RECORD_CORRUPT"


def test_cli_letter_transport_counts_fresh_dispatch_as_sent(project: Path, monkeypatch: pytest.MonkeyPatch,
                                                            capsys: pytest.CaptureFixture[str]) -> None:
    import argparse
    from types import SimpleNamespace

    from v7_harness import cli
    from v7_harness.coord import deliver as deliver_mod

    _register(project, "claude", NEW)
    reasons = iter(["DISPATCHED", "PUBLISHED", "QUEUED_WAKE", "DELIVERY_FAILED:rc=1"] * 4)
    monkeypatch.setattr(deliver_mod, "deliver", lambda *a, **k: SimpleNamespace(delivered=False, reason=next(reasons)))
    args = argparse.Namespace(project=str(project), action="run", tool="claude", desk=None, handoff_id=None, card=None, signal=None)
    cli.cmd_coord_desk_handoff(args)
    out = json.loads(capsys.readouterr().out)
    statuses = [v for k, v in out["notified"].items() if not k.endswith(":claude")]
    assert statuses and "SENT" in statuses  # a fresh dispatch is SENT, not SEND_FAILED
    assert all(s in ("SENT", "SEND_FAILED") for s in statuses)


def test_cli_wired_into_desk_commands() -> None:
    from v7_harness import cli

    assert "desk-handoff" in cli._DESK_COMMANDS
    assert callable(cli.cmd_coord_desk_handoff)


def test_lease_renew_keeps_dispatch_valid_past_lease(project: Path) -> None:
    t0 = 5000.0
    won = dh.takeover(project, "claude", NEW, now=t0)
    mid = t0 + dh.LEASE_S - 10
    assert dh.renew_lease(project, "claude", NEW, won["epoch"], now=mid)["reason"] == "RENEWED"
    past_original = t0 + dh.LEASE_S + 5
    assert dh.check_dispatch(project, "claude", NEW, now=past_original)["ok"] is True
    assert dh.check_dispatch(project, "claude", NEW, now=mid + dh.LEASE_S + 1)["reason"] == "DESK_LEASE_EXPIRED"


def test_invalid_tool_and_corrupt_records_fail_closed(project: Path) -> None:
    assert dh.check_dispatch(project, "claud", NEW)["ok"] is False  # misspelled tool never opens the gate
    assert dh.renew_lease(project, "claud", NEW, 1)["ok"] is False
    assert dh.takeover(project, "claud", NEW)["ok"] is False
    path = project / ".coord" / "presence" / "desk_conductor_claude.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    for body in ("{not json", "{}", json.dumps({"desk": NEW})):  # corrupt, empty object, partial record
        path.write_text(body, encoding="utf-8")
        assert dh.check_dispatch(project, "claude", NEW)["ok"] is False
        assert dh.takeover(project, "claude", NEW2)["ok"] is False
        assert dh.run_handoff(project, "claude")["ok"] is True  # detect reports CORRUPT, nothing is taken over
        assert path.read_text(encoding="utf-8") == body  # never overwritten
    assert dh.renew_lease(project, "claude", NEW, 1)["ok"] is False
    unknown_mid = {"codex": "LIMITED", "claude": "UNKNOWN", "antigravity": "ACTIVE"}
    assert dh.authority(unknown_mid) == ""
    path.unlink()
    assert dh.takeover(project, "antigravity", NEW, states=unknown_mid)["reason"] == "AUTHORITY_UNKNOWN"


def test_corrupt_windows_json_refuses_takeover(project: Path) -> None:
    (project / ".coord" / "windows.json").write_text("{broken", encoding="utf-8")
    refused = dh.takeover(project, "claude", NEW)
    assert refused["ok"] is False and refused["reason"] == "DESK_RECORD_CORRUPT"
    assert dh.conductor(project, "claude")["epoch"] == 0  # nothing committed


def test_busy_ledger_does_not_break_a_committed_takeover(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def busy(*a, **k):
        raise TimeoutError("DESK_LOCK_BUSY")

    monkeypatch.setattr(dh, "append_ledger", busy)
    out = dh.takeover(project, "claude", NEW)
    assert out["ok"] is True and out["ledger_ok"] is False and dh.conductor(project, "claude")["desk"] == NEW


def test_ledger_survives_parallel_appends(project: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: dh.append_ledger(project, "PROBE", n=i), range(40)))
    rows = [json.loads(x) for x in dh.ledger_path(project).read_text(encoding="utf-8").splitlines()]
    assert sorted(r["n"] for r in rows) == list(range(40))
