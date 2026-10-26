"""Local metadata-only AI Resource Usage Ledger. No credentials or transcript storage.

Subscription quota, API prices and observed transcript tokens are different units.
Unknown metrics remain null. Only allowlisted local JSONL locations are opened.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

PROVIDERS = ('codex', 'claude', 'antigravity', 'ollama')
METRICS = ('uncached_input', 'cache_read', 'cache_write', 'output', 'reasoning')
SCHEMA_VERSION = 1
PARSER_REVISION = 2  # Revision 1 mixed independent native/legacy cumulative scopes.


def _hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def _label(value, fallback='UNKNOWN'):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/@+ -]{1,128}', value) else fallback


def _time(value):
    if not isinstance(value, str):
        raise ValueError('missing_timestamp')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if stamp.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    return stamp.astimezone(timezone.utc)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')


def _count(value):
    if type(value) is not int or value < 0:
        raise ValueError('invalid_counter')
    return value


def _normalize(provider, usage):
    """Codex cache is part of input; Claude cache is additional input."""
    if provider == 'codex':
        inp = _count(usage['input_tokens'])
        cache = _count(usage.get('cached_input_tokens', 0))
        write = _count(usage.get('cache_write_input_tokens', 0))
        output = _count(usage['output_tokens'])
        reasoning = _count(usage.get('reasoning_output_tokens', 0))
        if cache + write > inp or reasoning > output:
            raise ValueError('subset_exceeds_total')
        return dict(zip(METRICS, (inp-cache-write, cache, write, output, reasoning)))
    if provider == 'claude':
        return dict(zip(METRICS, (_count(usage['input_tokens']),
                    _count(usage.get('cache_read_input_tokens', 0)),
                    _count(usage.get('cache_creation_input_tokens', 0)),
                    _count(usage['output_tokens']), None)))
    return dict(zip(METRICS, (_count(usage['input_tokens']), 0, 0,
                            _count(usage['output_tokens']), None)))


@contextmanager
def _connect(db):
    db = Path(db)
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db), timeout=60)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA busy_timeout=60000')
    con.executescript('''
      CREATE TABLE IF NOT EXISTS sources (
        path TEXT PRIMARY KEY, provider TEXT, mtime INTEGER, size INTEGER,
        offset INTEGER, guard TEXT, digest TEXT, state TEXT, stats TEXT, last_seen TEXT);
      CREATE TABLE IF NOT EXISTS contributions (
        source TEXT, provider TEXT, event_key TEXT, session_key TEXT,
        timestamp TEXT, model TEXT, category TEXT,
        uncached_input INTEGER, cache_read INTEGER, cache_write INTEGER,
        output INTEGER, reasoning INTEGER,
        PRIMARY KEY(source, provider, event_key));
      CREATE INDEX IF NOT EXISTS events_provider ON contributions(provider,event_key);
      CREATE TABLE IF NOT EXISTS quota_snapshots (
        id TEXT PRIMARY KEY, provider TEXT, observed_at TEXT, used_percent REAL,
        window_minutes INTEGER, resets_at TEXT, origin TEXT);
      CREATE TABLE IF NOT EXISTS inventory (
        provider TEXT PRIMARY KEY, data TEXT);
    ''')
    try:
        with con:
            yield con
    finally:
        con.close()


def discover(home):
    """Inventory explicitly known locations; never descend credential folders."""
    home = Path(home)
    found = []
    for provider, roots in (
        ('codex', [home/'.codex/sessions', home/'.codex/archived_sessions']),
        ('claude', [home/'.claude/projects']),
    ):
        for root in roots:
            if root.is_dir():
                found.extend((provider, p.resolve()) for p in root.rglob('*.jsonl') if p.is_file())
    p = home/'.cache/olla/usage.jsonl'
    if p.is_file():
        found.append(('ollama', p.resolve()))
    opaque = 0
    for part in ('antigravity', 'antigravity-cli', 'antigravity-ide'):
        root = home/'.gemini'/part/'conversations'
        if root.is_dir():
            opaque += sum(1 for p in root.rglob('*') if p.is_file() and p.suffix in ('.db', '.pb'))
    return sorted(set(found), key=lambda v: (v[0], str(v[1]))), opaque


def _event(provider, key, sid, stamp, model, category, counts):
    return (provider, key, _hash(str(sid)), _iso(_time(stamp)),
            _label(model), _label(category), *(counts[k] for k in METRICS))


def _codex(row, state, stats):
    payload = row.get('payload') or {}
    if row.get('type') == 'session_meta':
        state['session'] = _hash(str(payload.get('id', state['session'])))
        return None
    if row.get('type') == 'turn_context':
        state['model'] = _label(payload.get('model'))
        return None
    if row.get('type') == 'token_usage_record':
        # Native thread counters can restart while token_count retains old history.
        # Per-response usage and response identity are the authoritative native view.
        stats['alternative_usage_rows'] = stats.get('alternative_usage_rows', 0) + 1
        if not isinstance(payload.get('usage'), dict):
            stats['unsupported_usage_rows'] += 1
            return None
        counts = _normalize('codex', payload['usage'])
        state['pending_native'] = counts
        response_id = payload.get('response_id')
        key = _hash('response:' + str(response_id)) if response_id else _hash(json.dumps([row.get('timestamp'), counts], sort_keys=True))
        return _event('codex', key, payload.get('session_id', state['session']),
                      row.get('timestamp'), state.get('model', 'UNKNOWN'), 'native_response', counts)
    elif row.get('type') == 'event_msg' and payload.get('type') == 'token_count':
        info = payload.get('info')
    else:
        return None
    if not isinstance(info, dict) or not isinstance(info.get('total_token_usage'), dict):
        stats['unsupported_usage_rows'] += 1
        return None
    total = _normalize('codex', info['total_token_usage'])
    previous = state.get('cumulative')
    state['cumulative'] = total
    last = info.get('last_token_usage')
    pending = state.pop('pending_native', None)
    if pending is not None and isinstance(last, dict) and _normalize('codex', last) == pending:
        stats['paired_native_rows'] = stats.get('paired_native_rows', 0) + 1
        return None
    # Older alternate-view fixture/source may omit last_token_usage.
    if pending is not None and last is None and total == pending:
        stats['paired_native_rows'] = stats.get('paired_native_rows', 0) + 1
        return None
    if previous is None:
        delta = total
    elif any(total[k] < previous[k] for k in METRICS):
        stats['counter_resets'] += 1
        last = info.get('last_token_usage')
        if not isinstance(last, dict):
            stats['errors'] += 1
            return None
        delta = _normalize('codex', last)
    else:
        delta = {k: total[k]-previous[k] for k in METRICS}
    if not any(delta[k] for k in ('uncached_input', 'cache_read', 'cache_write', 'output')):
        return None
    # A fork or copy repeats the original timestamp and cumulative observation.
    # The fingerprint deliberately excludes path/session so copied history counts once.
    key = _hash(json.dumps([row.get('timestamp'), total], sort_keys=True))
    return _event('codex', key, state['session'], row.get('timestamp'),
                  state.get('model', 'UNKNOWN'), 'token_count', delta)


def _claude(row, state, stats):
    message = row.get('message')
    if row.get('type') != 'assistant' or not isinstance(message, dict):
        return None
    if message.get('model') == '<synthetic>':
        stats['non_inference_rows'] += 1
        return None
    usage = message.get('usage')
    if not isinstance(usage, dict) or not message.get('id'):
        stats['unsupported_usage_rows'] += 1
        return None
    sid = row.get('sessionId', state['session'])
    counts = _normalize('claude', usage)
    return _event('claude', _hash(str(message['id'])), sid, row.get('timestamp'),
                  message.get('model'), 'assistant', counts)


def _ollama(row, state, stats):
    category = _label(row.get('event'), 'UNKNOWN')
    categories = stats.setdefault('event_categories', {})
    categories[category] = categories.get(category, 0) + 1
    inference_events = {'ask', 'draft', 'generate', 'inference', 'pilot_local'}
    pilot_ok = (row.get('model') and type(row.get('elapsed_s')) in (int, float)
                and row['elapsed_s'] >= 0 and str(row.get('status', '')).lower()
                in ('ok', 'success', 'pass', 'applied', 'done'))
    if (category not in inference_events or row.get('cached') is True
            or (category == 'pilot_local' and not pilot_ok)):
        stats['non_inference_rows'] += 1
        return None
    if 'input_tokens' not in row or 'output_tokens' not in row:
        stats['non_inference_rows'] += 1
        return None
    counts = _normalize('ollama', row)
    if not counts['uncached_input'] and not counts['output']:
        stats['non_inference_rows'] += 1
        return None
    stamp = row.get('ts', row.get('timestamp'))
    if isinstance(stamp, str) and datetime.fromisoformat(stamp.replace('Z', '+00:00')).tzinfo is None:
        # Legacy olla uses naive local timestamps. Expose this assumption, not false UTC precision.
        stamp = datetime.fromisoformat(stamp).replace(tzinfo=_tz('Asia/Seoul')).isoformat()
        stats['naive_timestamps_kst_assumed'] = stats.get('naive_timestamps_kst_assumed', 0) + 1
    # Hash only metadata, never an arbitrary row containing prompt text.
    identity = [stamp, category, counts, _label(row.get('caller')), _label(row.get('model'))]
    key = _hash(json.dumps(identity, sort_keys=True))
    return _event('ollama', key, row.get('session_id', row.get('session', state['session'])), stamp,
                  row.get('model'), category, counts)


def _stats():
    return dict.fromkeys(('rows', 'malformed_rows', 'errors', 'unsupported_usage_rows',
                         'counter_resets', 'non_inference_rows', 'usage_rows'), 0)


def _native_quotas(row, state):
    if row.get('type') != 'event_msg' or row.get('payload', {}).get('type') != 'token_count':
        return []
    limits = row['payload'].get('rate_limits')
    if not isinstance(limits, dict):
        return []
    values = []
    previous = state.setdefault('quota_signatures', {})
    for pool in ('primary', 'secondary'):
        quota = limits.get(pool)
        if not isinstance(quota, dict) or quota.get('used_percent') is None:
            continue
        reset = quota.get('resets_at')
        if reset is not None:
            if type(reset) not in (int, float) or not math.isfinite(reset) or reset < 0:
                raise ValueError('invalid_reset')
            reset = _iso(datetime.fromtimestamp(reset, timezone.utc))
        item = _quota_values(provider='codex', used_percent=quota['used_percent'],
                 window_minutes=quota.get('window_minutes'), resets_at=reset,
                 observed_at=row.get('timestamp'), origin='native_transcript')
        signature = list(item[2:5])
        if previous.get(pool) != signature:
            values.append(item)
            previous[pool] = signature
    return values


def _guard(stream, offset):
    stream.seek(max(0, offset-128))
    return hashlib.sha256(stream.read(min(offset, 128))).hexdigest()


def _upsert(con, source, event):
    con.execute('''INSERT INTO contributions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source,provider,event_key) DO UPDATE SET
        uncached_input=MAX(uncached_input,excluded.uncached_input),
        cache_read=MAX(cache_read,excluded.cache_read),
        cache_write=MAX(cache_write,excluded.cache_write),
        output=MAX(output,excluded.output),
        reasoning=CASE WHEN excluded.reasoning IS NULL THEN reasoning
          WHEN reasoning IS NULL THEN excluded.reasoning ELSE MAX(reasoning,excluded.reasoning) END''',
        (source, *event))


def collect(home=None, db=None):
    """Transactional, idempotent collection; append tails avoid rescanning history."""
    home = Path(home or Path.home())
    db = Path(db or home/'.uaos/usage/ledger.sqlite3')
    sources, opaque = discover(home)
    result = {'files_discovered': len(sources), 'files_parsed': 0,
              'files_incremental': 0, 'files_unchanged': 0, 'read_errors': 0,
              'parser_revision': PARSER_REVISION}
    with _connect(db) as con:
        con.execute('BEGIN IMMEDIATE')
        inventory = {p: {'source_files': sum(p == v[0] for v in sources)} for p in PROVIDERS}
        inventory['antigravity']['opaque_files'] = opaque
        for provider, path in sources:
            source = str(path)
            try:
                stat = path.stat()
                old = con.execute('SELECT * FROM sources WHERE path=?', (source,)).fetchone()
                revision_matches = bool(old and json.loads(old['state']).get('_parser_revision') == PARSER_REVISION)
                if revision_matches and (old['mtime'], old['size']) == (stat.st_mtime_ns, stat.st_size):
                    result['files_unchanged'] += 1
                    continue
                with path.open('rb') as stream:
                    incremental = bool(revision_matches and stat.st_size > old['size'] and
                                       _guard(stream, old['offset']) == old['guard'])
                    offset = old['offset'] if incremental else 0
                    state = json.loads(old['state']) if incremental else {'session': _hash(source), '_parser_revision': PARSER_REVISION}
                    stats = json.loads(old['stats']) if incremental else _stats()
                    if not incremental:
                        con.execute('DELETE FROM contributions WHERE source=?', (source,))
                    digest = hashlib.sha256()
                    if incremental:
                        digest.update(bytes.fromhex(old['digest']))
                    stream.seek(offset)
                    while True:
                        raw = stream.readline()
                        if not raw or not raw.endswith(b'\n'):
                            break  # An in-flight partial line is retried on a later append.
                        offset = stream.tell()
                        digest.update(raw)
                        stats['rows'] += 1
                        try:
                            row = json.loads(raw)
                            if not isinstance(row, dict):
                                raise ValueError('object_required')
                            if provider == 'codex':
                                try:
                                    for quota in _native_quotas(row, state):
                                        _insert_quota(con, quota)
                                        stats['native_quota_snapshots'] = stats.get('native_quota_snapshots', 0) + 1
                                except (ValueError, TypeError, OverflowError, OSError):
                                    stats['errors'] += 1
                            event = {'codex': _codex, 'claude': _claude, 'ollama': _ollama}[provider](row, state, stats)
                            if event:
                                _upsert(con, source, event)
                                stats['usage_rows'] += 1
                        except (ValueError, KeyError, TypeError, OverflowError, AttributeError):
                            stats['malformed_rows'] += 1
                            stats['errors'] += 1
                    guard = _guard(stream, offset)
                    con.execute('INSERT OR REPLACE INTO sources VALUES (?,?,?,?,?,?,?,?,?,?)',
                        (source, provider, stat.st_mtime_ns, stat.st_size, offset, guard,
                         digest.hexdigest(), json.dumps(state), json.dumps(stats), _iso(datetime.now(timezone.utc))))
                    result['files_parsed'] += 1
                    result['files_incremental'] += int(incremental)
            except OSError:
                result['read_errors'] += 1
        for provider, data in inventory.items():
            con.execute('INSERT OR REPLACE INTO inventory VALUES (?,?)', (provider, json.dumps(data)))
    return result


def _tz(name):
    # Fixed KST avoids requiring third-party tzdata on Windows; no DST in reporting period.
    if name == 'Asia/Seoul':
        return timezone(timedelta(hours=9))
    if name == 'UTC':
        return timezone.utc
    from zoneinfo import ZoneInfo
    return ZoneInfo(name)


def _aggregate(rows, available):
    result = {'calls': len(rows), 'sessions': len({r['session_key'] for r in rows}),
              'active_days': len({r['day'] for r in rows})}
    for k in METRICS:
        values = [r[k] for r in rows]
        result[k] = sum(v for v in values if v is not None) if available and all(v is not None for v in values) else None
    result['total_tokens'] = sum(result[k] for k in METRICS[:-1]) if all(result[k] is not None for k in METRICS[:-1]) else None
    result['first_seen'] = min((r['timestamp'] for r in rows), default=None)
    result['last_seen'] = max((r['timestamp'] for r in rows), default=None)
    return result


def report(db=None, *, now=None, timezone_name='Asia/Seoul', start=None, end=None):
    """All-time and 7/30 calendar-day windows in chosen timezone, inclusive dates."""
    db = Path(db or Path.home()/'.uaos/usage/ledger.sqlite3')
    current = _time(now) if now else datetime.now(timezone.utc)
    zone = _tz(timezone_name)
    today = current.astimezone(zone).date()
    start_day = datetime.fromisoformat(start).date() if start else None
    end_day = datetime.fromisoformat(end).date() if end else None
    if start_day and end_day and start_day > end_day:
        raise ValueError('start_after_end')
    with _connect(db) as con:
        source_rows = list(con.execute('SELECT * FROM sources'))
        inventory = {r['provider']: json.loads(r['data']) for r in con.execute('SELECT * FROM inventory')}
        columns = ','.join(f'MAX({k}) AS {k}' for k in METRICS)
        events = [dict(r) for r in con.execute(f'''SELECT provider,event_key,MIN(session_key) AS session_key,
          MIN(timestamp) AS timestamp,MAX(model) AS model,MAX(category) AS category,{columns}
          FROM contributions GROUP BY provider,event_key''')]
        snapshots = [dict(r) for r in con.execute('SELECT provider,observed_at,used_percent,window_minutes,resets_at,origin FROM quota_snapshots ORDER BY observed_at')]
    coverage = {}
    totals = defaultdict(int)
    source_manifest = []
    for r in source_rows:
        stats = json.loads(r['stats'])
        for k, v in stats.items():
            if type(v) is int:
                totals[k] += v
        source_manifest.append({'provider': r['provider'], 'path_hash': _hash(r['path']),
                                'fingerprint': r['digest'], 'hash_scheme': 'sha256-or-append-chain',
                                'size': r['size'], 'offset': r['offset'], 'last_seen': r['last_seen'],
                                'stats': stats})
    for p in PROVIDERS:
        files = [r for r in source_rows if r['provider'] == p]
        usage_rows = sum(json.loads(r['stats'])['usage_rows'] for r in files)
        coverage[p] = {'status': 'PARTIAL_LOCAL' if usage_rows else 'UNKNOWN',
                       'source_files': len(files), 'usage_rows': usage_rows,
                       'opaque_files': inventory.get(p, {}).get('opaque_files', 0),
                       'non_inference_rows': sum(json.loads(r['stats'])['non_inference_rows'] for r in files),
                       'subscription_quota': 'UNKNOWN', 'cloud_history': 'UNKNOWN',
                       'global_usage': 'UNKNOWN',
                       'count_scope': 'observed_local_events' if p != 'antigravity' else 'UNKNOWN'}
    filtered = []
    for event in events:
        stamp = _time(event['timestamp'])
        day = stamp.astimezone(zone).date()
        if stamp > current or (start_day and day < start_day) or (end_day and day > end_day):
            continue
        event['day'] = day.isoformat()
        filtered.append(event)
    windows = {}
    for name, days in (('all_time', None), ('last7', 7), ('last30', 30)):
        selected = [e for e in filtered if days is None or e['day'] >= (today-timedelta(days=days-1)).isoformat()]
        providers = {p: _aggregate([e for e in selected if e['provider'] == p], coverage[p]['status'] != 'UNKNOWN') for p in PROVIDERS}
        for p in ('antigravity',):
            if coverage[p]['status'] == 'UNKNOWN':
                providers[p].update(calls=None, sessions=None, active_days=None)
        grouped = defaultdict(list)
        for e in selected:
            grouped[(e['provider'], e['model'], e['day'])].append(e)
        daily = [dict(provider=p, model=m, day=d, **_aggregate(rows, True)) for (p,m,d), rows in sorted(grouped.items())]
        windows[name] = {'providers': providers, 'daily': daily}
    return {'schema_version': SCHEMA_VERSION, 'generated_at': _iso(current), 'timezone': timezone_name,
            'units': {'tokens': 'observed local metadata; not subscription quota', 'money': None,
                      'reasoning': 'subset of output; excluded from total_tokens'},
            'coverage': coverage, 'sources': dict(totals, count=len(source_rows)),
            'source_manifest': source_manifest, 'windows': windows, 'quota_snapshots': snapshots,
            'limitations': ['Cloud/opaque histories excluded; missing data is UNKNOWN.',
                            'Historical source files removed after collection remain in ledger.',
                            'Codex resets without last usage are skipped conservatively.',
                            'Legacy Ollama naive timestamps assume Asia/Seoul; counts disclosed in source stats.',
                            'Ollama pilot_local requires model, elapsed time and explicit success; other hook/cache estimates excluded.',
                            'Calls are observed usage events/messages, not billed requests.']}


def _quota_values(*, provider, used_percent, window_minutes=None, resets_at=None,
                  observed_at=None, origin='observed_ui'):
    if provider not in PROVIDERS or origin not in ('observed_ui', 'provider_api', 'user_report', 'native_transcript'):
        raise ValueError('invalid_snapshot_enum')
    if type(used_percent) not in (int, float) or not math.isfinite(used_percent) or not 0 <= used_percent <= 100:
        raise ValueError('invalid_percentage')
    if window_minutes is not None and (type(window_minutes) is not int or window_minutes <= 0):
        raise ValueError('invalid_window')
    stamp = _iso(_time(observed_at)) if observed_at else _iso(datetime.now(timezone.utc))
    reset = _iso(_time(resets_at)) if resets_at else None
    return (provider, stamp, used_percent, window_minutes, reset, origin)


def _insert_quota(con, values):
    con.execute('INSERT OR REPLACE INTO quota_snapshots VALUES (?,?,?,?,?,?,?)',
                (_hash(json.dumps(values)), *values))


def record_quota(db, *, provider, used_percent, window_minutes=None, resets_at=None,
                 observed_at=None, origin='observed_ui'):
    values = _quota_values(provider=provider, used_percent=used_percent,
             window_minutes=window_minutes, resets_at=resets_at,
             observed_at=observed_at, origin=origin)
    with _connect(db) as con:
        _insert_quota(con, values)
    return {'recorded': True, 'provider': provider, 'origin': origin}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('collect', 'report', 'snapshot'))
    parser.add_argument('--home', type=Path, default=Path.home())
    parser.add_argument('--db', type=Path)
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--timezone', default='Asia/Seoul')
    parser.add_argument('--provider', choices=PROVIDERS)
    parser.add_argument('--used-percent', type=float)
    parser.add_argument('--window-minutes', type=int)
    parser.add_argument('--resets-at')
    parser.add_argument('--observed-at')
    parser.add_argument('--origin', choices=('observed_ui', 'provider_api', 'user_report'), default='observed_ui')
    args = parser.parse_args(argv)
    db = args.db or args.home/'.uaos/usage/ledger.sqlite3'
    try:
        if args.command == 'collect':
            result = collect(args.home, db)
        elif args.command == 'report':
            result = report(db, timezone_name=args.timezone, start=args.start, end=args.end)
        else:
            result = record_quota(db, provider=args.provider, used_percent=args.used_percent,
                     window_minutes=args.window_minutes, resets_at=args.resets_at,
                     observed_at=args.observed_at, origin=args.origin)
    except (ValueError, OSError, sqlite3.Error):
        parser.exit(2, 'usage_accounting: invalid arguments or unavailable local ledger\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
