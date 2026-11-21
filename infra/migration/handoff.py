"""Destination preparation. Never creates AWS resources; upload is explicit."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tarfile
import zipfile

from portable_data import sha, verify, write_json


def load_env(path):
    from dotenv import dotenv_values
    values = dotenv_values(path)
    for key, value in values.items():
        if value is not None: os.environ[key] = value


def destination():
    import boto3
    from botocore.config import Config
    profile = os.getenv('AWS_PROFILE')
    sess = boto3.Session(profile_name=profile or None, region_name=os.environ['AWS_REGION'])
    cfg = Config(connect_timeout=10, read_timeout=60, retries={'mode': 'standard', 'total_max_attempts': 3})
    expected = os.environ['AWS_EXPECTED_ACCOUNT_ID']
    actual = sess.client('sts', config=cfg).get_caller_identity()['Account']
    if expected != actual: raise ValueError('Destination AWS account mismatch')
    if actual == os.getenv('SOURCE_AWS_ACCOUNT_ID'): raise ValueError('Source account cannot be the destination')
    return sess, cfg, actual


def unpack(archive, expected_sha, directory):
    if sha(archive) != expected_sha: raise ValueError('Archive SHA256 mismatch')
    root = Path(directory).resolve()
    if root.exists(): raise ValueError('Extraction destination must not exist')
    with tarfile.open(archive, 'r:gz') as t:
        members = t.getmembers()
        if sum(m.size for m in members) > 10 * 1024**3: raise ValueError('Archive exceeds 10 GiB limit')
        for m in members:
            if not (m.isfile() or m.isdir()) or not (root / m.name).resolve().is_relative_to(root):
                raise ValueError('Unsafe archive member')
        root.mkdir(parents=True)
        os.chmod(root, 0o700)
        t.extractall(root, members=members, filter='data')
    manifests = list(root.glob('*/manifest.json'))
    if len(manifests) != 1: raise ValueError('Expected one bundle manifest')
    result = manifests[0].parent
    verify(result)
    return result


def code_package(repo, output):
    """Committed tree only. Working files, credentials and exports are never added."""
    repo, output = Path(repo).resolve(), Path(output).resolve()
    if output.exists(): raise ValueError('Output already exists')
    revision = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    subprocess.run(['git', '-C', str(repo), 'archive', '--format=zip', '--output=' + str(output), revision], check=True)
    with zipfile.ZipFile(output) as z:
        for name in z.namelist():
            parts = Path(name).parts
            if any(p in ('.aws', '.git', 'node_modules') for p in parts) or (Path(name).name.startswith('.env') and not name.endswith('.example')):
                raise ValueError('Unexpected secret/configuration entry in committed archive; inspect manually')
    return {'commit': revision, 'file': output.name, 'sha256': sha(output), 'bytes': output.stat().st_size}


def runtime_config(output):
    # No credentials are written; the host role reads new account secrets.
    required = ['AWS_REGION', 'CHAT_SECRET_ARN', 'MYSQL_SECRET_ARN', 'JOBS_TABLE', 'WORK_QUEUE_URL']
    config = {key: os.environ[key] for key in required}
    config.update(JOB_SEARCH_BACKEND='elasticsearch', TRAINING_SEARCH_BACKEND='elasticsearch')
    config['ELASTICSEARCH_URL'] = os.getenv('ELASTICSEARCH_URL', 'http://127.0.0.1:19200')
    for key in ('ELASTICSEARCH_INDEX', 'ELASTICSEARCH_TRAINING_INDEX', 'ENABLE_TXT_VECTOR_SEARCH', 'ENABLE_ZERO_RESULT_VECTOR_FALLBACK'):
        if os.getenv(key): config[key] = os.environ[key]
    p = Path(output)
    if p.exists(): raise ValueError('Runtime config output already exists')
    p.parent.mkdir(parents=True, exist_ok=True); write_json(p, config); os.chmod(p, 0o600)
    return {'status': 'config_template_written', 'secret_values_written': False}


def upload(args):
    if not args.confirm_private_upload: raise ValueError('Use --confirm-private-upload after checking destination')
    sess, cfg, account = destination()
    bucket = os.environ['MIGRATION_BUCKET']
    if bucket == os.getenv('WEB_BUCKET'): raise ValueError('Never upload data to the web hosting bucket')
    s3 = sess.client('s3', config=cfg)
    s3.head_bucket(Bucket=bucket, ExpectedBucketOwner=account)
    block = s3.get_public_access_block(Bucket=bucket, ExpectedBucketOwner=account)['PublicAccessBlockConfiguration']
    if not all(block.get(k) for k in ('BlockPublicAcls', 'IgnorePublicAcls', 'BlockPublicPolicy', 'RestrictPublicBuckets')):
        raise ValueError('Private destination requires all public access blocks')
    tags = {t['Key']: t['Value'] for t in s3.get_bucket_tagging(Bucket=bucket, ExpectedBucketOwner=account)['TagSet']}
    if tags.get('Purpose') != 'private-migration': raise ValueError('Use a dedicated bucket tagged Purpose=private-migration')
    if sha(args.archive) != args.sha256: raise ValueError('Archive checksum mismatch')
    key = 'migration/' + args.sha256 + '/' + Path(args.archive).name
    # Explicit PUT (rather than transfer manager) enforces expected ownership.
    if Path(args.archive).stat().st_size >= 5 * 1024**3: raise ValueError('Use an approved multipart workflow for >=5 GiB')
    with Path(args.archive).open('rb') as f:
        s3.put_object(Bucket=bucket, Key=key, Body=f, ServerSideEncryption='AES256', ExpectedBucketOwner=account,
                      Metadata={'sha256': args.sha256})
    head = s3.head_object(Bucket=bucket, Key=key, ExpectedBucketOwner=account)
    if head['ContentLength'] != Path(args.archive).stat().st_size or head['Metadata'].get('sha256') != args.sha256:
        raise RuntimeError('Upload metadata verification failed')
    return {'status': 'uploaded_private', 'key': key, 'bytes': head['ContentLength']}


def main():
    p = argparse.ArgumentParser(); p.add_argument('action', choices=['doctor', 'unpack', 'package-code', 'render-config', 'upload'])
    p.add_argument('--env', default='.env'); p.add_argument('--archive'); p.add_argument('--sha256')
    p.add_argument('--directory'); p.add_argument('--repo', default='.'); p.add_argument('--output')
    p.add_argument('--confirm-private-upload', action='store_true'); a = p.parse_args()
    if a.action == 'package-code': result = code_package(a.repo, a.output)
    elif a.action == 'unpack': result = {'status': 'verified', 'directory': str(unpack(a.archive, a.sha256, a.directory))}
    else:
        load_env(a.env)
        if a.action == 'doctor':
            _, _, account = destination(); result = {'status': 'destination_identity_verified', 'account': account,
                'resources_created': 0, 'note': 'This checks identity, not resource readiness or deployment.'}
        elif a.action == 'render-config': result = runtime_config(a.output)
        else: result = upload(a)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
