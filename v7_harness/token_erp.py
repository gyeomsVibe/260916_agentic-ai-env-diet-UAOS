"""U402 Token ERP: one official token-accounting view over the existing usage ledger.

Motifs from the accounting product 얼마에요 (iquest.co.kr, read 2026-11-28) mapped to tokens:
  전표 (voucher)        -> one observed model call in usage_accounting's `contributions` table
  계정 (account)        -> <provider>:<tier>, tier = local (Ollama) | helper | core
  원장/시산표           -> `trial-balance`: per-account totals and shares, plus 50/30/20 tier check
  예산관리 (+초과 경보) -> `budget`: latest subscription quota snapshots per provider/window
  결산 (closing)        -> `close`: freezes one card's trial balance into an append-only closing book

It extends usage_accounting (same DB, same dedupe rule) instead of adding a second ledger.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

from .usage_accounting import _connect, record_quota  # noqa: F401  (record_quota re-exported for `budget --record`)

# 50/30/20 is the user's standing routing target (CLAUDE.md U400); tolerance 10 points avoids flapping on small samples.
TARGET = {'local': 50.0, 'helper': 30.0, 'core': 20.0}
TOLERANCE_PCT = 10.0
# Helper tier = cheaper models the routing rules name as helpers (Haiku/Sonnet, GPT mini/Luna/Spark, Gemini Flash).
HELPER_MARKERS = ('haiku', 'sonnet', 'mini', 'luna', 'spark', 'flash')
DEFAULT_DB = Path.home() / '.uaos/usage/ledger.sqlite3'


def tier(provider, model):
    if provider == 'ollama':
        return 'local'
    model = (model or '').lower()
    return 'helper' if any(m in model for m in HELPER_MARKERS) else 'core'


def vouchers(db, since=None, until=None):
    """Deduplicated vouchers; fresh = uncached_input + cache_write + output (cache_read is re-read context)."""
    with _connect(db) as con:
        rows = con.execute('''SELECT provider, event_key, MIN(timestamp) ts, MAX(model) model,
            MAX(COALESCE(uncached_input,0)) ui, MAX(COALESCE(cache_read,0)) cr,
            MAX(COALESCE(cache_write,0)) cw, MAX(COALESCE(output,0)) out
            FROM contributions GROUP BY provider, event_key ORDER BY ts''').fetchall()
    out = []
    for r in rows:
        if (since and r['ts'] < since) or (until and r['ts'] > until):
            continue
        out.append({'ts': r['ts'], 'account': f"{r['provider']}:{tier(r['provider'], r['model'])}",
                    'model': r['model'], 'fresh': r['ui'] + r['cw'] + r['out'], 'cache_read': r['cr']})
    return out


def trial_balance(db, since=None, until=None):
    accounts = defaultdict(lambda: {'calls': 0, 'fresh': 0, 'cache_read': 0})
    tiers = defaultdict(lambda: {'calls': 0, 'fresh': 0})
    for v in vouchers(db, since, until):
        a = accounts[v['account']]
        a['calls'] += 1
        a['fresh'] += v['fresh']
        a['cache_read'] += v['cache_read']
        t = tiers[v['account'].split(':')[1]]
        t['calls'] += 1
        t['fresh'] += v['fresh']
    calls = sum(t['calls'] for t in tiers.values())
    check = {}
    for name, target in TARGET.items():
        share = round(100.0 * tiers[name]['calls'] / calls, 1) if calls else 0.0
        check[name] = {'target_pct': target, 'call_share_pct': share, 'delta_pct': round(share - target, 1)}
    verdict = 'NO_DATA' if not calls else (
        'ON_TARGET' if all(abs(c['delta_pct']) <= TOLERANCE_PCT for c in check.values()) else 'OFF_TARGET')
    return {'range': {'since': since, 'until': until}, 'accounts': dict(sorted(accounts.items())),
            'tiers': {k: dict(v) for k, v in tiers.items()}, 'target_check': check,
            'share_basis': 'calls (Ollama local tokens are not comparable to paid tokens)', 'verdict': verdict}


def _utc(text):
    value = datetime.fromisoformat(text)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _freshness(row, now):
    """EXPIRED when the window already reset; UNKNOWN when the observation's age cannot be bounded by its window."""
    try:
        if row['resets_at'] and _utc(row['resets_at']) <= now:
            return 'EXPIRED'
        if not row['window_minutes'] or now - _utc(row['observed_at']) > timedelta(minutes=row['window_minutes']):
            return 'UNKNOWN'
    except (TypeError, ValueError):
        return 'UNKNOWN'  # unparsable timestamps fail closed
    return None


def budget(db, now=None):
    """Latest snapshot per provider and window; alert at >=80% used (예산 초과 경보); stale snapshots never read OK."""
    now = _utc(now) if now else datetime.now(timezone.utc)
    with _connect(db) as con:
        rows = con.execute('''SELECT provider, window_minutes, used_percent, resets_at, observed_at, origin
            FROM quota_snapshots ORDER BY observed_at''').fetchall()
    latest = {}
    for r in rows:
        latest[(r['provider'], r['window_minutes'])] = dict(r)
    items = []
    for row in latest.values():
        used = row['used_percent']
        row['status'] = _freshness(row, now) or ('OVER' if used >= 100 else ('ALERT' if used >= 80 else 'OK'))
        items.append(row)
    return {'budgets': sorted(items, key=lambda r: (r['provider'], r['window_minutes'] or 0)),
            'note': 'percent of subscription window; never converted to tokens'}


def close(db, book, card, since, until=None):
    """Append-only closing entry; the same card+range is closed once (idempotent), also across processes."""
    tb = trial_balance(db, since, until)
    key = hashlib.sha256(json.dumps([card, since, until], sort_keys=True).encode()).hexdigest()[:16]
    book = Path(book)
    with _connect(db) as con:
        con.execute('BEGIN IMMEDIATE')  # one writer at a time across processes: check-and-append is atomic
        if book.is_file():
            for line in book.read_text(encoding='utf-8').splitlines():
                if line.strip() and json.loads(line).get('closing_id') == key:
                    return {'closing_id': key, 'status': 'ALREADY_CLOSED'}
        entry = {'closing_id': key, 'card': card, 'closed_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
                 'trial_balance': tb}
        book.parent.mkdir(parents=True, exist_ok=True)
        with book.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return {'closing_id': key, 'status': 'CLOSED', 'verdict': tb['verdict']}


def main(argv=None):
    parser = argparse.ArgumentParser(prog='uaos erp', description=__doc__)
    parser.add_argument('command', choices=('journal', 'trial-balance', 'budget', 'close'))
    parser.add_argument('--db', type=Path, default=DEFAULT_DB)
    parser.add_argument('--since')
    parser.add_argument('--until')
    parser.add_argument('--limit', type=int, default=50)
    parser.add_argument('--card')
    parser.add_argument('--book', type=Path, default=Path('.coord/usage/erp_closings.jsonl'))
    args = parser.parse_args(argv)
    if args.command == 'journal':
        result = vouchers(args.db, args.since, args.until)[-args.limit:]
    elif args.command == 'trial-balance':
        result = trial_balance(args.db, args.since, args.until)
    elif args.command == 'budget':
        result = budget(args.db)
    else:
        if not args.card or not args.since:
            parser.exit(2, 'uaos erp close: --card and --since are required\n')
        result = close(args.db, args.book, args.card, args.since, args.until)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
