```contract
work_id: U304-C-A3
worker: apply
goal: Re-base the U304-C planner's main-model tiers on the merged U304-B lineup (one main per tool) and keep High effort scarce
inputs:
- v7_harness/coord/schedule_planner.py sha256=7403a7193d10d7b66e3ac6b2de1df06438bb3d31e25fa4580310aa3f48a97e42
- tests/test_u304c_schedule_planner.py sha256=ac364c9bd219867664734aa27e86e860df349ae616b17ecee19878fea829e5fb
allow:
- v7_harness/coord/schedule_planner.py
- tests/test_u304c_schedule_planner.py
- .coord/tasks/U304-C-schedule-planner.md
acceptance: python -m pytest tests/test_u304c_schedule_planner.py tests/test_u304b_helper_lineup.py -q
forbidden: edits outside allow; deleting tests; weakening any assertion other than the four stale model ids; network; commit/push
stop: two failures with the same cause; no output
judge: antigravity
timeout_s: 900
remote_budget_tokens: 0
```

## Instructions for the worker

Receipt: after merging main (PR #276, U304-B), `get_official_tool_lineup()` lists one main per tool
(codex gpt-6.1-sol + escalation gpt-6-astra, claude claude-opus-5-5 only, antigravity gemini-4-argon only).
The planner's hard-coded standard mains (gpt-6-sol, claude-sonnet-5-5, gemini-3.1-pro) no longer exist, so
4 u304c tests fail. Fix: derive the tier models from the lineup (fallback table updated to the same values), and
when a tool has no cheaper main, a non-flagship step runs its main at Medium so High stays a budget-paced
flagship grant (Opus 5.5 / Argon High stay scarce). Apply the blocks exactly.

===EDIT: v7_harness/coord/schedule_planner.py===
<<<<<<< SEARCH
# Flagship vs cheaper main per tool (윤겸스 2026-11-04 item 4: Claude Opus 5.5, Antigravity Gemini 4 Argon,
# Codex GPT-6 Astra as the flagship examples). The standard main is the next model of the same family that the
# router already uses as a main (not as a helper), so a demotion never lands on the helper itself.
MAIN_MODEL_TIERS: dict[str, dict[str, str]] = {
    "codex": {"flagship": "gpt-6-astra", "standard": "gpt-6-sol"},
    "claude": {"flagship": "claude-opus-5-5", "standard": "claude-sonnet-5-5"},
    "antigravity": {"flagship": "gemini-4-argon", "standard": "gemini-3.1-pro"},
}
=======
# Flagship vs standard main per tool (윤겸스 2026-11-04 item 4). Live values come from the U304-B lineup via
# _tier_model; this fallback mirrors that lineup of 2026-11-04 (one main per tool, no cheaper sibling main).
MAIN_MODEL_TIERS: dict[str, dict[str, str]] = {
    "codex": {"flagship": "gpt-6-astra", "standard": "gpt-6.1-sol"},
    "claude": {"flagship": "claude-opus-5-5", "standard": "claude-opus-5-5"},
    "antigravity": {"flagship": "gemini-4-argon", "standard": "gemini-4-argon"},
}


def _tier_model(tool: str, lineup: dict[str, Any], tier_key: str) -> str:
    """Flagship = lineup keypoint escalation (else its main); standard = lineup main (U304-B owns the lineup)."""
    if tier_key == "flagship":
        return str(lineup.get("keypoint_escalation_model") or lineup.get("main_model") or MAIN_MODEL_TIERS[tool]["flagship"])
    return str(lineup.get("main_model") or MAIN_MODEL_TIERS[tool]["standard"])
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/schedule_planner.py===
<<<<<<< SEARCH
    main = MAIN_MODEL_TIERS[norm][tier_key]
    model_note = f"{tier_key} main of {norm}"
=======
    main = _tier_model(norm, lineup, tier_key)
    model_note = f"{tier_key} main of {norm}"
    effort = cls["effort"]
    if cls["tier"] != "FLAGSHIP" and effort == "High" and main == _tier_model(norm, lineup, "flagship"):
        effort = "Medium"  # no cheaper main: High stays a budget-paced flagship grant
        model_note += "; High reserved for flagship grants (no cheaper main in lineup)"
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/coord/schedule_planner.py===
<<<<<<< SEARCH
        "main_effort": cls["effort"],
        "main_effort_param": {str(lineup.get("thinking_param_name") or "effort"): cls["effort"].lower()},
=======
        "main_effort": effort,
        "main_effort_param": {str(lineup.get("thinking_param_name") or "effort"): effort.lower()},
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u304c_schedule_planner.py===
<<<<<<< SEARCH
        # Same design burden, not important: High effort on the cheaper main, never the flagship.
=======
        # Same design burden, not important: never a flagship grant; with no cheaper main, Medium on the main.
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u304c_schedule_planner.py===
<<<<<<< SEARCH
        self.assertEqual((b["tier"], b["main_model"], b["main_effort"]), ("STANDARD_HIGH", "claude-sonnet-5-5", "High"))
=======
        self.assertEqual((b["tier"], b["main_model"], b["main_effort"]), ("STANDARD_HIGH", "claude-opus-5-5", "Medium"))
        c = sp.assign_step("codex", lo_imp)  # Codex keeps a cheaper main, so High effort stays on it
        self.assertEqual((c["main_model"], c["main_effort"]), ("gpt-6.1-sol", "High"))
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u304c_schedule_planner.py===
<<<<<<< SEARCH
        self.assertEqual((a["tier"], a["main_model"]), ("STANDARD_HIGH", "gpt-6-sol"))
=======
        self.assertEqual((a["tier"], a["main_model"]), ("STANDARD_HIGH", "gpt-6.1-sol"))
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u304c_schedule_planner.py===
<<<<<<< SEARCH
        # The judge is never the rerouted author: no Argon, High effort on the cheaper own main.
        j = sp.assign_step("claude", _heavy(False), allowance=allow, no_reroute=("antigravity",))
        self.assertEqual((j["tool"], j["tier"], j["main_model"], j["main_effort"]),
                         ("claude", "STANDARD_HIGH", "claude-sonnet-5-5", "High"))
=======
        # The judge is never the rerouted author: no Argon, no flagship grant; Opus without High.
        j = sp.assign_step("claude", _heavy(False), allowance=allow, no_reroute=("antigravity",))
        self.assertEqual((j["tool"], j["tier"], j["main_model"], j["main_effort"]),
                         ("claude", "STANDARD_HIGH", "claude-opus-5-5", "Medium"))
>>>>>>> REPLACE
===END===

===EDIT: tests/test_u304c_schedule_planner.py===
<<<<<<< SEARCH
        opus = sum(sp.assign_step("claude", _heavy(True), allowance=allow)["main_model"] == "claude-opus-5-5"
                   for _ in range(20))
=======
        opus = sum(sp.assign_step("claude", _heavy(True), allowance=allow)["main_effort"] == "High"
                   for _ in range(20))
>>>>>>> REPLACE
===END===

===EDIT: .coord/tasks/U304-C-schedule-planner.md===
<<<<<<< SEARCH
3. **Assign**: main model from `MAIN_MODEL_TIERS` (codex gpt-6-astra/gpt-6-sol, claude opus-5-5/sonnet-5-5, antigravity gemini-4-argon/gemini-3.1-pro), validated against the lineup;
=======
3. **Assign**: main model from the U304-B lineup (flagship = `keypoint_escalation_model`, standard = `main_model`: codex gpt-6-astra/gpt-6.1-sol, claude opus-5-5 only, antigravity gemini-4-argon only; `MAIN_MODEL_TIERS` is the fallback), validated against the lineup; a tool with no cheaper main runs non-flagship steps at `Medium`, so `High` on Opus 5.5 / Argon stays a budget-paced flagship grant (U304-C-A3, after PR #276);
>>>>>>> REPLACE
===END===
