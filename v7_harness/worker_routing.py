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
HAIKU = 'claude-haiku-5-5'


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _positive(value):
    try:
        return type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        return False


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
    return type(task.get('local_qualified')) is bool and type(task.get('allow_remote')) is bool


def plan(task: dict, availability: dict) -> dict:
    """The same deterministic→local→explicit bounded Haiku policy for all callers."""
    if not _valid(task, availability):
        return _answer(None, 'INVALID_OR_UNBOUNDED_TASK', 'BLOCKED')
    kind = task.get('kind')
    if kind in EXACT:
        return _answer('deterministic', 'EXACT_OPERATION')
    if kind in JUDGMENTS:
        return _answer('conductor', 'INDEPENDENT_JUDGMENT_REQUIRED')
    if kind not in LOCAL_TASKS:
        return _answer(None, 'UNKNOWN_TASK_KIND', 'BLOCKED')
    total = task['input_tokens'] + task['output_tokens']
    if (availability.get('local') is True and task['local_qualified']
        and task['local_failures'] < 2 and task['changed_lines'] <= EDIT_LINES
        and total <= LOCAL_CONTEXT and 0 < task['output_tokens'] <= LOCAL_OUTPUT
        and _positive(task.get('timeout_s'))):
        return _answer('local', 'QUALIFIED_BOUNDED_LOCAL_FIRST')
    return _remote(task, availability, total)


def _remote(task, availability, total):
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
