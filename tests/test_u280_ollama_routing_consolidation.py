"""U280: Ollama accepted-work task-fit routing consolidation into v7_harness.worker_routing."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

from v7_harness.worker_routing import (
    EDIT_LINES,
    evaluate_ollama_task_fit,
    forecast,
    plan,
    select_pool_worker,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


class TestU280OllamaRoutingConsolidation(unittest.TestCase):
    def base_task(self, **overrides):
        task = {
            'caller': 'codex',
            'kind': 'edit',
            'input_tokens': 800,
            'output_tokens': 200,
            'changed_lines': 8,
            'local_qualified': True,
            'local_failures': 0,
            'allow_remote': False,
            'budget_tokens': 3000,
            'budget_usd': 0.04,
            'timeout_s': 60,
        }
        task.update(overrides)
        return task

    def test_01_precedence_1_touches_evaluator_flag_refuses_local(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            touches_evaluator=True,
            exact_dictation=True,
            same_cause_failures=0,
            functions=1,
            changed_lines=5,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res['verdict'], 'REFUSE_LOCAL_EVALUATOR_OR_GATE')
        self.assertFalse(res['local_qualified'])
        self.assertEqual(res['worker'], 'conductor')
        self.assertFalse(res['execution_authorized'])

    def test_02_precedence_1_evaluator_or_gate_file_paths_refuse_local(self):
        for path in (
            'v7_harness/judge.py',
            'v7_harness/calculator_gate.py',
            'v7_harness/firewall_audit.py',
            'v7_harness/coord/stop_gate.py',
            'tests/test_u280_ollama_routing_consolidation.py',
        ):
            with self.subTest(path=path):
                res = evaluate_ollama_task_fit(
                    kind='patch',
                    target_files=[path],
                    functions=1,
                    changed_lines=4,
                    exact_search_block=True,
                    pinned_acceptance=True,
                )
                self.assertEqual(res['verdict'], 'REFUSE_LOCAL_EVALUATOR_OR_GATE')
                self.assertFalse(res['local_qualified'])

    def test_03_precedence_1_security_or_consensus_judgment_kinds_refuse_local(self):
        for kind in ('final_approval', 'security_judgment', 'concurrency_judgment', 'evaluator', 'security', 'consensus', 'gate'):
            with self.subTest(kind=kind):
                res = evaluate_ollama_task_fit(kind=kind, source_verified=True)
                self.assertEqual(res['verdict'], 'REFUSE_LOCAL_EVALUATOR_OR_GATE')
                self.assertEqual(res['worker'], 'conductor')

    def test_04_precedence_1_beats_precedence_2_and_3(self):
        res = evaluate_ollama_task_fit(
            kind='deterministic',
            touches_evaluator=True,
            exact_dictation=True,
            same_cause_failures=5,
        )
        self.assertEqual(res['verdict'], 'REFUSE_LOCAL_EVALUATOR_OR_GATE')

    def test_05_precedence_2_exact_dictation_routes_deterministic_first(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            exact_dictation=True,
            same_cause_failures=3,
            changed_lines=10,
        )
        self.assertEqual(res['verdict'], 'DETERMINISTIC_APPLY_FIRST')
        self.assertEqual(res['worker'], 'deterministic')
        self.assertFalse(res['local_qualified'])

    def test_06_precedence_2_zero_change_patch_routes_deterministic_first(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            changed_lines=0,
            functions=1,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res['verdict'], 'DETERMINISTIC_APPLY_FIRST')
        self.assertEqual(res['worker'], 'deterministic')

    def test_07_precedence_2_exact_operation_kinds_route_deterministic_first(self):
        for kind in ('count', 'hash', 'validate', 'extract_exact', 'deterministic'):
            with self.subTest(kind=kind):
                res = evaluate_ollama_task_fit(kind=kind, changed_lines=0)
                self.assertEqual(res['verdict'], 'DETERMINISTIC_APPLY_FIRST')
                self.assertEqual(res['worker'], 'deterministic')

    def test_08_precedence_3_same_cause_failures_at_2_quarantines_local(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            same_cause_failures=2,
            functions=1,
            changed_lines=5,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res['verdict'], 'QUARANTINE_LOCAL_SAME_CAUSE')
        self.assertFalse(res['local_qualified'])
        self.assertIsNone(res['worker'])

    def test_09_precedence_3_same_cause_failures_beats_preprocess_and_patch(self):
        res = evaluate_ollama_task_fit(
            kind='map',
            same_cause_failures=3,
            source_verified=True,
        )
        self.assertEqual(res['verdict'], 'QUARANTINE_LOCAL_SAME_CAUSE')
        self.assertFalse(res['local_qualified'])

    def test_10_precedence_3_single_failure_still_allows_qualified_work(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            same_cause_failures=1,
            functions=1,
            changed_lines=10,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res['verdict'], 'ALLOW_LOCAL_MICRO_PATCH')
        self.assertTrue(res['local_qualified'])

    def test_11_precedence_4_whole_file_rewrite_escalates_for_bounded_slice(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            whole_file_rewrite=True,
            functions=1,
            changed_lines=10,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')
        self.assertFalse(res['local_qualified'])

    def test_12_precedence_4_changed_lines_over_20_escalates(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            functions=1,
            changed_lines=EDIT_LINES + 1,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')
        self.assertFalse(res['local_qualified'])

    def test_13_precedence_4_multi_file_architecture_or_multiple_targets_escalates(self):
        res_flag = evaluate_ollama_task_fit(
            kind='patch',
            multi_file_architecture=True,
            functions=1,
            changed_lines=5,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res_flag['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')

        res_files = evaluate_ollama_task_fit(
            kind='patch',
            target_files=['v7_harness/a.py', 'v7_harness/b.py'],
            functions=1,
            changed_lines=5,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res_files['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')

    def test_14_precedence_4_multi_function_patch_escalates(self):
        res = evaluate_ollama_task_fit(
            kind='patch',
            functions=2,
            changed_lines=8,
            exact_search_block=True,
            pinned_acceptance=True,
        )
        self.assertEqual(res['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')
        self.assertFalse(res['local_qualified'])

    def test_15_precedence_5_narrow_preprocess_with_source_verification_allowed(self):
        for kind in ('map', 'draft', 'summarize', 'classify', 'extract', 'extract_semantic', 'transform'):
            with self.subTest(kind=kind):
                res = evaluate_ollama_task_fit(
                    kind=kind,
                    source_verified=True,
                    changed_lines=0,
                )
                self.assertEqual(res['verdict'], 'ALLOW_LOCAL_PREPROCESS')
                self.assertTrue(res['local_qualified'])
                self.assertEqual(res['worker'], 'local')

    def test_16_precedence_5_preprocess_without_source_verification_escalates(self):
        for kind in ('map', 'draft', 'summarize'):
            with self.subTest(kind=kind):
                res = evaluate_ollama_task_fit(kind=kind, source_verified=False)
                self.assertEqual(res['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')
                self.assertFalse(res['local_qualified'])

    def test_17_precedence_6_single_function_micro_patch_at_boundary_20_lines_allowed(self):
        for lines in (1, 12, EDIT_LINES):
            with self.subTest(lines=lines):
                res = evaluate_ollama_task_fit(
                    kind='patch',
                    target_files=['v7_harness/coord/desk_delta.py'],
                    functions=1,
                    changed_lines=lines,
                    exact_search_block=True,
                    pinned_acceptance=True,
                )
                self.assertEqual(res['verdict'], 'ALLOW_LOCAL_MICRO_PATCH')
                self.assertTrue(res['local_qualified'])
                self.assertEqual(res['worker'], 'local')

    def test_18_precedence_6_patch_missing_exact_search_or_pinned_acceptance_escalates(self):
        no_search = evaluate_ollama_task_fit(
            kind='patch',
            functions=1,
            changed_lines=5,
            exact_search_block=False,
            pinned_acceptance=True,
        )
        self.assertEqual(no_search['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')
        self.assertFalse(no_search['local_qualified'])

        no_gate = evaluate_ollama_task_fit(
            kind='patch',
            functions=1,
            changed_lines=5,
            exact_search_block=True,
            pinned_acceptance=False,
        )
        self.assertEqual(no_gate['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')
        self.assertFalse(no_gate['local_qualified'])

    def test_19_invalid_types_and_booleans_fail_closed(self):
        bad_cases = [
            ({'kind': ''}, 'INVALID_TASK_KIND'),
            ({'kind': None}, 'INVALID_TASK_KIND'),
            ({'kind': 'patch', 'same_cause_failures': True}, 'INVALID_COUNTERS'),
            ({'kind': 'patch', 'changed_lines': -1}, 'INVALID_COUNTERS'),
            ({'kind': 'patch', 'functions': '1'}, 'INVALID_COUNTERS'),
            ({'kind': 'map', 'source_verified': 'yes'}, 'INVALID_BOOLEAN_FLAGS'),
            ({'kind': 'patch', 'touches_evaluator': 1}, 'INVALID_BOOLEAN_FLAGS'),
            ({'kind': 'patch', 'target_files': 'v7_harness/a.py'}, 'INVALID_TARGET_FILES'),
        ]
        for kwargs, expected_reason in bad_cases:
            with self.subTest(kwargs=kwargs):
                res = evaluate_ollama_task_fit(**kwargs)
                self.assertEqual(res['verdict'], 'ESCALATE_BOUNDED_SLICE_REQUIRED')
                self.assertFalse(res['local_qualified'])
                self.assertEqual(res['reason'], expected_reason)

    def test_20_plan_integration_derives_qualification_and_blocks_evaluator_files(self):
        micro_task = {
            'caller': 'antigravity',
            'kind': 'patch',
            'input_tokens': 1000,
            'output_tokens': 200,
            'changed_lines': 10,
            'local_failures': 0,
            'allow_remote': False,
            'timeout_s': 60,
            'functions': 1,
            'exact_search_block': True,
            'pinned_acceptance': True,
            'target_files': ['v7_harness/coord/lanes.py'],
        }
        routed = select_pool_worker(micro_task, {'local': True, 'haiku': True})
        self.assertEqual(routed['status'], 'READY')
        self.assertEqual(routed['worker'], 'local')
        self.assertEqual(routed['model'], 'qwen2.5-coder:7b')

        eval_task = dict(micro_task, target_files=['v7_harness/judge.py'])
        eval_routed = plan(eval_task, {'local': True, 'haiku': True})
        self.assertEqual(eval_routed['worker'], 'conductor')
        self.assertEqual(eval_routed['reason'], 'REFUSE_LOCAL_EVALUATOR_OR_GATE')

    def test_21_plan_integration_routes_exact_dictation_to_deterministic(self):
        dictation_task = self.base_task(
            kind='edit',
            changed_lines=6,
            exact_dictation=True,
        )
        routed = plan(dictation_task, {'local': True, 'haiku': True})
        self.assertEqual(routed['status'], 'READY')
        self.assertEqual(routed['worker'], 'deterministic')
        self.assertEqual(routed['reason'], 'DETERMINISTIC_APPLY_FIRST')

    def test_22_backward_compatibility_with_u237_and_u281_contracts(self):
        local_res = select_pool_worker(self.base_task(), {'local': True, 'haiku': True})
        self.assertEqual(local_res['worker'], 'local')
        self.assertEqual(local_res['model'], 'qwen2.5-coder:7b')

        haiku_res = select_pool_worker(
            self.base_task(local_failures=2, allow_remote=True),
            {'local': True, 'haiku': True},
        )
        self.assertEqual(haiku_res['worker'], 'claude')
        self.assertEqual(haiku_res['model'], 'claude-haiku-5-5')
        self.assertEqual(haiku_res['subagent'], 'uaos-haiku-worker')

        luna_res = select_pool_worker(
            self.base_task(local_qualified=False, allow_remote=True, remote_model='gpt-6-luna'),
            {'codex': True},
        )
        self.assertEqual(luna_res['worker'], 'codex')
        self.assertEqual(luna_res['model'], 'gpt-6-luna')
        self.assertEqual(luna_res['subagent'], 'uaos-luna-worker')

        price = forecast(calls=10, input_tokens=1000, output_tokens=200)
        self.assertEqual(price['quota_saving'], 'UNMEASURED')

    def test_23_worker_routing_is_pure_with_no_subprocess_or_network_imports(self):
        src = (REPO_ROOT / 'v7_harness' / 'worker_routing.py').read_text(encoding='utf-8')
        tree = ast.parse(src)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split('.')[0])
        self.assertEqual(imported, {'math'})

    def test_24_research_note_preserves_1625_and_590_ledger_audit_and_citations(self):
        note = (
            REPO_ROOT / '.coord' / 'notes' / 'U280_ollama_accepted_work_routing_research.md'
        ).read_text(encoding='utf-8')
        self.assertIn('1625', note)
        self.assertIn('590', note)
        self.assertIn('https://docs.ollama.com/capabilities/structured-outputs', note)
        self.assertIn('https://arxiv.org/abs/2506.02153', note)
        self.assertIn('evaluate_ollama_task_fit', note)


if __name__ == '__main__':
    unittest.main()
