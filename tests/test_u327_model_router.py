"""U327: release-adaptive model router. Offline only: no network, no API key, no paid call."""

from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path

from v7_harness.coord import model_router as mr

OK = {"state": "OK", "admit_paid": True}
ALL_OK = {"codex": OK, "claude": OK, "antigravity": OK}
BASE = {"quality": 0.80, "cost": 0.50, "error_rate": 0.01, "timeout_rate": 0.0}
GOOD = {"samples": 30, "quality": 0.82, "cost": 0.45, "error_rate": 0.01, "timeout_rate": 0.0}


def fake_entry(lifecycle: str = "active", traffic: int = 100, **caps: float) -> dict:
    capabilities = {"reasoning": 1.0, "accuracy": 1.0, "cost": 1.0, "speed": 1.0, "coding": 1.0, "context": 1.0,
                    "latency": 1.0, "stability": 1.0}
    capabilities.update(caps)
    return {
        "tool": "codex", "model_id": "test-model-x", "display": "Test Model X", "roles": ["helper"],
        "thinking_levels": ["Low", "Medium", "High"], "thinking_param_name": "reasoning_effort",
        "status": "active", "released_at": "2026-11-20", "relative_cost": 1, "lifecycle": lifecycle, "traffic_pct": traffic, "paid": True,
        "capabilities": capabilities,
        "source_url": "https://developers.openai.com/codex/models", "why": "fake model for the U327 test",
    }


class RegistryCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "model_registry.json"
        self.path.write_text(mr.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    def add(self, entry: dict) -> None:
        reg = json.loads(self.path.read_text(encoding="utf-8"))
        reg["models"].append(entry)
        self.path.write_text(json.dumps(reg), encoding="utf-8")

    def entry(self, model_id: str) -> dict:
        return next(m for m in mr.load_registry(self.path)["models"] if m["model_id"] == model_id)


class TestRegistry(RegistryCase):
    def test_day0_registry_is_valid_and_matches_old_lineup(self) -> None:
        reg = mr.load_registry()
        ids = {(m["tool"], m["model_id"]) for m in reg["models"]}
        self.assertEqual(ids, {("codex", "gpt-6.1-sol"), ("codex", "gpt-6-luna"), ("codex", "gpt-6-astra"),
                               ("antigravity", "gemini-4-argon"), ("antigravity", "gemini-3.5-flash-lite"),
                               ("claude", "claude-opus-5-5"), ("claude", "claude-haiku-5-5"),
                               ("ollama", "qwen2.5-coder:7b")})
        self.assertEqual(mr.seat_model(reg, "codex", "primary")["model_id"], "gpt-6.1-sol")
        self.assertEqual(mr.seat_model(reg, "claude", "helper")["model_id"], "claude-haiku-5-5")
        self.assertEqual(mr.keypoint_model(reg, "codex")["model_id"], "gpt-6-astra")
        self.assertIsNone(mr.keypoint_model(reg, "claude"))

    def test_keypoint_model_ranked_by_fitness_not_list_order(self) -> None:
        weak = fake_entry(reasoning=0.1, accuracy=0.1, cost=0.1)
        weak.update(model_id="test-keypoint-weak", roles=["primary"], keypoint_only=True)
        strong = fake_entry(reasoning=1.0, accuracy=1.0, cost=1.0)
        strong.update(model_id="test-keypoint-strong", roles=["primary"], keypoint_only=True)
        for order in ((strong, weak), (weak, strong)):
            reg = copy.deepcopy(mr.load_registry())
            reg["models"] = [m for m in reg["models"] if not m.get("keypoint_only")] + [copy.deepcopy(e) for e in order]
            self.assertEqual(mr.keypoint_model(reg, "codex")["model_id"], "test-keypoint-strong")

    def test_seed_weights_carry_a_why(self) -> None:
        profiles = mr.load_registry()["task_profiles"]
        self.assertEqual(profiles["architecture"]["weights"], {"reasoning": 0.6, "accuracy": 0.3, "cost": 0.1})
        self.assertEqual(profiles["bulk_summary"]["weights"], {"speed": 0.5, "cost": 0.4, "accuracy": 0.1})
        self.assertEqual(profiles["code_gen"]["weights"], {"coding": 0.7, "context": 0.3})
        self.assertEqual(profiles["realtime"]["weights"], {"latency": 0.6, "stability": 0.3, "cost": 0.1})
        for p in profiles.values():
            self.assertTrue(p["why"].strip())
            self.assertAlmostEqual(sum(p["weights"].values()), 1.0)

    def test_non_official_source_url_is_rejected(self) -> None:
        bad = fake_entry()
        bad["source_url"] = "https://example.com/blog"
        reg = mr.load_registry()
        reg["models"].append(bad)
        with self.assertRaises(ValueError):
            mr.validate_registry(reg)


class TestSelection(RegistryCase):
    def test_a_new_model_is_selected_with_zero_py_edit(self) -> None:
        before = mr.select_model("codex", "code_gen", {"roles": ["helper"]}, ALL_OK, registry_file=self.path)
        self.assertEqual(before["model_id"], "gpt-6-luna")
        self.add(fake_entry())  # a data edit only
        after = mr.select_model("codex", "code_gen", {"roles": ["helper"]}, ALL_OK, registry_file=self.path)
        self.assertEqual(after["model_id"], "test-model-x")
        self.assertEqual(after["thinking_param_name"], "reasoning_effort")
        # the shipped registry is untouched
        self.assertNotIn("test-model-x", mr.DEFAULT_REGISTRY_PATH.read_text(encoding="utf-8"))

    def test_nature_profiles_pick_different_models(self) -> None:
        arch = mr.select_model("claude", "architecture", {}, ALL_OK)
        self.assertEqual((arch["model_id"], arch["thinking_level"]), ("claude-opus-5-5", "High"))
        bulk = mr.select_model(None, "bulk_summary", {}, ALL_OK)
        self.assertEqual((bulk["tool"], bulk["route"]), ("ollama", "local"))
        self.assertEqual(bulk["thinking_level"], None)
        code = mr.select_model("antigravity", "IMPL_CODE", {}, ALL_OK)
        self.assertEqual((code["nature"], code["thinking_level"]), ("code_gen", "Medium"))

    def test_keypoint_model_only_on_explicit_keypoint(self) -> None:
        plain = mr.select_model("codex", "architecture", {}, ALL_OK)
        self.assertNotEqual(plain["model_id"], "gpt-6-astra")
        key = mr.select_model("codex", "architecture", {"keypoint": True}, ALL_OK)
        self.assertEqual(key["model_id"], "gpt-6-astra")

    def test_quota_pressure_lowers_thinking_but_not_for_architecture(self) -> None:
        hot = {"claude": {"state": "OK", "used_pct": 85.0}}
        self.assertEqual(mr.select_model("claude", "code_gen", {}, hot)["thinking_level"], "Low")
        self.assertEqual(mr.select_model("claude", "architecture", {}, hot)["thinking_level"], "High")

    def test_unknown_nature_does_not_escalate(self) -> None:
        self.assertEqual(mr.select_model("codex", "???", {}, ALL_OK)["nature"], "code_gen")


class TestQuotaFailsClosed(RegistryCase):
    def test_c_unknown_or_missing_quota_has_no_paid_route(self) -> None:
        for quota in ({}, None, {"codex": {"state": "UNKNOWN"}}, {"codex": {"state": "UNKNOWN", "used_pct": 1.0}},
                      {"codex": {"state": "LIMITED"}}, {"codex": "OK"}):
            got = mr.select_model("codex", "architecture", {}, quota)
            self.assertEqual((got["route"], got["model_id"]), ("NONE", None), quota)
            self.assertIn("gpt-6.1-sol", got["blocked_paid"])

    def test_c_local_route_survives_unknown_quota_and_low_pct_is_not_tokens(self) -> None:
        got = mr.select_model(None, "bulk_summary", {}, {"codex": {"state": "UNKNOWN", "used_pct": 0.0}})
        self.assertEqual((got["route"], got["model_id"]), ("local", "qwen2.5-coder:7b"))
        self.assertEqual(got["weighted_tokens_spent"], 0.0)  # a quota percentage is never turned into a token count

    def test_c_allow_paid_false_never_returns_paid(self) -> None:
        got = mr.select_model(None, "architecture", {"allow_paid": False}, ALL_OK)
        self.assertEqual(got["tool"], "ollama")


class TestLifecycle(RegistryCase):
    policy = mr.load_registry()["rollout_policy"]

    def test_b_failed_shadow_metrics_roll_back_and_persist(self) -> None:
        self.add(fake_entry("shadow", 5))
        bad = dict(GOOD, error_rate=0.20)
        d = mr.advance_rollout("codex", "test-model-x", bad, BASE, self.path)
        self.assertEqual(d["action"], "rollback")
        e = self.entry("test-model-x")
        self.assertEqual((e["lifecycle"], e["traffic_pct"]), ("rolled_back", 0))
        self.assertIn("error spike", e["rollback_reason"])
        got = mr.select_model("codex", "code_gen", {"roles": ["helper"]}, ALL_OK, registry_file=self.path)
        self.assertEqual(got["model_id"], "gpt-6-luna")

    def test_b_failed_canary_rolls_back_on_timeout_and_quality_drop(self) -> None:
        for bad, why in ((dict(GOOD, timeout_rate=0.10), "timeout"), (dict(GOOD, quality=0.70), "quality drop")):
            self.add(fake_entry("canary", 20))
            d = mr.advance_rollout("codex", "test-model-x", bad, BASE, self.path)
            self.assertEqual(d["action"], "rollback")
            self.assertIn(why, d["reason"])
            reg = mr.load_registry(self.path)
            reg["models"] = [m for m in reg["models"] if m["model_id"] != "test-model-x"]
            self.path.write_text(json.dumps(reg), encoding="utf-8")

    def test_d_canary_step_progression_5_20_50_100_active(self) -> None:
        self.add(fake_entry("shadow", 5))
        seen = []
        for _ in range(5):
            d = mr.advance_rollout("codex", "test-model-x", GOOD, BASE, self.path)
            self.assertEqual(d["action"], "promote")
            e = self.entry("test-model-x")
            seen.append((e["lifecycle"], e["traffic_pct"]))
        self.assertEqual(seen, [("canary", 5), ("canary", 20), ("canary", 50), ("canary", 100), ("active", 100)])

    def test_advance_rollout_is_serialized_under_real_parallel_calls(self) -> None:
        self.add(fake_entry("shadow", 5))
        barrier = threading.Barrier(5)
        actions: list[str] = []

        def go() -> None:
            barrier.wait()
            actions.append(mr.advance_rollout("codex", "test-model-x", GOOD, BASE, self.path)["action"])

        threads = [threading.Thread(target=go) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(actions, ["promote"] * 5)  # a lost update would leave the entry short of "active"
        e = self.entry("test-model-x")
        self.assertEqual((e["lifecycle"], e["traffic_pct"]), ("active", 100))

    def test_unknown_model_id_is_charged_the_priciest_weight(self) -> None:
        reg = mr.load_registry()
        worst = max(float(m["relative_cost"]) for m in reg["models"])
        self.assertEqual(mr.weighted_token_use([{"model_id": "never-heard-of-it", "tokens": 10}], reg), 10 * worst)

    def test_official_lineup_is_live_not_frozen_at_import(self) -> None:
        import os

        from v7_harness.coord import helper_thinking_router as htr

        reg = mr.load_registry()
        for m in reg["models"]:
            if m["model_id"] == "claude-haiku-5-5":
                m["model_id"] = "claude-haiku-9-9"
        reg_file = Path(self._tmp.name) / "live.json"
        reg_file.write_text(json.dumps(reg), encoding="utf-8")
        before = htr.get_official_tool_lineup("claude")["primary_helper_model"]
        self.assertEqual(before, "claude-haiku-5-5")
        old = os.environ.get(mr.REGISTRY_ENV)
        os.environ[mr.REGISTRY_ENV] = str(reg_file)
        try:
            self.assertEqual(htr.get_official_tool_lineup("claude")["primary_helper_model"], "claude-haiku-9-9")
        finally:
            if old is None:
                os.environ.pop(mr.REGISTRY_ENV)
            else:
                os.environ[mr.REGISTRY_ENV] = old

    def test_d_hold_when_few_samples_or_no_criterion(self) -> None:
        e = fake_entry("canary", 5)
        self.assertEqual(mr.evaluate_rollout(e, dict(GOOD, samples=3), BASE, self.policy)["action"], "hold")
        worse_pricier = dict(GOOD, quality=0.795, cost=0.60)  # within the drop tolerance, not better, not cheaper
        self.assertEqual(mr.evaluate_rollout(e, worse_pricier, BASE, self.policy)["action"], "hold")

    def test_d_quality_plus_10_percent_promotes_even_if_pricier(self) -> None:
        e = fake_entry("canary", 5)
        better = dict(GOOD, quality=0.80 * 1.10, cost=0.90)
        self.assertEqual(mr.evaluate_rollout(e, better, BASE, self.policy)["next_traffic_pct"], 20)

    def test_equal_cost_and_equal_quality_promotes(self) -> None:
        e = fake_entry("canary", 50)
        self.assertEqual(mr.evaluate_rollout(e, dict(GOOD, quality=0.80, cost=0.50), BASE, self.policy)["next_traffic_pct"], 100)

    def test_canary_only_serves_its_traffic_bucket(self) -> None:
        self.add(fake_entry("canary", 20))
        hits = 0
        for i in range(200):
            got = mr.select_model("codex", "code_gen", {"roles": ["helper"], "card_id": f"U{i}"}, ALL_OK,
                                  registry_file=self.path)
            hits += got["model_id"] == "test-model-x"
        self.assertTrue(10 <= hits <= 80, hits)  # ~20 % of 200, deterministic per card id
        again = mr.select_model("codex", "code_gen", {"roles": ["helper"], "card_id": "U7"}, ALL_OK, registry_file=self.path)
        same = mr.select_model("codex", "code_gen", {"roles": ["helper"], "card_id": "U7"}, ALL_OK, registry_file=self.path)
        self.assertEqual(again["model_id"], same["model_id"])

    def test_shadow_never_serves_but_is_judged_by_an_independent_tool(self) -> None:
        self.add(fake_entry("shadow", 100))
        got = mr.select_model("codex", "code_gen", {"roles": ["helper"], "card_id": "U1"}, ALL_OK, registry_file=self.path)
        self.assertEqual(got["model_id"], "gpt-6-luna")
        sh = got["shadow_eval"]
        self.assertEqual(sh["model_id"], "test-model-x")
        self.assertNotIn(sh["judge_tool"], ("codex",))

    def test_apply_is_pure(self) -> None:
        reg = mr.load_registry()
        snap = copy.deepcopy(reg)
        mr.apply_rollout_decision(reg, "codex", "gpt-6-luna", {"action": "rollback", "reason": "x"})
        self.assertEqual(reg, snap)


class TestAddendum(RegistryCase):
    def test_A_deprecated_is_skipped_and_vendor_allowlist_is_host_based(self) -> None:
        self.add(fake_entry())
        arg = ("codex", "code_gen", {"roles": ["helper"]}, ALL_OK)
        self.assertEqual(mr.select_model(*arg, registry_file=self.path)["model_id"], "test-model-x")
        reg = json.loads(self.path.read_text(encoding="utf-8"))
        next(m for m in reg["models"] if m["model_id"] == "test-model-x")["status"] = "deprecated"
        self.path.write_text(json.dumps(reg), encoding="utf-8")
        self.assertEqual(mr.select_model(*arg, registry_file=self.path)["model_id"], "gpt-6-luna")
        allow = tuple(mr.load_registry()["source_allowlist"])
        for good in ("https://docs.anthropic.com/x", "https://platform.openai.com/x", "https://ai.google.dev/x",
                     "https://ollama.com/library/x"):
            self.assertTrue(mr._vendor_url_ok(good, allow), good)
        for bad in ("http://ollama.com/x", "https://ollama.com.evil.io/x", "https://evil.io/openai.com",
                    "https://notopenai.com/x"):
            self.assertFalse(mr._vendor_url_ok(bad, allow), bad)
        for field, value in (("status", "available"), ("released_at", "yesterday"), ("relative_cost", -1)):
            broken = mr.load_registry()
            broken["models"][0][field] = value
            with self.assertRaises(ValueError):
                mr.validate_registry(broken)
        missing = mr.load_registry()
        del missing["models"][0]["released_at"]
        with self.assertRaises(ValueError):
            mr.validate_registry(missing)

    def test_B_med_policy_one_down_step_only_when_retry_is_zero(self) -> None:
        strict = mr.select_model("claude", "architecture", {}, ALL_OK)
        med0 = mr.select_model("claude", "architecture", {"risk_policy": "med", "retry": 0}, ALL_OK)
        med1 = mr.select_model("claude", "architecture", {"risk_policy": "med", "retry": 1}, ALL_OK)
        self.assertEqual((strict["thinking_level"], med0["thinking_level"], med1["thinking_level"]),
                         ("High", "Medium", "High"))
        self.assertIs(med0["acceptance_weakened"], False)
        hot = {"claude": {"state": "OK", "used_pct": 90.0}}  # pressure + med must not stack into two steps
        stacked = mr.select_model("claude", "code_gen", {"risk_policy": "med", "retry": 0}, hot)
        self.assertEqual(stacked["thinking_level"], "Low")  # Medium -> Low once, not below
        with self.assertRaises(ValueError):
            mr.select_model("claude", "code_gen", {"risk_policy": "yolo"}, ALL_OK)

    def test_C_bootstrap_cold_start_bands_and_relative_cost(self) -> None:
        boot = {"codex": {"state": "BOOTSTRAP", "receipts": 0, "health": "OK", "auth": "OK"}}
        got = mr.select_model("codex", "architecture", {}, boot)
        self.assertEqual((got["route"], got["bootstrap"], got["bootstrap_cap_tokens"]), ("paid", True, 12000))
        # unknown health/auth, an existing receipt, or a spent cap closes the bootstrap route again
        for bad in ({**boot["codex"], "health": "UNKNOWN"}, {**boot["codex"], "auth": "UNKNOWN"},
                    {**boot["codex"], "receipts": 1}):
            self.assertEqual(mr.select_model("codex", "architecture", {}, {"codex": bad})["route"], "NONE", bad)
        reg = mr.load_registry()
        usage = [{"model_id": "gpt-6.1-sol", "tokens": 1000}, {"model_id": "gpt-6-luna", "tokens": 1000}]
        self.assertEqual(mr.weighted_token_use(usage, reg), 1000 * 8 + 1000 * 1)  # relative_cost weights the mix
        spent = mr.select_model("codex", "architecture", {"card_usage": [{"model_id": "gpt-6.1-sol", "tokens": 1500}]}, boot)
        self.assertEqual(spent["route"], "NONE")  # 1,500 x 8 = 12,000 reaches the hard cap
        # 5h and weekly bands are separate; the worse one wins
        split = {"codex": {"five_hour": {"state": "OK", "used_pct": 10.0}, "seven_day": {"state": "UNKNOWN"}}}
        self.assertEqual(mr.quota_view(split["codex"])[0], "UNKNOWN")
        self.assertEqual(mr.select_model("codex", "architecture", {}, split)["route"], "NONE")
        both = {"codex": {"five_hour": {"state": "OK", "used_pct": 10.0}, "seven_day": {"state": "OK", "used_pct": 75.0}}}
        self.assertEqual(mr.quota_view(both["codex"]), ("OK", 75.0))
        self.assertEqual(mr.select_model("codex", "code_gen", {}, both)["thinking_level"], "Low")  # weekly band drives pressure


class TestHardening(RegistryCase):
    def test_partial_quota_band_fails_closed(self) -> None:
        self.assertEqual(mr.quota_view({"five_hour": {"state": "OK", "used_pct": 5.0}})[0], "UNKNOWN")
        self.assertEqual(mr.quota_view({"seven_day": {"state": "OK", "used_pct": 5.0}})[0], "UNKNOWN")
        # same bands, both present: only the missing band made the difference
        self.assertEqual(mr.quota_view({"five_hour": {"state": "OK", "used_pct": 5.0},
                                        "seven_day": {"state": "OK", "used_pct": 5.0}})[0], "OK")
        self.assertEqual(mr.select_model("codex", "architecture", {},
                                         {"codex": {"five_hour": {"state": "OK", "used_pct": 5.0}}})["route"], "NONE")

    def test_validate_rejects_bool_numbers_and_bad_or_duplicate_ids(self) -> None:
        base = mr.load_registry()
        for field, bad in (("relative_cost", True), ("traffic_pct", True)):
            reg = copy.deepcopy(base)
            reg["models"][0][field] = bad
            with self.assertRaises(ValueError):
                mr.validate_registry(reg)
        reg = copy.deepcopy(base)
        reg["models"][0]["model_id"] = "  "
        with self.assertRaises(ValueError):
            mr.validate_registry(reg)
        reg = copy.deepcopy(base)
        reg["models"].append(copy.deepcopy(reg["models"][0]))
        with self.assertRaises(ValueError):
            mr.validate_registry(reg)
        # display is required for every model; thinking_param_name only for paid models
        reg = copy.deepcopy(base)
        reg["models"][0].pop("display")
        with self.assertRaises(ValueError):
            mr.validate_registry(reg)
        paid = next(m for m in base["models"] if m.get("paid", True))
        reg = copy.deepcopy(base)
        next(m for m in reg["models"] if m["model_id"] == paid["model_id"]).pop("thinking_param_name")
        with self.assertRaises(ValueError):
            mr.validate_registry(reg)
        local = next(m for m in base["models"] if m.get("paid") is False)
        reg = copy.deepcopy(base)
        next(m for m in reg["models"] if m["model_id"] == local["model_id"]).pop("thinking_param_name", None)
        mr.validate_registry(reg)  # a local calculator needs none

    def test_stale_holder_write_is_refused_after_another_writer_moved_the_revision(self) -> None:
        self.add(fake_entry("shadow", 5))
        reg = mr.load_registry(self.path)
        seen = int(reg.get("revision", 0))  # a paused holder read the file at this revision
        mr.advance_rollout("codex", "test-model-x", GOOD, BASE, self.path)  # a newer holder wrote meanwhile
        landed = self.entry("test-model-x")
        self.assertEqual(landed["lifecycle"], "canary")
        stale = copy.deepcopy(reg)
        next(m for m in stale["models"] if m["model_id"] == "test-model-x")["lifecycle"] = "rolled_back"
        with self.assertRaises(mr.RegistryConflict):
            mr._commit_if_revision(stale, seen, self.path)  # the paused holder wakes and tries to write
        self.assertEqual(self.entry("test-model-x"), landed)  # its write did not land

    def test_revision_increases_by_one_per_write(self) -> None:
        self.add(fake_entry("shadow", 5))
        before = int(mr.load_registry(self.path).get("revision", 0))
        mr.advance_rollout("codex", "test-model-x", GOOD, BASE, self.path)
        self.assertEqual(int(mr.load_registry(self.path).get("revision", 0)), before + 1)

    def test_lock_is_held_by_the_os_across_real_processes_and_freed_when_holder_dies(self) -> None:
        import os
        import subprocess
        import sys

        root = str(Path(__file__).resolve().parents[1])
        code = (
            "import sys,time;from v7_harness.coord import model_router as mr\n"
            "with mr._registry_lock(sys.argv[1]):\n"
            "    print('held',flush=True);time.sleep(60)\n"
        )
        holder = subprocess.Popen([sys.executable, "-c", code, str(self.path)], cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), "held")
            old = mr._LOCK_WAIT_S
            mr._LOCK_WAIT_S = 0.4
            try:
                # Age is irrelevant: even an ancient-looking lock file stays owned while the holder lives.
                lock = Path(str(self.path) + ".lock")
                os.utime(lock, (1, 1))
                with self.assertRaises(TimeoutError):
                    with mr._registry_lock(self.path):
                        pass
            finally:
                mr._LOCK_WAIT_S = old
        finally:
            holder.kill()
            holder.wait()
            holder.stdout.close()
        self.add(fake_entry("shadow", 5))
        self.assertEqual(mr.advance_rollout("codex", "test-model-x", GOOD, BASE, self.path)["action"], "promote")

    def test_competing_threads_never_hold_the_lock_together(self) -> None:
        inside = [0]
        worst = [0]
        guard = threading.Lock()
        barrier = threading.Barrier(6)

        def work() -> None:
            barrier.wait()
            with mr._registry_lock(self.path):
                with guard:
                    inside[0] += 1
                    worst[0] = max(worst[0], inside[0])
                threading.Event().wait(0.01)
                with guard:
                    inside[0] -= 1

        threads = [threading.Thread(target=work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(worst[0], 1)

    def test_missing_seat_or_helper_keys_raise_a_clear_value_error(self) -> None:
        from v7_harness.coord import helper_thinking_router as htr

        reg = mr.load_registry()
        for m in reg["models"]:
            if m["tool"] == "claude" and "helper" in m["roles"]:
                m.pop("helper_subagent")
        with self.assertRaises(ValueError):
            htr._build_lineup("claude", reg)
        reg = mr.load_registry()
        for m in reg["models"]:
            if m["tool"] == "claude" and "helper" in m["roles"]:
                m.pop("helper_telemetry_lane")
        with self.assertRaises(ValueError):
            htr._build_lineup("claude", reg)
        reg = mr.load_registry()
        reg["models"] =[m for m in reg["models"] if m["tool"] != "antigravity"]
        with self.assertRaises(ValueError):
            htr._build_lineup("antigravity", reg)


if __name__ == "__main__":
    unittest.main()
