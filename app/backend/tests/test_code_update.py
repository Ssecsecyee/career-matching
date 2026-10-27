"""Exercise code release and rollback in a temporary directory; no AWS calls."""
import io
import hashlib
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

INFRA=Path(__file__).resolve().parents[3]/'infra'
sys.path.insert(0,str(INFRA))
from update_backend import remote_script

class UpdateTests(unittest.TestCase):
    def exercise(self, fail=False):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'app').mkdir()
            (root/'app/worker.py').write_text('VERSION="old"')
            (root/'mysql').mkdir()
            (root/'mysql/preserved').write_text('data')
            payload=io.BytesIO()
            with ZipFile(payload,'w') as archive:archive.writestr('worker.py','VERSION="new"')
            data=payload.getvalue()
            script=remote_script('https://example.invalid/release',hashlib.sha256(data).hexdigest(),'test')
            script=script.replace("pathlib.Path('/opt/career')",'pathlib.Path('+repr(str(root))+')')
            def run(command,**kwargs):
                if fail and command[:3]==['systemctl','is-active','--quiet']:raise RuntimeError('simulated inactive')
            with patch('urllib.request.urlopen',return_value=io.BytesIO(data)), patch('subprocess.run',side_effect=run),patch('time.sleep'):
                if fail:
                    with self.assertRaisesRegex(RuntimeError,'previous code restored'):exec(script,{})
                else:exec(script,{})
            self.assertEqual((root/'app/worker.py').read_text(),'VERSION="old"' if fail else 'VERSION="new"')
            self.assertEqual((root/'mysql/preserved').read_text(),'data')
    def test_update_keeps_database_and_previous_code(self):self.exercise()
    def test_failed_start_restores_previous_code(self):self.exercise(True)
    def test_bad_hash_never_stops_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            script=remote_script('https://example.invalid/release','bad','test').replace("pathlib.Path('/opt/career')",'pathlib.Path('+repr(folder)+')')
            with patch('urllib.request.urlopen',return_value=io.BytesIO(b'bad')),patch('subprocess.run') as run:
                with self.assertRaisesRegex(RuntimeError,'checksum'):exec(script,{})
                run.assert_not_called()

    def test_presigned_download_uses_v4_without_real_credentials(self):
        import boto3
        from botocore.config import Config
        from urllib.parse import urlsplit, parse_qs
        client=boto3.Session(aws_access_key_id='offline-key',aws_secret_access_key='offline-secret',region_name='ap-northeast-2').client('s3',config=Config(signature_version='s3v4',s3={'addressing_style':'virtual'}))
        url=client.generate_presigned_url('get_object',Params={'Bucket':'offline-release-bucket','Key':'release.zip'},ExpiresIn=900)
        query=parse_qs(urlsplit(url).query)
        self.assertEqual(query['X-Amz-Algorithm'],['AWS4-HMAC-SHA256'])
        self.assertIn('/ap-northeast-2/s3/aws4_request',query['X-Amz-Credential'][0])

    def test_download_failure_is_redacted_and_worker_not_stopped(self):
        import urllib.error
        from update_backend import safe_failure
        with tempfile.TemporaryDirectory() as folder:
            script=remote_script('https://private.invalid/?token=hidden','bad','test').replace("pathlib.Path('/opt/career')",'pathlib.Path('+repr(folder)+')')
            failure=urllib.error.HTTPError('https://private.invalid',400,'private',{},io.BytesIO(b'<Error><Code>InvalidRequest</Code><Message>private</Message></Error>'))
            with patch('urllib.request.urlopen',side_effect=failure),patch('subprocess.run') as run:
                with self.assertRaisesRegex(RuntimeError,'S3_DOWNLOAD_ERROR:400:InvalidRequest') as caught:exec(script,{})
                run.assert_not_called()
            summary=safe_failure('RuntimeError: '+str(caught.exception))
            self.assertEqual(summary['s3_error_code'],'InvalidRequest')
            self.assertNotIn('hidden',str(summary))
