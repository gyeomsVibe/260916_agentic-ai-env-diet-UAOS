"""Shared bounded task planner. A READY plan never grants execution or admission."""
import math

CALLERS = ('codex', 'claude', 'antigravity')
EXACT = ('count', 'hash', 'validate', 'extract_exact')
JUDGMENTS = ('final_approval', 'security_judgment', 'concurrency_judgment')
LOCAL_TASKS = ('transform', 'draft', 'summarize', 'edit', 'classify', 'extract_semantic')
# Existing Ollama defaults in adapters/ollama_worker.py; U198 bounds one edit slice.
LOCAL_CONTEXT = 16384
LOCAL_OUTPUT = 4096
EDIT_LINES = 20
# Standing circuit-breaker rule (AGENTS.md & docs/01): after 2 failures of the same cause, stop the local route.
MAX_LOCAL_SAME_CAUSE_FAILURES = 2
HAIKU = 'claude-haiku-5-5'

OLLAMA_PREPROCESS_KINDS = ('map', 'draft', 'summarize', 'classify', 'extract', 'extract_semantic', 'transform')
OLLAMA_PATCH_KINDS = ('patch', 'edit', 'micro_patch')
U280_NEW_KINDS = ('patch', 'micro_patch', 'map', 'extract')
# Segment-level tokens matched against path directory segments and `_`/`.`-delimited stem tokens so ordinary
# names like `version.py`, `preview.md`, `navigate.py`, `aggregate.py`, `latest/x.py` are not false-refused.
EVALUATOR_GATE_SEGMENT_TOKENS = (
    'evaluator', 'evaluators', 'judge', 'gate', 'gates', 'ledger', 'ledgers',
    'audit', 'audits', 'review', 'reviews', 'rsi', 'security', 'consensus',
    'test', 'tests',
)
EVALUATOR_GATE_STEMS = (
    'calculator_gate', 'firewall_audit', 'stop_gate', 'output_gate',
    'evidence_ledger', 'usage_ledger', 'intent_ledger', 'rsi_release',
    'proof_receipt', 'worker_routing',
)


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _positive(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


def _is_evaluator_or_gate_path(path: str) -> bool:
    norm = path.strip().lower().replace('\\', '/')
    parts = [p for p in norm.split('/') if p]
    if not parts:
        return False
    for seg in parts[:-1]:
        seg_tokens = [t for t in seg.replace('-', '_').split('_') if t]
        if seg in EVALUATOR_GATE_SEGMENT_TOKENS or any(t in EVALUATOR_GATE_SEGMENT_TOKENS for t in seg_tokens):
            return True
    filename = parts[-1]
    stem = filename.rsplit('.', 1)[0]
    if stem in EVALUATOR_GATE_STEMS or stem.startswith('test_') or stem.endswith('_test'):
        return True
    stem_tokens = [t for t in stem.replace('-', '_').split('_') if t]
    return any(t in EVALUATOR_GATE_SEGMENT_TOKENS for t in stem_tokens)


def evaluate_ollama_task_fit(
    task: dict | str | None = None,
    *,
    kind: str | None = None,
    target_files: tuple[str, ...] | list[str] | None = None,
    touches_evaluator: bool = False,
    exact_dictation: bool = False,
    same_cause_failures: int = 0,
    whole_file_rewrite: bool = False,
    multi_file_architecture: bool = False,
    functions: int = 1,
    changed_lines: int = 0,
    source_verified: bool = False,
    exact_search_block: bool = False,
    pinned_acceptance: bool = False,
) -> dict:
    """Pure deterministic first-match Ollama task-fit evaluator (U280).

    Note: `kind` and `target_files` are normalized to lowercase stripped strings before matching.
    """
    if isinstance(task, dict):
        kind = task.get('kind', kind)
        target_files = task.get('target_files', target_files)
        touches_evaluator = task.get('touches_evaluator', touches_evaluator)
        exact_dictation = task.get('exact_dictation', exact_dictation)
        same_cause_failures = task.get(
            'same_cause_failures', task.get('local_failures', same_cause_failures)
        )
        whole_file_rewrite = task.get('whole_file_rewrite', whole_file_rewrite)
        multi_file_architecture = task.get('multi_file_architecture', multi_file_architecture)
        functions = task.get('functions', functions)
        changed_lines = task.get('changed_lines', changed_lines)
        source_verified = task.get('source_verified', source_verified)
        exact_search_block = task.get('exact_search_block', exact_search_block)
        pinned_acceptance = task.get('pinned_acceptance', pinned_acceptance)
    elif isinstance(task, str):
        kind = task
    elif task is not None:
        return {
            'verdict': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
            'local_qualified': False,
            'worker': None,
            'reason': 'INVALID_TASK_SPEC',
            'execution_authorized': False,
        }

    if not isinstance(kind, str) or not kind.strip():
        return {
            'verdict': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
            'local_qualified': False,
            'worker': None,
            'reason': 'INVALID_TASK_KIND',
            'execution_authorized': False,
        }
    if any(not _integer(n, 0) for n in (same_cause_failures, functions, changed_lines)):
        return {
            'verdict': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
            'local_qualified': False,
            'worker': None,
            'reason': 'INVALID_COUNTERS',
            'execution_authorized': False,
        }
    bool_flags = (
        touches_evaluator, exact_dictation, whole_file_rewrite,
        multi_file_architecture, source_verified, exact_search_block, pinned_acceptance,
    )
    if any(type(b) is not bool for b in bool_flags):
        return {
            'verdict': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
            'local_qualified': False,
            'worker': None,
            'reason': 'INVALID_BOOLEAN_FLAGS',
            'execution_authorized': False,
        }
    if target_files is not None:
        if not isinstance(target_files, (list, tuple)) or any(not isinstance(p, str) or not p.strip() for p in target_files):
            return {
                'verdict': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
                'local_qualified': False,
                'worker': None,
                'reason': 'INVALID_TARGET_FILES',
                'execution_authorized': False,
            }
        files_norm = tuple(p.strip().lower() for p in target_files if p.strip())
    else:
        files_norm = ()

    norm_kind = kind.strip().lower()
    touches_gate_file = any(_is_evaluator_or_gate_path(path) for path in files_norm)

    # Precedence (1): evaluator/security/consensus/gate files -> REFUSE_LOCAL_EVALUATOR_OR_GATE
    if touches_evaluator or touches_gate_file or norm_kind in JUDGMENTS or norm_kind in ('evaluator', 'security', 'consensus', 'gate'):
        return {
            'verdict': 'REFUSE_LOCAL_EVALUATOR_OR_GATE',
            'local_qualified': False,
            'worker': 'conductor',
            'reason': 'REFUSE_LOCAL_EVALUATOR_OR_GATE',
            'execution_authorized': False,
        }

    # Precedence (2): zero-change or already-exact dictation patch -> DETERMINISTIC_APPLY_FIRST
    if exact_dictation or norm_kind in EXACT or norm_kind == 'deterministic' or (norm_kind in OLLAMA_PATCH_KINDS and changed_lines == 0):
        return {
            'verdict': 'DETERMINISTIC_APPLY_FIRST',
            'local_qualified': False,
            'worker': 'deterministic',
            'reason': 'DETERMINISTIC_APPLY_FIRST',
            'execution_authorized': False,
        }

    # Precedence (3): same-cause local failures >= MAX_LOCAL_SAME_CAUSE_FAILURES (2, standing circuit-breaker) -> QUARANTINE_LOCAL_SAME_CAUSE
    if same_cause_failures >= MAX_LOCAL_SAME_CAUSE_FAILURES:
        return {
            'verdict': 'QUARANTINE_LOCAL_SAME_CAUSE',
            'local_qualified': False,
            'worker': None,
            'reason': 'QUARANTINE_LOCAL_SAME_CAUSE',
            'execution_authorized': False,
        }

    # Precedence (4): whole-file rewrite or >20 changed lines or multi-file architecture -> ESCALATE_BOUNDED_SLICE_REQUIRED
    # >= 2 files or functions!=1 compounds local 7b edit drift across boundaries (docs/16 bench v2 & 590-row ledger audit);
    # single-file (len==1), single-function (functions==1), <=20 lines (EDIT_LINES) is the verified local micro-patch ceiling.
    if (
        whole_file_rewrite
        or multi_file_architecture
        or changed_lines > EDIT_LINES
        or len(files_norm) > 1
        or (norm_kind in OLLAMA_PATCH_KINDS and functions != 1)
    ):
        return {
            'verdict': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
            'local_qualified': False,
            'worker': 'conductor',
            'reason': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
            'execution_authorized': False,
        }

    # Precedence (5): narrow map/draft/summary with source verification -> ALLOW_LOCAL_PREPROCESS
    if norm_kind in OLLAMA_PREPROCESS_KINDS and source_verified:
        return {
            'verdict': 'ALLOW_LOCAL_PREPROCESS',
            'local_qualified': True,
            'worker': 'local',
            'reason': 'ALLOW_LOCAL_PREPROCESS',
            'execution_authorized': False,
        }

    # Precedence (6): single-function patch <=20 lines on 1 declared non-evaluator target file with exact SEARCH block and pinned acceptance -> ALLOW_LOCAL_MICRO_PATCH
    if (
        norm_kind in OLLAMA_PATCH_KINDS
        and len(files_norm) == 1
        and functions == 1
        and 0 < changed_lines <= EDIT_LINES
        and exact_search_block
        and pinned_acceptance
    ):
        return {
            'verdict': 'ALLOW_LOCAL_MICRO_PATCH',
            'local_qualified': True,
            'worker': 'local',
            'reason': 'ALLOW_LOCAL_MICRO_PATCH',
            'execution_authorized': False,
        }

    return {
        'verdict': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
        'local_qualified': False,
        'worker': 'conductor',
        'reason': 'ESCALATE_BOUNDED_SLICE_REQUIRED',
        'execution_authorized': False,
    }


def forecast(*, calls, input_tokens, output_tokens, cache_read_tokens=0, cache_write_tokens=0):
    """API price scenario only; subscription quota savings require measurement."""
    if not all(_integer(x) for x in (calls, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)):
        raise ValueError('scenario counts must be nonnegative integers, never quota percentages')
    fresh = input_tokens - cache_read_tokens - cache_write_tokens
    if fresh < 0:
        raise ValueError('cache read/write counts must be disjoint subsets of total input')
    # Official Haiku5.5 per-million USD, 1-hour cache write; >100k input uses long tier.
    rates = (.10, .01, .20, .50) if input_tokens <= 100000 else (.50, .05, 1.0, 2.50)
    amounts = (fresh, cache_read_tokens, cache_write_tokens, output_tokens)
    try:
        cost = calls * sum(n*r for n, r in zip(amounts, rates)) / 1000000
    except OverflowError as exc:
        raise ValueError('scenario exceeds finite numeric range') from exc
    if not math.isfinite(cost):
        raise ValueError('scenario cost exceeds finite numeric range')
    return {'estimated_usd': cost, 'quota_saving': 'UNMEASURED',
            'price_tier': 'standard' if input_tokens <= 100000 else 'long_input'}


def _answer(worker, reason, status='READY', model=None):
    return {'status': status, 'worker': worker, 'model': model, 'reason': reason,
            'execution_authorized': False}


def _valid(task, availability):
    if not isinstance(task, dict) or not isinstance(availability, dict):
        return False
    if task.get('caller') not in CALLERS:
        return False
    for key in ('input_tokens', 'output_tokens', 'changed_lines', 'local_failures'):
        if not _integer(task.get(key)):
            return False
    if type(task.get('allow_remote')) is not bool:
        return False
    if 'local_qualified' in task:
        return type(task.get('local_qualified')) is bool
    # Without explicit boolean local_qualified, only tasks carrying explicit U280 fit qualification keys are valid.
    return any(
        k in task for k in (
            'touches_evaluator', 'target_files', 'exact_dictation',
            'same_cause_failures', 'whole_file_rewrite', 'multi_file_architecture',
            'functions', 'source_verified', 'exact_search_block', 'pinned_acceptance',
        )
    )


def plan(task: dict, availability: dict) -> dict:
    """The same deterministic→local→explicit bounded Haiku policy for all callers.

    Note: `kind` is normalized to lowercase stripped string so `evaluate_ollama_task_fit` and `plan` agree on case.
    """
    if not _valid(task, availability):
        return _answer(None, 'INVALID_OR_UNBOUNDED_TASK', 'BLOCKED')
    raw_kind = task.get('kind')
    kind = raw_kind.strip().lower() if isinstance(raw_kind, str) else raw_kind
    fit = None
    if (
        'local_qualified' not in task
        or kind in U280_NEW_KINDS
        or any(
            k in task for k in (
                'touches_evaluator', 'target_files', 'exact_dictation',
                'same_cause_failures', 'whole_file_rewrite', 'multi_file_architecture',
                'functions', 'source_verified', 'exact_search_block', 'pinned_acceptance',
            )
        )
    ):
        fit = evaluate_ollama_task_fit(task)
        if str(fit.get('reason', '')).startswith('INVALID_'):
            return _answer(None, 'INVALID_OR_UNBOUNDED_TASK', 'BLOCKED')
        if fit['verdict'] == 'REFUSE_LOCAL_EVALUATOR_OR_GATE':
            return _answer('conductor', fit['reason'])
        if fit['verdict'] == 'DETERMINISTIC_APPLY_FIRST':
            return _answer('deterministic', fit['reason'])
    if kind in EXACT:
        return _answer('deterministic', 'EXACT_OPERATION')
    if kind in JUDGMENTS:
        return _answer('conductor', 'INDEPENDENT_JUDGMENT_REQUIRED')
    if kind not in LOCAL_TASKS and kind not in OLLAMA_PREPROCESS_KINDS and kind not in OLLAMA_PATCH_KINDS:
        return _answer(None, 'UNKNOWN_TASK_KIND', 'BLOCKED')
    caller_qualified = task['local_qualified'] if 'local_qualified' in task else True
    fit_qualified = bool(fit['local_qualified']) if fit is not None else True
    local_qualified = bool(caller_qualified and fit_qualified)
    total = task['input_tokens'] + task['output_tokens']
    if (availability.get('local') is True and local_qualified
        and task['local_failures'] < MAX_LOCAL_SAME_CAUSE_FAILURES and task['changed_lines'] <= EDIT_LINES
        and total <= LOCAL_CONTEXT and 0 < task['output_tokens'] <= LOCAL_OUTPUT
        and _positive(task.get('timeout_s'))):
        return _answer('local', 'QUALIFIED_BOUNDED_LOCAL_FIRST')
    return _remote(task, availability, total)


def _remote(task, availability, total):
    if not isinstance(task.get('remote_model', HAIKU), str):
        return _answer(None, 'INVALID_NATIVE_MODEL', 'BLOCKED')
    if task.get('remote_model', HAIKU) != HAIKU:
        return _native_helper(task, availability, total)
    if not task['allow_remote'] or availability.get('haiku') is not True:
        return _answer(None, 'NO_EXPLICIT_AVAILABLE_HAIKU_ROUTE', 'BLOCKED')
    if (not _integer(task.get('budget_tokens'), 1) or not _positive(task.get('budget_usd'))
            or not _positive(task.get('timeout_s'))):
        return _answer(None, 'REMOTE_POSITIVE_CAPS_REQUIRED', 'BLOCKED')
    if task['input_tokens'] <= 0 or task['output_tokens'] <= 0 or total > task['budget_tokens']:
        return _answer(None, 'REMOTE_TOTAL_TOKEN_CAP', 'BLOCKED')
    try:
        estimated = forecast(calls=1, input_tokens=task['input_tokens'], output_tokens=task['output_tokens'])
    except (OverflowError, ValueError):
        return _answer(None, 'INVALID_PRICE_SCENARIO', 'BLOCKED')
    if estimated['estimated_usd'] > task['budget_usd']:
        return _answer(None, 'REMOTE_ESTIMATED_USD_CAP', 'BLOCKED')
    result = _answer('claude', 'EXPLICIT_CAPPED_HAIKU_REQUIRES_PILOT_ADMISSION', model=HAIKU)
    result.update(estimated)
    return result


def _native_helper(task, availability, total):
    lanes = {'gpt-6-luna': ('codex', 'uaos-luna-worker'), 'gemini-3.8-flash-low': ('agy', 'uaos-flash-worker')}
    model = task.get('remote_model')
    seat, agent = lanes.get(model, (None, None))
    if seat is None or not task['allow_remote'] or availability.get(seat) is not True:
        return _answer(None, 'NO_EXPLICIT_AVAILABLE_NATIVE_HELPER', 'BLOCKED')
    if not _integer(task.get('budget_tokens'), 1) or not all(_positive(task.get(k)) for k in ('budget_usd', 'timeout_s')):
        return _answer(None, 'NATIVE_POSITIVE_CAPS_REQUIRED', 'BLOCKED')
    if task['input_tokens'] <= 0 or task['output_tokens'] <= 0 or total > task['budget_tokens']:
        return _answer(None, 'NATIVE_TOTAL_TOKEN_CAP', 'BLOCKED')
    result = _answer(seat, 'EXPLICIT_NATIVE_HELPER_REQUIRES_ADMISSION', model=model)
    result.update(subagent=agent, require_exact_model=True, model_pin='exact', quota_saving='UNMEASURED')
    return result


def select_pool_worker(task: dict, availability: dict) -> dict:
    """Resolve 3-tool worker pool dispatch spec (local Ollama coder vs bounded Haiku 5.5 subagent)."""
    decision = dict(plan(task, availability))
    worker = decision.get('worker')
    if worker in ('codex', 'agy'):
        return decision
    if worker == 'local':
        decision['model'] = 'qwen2.5-coder:7b'
        decision['subagent'] = None
        decision['require_exact_model'] = False
        decision['model_pin'] = 'none'
    elif worker == 'claude' and decision.get('model') == HAIKU:
        decision['subagent'] = 'uaos-haiku-worker'
        decision['require_exact_model'] = True
        decision['model_pin'] = 'exact'
    else:
        decision['subagent'] = None
        decision['require_exact_model'] = False
        decision['model_pin'] = 'none'
    return decision
