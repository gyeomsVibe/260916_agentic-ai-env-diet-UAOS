"""U232: usage_accounting.collect() digest determinism, partial-line retry, bounded lines."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from v7_harness import usage_accounting as ua


def _row(i, pad=''):
    return json.dumps({'event': 'ask', 'model': 'm', 'input_tokens': 1 + i, 'output_tokens': 2,
                       'ts': f'2026-01-01T00:00:{i:02d}Z'}) + pad


class UsageCollectTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)/'home'
        self.log = self.home/'.cache/olla/usage.jsonl'
        self.log.parent.mkdir(parents=True)

    def _db(self, name):
        return Path(self._tmp.name)/name

    def _query(self, db, sql):
        con = sqlite3.connect(str(db))
        try:
            return con.execute(sql).fetchall()
        finally:
            con.close()

    def test_digest_same_for_incremental_and_full_parse(self):
        self.log.write_bytes((_row(1) + '\n' + _row(2) + '\n').encode())
        inc = self._db('inc.sqlite3')
        ua.collect(self.home, inc)
        with self.log.open('ab') as f:
            f.write((_row(3) + '\n').encode())
        self.assertEqual(ua.collect(self.home, inc)['files_incremental'], 1)
        full = self._db('full.sqlite3')
        self.assertEqual(ua.collect(self.home, full)['files_incremental'], 0)
        q = 'SELECT digest, offset FROM sources'
        self.assertEqual(self._query(inc, q), self._query(full, q))

    def test_partial_last_line_completed_in_place_is_not_skipped(self):
        # The last line is valid JSON padded with a space and no newline, so it is a partial line.
        self.log.write_bytes((_row(1) + '\n' + _row(2, ' ')).encode())
        st = self.log.stat()
        db = self._db('p.sqlite3')
        ua.collect(self.home, db)
        self.assertEqual(self._query(db, 'SELECT COUNT(*) FROM contributions'), [(1,)])
        data = bytearray(self.log.read_bytes())
        data[-1:] = b'\n'  # same size, same mtime: only the (mtime, size) pair matches the stored row
        self.log.write_bytes(bytes(data))
        os.utime(self.log, ns=(st.st_atime_ns, st.st_mtime_ns))
        self.assertEqual((self.log.stat().st_mtime_ns, self.log.stat().st_size), (st.st_mtime_ns, st.st_size))
        ua.collect(self.home, db)
        self.assertEqual(self._query(db, 'SELECT COUNT(*) FROM contributions'), [(2,)])

    def test_fully_consumed_unchanged_file_is_still_skipped(self):
        self.log.write_bytes((_row(1) + '\n').encode())
        db = self._db('s.sqlite3')
        ua.collect(self.home, db)
        self.assertEqual(ua.collect(self.home, db)['files_unchanged'], 1)

    def test_oversize_line_is_bounded_counted_and_skipped(self):
        limit = 1024
        sizes = []
        target = self.log.resolve()

        class Spy:
            def __init__(self, stream):
                self._s = stream

            def __getattr__(self, name):
                return getattr(self._s, name)

            def __enter__(self):
                self._s.__enter__()
                return self

            def __exit__(self, *exc):
                return self._s.__exit__(*exc)

            def readline(self, size=-1):
                sizes.append(size)
                return self._s.readline(size)

        orig = Path.open

        def spy_open(path, *a, **k):
            stream = orig(path, *a, **k)
            return Spy(stream) if Path(path) == target and a and a[0] == 'rb' else stream

        self.log.write_bytes((_row(1) + '\n' + 'x' * 5000 + '\n' + _row(2) + '\n').encode())
        db = self._db('o.sqlite3')
        with mock.patch.object(ua, 'MAX_LINE_BYTES', limit), mock.patch.object(Path, 'open', spy_open):
            ua.collect(self.home, db)
        self.assertTrue(sizes and all(0 < s <= limit + 1 for s in sizes), sizes)
        self.assertEqual(self._query(db, 'SELECT COUNT(*) FROM contributions'), [(2,)])
        stats = json.loads(self._query(db, 'SELECT stats FROM sources')[0][0])
        self.assertEqual((stats['oversize_rows'], stats['rows']), (1, 3))

    def test_unterminated_oversize_tail_waits_for_newline(self):
        self.log.write_bytes((_row(1) + '\n' + 'x' * 3000).encode())
        db = self._db('t.sqlite3')
        with mock.patch.object(ua, 'MAX_LINE_BYTES', 1024):
            ua.collect(self.home, db)
            first = self._query(db, 'SELECT offset FROM sources')[0][0]
            with self.log.open('ab') as f:
                f.write(b'\n' + _row(2).encode() + b'\n')
            ua.collect(self.home, db)
        self.assertEqual(first, len(_row(1)) + 1)
        self.assertEqual(self._query(db, 'SELECT COUNT(*) FROM contributions'), [(2,)])


if __name__ == '__main__':
    unittest.main()
