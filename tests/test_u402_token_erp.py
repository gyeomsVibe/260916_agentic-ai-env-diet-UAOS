import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Child process for the concurrency test: spin until the go-file exists so all children call close() together.
_CLOSE_CHILD = (
    'import json, sys, time\n'
    'from pathlib import Path\n'
    'from v7_harness import token_erp\n'
    'db, book, go = sys.argv[1:4]\n'
    'while not Path(go).exists(): time.sleep(0.001)\n'
    'print(json.dumps(token_erp.close(db, book, "U402", "2026-11-21")))\n'
)

from v7_harness import token_erp
from v7_harness.cli import main as cli_main
from v7_harness.usage_accounting import _connect, record_quota


def _seed(db, rows):
    with _connect(db) as con:
        for i, (provider, model, ts, ui, cr, out) in enumerate(rows):
            # Two contributions for one event: the ERP must count the event once (MAX dedupe, as usage report does).
            for src in ('a', 'b'):
                con.execute('INSERT INTO contributions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                            (src, provider, f'e{i}', 's', ts, model, 'c', ui, cr, 0, out, 0))


class TokenErpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / 'ledger.sqlite3'

    def tearDown(self):
        self.tmp.cleanup()

    def test_tier_mapping(self):
        self.assertEqual(token_erp.tier('ollama', 'qwen'), 'local')
        self.assertEqual(token_erp.tier('claude', 'claude-haiku-5-5'), 'helper')
        self.assertEqual(token_erp.tier('codex', 'gpt-6-luna'), 'helper')
        self.assertEqual(token_erp.tier('claude', 'claude-opus-5-5'), 'core')

    def test_journal_dedupes_and_filters_range(self):
        _seed(self.db, [('claude', 'claude-opus-5-5', '2026-11-20T00:00:00+00:00', 10, 100, 5),
                        ('ollama', 'qwen', '2026-11-27T00:00:00+00:00', 7, 0, 3)])
        rows = token_erp.vouchers(self.db, since='2026-11-21')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['account'], 'ollama:local')
        self.assertEqual(rows[0]['fresh'], 10)

    def test_trial_balance_target_check(self):
        rows = [('ollama', 'q', '2026-11-27T00:00:00+00:00', 1, 0, 1)] * 5
        rows += [('claude', 'claude-haiku-5-5', '2026-11-27T00:00:00+00:00', 1, 0, 1)] * 3
        rows += [('claude', 'claude-opus-5-5', '2026-11-27T00:00:00+00:00', 1, 9, 1)] * 2
        _seed(self.db, rows)
        tb = token_erp.trial_balance(self.db)
        self.assertEqual(tb['verdict'], 'ON_TARGET')
        self.assertEqual(tb['target_check']['local']['call_share_pct'], 50.0)
        self.assertEqual(tb['accounts']['claude:core']['cache_read'], 18)

    def test_trial_balance_off_target_and_empty(self):
        self.assertEqual(token_erp.trial_balance(self.db)['verdict'], 'NO_DATA')
        _seed(self.db, [('codex', 'gpt-6.2-sol', '2026-11-27T00:00:00+00:00', 1, 0, 1)] * 4)
        tb = token_erp.trial_balance(self.db)
        self.assertEqual(tb['verdict'], 'OFF_TARGET')
        self.assertEqual(tb['target_check']['core']['delta_pct'], 80.0)

    def test_budget_latest_snapshot_and_alert(self):
        record_quota(self.db, provider='codex', used_percent=50, window_minutes=10080, observed_at='2026-11-27T00:00:00+00:00')
        record_quota(self.db, provider='codex', used_percent=86, window_minutes=10080, observed_at='2026-11-28T00:00:00+00:00')
        # R2: pin `now` inside the 7-day window so this test cannot rot into EXPIRED/UNKNOWN on the calendar.
        items = token_erp.budget(self.db, now='2026-11-28T12:00:00+00:00')['budgets']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['used_percent'], 86)
        self.assertEqual(items[0]['status'], 'ALERT')

    def test_close_is_idempotent(self):
        _seed(self.db, [('ollama', 'q', '2026-11-27T00:00:00+00:00', 1, 0, 1)])
        book = Path(self.tmp.name) / 'closings.jsonl'
        first = token_erp.close(self.db, book, 'U402', '2026-11-21')
        again = token_erp.close(self.db, book, 'U402', '2026-11-21')
        self.assertEqual(first['status'], 'CLOSED')
        self.assertEqual(again['status'], 'ALREADY_CLOSED')
        self.assertEqual(len(book.read_text(encoding='utf-8').splitlines()), 1)

    def test_parallel_close_writes_exactly_one_entry(self):
        # R2 (Codex REVISE a): real processes, not threads; Windows appends from processes can race and duplicate.
        _seed(self.db, [('ollama', 'q', '2026-11-27T00:00:00+00:00', 1, 0, 1)])
        token_erp.trial_balance(self.db)  # create schema before children start, so the race is on close() only
        book = Path(self.tmp.name) / 'closings.jsonl'
        go = Path(self.tmp.name) / 'go'
        children = [subprocess.Popen([sys.executable, '-c', _CLOSE_CHILD, str(self.db), str(book), str(go)],
                                     cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True) for _ in range(8)]
        time.sleep(2.0)  # let every child import and start spinning on the go-file
        go.write_text('go', encoding='utf-8')
        results = []
        for child in children:
            out, err = child.communicate(timeout=120)
            self.assertEqual(child.returncode, 0, err)
            results.append(json.loads(out))
        self.assertEqual(len({r['closing_id'] for r in results}), 1)
        self.assertEqual(sorted(r['status'] for r in results), ['ALREADY_CLOSED'] * 7 + ['CLOSED'])
        self.assertEqual(len(book.read_text(encoding='utf-8').splitlines()), 1)

    def test_budget_expired_or_stale_quota_is_never_ok(self):
        # R2 (Codex REVISE b): an observation whose window has reset, or whose age cannot be bounded, fails closed.
        now = '2026-11-28T12:00:00+00:00'
        record_quota(self.db, provider='codex', used_percent=14, window_minutes=10080,
                     resets_at='2026-11-01T00:00:00+00:00', observed_at='2026-10-25T00:00:00+00:00')
        record_quota(self.db, provider='claude', used_percent=20, window_minutes=300,
                     observed_at='2026-11-27T00:00:00+00:00')
        record_quota(self.db, provider='antigravity', used_percent=30, observed_at='2026-11-28T11:00:00+00:00')
        record_quota(self.db, provider='ollama', used_percent=10, window_minutes=300,
                     resets_at='2026-11-28T14:00:00+00:00', observed_at='2026-11-28T11:00:00+00:00')
        status = {b['provider']: b['status'] for b in token_erp.budget(self.db, now=now)['budgets']}
        self.assertEqual(status, {'codex': 'EXPIRED', 'claude': 'UNKNOWN', 'antigravity': 'UNKNOWN', 'ollama': 'OK'})

    def test_cli_dispatch(self):
        _seed(self.db, [('ollama', 'q', '2026-11-27T00:00:00+00:00', 1, 0, 1)])
        from contextlib import redirect_stdout
        import io
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(cli_main(['erp', 'trial-balance', '--db', str(self.db)]), 0)
        self.assertIn('ollama:local', json.loads(buf.getvalue())['accounts'])


if __name__ == '__main__':
    unittest.main()
