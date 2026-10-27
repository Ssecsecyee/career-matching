"""User-run code-only release. No infrastructure replacement or SQL migrations."""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import re
from pathlib import Path
import sys
import urllib.request
from zipfile import ZipFile, ZIP_DEFLATED
from deploy import session, client, outputs

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/backend-state.json'
RELEASE=ROOT/'infra/.build/code-release.json'


def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2),encoding='utf-8')


def build(args):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'infra/.build'/('code-'+stamp)
    folder.mkdir(parents=True)
    for name,worker in [('api.zip',False),('worker-code.zip',True)]:
        with ZipFile(folder/name,'w',ZIP_DEFLATED) as archive:
            for path in sorted((ROOT/'app/backend/src').rglob('*.py')):
                archive.write(path,'src/'+path.relative_to(ROOT/'app/backend/src').as_posix())
            if worker:
                for filename in ('worker.py','server_admin.py'):
                    archive.write(ROOT/'app/backend'/filename,filename)
    value={'stamp':stamp,'folder':str(folder),'hashes':{name:hashlib.sha256((folder/name).read_bytes()).hexdigest() for name in ('api.zip','worker-code.zip')}}
    save(RELEASE,value)
    print(json.dumps({'status':'built','release':stamp,'aws_operations':0,'database_changes':0}))


def remote_script(url,checksum,stamp):
    # Only code is extracted; keep config, MySQL data, schema and credentials untouched.
    return """import base64, compileall, hashlib, io, json, os, pathlib, shutil, subprocess, time, urllib.request, zipfile
root=pathlib.Path('/opt/career')
release=root/'releases'/STAMP
stage=release/'app'
old=root/'app'
backup=release/'previous-app'
release.mkdir(parents=True,exist_ok=False)
try:
    with urllib.request.urlopen(URL,timeout=30) as response:
        data=response.read(5*1024*1024+1)
except urllib.error.HTTPError as exc:
    import re, xml.etree.ElementTree as ET
    code='UnknownS3Error'
    try:
        parsed=ET.fromstring(exc.read(16384))
        candidate=parsed.findtext('Code','')
        if re.fullmatch(r'[A-Za-z0-9_]{1,80}',candidate):code=candidate
    except Exception:
        pass
    raise RuntimeError('S3_DOWNLOAD_ERROR:'+str(exc.code)+':'+code) from None
if len(data)>5*1024*1024 or hashlib.sha256(data).hexdigest()!=CHECKSUM:
    raise RuntimeError('Release checksum mismatch')
shutil.copytree(old,stage,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    for item in archive.infolist():
        name=item.filename
        if item.file_size>1024*1024 or not (name in ('worker.py','server_admin.py') or (name.startswith('src/') and name.endswith('.py'))):
            raise RuntimeError('Unexpected release member')
        if '..' in pathlib.PurePosixPath(name).parts or name.startswith('/'):
            raise RuntimeError('Invalid release member')
    if sum(item.file_size for item in archive.infolist())>5*1024*1024:
        raise RuntimeError('Expanded release too large')
    archive.extractall(stage)
if not compileall.compile_dir(str(stage),quiet=2):
    raise RuntimeError('Compilation failed')
subprocess.run(['systemctl','stop','career-worker'],check=True)
switched=False
try:
    old.rename(backup)
    stage.rename(old)
    switched=True
    subprocess.run(['systemctl','start','career-worker'],check=True)
    time.sleep(5)
    subprocess.run(['systemctl','is-active','--quiet','career-worker'],check=True)
except Exception:
    subprocess.run(['systemctl','stop','career-worker'],check=False)
    if switched:
        old.rename(release/'failed-app')
    if backup.exists():
        backup.rename(old)
    subprocess.run(['systemctl','start','career-worker'],check=True)
    raise RuntimeError('Worker update failed; previous code restored') from None
print(json.dumps({'status':'worker_updated','release':STAMP,'database_changes':0}))
""".replace('STAMP',repr(stamp)).replace('URL',repr(url)).replace('CHECKSUM',repr(checksum))


def settings(args):
    value=json.loads(STATE.read_text(encoding='utf-8'))
    args.profile=value['profile'];args.region=value['region'];args.stack=value['stack']
    return value,session(args)


def apply(args):
    if not args.confirm_maintenance:
        raise ValueError('Run during a quiet period with --confirm-maintenance; worker briefly restarts')
    state,sess=settings(args)
    release=json.loads(RELEASE.read_text(encoding='utf-8'))
    if release.get('command_id'):
        raise ValueError('This release was already submitted. Use result, or build a new release')
    out=outputs(client(sess,'cloudformation'),state['stack'])
    folder=Path(release['folder'])
    # Seoul S3 presigned requests require Signature Version 4.
    from botocore.config import Config
    s3=sess.client('s3',region_name=args.region,config=Config(
        signature_version='s3v4',s3={'addressing_style':'virtual'},
        connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2}))
    keys={}
    for name,checksum in release['hashes'].items():
        data=(folder/name).read_bytes()
        if hashlib.sha256(data).hexdigest()!=checksum:raise ValueError('Code changed after build')
        key='code-releases/'+release['stamp']+'/'+name
        s3.put_object(Bucket=state['bucket'],Key=key,Body=data,ServerSideEncryption='AES256')
        keys[name]=key
    # Preserve the previous Lambda ZIP locally before changing its validator.
    lam=client(sess,'lambda')
    current=lam.get_function(FunctionName=out['ApiFunction'])
    with urllib.request.urlopen(current['Code']['Location'],timeout=30) as response:
        (folder/'previous-api.zip').write_bytes(response.read(20*1024*1024))
    lam.update_function_code(FunctionName=out['ApiFunction'],S3Bucket=state['bucket'],S3Key=keys['api.zip'])
    lam.get_waiter('function_updated_v2').wait(FunctionName=out['ApiFunction'],WaiterConfig={'Delay':3,'MaxAttempts':15})
    # Short-lived, signed download avoids expanding the instance role's S3 permissions.
    url=s3.generate_presigned_url('get_object',Params={'Bucket':state['bucket'],'Key':keys['worker-code.zip']},ExpiresIn=900)
    script=remote_script(url,release['hashes']['worker-code.zip'],release['stamp'])
    encoded=base64.b64encode(script.encode()).decode()
    command="/opt/career/venv/bin/python -c \"import base64; exec(base64.b64decode('"+encoded+"'))\""
    result=client(sess,'ssm').send_command(InstanceIds=[out['WorkerInstanceId']],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=180,Comment='Code-only career worker release; preserve MySQL and previous application')
    release.update(command_id=result['Command']['CommandId'],instance_id=out['WorkerInstanceId'])
    save(RELEASE,release)
    print('Code update submitted. Run: python infra\\update_backend.py result. No SQL or infrastructure changes.')


def safe_failure(stderr):
    # Return exception type, numeric HTTP status, and code locations only.
    # Do not return source lines, command text, URLs or exception argument values.
    lines=stderr.splitlines()
    kinds=re.findall(r'(?m)^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception)):',stderr)
    http=re.search(r'HTTP Error (\d{3})',stderr)
    frames=[]
    for line in lines:
        match=re.match(r'\s*File "([^"\n]+)", line (\d+)',line)
        if match:
            frames.append({'file':Path(match[1]).name,'line':int(match[2])})
    s3_error=re.search(r'S3_DOWNLOAD_ERROR:(\d{3}):([A-Za-z0-9_]{1,80})',stderr)
    return {'s3_error_code':s3_error.group(2) if s3_error else None, 's3_http_status':int(s3_error.group(1)) if s3_error else None, 'error_type':kinds[-1] if kinds else 'RemoteCommandFailed',
            'http_status':int(http.group(1)) if http else None,'locations':frames[-6:]}


def result(args):
    state,sess=settings(args)
    release=json.loads(RELEASE.read_text(encoding='utf-8'))
    if not release.get('command_id'):raise ValueError('No update submitted')
    value=client(sess,'ssm').get_command_invocation(CommandId=release['command_id'],InstanceId=release['instance_id'])
    # Never expose download URLs, config values, or remote traceback contents.
    print(json.dumps({'status':value['Status'],'output':value['StandardOutputContent'],
        'error':safe_failure(value.get('StandardErrorContent','')) if value['Status']=='Failed' else None},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','apply','result'])
    parser.add_argument('--confirm-maintenance',action='store_true')
    args=parser.parse_args()
    try:globals()[args.action](args)
    except Exception as exc:
        code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
        print('Stopped: '+code+'. '+(str(exc) if type(exc) is ValueError else 'Check release prerequisites; do not share credentials.'),file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
