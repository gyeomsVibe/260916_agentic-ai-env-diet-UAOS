"""U366: deterministic reconciliation of the live master and sub-process schedules (0 tokens).

Receipt: the live master schedule kept `current_phase_id: U315` after U315 merged and 12 review items stayed BLOCKED
after later releases resolved 11 of them. `schedule_reconcile` closes the 11 as DONE_SUPERSEDED, isolates U325 as
HELD_FOR_CODEX, advances the head to U366, and writes the three-tier categories, editing the live files as open dicts.
"""

from __future__ import annotations

import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from v7_harness.coord import schedule_planner  # noqa: E402
from v7_harness.coord import schedule_reconcile as sr  # noqa: E402
from v7_harness.coord.master_scheduler import MasterSchedule, MasterTaskScheduler, PhaseItem  # noqa: E402

NOW = 1_800_000_000.0  # 2027-01-15, later than every stamp in the fixtures
# The untracked live runtime file of this checkout, or of the project that holds this worktree under .work/.
LIVE_MASTER = next((base / ".coord" / "master_schedule.json" for base in (ROOT, *ROOT.parents)
                    if (base / ".coord" / "master_schedule.json").is_file()), ROOT / ".coord" / "master_schedule.json")


def _legacy_phase(pid: str, state: str = "BLOCKED", **extra) -> dict:
    """A live-shape phase: no title/mia_stage, extra keys MasterSchedule.from_dict() would reject."""
    return {"phase_id": pid, "state": state, "owner_tool": "codex", "depends_on": [], "pr": 293,
            "note": f"legacy {pid}", **extra}


def _live_master() -> dict:
    phases = [_legacy_phase("U315", "DONE")]
    phases += [_legacy_phase(pid) for pid in sr.SUPERSEDED]
    phases.append(_legacy_phase("U325", logical_alias="U321-R", waiting_on="API_CONTRACT"))
    for phase in phases:
        if phase["phase_id"] == "U321-A4B-INDEPENDENT-261108":
            phase["depends_on"] = ["U325"]
    phases.append(_legacy_phase("U900-KEEP", "BLOCKED", note="not in the reconcile list"))
    return {"schedule_id": "U144-MASTER", "title": "3-Tool Seamless Pipeline", "goal": "g", "current_phase_id": "U315",
            "phases": phases, "created_at": "2026-10-03T19:23:42", "updated_at": "2026-11-09T00:13:57+0900",
            "nonstop_3tool_readiness": {"keep": [1, 2]}, "desk_reconciliation_261108": {"k": "v"},
            "desk_resume_261108": "r", "failover_state": {"mode": "SOLE_SURVIVOR_AUTONOMOUS",
                                                          "active_tools": ["antigravity"]}}


def _sub() -> dict:
    return {"schema": "uaos-sub-process-schedule-v1", "total_active_cards": 4,
            "card_sub_schedules": [{"phase_id": "U315", "card_state": "DONE", "custom": {"x": 1}}],
            "updated_at": "2026-11-22T14:56:16Z"}


def _desk(tmp_path: Path, master: dict | None = None, sub: dict | None = None) -> Path:
    coord = tmp_path / "proj" / ".coord"
    coord.mkdir(parents=True)
    (coord / "master_schedule.json").write_text(json.dumps(master or _live_master(), ensure_ascii=False),
                                                encoding="utf-8")
    if sub is not False:
        (coord / "sub_process_schedule.json").write_text(json.dumps(sub or _sub()), encoding="utf-8")
    return tmp_path / "proj"


def _load(desk: Path, name: str) -> dict:
    return json.loads((desk / ".coord" / name).read_text(encoding="utf-8"))


def _state(master: dict, pid: str) -> str:
    return next(p["state"] for p in master["phases"] if p["phase_id"] == pid)


class TestU366ScheduleSync:
    def test_reconciliation_zero_token_offline(self, tmp_path: Path) -> None:
        desk = _desk(tmp_path)
        boom = mock.Mock(side_effect=AssertionError("no network or subprocess may run"))
        with mock.patch.object(socket, "socket", boom), mock.patch.object(subprocess, "Popen", boom):
            result = sr.reconcile_master_schedule(desk, now=NOW)
        assert result["ok"] is True and result["changed"] is True
        master = _load(desk, "master_schedule.json")
        for pid in sr.SUPERSEDED:
            assert _state(master, pid) == "DONE_SUPERSEDED"
        assert _state(master, "U325") == "HELD_FOR_CODEX"
        assert _state(master, "U900-KEEP") == "BLOCKED"
        assert master["current_phase_id"] == "U366"
        assert result["current_phase_id"] == {"from": "U315", "to": "U366"}
        assert len(result["changes"]) == 12
        cats = _load(desk, "schedule_categories.json")
        assert set(cats["categories"]) == {"LIVE", "STAGED_UNWIRED", "HELD_BLOCKED"}
        assert "U325" in cats["categories"]["HELD_BLOCKED"] and cats["fencing_epoch"] == 5
        sub = _load(desk, "sub_process_schedule.json")
        assert sub["active_cards"][0] == "U366" and sub["card_sub_schedules"][0]["custom"] == {"x": 1}
        dry = sr.reconcile_master_schedule(_desk(tmp_path / "dry"), dry_run=True, now=NOW)
        assert dry["changed"] is True and not (tmp_path / "dry" / "proj" / ".coord" / "schedule_categories.json").exists()
        assert _load(tmp_path / "dry" / "proj", "master_schedule.json")["current_phase_id"] == "U315"

    def test_reconcile_notification_deduplicated(self, tmp_path: Path) -> None:
        desk = _desk(tmp_path)
        first = sr.reconcile_master_schedule(desk, now=NOW)
        assert first["notified"] is True
        notice = _load(desk, "schedule_reconcile_notice.json")
        assert notice["key"] == "U315->U366@5"
        before = (desk / ".coord" / "master_schedule.json").read_bytes()
        for step in range(1, 6):
            again = sr.reconcile_master_schedule(desk, now=NOW + step)
            assert again["ok"] is True and again["notified"] is False and again["changed"] is False
        assert (desk / ".coord" / "master_schedule.json").read_bytes() == before
        assert _load(desk, "schedule_reconcile_notice.json") == notice

    def test_dag_cycle_detection_fails_closed(self, tmp_path: Path) -> None:
        master = _live_master()
        master["phases"].append(_legacy_phase("CYC-A", "PLANNED", depends_on=["CYC-B"]))
        master["phases"].append(_legacy_phase("CYC-B", "PLANNED", depends_on=["CYC-C"]))
        master["phases"].append(_legacy_phase("CYC-C", "PLANNED", depends_on=["CYC-A"]))
        desk = _desk(tmp_path, master)
        before = (desk / ".coord" / "master_schedule.json").read_bytes()
        result = sr.reconcile_master_schedule(desk, now=NOW)
        assert result["ok"] is False and result["reason"] == "CYCLE_DETECTED"
        assert result["cycle"][0] == result["cycle"][-1] and set(result["cycle"]) == {"CYC-A", "CYC-B", "CYC-C"}
        assert (desk / ".coord" / "master_schedule.json").read_bytes() == before
        assert not (desk / ".coord" / "schedule_categories.json").exists()
        assert sr.find_cycle([{"phase_id": "S", "depends_on": ["S"]}]) == ["S", "S"]
        assert sr.find_cycle(_live_master()["phases"]) == []

    def test_atomic_write_prevents_corruption(self, tmp_path: Path) -> None:
        desk = _desk(tmp_path)
        before = (desk / ".coord" / "master_schedule.json").read_bytes()
        with mock.patch("v7_harness.coord.schedule_planner.os.replace", side_effect=OSError("disk full")):
            result = sr.reconcile_master_schedule(desk, now=NOW)
        assert result["ok"] is False and result["reason"] == "WRITE_FAILED"
        assert (desk / ".coord" / "master_schedule.json").read_bytes() == before
        assert json.loads(before)["current_phase_id"] == "U315"
        assert list((desk / ".coord").glob(".*.tmp")) == []
        backups = list((desk / ".work").glob("backup_*/*/master_schedule.json"))
        assert len(backups) == 1 and backups[0].read_bytes() == before
        assert sr.reconcile_master_schedule(desk, now=NOW)["ok"] is True
        assert _load(desk, "master_schedule.json")["current_phase_id"] == "U366"

    def test_concurrent_reconcile_single_winner(self, tmp_path: Path) -> None:
        desk = _desk(tmp_path)
        barrier = threading.Barrier(6)
        results: list[dict] = []
        guard = threading.Lock()

        def run() -> None:
            barrier.wait()
            outcome = sr.reconcile_master_schedule(desk, now=NOW)
            with guard:
                results.append(outcome)

        threads = [threading.Thread(target=run) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        assert len(results) == 6 and all(r["ok"] for r in results)
        assert sum(r["changed"] for r in results) == 1
        assert sum(r["notified"] for r in results) == 1
        master = _load(desk, "master_schedule.json")
        assert master["current_phase_id"] == "U366"
        assert sum(p["phase_id"] == "U366" for p in master["phases"]) == 1
        assert not (desk / ".coord" / "schedule_planner.lock").exists()

    def test_stale_epoch_overwrite_rejected(self, tmp_path: Path) -> None:
        desk = _desk(tmp_path)
        assert sr.reconcile_master_schedule(desk, now=NOW, fencing_epoch=6)["fencing_epoch"] == 6
        snapshot = {name: (desk / ".coord" / name).read_bytes()
                    for name in ("master_schedule.json", "schedule_categories.json")}
        old = sr.reconcile_master_schedule(desk, now=NOW + 1, fencing_epoch=5)
        assert old["ok"] is False and old["reason"] == "STALE_EPOCH" and old["stored_epoch"] == 6
        past = sr.reconcile_master_schedule(desk, now=NOW - 3600)
        assert past["ok"] is False and past["reason"] == "STALE_STATE"
        for name, data in snapshot.items():
            assert (desk / ".coord" / name).read_bytes() == data
        assert sr.reconcile_master_schedule(desk, now=NOW + 2)["fencing_epoch"] == 6  # default keeps the stored max

    def test_conductor_absent_fallback_preserved(self, tmp_path: Path) -> None:
        master = _live_master()
        master["acting_conductor"] = {"tool": "antigravity", "since": "2026-11-20T00:00:00Z", "epoch": 5}
        desk = _desk(tmp_path, master)
        result = sr.reconcile_master_schedule(desk, now=NOW)
        assert result["ok"] is True and result["acting_conductor"] == master["acting_conductor"]
        after = _load(desk, "master_schedule.json")
        assert after["acting_conductor"] == master["acting_conductor"]
        assert after["failover_state"] == master["failover_state"]
        no_acting = _live_master()
        report = sr.reconcile_master_schedule(_desk(tmp_path / "b", no_acting), dry_run=True, now=NOW)
        assert report["acting_conductor"] == "SOLE_SURVIVOR_AUTONOMOUS"
        for broken in ("SOLE_SURVIVOR_AUTONOMOUS", ["antigravity"], None, 7):  # a non-dict failover_state never raises
            odd = _live_master()
            odd["failover_state"] = broken
            odd_desk = _desk(tmp_path / f"odd_{type(broken).__name__}", odd)
            odd_report = sr.reconcile_master_schedule(odd_desk, now=NOW)
            assert odd_report["ok"] is True and odd_report["acting_conductor"] is None
            assert _load(odd_desk, "master_schedule.json")["failover_state"] == broken

    def test_held_cards_isolated_without_blocking(self, tmp_path: Path) -> None:
        desk = _desk(tmp_path)
        result = sr.reconcile_master_schedule(desk, now=NOW)
        master = _load(desk, "master_schedule.json")
        assert _state(master, "U325") == "HELD_FOR_CODEX"
        assert _state(master, "U321-A4B-INDEPENDENT-261108") == "DONE_SUPERSEDED"  # its HELD dependency blocks nothing
        assert master["current_phase_id"] == "U366" and _state(master, "U366") == "ACTIVE"
        assert "U325" in result["categories"]["HELD_BLOCKED"]
        assert "U325" not in result["active_cards"]
        assert result["active_cards"] == ["U366", "U351", "U352", "U363"]
        assert "U365" in result["categories"]["LIVE"] and "U365" not in result["categories"]["STAGED_UNWIRED"]
        assert not set(result["categories"]["HELD_BLOCKED"]) & set(result["active_cards"])
        u325 = next(p for p in master["phases"] if p["phase_id"] == "U325")
        assert u325["logical_alias"] == "U321-R" and u325["evidence"]["u366_reconcile"]["from"] == "BLOCKED"

    def test_minimal_to_dict_fixture_still_loads(self, tmp_path: Path) -> None:
        phases = [PhaseItem(phase_id="U315", title="t", owner_tool="codex", mia_stage="s", state="DONE"),
                  PhaseItem(phase_id="U325", title="t", owner_tool="codex", mia_stage="s", state="BLOCKED")]
        schedule = MasterSchedule(schedule_id="S", title="T", goal="G", current_phase_id="U315", phases=phases)
        desk = _desk(tmp_path, schedule.to_dict(), sub=False)
        assert sr.reconcile_master_schedule(desk, now=NOW)["ok"] is True
        loaded = MasterSchedule.from_dict(_load(desk, "master_schedule.json"))
        assert loaded.current_phase_id == "U366" and loaded.phases[1].state == "HELD_FOR_CODEX"
        assert not (desk / ".coord" / "sub_process_schedule.json").exists()

    def test_naive_local_updated_at_not_stale(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Receipt (AGY A2 review): naive local stamps read as UTC put a KST (+09:00) save 9 h in the future.
        if hasattr(time, "tzset"):  # POSIX CI: run at +09:00 so a UTC host still exercises the offset
            monkeypatch.setenv("TZ", "Asia/Seoul")
            time.tzset()
        try:
            for text in ("2026-11-23T01:00:00", "2026-11-23T01:00:00+09:00", "2026-11-22T16:00:00Z",
                         time.strftime("%Y-%m-%dT%H:%M:%S")):
                assert sr._ts(text) == schedule_planner._ts(text), text
            assert sr._ts("2026-11-09T00:13:57+0900") == sr._ts("2026-11-09T00:13:57+09:00")
            desk = tmp_path / "proj"
            phases = [PhaseItem(phase_id="U315", title="t", owner_tool="codex", mia_stage="s", state="DONE")]
            MasterTaskScheduler(desk).save_schedule(
                MasterSchedule(schedule_id="S", title="T", goal="G", current_phase_id="U315", phases=phases))
            result = sr.reconcile_master_schedule(desk)
            assert result["ok"] is True, result
            assert _load(desk, "master_schedule.json")["current_phase_id"] == "U366"
        finally:
            if hasattr(time, "tzset"):
                monkeypatch.undo()
                time.tzset()

    def test_held_phase_leaves_live_and_staged_tiers(self, tmp_path: Path) -> None:
        master = _live_master()
        master["phases"].append(_legacy_phase("U351", "HELD_FOR_CODEX"))
        master["phases"].append({"phase_id": None, "state": "HELD_FOR_CODEX"})
        master["phases"].append({"phase_id": "  ", "state": "HELD_FOR_CODEX"})
        desk = _desk(tmp_path, master)
        result = sr.reconcile_master_schedule(desk, now=NOW)
        cats = result["categories"]
        assert result["ok"] is True
        assert "U351" in cats["HELD_BLOCKED"] and "U351" not in cats["STAGED_UNWIRED"]
        assert "U351" not in cats["LIVE"] and "U351" not in result["active_cards"]
        assert None not in cats["HELD_BLOCKED"] and "  " not in cats["HELD_BLOCKED"]
        assert all(isinstance(c, str) and c.strip() for c in cats["HELD_BLOCKED"])
        assert result["active_cards"] == ["U366", "U352", "U363"]
        assert _load(desk, "sub_process_schedule.json")["active_cards"] == ["U366", "U352", "U363"]

    @pytest.mark.skipif(not LIVE_MASTER.is_file(), reason="no live master schedule in this checkout")
    def test_live_master_copy_keeps_unknown_keys(self, tmp_path: Path) -> None:
        desk = tmp_path / "proj"
        (desk / ".coord").mkdir(parents=True)
        shutil.copy2(LIVE_MASTER, desk / ".coord" / "master_schedule.json")
        original = _load(desk, "master_schedule.json")
        result = sr.reconcile_master_schedule(desk, now=datetime.now(timezone.utc).timestamp() + 60)
        assert result["ok"] is True, result
        after = _load(desk, "master_schedule.json")
        assert set(original) <= set(after)
        for key in original:
            if key not in ("current_phase_id", "updated_at", "phases"):
                assert after[key] == original[key], key
        before_ids = {p.get("phase_id"): p for p in original["phases"]}
        for phase in after["phases"]:
            old = before_ids.get(phase.get("phase_id"))
            if old is not None:
                assert set(old) <= set(phase)
                for key in old:
                    if key not in ("state", "updated_at", "evidence"):
                        assert phase[key] == old[key]
        assert after["current_phase_id"] == "U366"
