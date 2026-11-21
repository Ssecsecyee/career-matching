import gzip
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from types import SimpleNamespace
from datetime import datetime, date, time, timedelta
from decimal import Decimal
from portable_data import encode, decode, ident, verify, sha, FORMAT
from handoff import unpack
from capture_source import remote_script


class PortableTests(unittest.TestCase):
    def test_exact_type_roundtrip(self):
        values = [None, '', '한글\n문장', 9223372036854775807, b'\x00\xff', Decimal('123.000001'),
                  datetime(2026, 11, 21, 1, 2, 3, 456789), date(2026, 11, 21), time(1, 2, 3), timedelta(days=-1, seconds=31)]
        for value in values:
            restored = decode(json.loads(json.dumps(encode(value))))
            self.assertEqual(restored, value)
            self.assertEqual(type(restored), type(value))

    def test_json_column_remains_string(self):
        value = '{"$type":"bytes","value":"not a blob"}'
        self.assertEqual(decode(encode(value)), value)

    def test_identifier_rejects_sql(self):
        for name in ('../x', 'table; DROP TABLE x', 'a`b', ''):
            with self.assertRaises(ValueError): ident(name)

    def test_manifest_detects_corruption_and_counts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root/'mysql').mkdir(); row = root/'mysql/jobs.jsonl.gz'
            with gzip.open(row, 'wt', encoding='utf-8') as f: f.write('[1,"테스트"]\n')
            m = {'format': FORMAT, 'tables': [{'name': 'jobs', 'rows': 1}], 'indices': [],
                 'files': {'mysql/jobs.jsonl.gz': {'sha256': sha(row), 'bytes': row.stat().st_size}}}
            (root/'manifest.json').write_text(json.dumps(m))
            verify(root)
            m['tables'][0]['rows'] = 2; (root/'manifest.json').write_text(json.dumps(m))
            with self.assertRaises(ValueError): verify(root)
            row.write_bytes(b'bad')
            with self.assertRaises(ValueError): verify(root)

    def test_tar_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bad.tar.gz'
            with tarfile.open(path, 'w:gz') as t:
                m = tarfile.TarInfo('../escape'); m.size = 1; t.addfile(m, io.BytesIO(b'x'))
            with self.assertRaises(ValueError): unpack(path, sha(path), Path(tmp)/'out')

    def test_tar_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'bad.tar.gz'
            with tarfile.open(path, 'w:gz') as t:
                m = tarfile.TarInfo('bundle/evil'); m.type = tarfile.SYMTYPE; m.linkname = '/etc'; t.addfile(m)
            with self.assertRaises(ValueError): unpack(path, sha(path), Path(tmp)/'out')

    def test_tar_digest_rejected_before_extract(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'x'; path.write_bytes(b'x')
            with self.assertRaises(ValueError): unpack(path, '0'*64, Path(tmp)/'out')

    def test_nonempty_mysql_target_refused_before_create(self):
        from portable_data import restore_mysql
        conn = MagicMock(); cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [{'existing_table': 'jobs'}]
        with patch('portable_data.verify', return_value={'tables': []}), patch('portable_data.mysql_connect', return_value=conn):
            with self.assertRaisesRegex(ValueError, 'must be empty'):
                restore_mysql(SimpleNamespace(directory='unused', confirm_empty_target=True))
        self.assertEqual(cursor.execute.call_args_list[0].args, ('SHOW TABLES',))
        self.assertEqual(cursor.execute.call_count, 1)
        conn.rollback.assert_called_once(); conn.close.assert_called_once()

    def test_source_runtime_uses_isolated_namespace_and_clock(self):
        code = remote_script('from datetime import time', '/opt/career/migration_exports/20261121T000000Z', 'test-token', 19731)
        compile(code, '<remote>', 'exec')
        self.assertIn('ns={"__name__":"portable_data"}', code)
        self.assertIn('_clock.monotonic()', code)
        self.assertNotIn('deadline=time.monotonic()', code)
        self.assertIn('HTTPServer((\'127.0.0.1\',19731)', code)

    def test_restore_es_existing_career_index_refused(self):
        from portable_data import restore_es
        with patch('portable_data.verify',return_value={'elasticsearch_version':'9.5.5'}), patch('portable_data.es_request',side_effect=[{'version':{'number':'9.5.5'}},[{'index':'career-existing'}]]) as request:
            with self.assertRaisesRegex(ValueError,'must be absent'):
                restore_es(SimpleNamespace(directory='unused',confirm_empty_target=True,elasticsearch='http://127.0.0.1:19200'))
        self.assertEqual(request.call_count,2)


if __name__ == '__main__': unittest.main()
