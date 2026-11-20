"""U332: user-desk router. No network, no paid call; concurrency tests use real OS processes."""

import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from v7_harness.coord import desk_router as dr

ROOT = Path(__file__).resolve().parents[1]
ALL_ACTIVE = {"codex": "ACTIVE", "claude": "ACTIVE", "antigravity": "ACTIVE"}
ALL_ADMITTED = {"codex": True, "claude": True, "antigravity": True}


def _opener(calls):
    def opener(project, card, tool, title, manual_path):
        calls.append((card, tool))
        return {"opened": True, "id": f"win-{card}"}
    return opener


def _run_parallel(code: str, args_list: list[list[str]], start_in_s: float = 1.5) -> list[str]:
    """Start one python process per args, all released at the same wall-clock instant; return their stdout."""
    start_at = time.time() + start_in_s
    prelude = f"import time; time.sleep(max(0, {start_at!r} - time.time()))\n"
    procs = [subprocess.Popen([sys.executable, "-c", prelude + code, *args], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True) for args in args_list]
    outs = []
    for proc in procs:
        out, err = proc.communicate(timeout=120)
        assert proc.returncode == 0, err
        outs.append(out.strip())
    return outs


class DeskRouterTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)

    def route(self, text, **kw):
        calls = kw.pop("calls", [])
        kw.setdefault("states", ALL_ACTIVE)
        kw.setdefault("admitted", ALL_ADMITTED)
        plan = dr.route_directive(self.project, text, tool="claude", opener=_opener(calls), **kw)
        return plan, calls

    def test_verbatim_preserved_byte_exact(self):
        raw = "윤겸스 지시:\r\n  끝 공백  \t\n\n마지막 줄 (개행 없음)".encode("utf-8")
        meta = dr.capture(self.project, raw)
        self.assertEqual((self.project / ".coord/directives" / f"{meta['d_id']}.md").read_bytes(), raw)
        self.assertEqual(meta["sha256"], hashlib.sha256(raw).hexdigest())
        # routing a directive must not rewrite its words either
        plan, _ = self.route("v7_harness/a.py 에 함수를 추가한다\r\n끝")
        stored = (self.project / ".coord/directives" / f"{plan['d_id']}.md").read_bytes()
        self.assertEqual(stored, "v7_harness/a.py 에 함수를 추가한다\r\n끝".encode("utf-8"))

    def test_three_concurrent_claims_exactly_one_owner(self):
        code = ("import sys; from pathlib import Path; from v7_harness.coord import desk_router as dr\n"
                "r = dr.claim(Path(sys.argv[1]), 'D-0001', sys.argv[2]); print(r['won'], r['owner'])")
        outs = _run_parallel(code, [[str(self.project), t] for t in ("codex", "claude", "antigravity")])
        winners = [o for o in outs if o.startswith("True")]
        self.assertEqual(len(winners), 1, outs)
        owner = winners[0].split()[1]
        self.assertTrue(all(o.endswith(owner) for o in outs), outs)  # losers see the same owner
        self.assertEqual(dr.current_owner(self.project, "D-0001"), owner)

    def test_burst_of_ten_directives_all_preserved_and_ordered(self):
        code = ("import sys; from pathlib import Path; from v7_harness.coord import desk_router as dr\n"
                "m = dr.capture(Path(sys.argv[1]), sys.argv[2].encode('utf-8')); print(m['d_id'])")
        texts = [f"지시 {n}: 원문 \"그대로\" {n * 7}" for n in range(10)]
        outs = _run_parallel(code, [[str(self.project), t] for t in texts])
        self.assertEqual(len(set(outs)), 10, outs)  # unique ids, nothing overwritten
        listed = dr.list_directives(self.project)
        self.assertEqual([m["seq"] for m in listed], list(range(1, 11)))  # ordered, gap-free
        stored = {(self.project / ".coord/directives" / f"{m['d_id']}.md").read_text(encoding="utf-8") for m in listed}
        self.assertEqual(stored, set(texts))

    def test_quick_vs_card(self):
        self.assertEqual(dr.classify("지금 상태 알려줘"), "quick")
        self.assertEqual(dr.classify("카드 U331 끝났어?"), "quick")
        self.assertEqual(dr.classify("v7_harness/coord/x.py 에 라우터를 구현한다"), "card")
        self.assertEqual(dr.classify("사용자 대화창 라우터를 새로 만들고 테스트까지 붙여라 " * 3), "card")
        plan, calls = self.route("지금 상태 알려줘")
        self.assertEqual(plan["state"], "QUICK_AT_DESK")
        self.assertEqual(calls, [])

    def test_dedupe_routes_to_existing_card_by_file(self):
        folder = self.project / ".coord/directives"
        folder.mkdir(parents=True)
        (folder / dr.REGISTRY).write_text(json.dumps({"cards": {"U900": {
            "id": "U900", "title": "stall fix", "status": "RUNNING", "tool": "claude",
            "files": ["v7_harness/coord/stall.py"], "lane": "IMPL_CODE"}}}), encoding="utf-8")
        text = "v7_harness/coord/stall.py 의 대기 종료 조건도 고쳐라"
        plan, calls = self.route(text)
        self.assertEqual(plan["state"], "ADDED_TO_EXISTING")
        self.assertEqual(plan["duplicate"]["card"], "U900")
        self.assertEqual(calls, [])  # no new window
        self.assertIn(text, (folder / "U900.addenda.md").read_text(encoding="utf-8"))  # verbatim goes to the running card

    def test_dedupe_ignores_finished_cards(self):
        folder = self.project / ".coord/directives"
        folder.mkdir(parents=True)
        (folder / dr.REGISTRY).write_text(json.dumps({"cards": {"U900": {
            "id": "U900", "status": "DONE", "files": ["v7_harness/coord/stall.py"], "lane": "IMPL_CODE"}}}), encoding="utf-8")
        plan, _ = self.route("v7_harness/coord/stall.py 를 고쳐라")
        self.assertEqual(plan["state"], "ROUTED")

    def test_split_disjoint_files_two_cards(self):
        plan, calls = self.route("1. v7_harness/coord/a_mod.py 에 함수를 추가\n2. v7_harness/coord/b_mod.py 에 함수를 추가")
        self.assertEqual(len(plan["cards"]), 2)
        self.assertTrue(all(c["depends_on"] == [] for c in plan["cards"]))
        self.assertEqual(len(calls), 2)  # both start now

    def test_split_shared_file_one_card(self):
        plan, _ = self.route("1. v7_harness/coord/a_mod.py 에 함수 추가\n2. v7_harness/coord/a_mod.py 의 테스트 수정")
        self.assertEqual(len(plan["cards"]), 1)

    def test_split_unknown_files_is_one_card(self):
        plan, _ = self.route("1. 라우터 구현을 만든다\n2. v7_harness/coord/b_mod.py 에 함수 추가")
        self.assertEqual(len(plan["cards"]), 1)  # cannot prove disjoint -> worst case

    def test_split_dependency_records_depends_on_and_successor_auto_starts(self):
        plan, calls = self.route("1. v7_harness/coord/a_mod.py 에 함수를 추가\n2. v7_harness/coord/b_mod.py 는 1번이 끝나면 그 결과를 써서 수정")
        first, second = plan["cards"]
        self.assertEqual(second["depends_on"], [first["id"]])
        self.assertEqual(second["status"], "WAITING")
        self.assertEqual([c[0] for c in calls], [first["id"]])  # only the predecessor opened
        later = []
        self.assertEqual(dr.advance(self.project, opener=_opener(later)), [])  # predecessor still running
        dr.set_card_status(self.project, first["id"], "DONE")
        self.assertEqual(dr.advance(self.project, opener=_opener(later)), [second["id"]])
        self.assertEqual([c[0] for c in later], [second["id"]])

    def test_quota_unknown_means_no_paid_route(self):
        for admitted in (None, {}, {"codex": None, "claude": "UNKNOWN", "antigravity": False}):
            plan, calls = self.route("v7_harness/coord/a_mod.py 에 함수를 추가", admitted=admitted)
            card = plan["cards"][0]
            self.assertIsNone(card["assignment"]["tool"], admitted)
            self.assertFalse(card["assignment"]["paid"])
            self.assertEqual(card["status"], "BLOCKED")
            self.assertEqual(calls, [])
            self.assertEqual(card["assignment"]["blocked"], "BLOCKED_QUOTA_UNKNOWN")

    def test_unknown_presence_means_no_route(self):
        plan, calls = self.route("v7_harness/coord/a_mod.py 에 함수를 추가", states={})
        self.assertEqual(plan["cards"][0]["status"], "BLOCKED")
        self.assertEqual(calls, [])

    def test_overloaded_tool_gets_no_new_card(self):
        assign = dr.assign_tool("IMPL_CODE", ALL_ACTIVE, ALL_ADMITTED, {"antigravity": 3})
        self.assertNotEqual(assign["tool"], "antigravity")
        self.assertEqual(assign["skipped"]["antigravity"], "overloaded")

    def test_manual_links_directive_and_audit_rejects_missing_link(self):
        plan, _ = self.route("v7_harness/coord/a_mod.py 에 함수를 추가")
        card = plan["cards"][0]
        manual = (self.project / card["manual"]).read_text(encoding="utf-8")
        self.assertIn(f"Directive: .coord/directives/{plan['d_id']}.md", manual)
        self.assertEqual(dr.manual_problems(self.project, manual), [])
        stripped = "\n".join(l for l in manual.splitlines() if not l.startswith("Directive:"))
        self.assertEqual(dr.manual_problems(self.project, stripped), ["MANUAL_MISSING_DIRECTIVE_LINK"])
        # the verbatim file changed after the manual was written -> the summary may have drifted
        (self.project / ".coord/directives" / f"{plan['d_id']}.md").write_bytes(b"changed")
        self.assertEqual(dr.manual_problems(self.project, manual), ["DIRECTIVE_SHA_MISMATCH"])
        (self.project / ".coord/directives" / f"{plan['d_id']}.md").unlink()
        self.assertEqual(dr.manual_problems(self.project, manual), ["DIRECTIVE_FILE_MISSING"])

    def test_router_handoff_when_owner_limited(self):
        meta = dr.capture(self.project, "x")
        self.assertTrue(dr.claim(self.project, meta["d_id"], "codex")["won"])
        same = dr.hand_off_if_limited(self.project, meta["d_id"], ALL_ACTIVE)
        self.assertFalse(same["handed_off"])
        limited = {"codex": "LIMITED", "claude": "ACTIVE", "antigravity": "ACTIVE"}
        moved = dr.hand_off_if_limited(self.project, meta["d_id"], limited)
        self.assertTrue(moved["handed_off"])
        self.assertEqual(dr.current_owner(self.project, meta["d_id"]), "claude")  # authority order
        none = dr.hand_off_if_limited(self.project, meta["d_id"], {"codex": "LIMITED", "claude": "UNKNOWN", "antigravity": "ABSENT"})
        self.assertFalse(none["handed_off"])  # UNKNOWN is no ground for acting
        self.assertEqual(none["reason"], "BLOCKED_NO_ACTIVE_TOOL")

    def test_losing_claim_becomes_peer_and_opens_nothing(self):
        meta = dr.capture(self.project, "x")
        dr.claim(self.project, meta["d_id"], "codex")
        again = dr.claim(self.project, meta["d_id"], "claude")
        self.assertEqual((again["won"], again["role"], again["owner"]), (False, "peer", "codex"))

    def test_concretize_ollama_down_and_bad_draft_fall_back(self):
        def down(_):
            raise RuntimeError("ollama down")

        text = "라우터를 구현한다. 테스트가 통과해야 한다. 네트워크는 쓰지 않는다."
        for drafter in (down, lambda _: "not json", lambda _: json.dumps({"goal": 5})):
            out = dr.concretize(text, drafter)
            self.assertEqual(out["source"], "deterministic_fallback")
            self.assertTrue(out["goal"] and out["success_signal"] and out["worst_cases"])
        self.assertEqual(dr.concretize(text, None)["source"], "deterministic")
        self.assertIn("네트워크는 쓰지 않는다.", dr.concretize(text)["non_goals"])
        good = json.dumps({"goal": "g", "success_signal": "s", "non_goals": ["n"], "worst_cases": [["a", "b", "c", "d"]]})
        self.assertEqual(dr.concretize(text, lambda _: good)["source"], "ollama")

    def test_status_reports_only_changes_in_three_lines(self):
        plan, _ = self.route("\n".join(f"{n}. v7_harness/coord/m{n}.py 에 함수 추가" for n in range(1, 6)))
        first = dr.status_lines(self.project)
        self.assertEqual(len(first), 3)
        self.assertEqual(dr.status_lines(self.project), [])  # nothing changed since
        dr.set_card_status(self.project, plan["cards"][0]["id"], "DONE")
        self.assertEqual(len(dr.status_lines(self.project)), 1)

    def test_replayed_native_event_is_idempotent_but_same_text_new_event_is_not(self):
        text = "v7_harness/coord/a_mod.py 에 함수를 추가"
        calls = []
        first, _ = self.route(text, event_id="evt-1", calls=calls)
        again, _ = self.route(text, event_id="evt-1", calls=calls)
        self.assertEqual(again["state"], "REPLAY")
        self.assertEqual(again["d_id"], first["d_id"])
        self.assertEqual(len(dr.list_directives(self.project)), 1)
        self.assertEqual(len(calls), 1)  # no second launch
        other, _ = self.route(text, event_id="evt-2", calls=calls)
        self.assertNotEqual(other["d_id"], first["d_id"])  # identical text, distinct event: a separate directive

    def test_concurrent_replay_of_one_event_makes_one_directive(self):
        code = ("import sys; from pathlib import Path; from v7_harness.coord import desk_router as dr\n"
                "m = dr.capture(Path(sys.argv[1]), 'same', event_id='evt-x'); print(m['d_id'])")
        outs = _run_parallel(code, [[str(self.project)] for _ in range(3)])
        self.assertEqual(len(set(outs)), 1, outs)
        self.assertEqual(len(dr.list_directives(self.project)), 1)

    def test_launch_intent_is_durable_before_native_launch_and_crash_is_not_relaunched(self):
        text = "v7_harness/coord/a_mod.py 에 함수를 추가"
        seen = []

        def crashing(project, card, tool, title, manual_path):
            seen.append(dr.running_cards(project)[0]["status"])  # intent already on disk when the launch starts
            raise RuntimeError("crash after native launch")

        plan = dr.route_directive(self.project, text, tool="claude", states=ALL_ACTIVE, admitted=ALL_ADMITTED,
                                  opener=crashing, event_id="evt-c")
        self.assertEqual(seen, ["LAUNCHING"])
        self.assertEqual(plan["cards"][0]["status"], "READY")
        calls = []
        again = dr.route_directive(self.project, text, tool="claude", states=ALL_ACTIVE, admitted=ALL_ADMITTED,
                                   opener=_opener(calls), event_id="evt-c")
        self.assertEqual((again["state"], calls), ("REPLAY", []))

    def test_replay_after_crash_before_plan_resumes_routing_without_double_launch(self):
        text = "v7_harness/coord/a_mod.py 에 함수를 추가"
        meta = dr.capture(self.project, text, source_tool="claude", event_id="evt-r")  # died right after capture: no plan
        self.assertEqual(meta["state"], "RECEIVED")
        dr.claim(self.project, meta["d_id"], "claude")  # and after the claim
        calls = []
        again = dr.route_directive(self.project, text, tool="claude", states=ALL_ACTIVE, admitted=ALL_ADMITTED,
                                   opener=_opener(calls), event_id="evt-r")
        self.assertEqual((again["state"], len(again["cards"]), len(calls)), ("ROUTED", 1, 1))
        third = dr.route_directive(self.project, text, tool="claude", states=ALL_ACTIVE, admitted=ALL_ADMITTED,
                                   opener=_opener(calls), event_id="evt-r")
        self.assertEqual((third["state"], len(calls)), ("REPLAY", 1))

    def test_resumed_routing_never_relaunches_a_launching_card(self):
        text = "v7_harness/coord/a_mod.py 에 함수를 추가"
        meta = dr.capture(self.project, text, source_tool="claude", event_id="evt-l")
        dr.claim(self.project, meta["d_id"], "claude")
        dr._register(dr._dir(self.project), {f"{meta['d_id'].replace('-', '')}-C1": {"id": f"{meta['d_id'].replace('-', '')}-C1",
                     "status": "LAUNCHING", "tool": "claude", "files": ["v7_harness/coord/a_mod.py"], "d_id": meta["d_id"]}})
        calls = []
        dr.route_directive(self.project, text, tool="claude", states=ALL_ACTIVE, admitted=ALL_ADMITTED,
                           opener=_opener(calls), event_id="evt-l")
        self.assertEqual(calls, [])

    def test_shared_resource_makes_later_card_wait_and_is_a_duplicate(self):
        cards = {"U1": {"id": "U1", "status": "RUNNING", "tool": "claude", "files": ["a.py"], "resources": ["port:8765"]},
                 "U2": {"id": "U2", "status": "READY", "tool": "codex", "files": ["b.py"], "resources": ["port:8765"]}}
        sig = dr.compute_signals(cards)
        self.assertEqual((sig["U1"]["signal"], sig["U2"]["signal"], sig["U2"]["waits_for"]), ("GO", "WAIT", ["U1"]))
        dup = dr.find_duplicate("서버", {"c.py"}, "IMPL_CODE", list(cards.values()), {"port:8765"})
        self.assertEqual(dup["kind"], "related")

    def test_parallel_same_owner_replays_launch_exactly_once(self):
        import threading
        text = "v7_harness/coord/a_mod.py 에 함수를 추가"
        meta = dr.capture(self.project, text, source_tool="claude", event_id="evt-p")
        dr.claim(self.project, meta["d_id"], "claude")
        calls, barrier = [], threading.Barrier(4)

        def slow_open(project, card, tool, title, manual_path):
            calls.append(card)
            time.sleep(0.2)
            return {"opened": True}

        def worker():
            barrier.wait()
            dr.route_directive(self.project, text, tool="claude", states=ALL_ACTIVE, admitted=ALL_ADMITTED,
                               opener=slow_open, event_id="evt-p")

        threads = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len(calls), 1, calls)  # one atomic dispatch claim: the others see EXISTS and never launch

    def test_commit_is_fenced_against_a_takeover_in_the_same_transaction(self):
        meta = dr.capture(self.project, "v7_harness/coord/a_mod.py 에 함수를 추가", source_tool="claude")
        dr.claim(self.project, meta["d_id"], "codex")
        epoch = dr.claim_epoch(self.project, meta["d_id"])
        dr.hand_off_if_limited(self.project, meta["d_id"], {"codex": "LIMITED", "claude": "ACTIVE"})
        plan = {"state": "ROUTED", "cards": []}
        self.assertFalse(dr._commit(self.project, meta, plan, {"X": {"id": "X", "status": "RUNNING"}}, "codex", epoch))
        self.assertFalse((self.project / ".coord/directives/cards.json").exists())  # the stale router wrote nothing
        self.assertEqual(dr._claim_dispatch(self.project, meta["d_id"], "codex", epoch, {"id": "Y"}), "FENCED")

    def test_advance_launches_outside_the_registry_lock_and_stop_wins(self):
        _seed(self.project, {"U1": {"id": "U1", "status": "DONE", "tool": "claude", "files": []},
                             "U2": {"id": "U2", "status": "WAITING", "tool": "claude", "files": [], "depends_on": ["U1"],
                                    "manual": ".coord/directives/manuals/U2.md"}})
        seen = {}

        def opener(project, cid, tool, title, manual_path):
            seen["status_during"] = _registry(self.project)["U2"]["status"]  # readable: the lock is not held here
            dr.propagate_stop(self.project, "D-0099")  # a stop arrives while the launch is in flight
            return {"opened": True}

        self.assertEqual(dr.advance(self.project, opener=opener), ["U2"])
        self.assertEqual(seen["status_during"], "LAUNCHING")
        self.assertEqual(_registry(self.project)["U2"]["status"], "STOPPED")  # the stop is not overwritten by RUNNING

    def test_stop_cancels_every_preclaimed_successor(self):
        _seed(self.project, {"U1": {"id": "U1", "status": "DONE", "tool": "claude", "files": []},
                             "U2": {"id": "U2", "status": "WAITING", "tool": "claude", "files": ["a.py"], "depends_on": ["U1"],
                                    "manual": ".coord/directives/manuals/U2.md"},
                             "U3": {"id": "U3", "status": "WAITING", "tool": "codex", "files": ["b.py"], "depends_on": ["U1"],
                                    "manual": ".coord/directives/manuals/U3.md"}})
        opened = []

        def opener(project, cid, tool, title, manual_path):
            opened.append(cid)
            dr.propagate_stop(self.project, "D-0099")  # the stop lands while the first successor launches
            return {"opened": True}

        dr.advance(self.project, opener=opener)
        self.assertEqual(len(opened), 1, opened)  # the second pre-claimed successor is cancelled, not launched
        cards = _registry(self.project)
        self.assertEqual({cards["U2"]["status"], cards["U3"]["status"]}, {"STOPPED"})

    def test_stale_router_is_fenced_after_handoff(self):
        meta = dr.capture(self.project, "v7_harness/coord/a_mod.py 에 함수를 추가", source_tool="claude")
        dr.claim(self.project, meta["d_id"], "codex")
        epoch = dr.claim_epoch(self.project, meta["d_id"])
        self.assertTrue(dr.is_router(self.project, meta["d_id"], "codex", epoch))
        dr.hand_off_if_limited(self.project, meta["d_id"], {"codex": "LIMITED", "claude": "ACTIVE"})
        self.assertFalse(dr.is_router(self.project, meta["d_id"], "codex", epoch))  # the old router's writes are refused
        self.assertTrue(dr.is_router(self.project, meta["d_id"], "claude", epoch + 1))

    def test_manual_directive_path_must_stay_inside_directives(self):
        outside = self.project / "secret.txt"
        outside.write_text("x", encoding="utf-8")
        sha = hashlib.sha256(b"x").hexdigest()
        for link in ("secret.txt", "../secret.txt", ".coord/directives/../../secret.txt"):
            manual = f"Directive: {link} (sha256 {sha})\n"
            self.assertEqual(dr.manual_problems(self.project, manual), ["DIRECTIVE_PATH_OUTSIDE_PROJECT"], link)

    def test_disjoint_files_sharing_a_port_stay_one_card(self):
        plan, _ = self.route("1. v7_harness/coord/a_mod.py 서버를 port 8765 에서 띄운다\n2. v7_harness/coord/b_mod.py 도 포트 8765 를 쓴다")
        self.assertEqual(len(plan["cards"]), 1)

    def test_cli_audit_manual_exit_codes(self):
        plan, _ = self.route("v7_harness/coord/a_mod.py 에 함수를 추가")
        manual = self.project / plan["cards"][0]["manual"]
        ok = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "route-directive", "--project", str(self.project),
                             "--tool", "claude", "--audit-manual", str(manual)], cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(ok.returncode, 0, ok.stderr)
        bad = self.project / "bad.md"
        bad.write_text("# no link\n", encoding="utf-8")
        res = subprocess.run([sys.executable, "-m", "v7_harness.cli", "coord", "route-directive", "--project", str(self.project),
                              "--tool", "claude", "--audit-manual", str(bad)], cwd=ROOT, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(res.returncode, 2)


def _seed(project: Path, cards: dict) -> None:
    folder = project / ".coord/directives"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / dr.REGISTRY).write_text(json.dumps({"cards": cards}), encoding="utf-8")


def _registry(project: Path) -> dict:
    return json.loads((project / ".coord/directives" / dr.REGISTRY).read_text(encoding="utf-8"))["cards"]


class SharedLedgerTests(unittest.TestCase):
    """Spec 9.8: three desks, one body."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)

    def test_three_process_parallel_appends_have_no_seq_gaps(self):
        code = ("import sys; from pathlib import Path; from v7_harness.coord import desk_ledger as dl\n"
                "[dl.append_directive(Path(sys.argv[1]), f'{sys.argv[2]} 지시 {n}', tool=sys.argv[2]) for n in range(5)]")
        _run_parallel(code, [[str(self.project), t] for t in ("codex", "claude", "antigravity")])
        from v7_harness.coord import desk_ledger as dl
        rows = dl.read_since(self.project, 0)
        self.assertEqual([r["seq"] for r in rows], list(range(1, 16)))
        self.assertEqual(len({r["text"] for r in rows}), 15)
        for r in rows:  # every ledger line has its byte-exact verbatim file
            self.assertEqual((self.project / ".coord/directives" / f"{r['d_id']}.md").read_text(encoding="utf-8"), r["text"])

    def test_offline_return_replays_from_cursor_and_ack_is_idempotent(self):
        from v7_harness.coord import desk_ledger as dl
        for n in range(3):
            dl.append_directive(self.project, f"claude 쪽 지시 {n}", tool="claude")
        lines = dl.inject(self.project, "codex")
        self.assertEqual(len(lines), 3)
        self.assertEqual(dl.cursor_of(self.project, "codex"), 3)
        self.assertEqual(dl.inject(self.project, "codex"), [])  # nothing new
        self.assertEqual(dl.ack(self.project, "codex", 1), 3)  # an old ack never moves the cursor back
        dl.append_directive(self.project, "다시 돌아온 뒤 지시", tool="antigravity")
        self.assertEqual(len(dl.inject(self.project, "codex")), 1)

    def test_fifty_directive_burst_injects_links_and_gists_not_full_text(self):
        from v7_harness.coord import desk_ledger as dl
        long_text = "긴 지시 " + "가나다라 " * 60
        for n in range(50):
            dl.append_directive(self.project, f"{n} {long_text}", tool="claude")
        lines = dl.inject(self.project, "antigravity")
        self.assertLessEqual(len(lines), dl.INJECT_MAX_LINES + 1)
        self.assertTrue(all(len(l) < 260 for l in lines))
        self.assertTrue(lines[0].endswith("D-0001.md") and "+42 more" in lines[-1])

    def test_truncated_burst_does_not_skip_the_unseen_tail(self):
        from v7_harness.coord import desk_ledger as dl
        for n in range(12):
            dl.append_directive(self.project, f"지시 번호 {n}", tool="claude")
        first = dl.inject(self.project, "codex", limit=5)
        self.assertEqual(dl.cursor_of(self.project, "codex"), 5)  # not 12: seq 6..12 are still unseen
        second = dl.inject(self.project, "codex", limit=5)
        self.assertTrue(second[0].startswith("D-0006"), second)
        third = dl.inject(self.project, "codex", limit=5)
        self.assertTrue(third[0].startswith("D-0011") and dl.cursor_of(self.project, "codex") == 12, third)
        self.assertEqual(len(first), 6)

    def test_torn_last_ledger_line_does_not_swallow_the_next_entry(self):
        from v7_harness.coord import desk_ledger as dl
        dl.append_directive(self.project, "첫 지시", tool="claude")
        with open(self.project / ".coord/directives" / dl.LEDGER, "ab") as handle:
            handle.write(b'{"seq": 2, "d_id": "D-00')  # crash mid-line: no trailing newline
        entry = dl.append_directive(self.project, "다음 지시", tool="codex")
        self.assertEqual([r["text"] for r in dl.read_since(self.project, 0)], ["첫 지시", "다음 지시"])
        self.assertEqual(entry["seq"], 2)

    def test_nonpositive_limit_and_old_conflicts_and_cursor_report(self):
        from v7_harness.coord import desk_ledger as dl
        dl.append_directive(self.project, "v7_harness/coord/stall.py 를 5분으로 고쳐라", tool="claude", now=1000.0)
        dl.append_directive(self.project, "v7_harness/coord/stall.py 는 10초로 고쳐라", tool="codex", now=1004.0)
        self.assertTrue(any(l.startswith("CONFLICT") for l in dl.inject(self.project, "antigravity")))
        dl.append_directive(self.project, "전혀 다른 새 지시 하나", tool="claude", now=5000.0)
        again = dl.inject(self.project, "antigravity")
        self.assertFalse(any(l.startswith("CONFLICT") for l in again), again)  # the old conflict is not re-announced
        for n in range(4):
            dl.append_directive(self.project, f"추가 지시 {n}", tool="claude", now=6000.0 + n * 100)
        lines = dl.inject(self.project, "antigravity", limit=-3)  # clamped to 1, never slices from the end
        self.assertEqual(len([l for l in lines if l.startswith("D-")]), 1)
        self.assertIn(f"cursor 3 -> {dl.cursor_of(self.project, 'antigravity')}", lines[-1])  # reports the real new cursor
        self.assertEqual(dl.cursor_of(self.project, "antigravity"), 4)

    def test_signals_tolerate_null_depends_on(self):
        sig = dr.compute_signals({"U1": {"id": "U1", "status": "RUNNING", "tool": "claude", "files": [], "depends_on": None}})
        self.assertEqual(sig["U1"]["signal"], "GO")

    def test_conflicting_directives_at_two_desks_later_seq_wins(self):
        from v7_harness.coord import desk_ledger as dl
        dl.append_directive(self.project, "v7_harness/coord/stall.py 를 5분으로 고쳐라", tool="claude", now=1000.0)
        dl.append_directive(self.project, "v7_harness/coord/stall.py 는 10초로 고쳐라", tool="codex", now=1004.0)
        lines = dl.inject(self.project, "antigravity")
        conflict = [l for l in lines if l.startswith("CONFLICT")]
        self.assertEqual(len(conflict), 1)
        self.assertIn("D-0002(codex) overrides D-0001(claude)", conflict[0])

    def test_stop_at_one_desk_halts_every_card_and_shows_first_everywhere(self):
        from v7_harness.coord import desk_ledger as dl
        _seed(self.project, {"U1": {"id": "U1", "status": "RUNNING", "tool": "claude", "files": ["a.py"]},
                             "U2": {"id": "U2", "status": "WAITING", "tool": "codex", "files": ["b.py"]},
                             "U3": {"id": "U3", "status": "DONE", "tool": "codex", "files": []}})
        dl.append_directive(self.project, "다른 지시", tool="claude")
        started = time.monotonic()
        dl.append_directive(self.project, "stop", tool="antigravity")
        lines = dl.inject(self.project, "codex")
        self.assertLess(time.monotonic() - started, dl.ACK_DEADLINE_S)
        self.assertTrue(lines[0].startswith("STOP D-0002"), lines)
        cards = _registry(self.project)
        self.assertEqual((cards["U1"]["status"], cards["U1"]["signal"]), ("STOPPED", "STOP"))
        self.assertEqual(cards["U2"]["status"], "STOPPED")
        self.assertEqual(cards["U3"]["status"], "DONE")  # finished cards are left alone

    def test_stop_text_routed_through_router_is_not_carded(self):
        plan = dr.route_directive(self.project, "멈춰", tool="codex", states=ALL_ACTIVE, admitted=ALL_ADMITTED)
        self.assertEqual((plan["state"], plan["cards"]), ("STOPPED", []))


class TrafficTests(unittest.TestCase):
    """Spec 9.7 dispatcher, signalman, traffic control and 9.7-1 (card keeps going)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.project = Path(self._tmp.name)

    def route(self, text, **kw):
        kw.setdefault("states", ALL_ACTIVE)
        kw.setdefault("admitted", ALL_ADMITTED)
        calls = []
        return dr.route_directive(self.project, text, tool="claude", opener=_opener(calls), **kw), calls

    def test_borderline_topic_opens_new_card_linked_to_existing(self):
        _seed(self.project, {"U900": {"id": "U900", "title": "alpha beta gamma delta epsilon", "status": "RUNNING", "tool": "claude",
                                      "files": [], "lane": "IMPL_CODE"}})
        plan, calls = self.route("구현 alpha beta gamma yyyy zzzz")
        self.assertEqual(plan["state"], "ROUTED")
        self.assertEqual(plan["linked_to"], "U900")
        self.assertEqual(len(calls), 1)

    def test_same_file_two_cards_one_go_and_successor_auto_starts(self):
        _seed(self.project, {
            "U1": {"id": "U1", "status": "RUNNING", "tool": "claude", "files": ["f.py"], "manual": "m1.md"},
            "U2": {"id": "U2", "status": "WAITING", "tool": "codex", "files": ["f.py"], "manual": "m2.md"}})
        sig = dr.signals(self.project)
        self.assertEqual((sig["U1"]["signal"], sig["U2"]["signal"]), ("GO", "WAIT"))
        self.assertEqual(sig["U2"]["waits_for"], ["U1"])
        calls = []
        self.assertEqual(dr.advance(self.project, opener=_opener(calls)), [])
        dr.set_card_status(self.project, "U1", "DONE")
        self.assertEqual(dr.advance(self.project, opener=_opener(calls)), ["U2"])

    def test_signal_deadlock_is_broken_by_authority_order(self):
        sig = dr.compute_signals({
            "A": {"id": "A", "status": "WAITING", "tool": "claude", "files": [], "depends_on": ["B"]},
            "B": {"id": "B", "status": "WAITING", "tool": "codex", "files": [], "depends_on": ["A"]}})
        self.assertEqual((sig["B"]["signal"], sig["A"]["signal"]), ("GO", "WAIT"))  # codex outranks claude

    def test_misdelivery_is_rerouted_by_card_map(self):
        _seed(self.project, {"U327": {"id": "U327", "status": "RUNNING", "tool": "claude", "files": ["v7_harness/coord/model_router.py"], "lane": "IMPL_CODE"},
                             "U329": {"id": "U329", "status": "RUNNING", "tool": "codex", "files": ["v7_harness/coord/stall.py"], "lane": "IMPL_CODE"}})
        wrong = dr.recipient_for(self.project, "stall.py 소유권 정리 편지", addressed_card="U327")
        self.assertEqual(wrong["deliver_to"], "U329")
        self.assertTrue(wrong["rerouted"])
        self.assertEqual(wrong["ack_only"], "U327")
        right = dr.recipient_for(self.project, "v7_harness/coord/stall.py 소유권", addressed_card="U329")
        self.assertEqual((right["deliver_to"], right["rerouted"]), ("U329", False))

    def test_overloaded_tool_is_skipped_for_new_cards(self):
        _seed(self.project, {f"U{n}": {"id": f"U{n}", "status": "RUNNING", "tool": "antigravity", "files": [f"x{n}.py"], "lane": "ARCH_DESIGN"}
                             for n in range(3)})
        plan, _ = self.route("v7_harness/coord/new_mod.py 에 함수를 추가")
        self.assertNotEqual(plan["cards"][0]["tool"], "antigravity")
        self.assertEqual(plan["cards"][0]["assignment"]["skipped"]["antigravity"], "overloaded")

    def test_merge_order_dependency_first_then_smaller(self):
        _seed(self.project, {"big": {"id": "big", "status": "RUNNING", "files": ["a", "b", "c"]},
                             "small": {"id": "small", "status": "RUNNING", "files": ["d"]},
                             "dep": {"id": "dep", "status": "WAITING", "files": [], "depends_on": ["big"]}})
        self.assertEqual(dr.merge_order(self.project), ["small", "big", "dep"])

    def test_running_card_keeps_going_through_unrelated_directives_stop_only_halts(self):
        _seed(self.project, {"U900": {"id": "U900", "title": "stall fix", "status": "RUNNING", "tool": "claude",
                                      "files": ["v7_harness/coord/stall.py"], "lane": "IMPL_CODE"}})
        unrelated = ["v7_harness/coord/zeta.py 에 캐시 만료 로직을 추가", "docs/guide.md 에 설치 안내 문단을 추가",
                     "tests/test_receipt.py 에 영수증 검증 구현"]
        for text in unrelated:
            plan, _ = self.route(text)
            self.assertEqual(plan["state"], "ROUTED")  # unrelated -> its own new card
        card = _registry(self.project)["U900"]
        self.assertEqual(card["status"], "RUNNING")
        self.assertEqual(dr.take_checkpoint_addenda(self.project, "U900"), [])  # nothing unrelated injected
        related, _ = self.route("v7_harness/coord/stall.py 의 종료 조건도 고쳐라")
        self.assertEqual(related["state"], "ADDED_TO_EXISTING")
        self.assertEqual(_registry(self.project)["U900"]["status"], "RUNNING")  # not interrupted
        self.assertEqual(dr.take_checkpoint_addenda(self.project, "U900"), [related["d_id"]])  # applied once at the checkpoint
        self.assertEqual(dr.take_checkpoint_addenda(self.project, "U900"), [])
        from v7_harness.coord import desk_ledger as dl
        dl.append_directive(self.project, "stop", tool="codex")
        self.assertEqual(_registry(self.project)["U900"]["status"], "STOPPED")

    # ---- agy REVISE (relay_c8384540): Part 4/4 defects, each with a reproducing case
    def test_merge_order_null_depends_on_and_halted_dependency(self):
        _seed(self.project, {
            "A": {"id": "A", "status": "READY", "tool": "claude", "files": ["a.py"], "depends_on": None},
            "S": {"id": "S", "status": "STOPPED", "tool": "claude", "files": ["s.py"]},
            "D": {"id": "D", "status": "READY", "tool": "claude", "files": ["d.py"], "depends_on": ["S"]},
        })
        self.assertEqual(dr.merge_order(self.project), ["A"])  # None deps ok; D waits on a halted card, never "satisfied"

    def test_recipient_reroutes_duplicate_kind_too(self):
        _seed(self.project, {"U900": {"id": "U900", "title": "stall fix", "status": "RUNNING", "tool": "claude",
                                      "files": ["v7_harness/coord/stall.py"], "lane": "IMPL_CODE"}})
        out = dr.recipient_for(self.project, "v7_harness/coord/stall.py 의 종료 조건 고쳐라", addressed_card="U777")
        self.assertEqual(out["deliver_to"], "U900")
        self.assertTrue(out["rerouted"])

    def test_addenda_reject_unsafe_card_id_and_empty_take_writes_nothing(self):
        for bad in ("../x", "a/b", "U1:2", "", "con\\x", "U332\n", "NUL", "com1"):
            with self.assertRaises(ValueError):
                dr.queue_addendum(self.project, bad, "D-0001")
        self.assertEqual(dr.take_checkpoint_addenda(self.project, "U901"), [])
        self.assertFalse((dr._dir(self.project) / "U901.addenda.json").exists())

    def test_addenda_peek_then_ack_survives_crash(self):
        dr.queue_addendum(self.project, "U901", "D-0001")
        self.assertEqual(dr.take_checkpoint_addenda(self.project, "U901", commit=False), ["D-0001"])
        self.assertEqual(dr.take_checkpoint_addenda(self.project, "U901", commit=False), ["D-0001"])  # crash before ack: still there
        dr.ack_addenda(self.project, "U901", ["D-0001", "D-0001"])  # a repeated id is recorded once
        self.assertEqual(dr._read_json(dr._dir(self.project) / "U901.addenda.json", {})["applied"], ["D-0001"])
        self.assertEqual(dr.take_checkpoint_addenda(self.project, "U901"), [])

    def test_status_lines_bounds_and_empty_title(self):
        _seed(self.project, {
            "U1": {"id": "U1", "title": "", "status": "READY", "tool": "claude"},
            "U2": {"id": "U2", "title": None, "status": "BLOCKED", "tool": None},
            "U3": {"id": "U3", "title": "third", "status": "READY", "tool": "codex"},
        })
        self.assertEqual(dr.status_lines(self.project, max_lines=0), [])
        one = dr.status_lines(self.project, max_lines=1)
        self.assertEqual(len(one), 1)
        self.assertIn("U2", one[0])  # BLOCKED is not hidden by a count line
        _seed(self.project, {
            "U1": {"id": "U1", "title": "", "status": "RUNNING", "tool": "claude"},
            "U2": {"id": "U2", "title": None, "status": "RUNNING", "tool": None},
        })
        text = "\n".join(dr.status_lines(self.project))
        self.assertNotIn("None", text.split("(U2)")[0].split("\n")[-1])
        self.assertIn("- U1 (U1)", text)


if __name__ == "__main__":
    unittest.main()
