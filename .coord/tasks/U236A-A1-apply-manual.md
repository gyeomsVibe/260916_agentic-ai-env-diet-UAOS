# U236A-A1: exact-model guard, slices 2 and 3 (cli.py wiring, manual.py lint)

Judge claude, deputy for LIMITED codex; Codex re-review owed. Both edits sit inside large functions (`_with_cap`
is nested in the pilot-run command), which the Ollama splicer cannot replace as whole top-level functions
(U236A-L2 SPLICE_UNSUPPORTED), so this 8-line non-test change goes through `worker: apply` (U98-D: Python under
20 lines). Contract and fixed acceptance: `.coord/tasks/U236A-L1-manual.md` rev 2.

```contract
work_id: U236A-A1
worker: apply
goal: pilot passes --require-model only for worker claude with model_pin exact, and lint rejects an alias under model_pin exact
inputs:
- v7_harness/cli.py
- v7_harness/manual.py
- tests/test_u236a_model_pin.py sha256=54441760f3e03595d249e5b257fb190e209e0937742cc52ecbfc053684321dd6
allow:
- v7_harness/cli.py
- v7_harness/manual.py
context_allow:
- tests/test_u236a_model_pin.py
acceptance: python -m unittest tests.test_u236a_model_pin.LintTests tests.test_u236a_model_pin.CliWiringTests tests.test_u38_cost_gate_and_claude_worker tests.test_cli tests.test_b20_model_flag tests.test_u44_claude_contract tests.test_u45_general_uaos tests.test_u46_followup_fixes tests.test_u69_admission_gate tests.test_u98d_delegate_first tests.test_u106_local_first
forbidden: editing or deleting tests; changing behavior without model_pin exact; edits outside allow; network; paid model calls; commit/push
stop: two failures with the same cause; edits outside allow; no output; 900 seconds
judge: claude
timeout_s: 900
remote_budget_tokens: 0
```

===EDIT: v7_harness/cli.py===
<<<<<<< SEARCH
    def _with_cap(command: list[str], worker: str) -> list[str]:
        return [*command, "--max-budget-usd", usd_cap] if worker == "claude" and usd_cap else command
=======
    def _with_cap(command: list[str], worker: str) -> list[str]:
        if worker != "claude":
            return command
        # U236a: `model_pin: exact` makes the worker fail closed unless the run used exactly the contract's model id.
        if contract and str(contract.get("model_pin") or "") == "exact" and contract.get("model"):
            command = [*command, "--require-model", str(contract["model"])]
        return [*command, "--max-budget-usd", usd_cap] if usd_cap else command
>>>>>>> REPLACE
===END===

===EDIT: v7_harness/manual.py===
<<<<<<< SEARCH
        if usd <= 0 or usd != usd:
            report.errors.append("REMOTE_WITHOUT_USD_CAP: worker claude needs remote_budget_usd > 0")
=======
        if usd <= 0 or usd != usd:
            report.errors.append("REMOTE_WITHOUT_USD_CAP: worker claude needs remote_budget_usd > 0")
        # U236a: an alias resolves per provider, so an exact pin needs the full model id.
        if str(contract.get("model_pin") or "") == "exact" and str(contract.get("model") or "") in ("", "haiku", "sonnet", "opus"):
            report.errors.append("MODEL_ALIAS: model_pin exact needs a full model id")
>>>>>>> REPLACE
===END===

## Output

- Reply with ===FILE / ===EDIT blocks only. No explanations. Do not claim success; the acceptance command decides.
