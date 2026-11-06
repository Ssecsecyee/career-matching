"""Explicit Work24 import through existing private artifact bucket and SSM."""
import argparse,base64,gzip,hashlib,json,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile,ZIP_STORED
import boto3
from botocore.config import Config

ROOT=Path(__file__).resolve().parents[1];STATE=ROOT/'infra/.build/work24-import/current.json'

def save(value):STATE.parent.mkdir(parents=True,exist_ok=True);STATE.write_text(json.dumps(value,indent=2),encoding='utf-8')
def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['build','submit','result']);ap.add_argument('--source',type=Path);ap.add_argument('--incremental',action='store_true');args=ap.parse_args()
    if args.action=='build':
        stamp='work24-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');folder=ROOT/'infra/.build'/stamp;folder.mkdir()
        source=args.source or ROOT/'workspace/work24/bulk_20261104/normalized/training.future.normalized.jsonl'
        with source.open('rb') as src,(folder/'training.jsonl.gz').open('xb') as out:
            with gzip.GzipFile(fileobj=out,mode='wb',mtime=0) as target:shutil.copyfileobj(src,target)
        with ZipFile(folder/'package.zip','w',ZIP_STORED) as archive:
            archive.write(folder/'training.jsonl.gz','training.jsonl.gz')
            for name in ['normalize_training.py','ingest_training.py','work24_export.py','work24_collect.py','ingest_work24.py','remote_import_work24.py','remote_update_work24.py']:
                archive.write(ROOT/'app/ingestion'/name,name)
            archive.write(ROOT/'app/ingestion/search_index/sync_outbox.py','sync_outbox.py')
            archive.write(ROOT/'app/ingestion/search_index/index_snapshot.py','index_snapshot.py')
            for path in (ROOT/'app/backend/src').rglob('*.py'):archive.write(path,'code/src/'+path.relative_to(ROOT/'app/backend/src').as_posix())
        value={'stamp':stamp,'folder':str(folder),'sha256':hashlib.sha256((folder/'package.zip').read_bytes()).hexdigest(),'entry':'remote_update_work24.py' if args.incremental else 'remote_import_work24.py'};save(value)
        print(json.dumps({'status':'built','bytes':(folder/'package.zip').stat().st_size,'aws_operations':0}));return
    cfg=json.loads((ROOT/'infra/.build/backend-state.json').read_text(encoding='utf-8'))
    sess=boto3.Session(profile_name=cfg['profile'],region_name=cfg['region'])
    config=Config(connect_timeout=5,read_timeout=45,retries={'mode':'standard','total_max_attempts':2})
    ssm=sess.client('ssm',config=config);value=json.loads(STATE.read_text())
    if args.action=='result':
        result=ssm.get_command_invocation(CommandId=value['command_id'],InstanceId=value['instance_id'])
        report={'status':result['Status'],'output':result.get('StandardOutputContent',''),'stderr_present':bool(result.get('StandardErrorContent'))}
        (Path(value['folder'])/'remote-status.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False));return
    if value.get('command_id'):raise ValueError('already_submitted_inspect_result')
    if sess.client('sts',config=config).get_caller_identity()['Account']!='954935267704':raise ValueError('unexpected_account')
    stack=sess.client('cloudformation',config=config).describe_stacks(StackName=cfg['stack'])['Stacks'][0]
    instance=next(x['OutputValue'] for x in stack['Outputs'] if x['OutputKey']=='WorkerInstanceId')
    package=Path(value['folder'])/'package.zip';data=package.read_bytes()
    if hashlib.sha256(data).hexdigest()!=value['sha256']:raise ValueError('package_changed')
    s3=sess.client('s3',config=Config(signature_version='s3v4',connect_timeout=5,read_timeout=120,retries={'mode':'standard','total_max_attempts':2}))
    key='ingestion-samples/'+value['stamp']+'/package.zip';s3.put_object(Bucket=cfg['bucket'],Key=key,Body=data,ServerSideEncryption='AES256')
    url=s3.generate_presigned_url('get_object',Params={'Bucket':cfg['bucket'],'Key':key},ExpiresIn=900)
    script='''import hashlib,io,json,os,pathlib,subprocess,urllib.request,zipfile
os.umask(0o077)
try:
 folder=pathlib.Path('/opt/career/ingestion-runs')/STAMP
 folder.mkdir(parents=True,exist_ok=False)
 with urllib.request.urlopen(URL,timeout=120) as response:data=response.read(150*1024*1024+1)
 if len(data)>150*1024*1024 or hashlib.sha256(data).hexdigest()!=CHECKSUM:raise ValueError('package_integrity')
 with zipfile.ZipFile(io.BytesIO(data)) as archive:
  if sum(i.file_size for i in archive.infolist())>160*1024*1024:raise ValueError('package_size')
  for item in archive.infolist():
   p=pathlib.PurePosixPath(item.filename)
   if p.is_absolute() or '..' in p.parts:raise ValueError('unsafe_package_path')
  archive.extractall(folder)
 del data
 result=subprocess.run(['/opt/career/venv/bin/python',str(folder/ENTRY)],cwd=folder)
 raise SystemExit(result.returncode)
except Exception as exc:
 print(json.dumps({'status':'failed_before_import','error_type':type(exc).__name__}));raise SystemExit(1)
'''.replace('STAMP',repr(value['stamp'])).replace('URL',repr(url)).replace('CHECKSUM',repr(value['sha256'])).replace('ENTRY',repr(value.get('entry','remote_import_work24.py')))
    command='/opt/career/venv/bin/python -c "import base64;exec(base64.b64decode(\''+base64.b64encode(script.encode()).decode()+'\'))"'
    result=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command],'executionTimeout':['3600']},TimeoutSeconds=60,Comment='Requested Work24 existing education table import; verified backup and no source deletion')
    value.update(instance_id=instance,command_id=result['Command']['CommandId']);save(value)
    print(json.dumps({'status':'submitted','command_id':value['command_id'],'instance_id':instance}))
if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'stopped','error_type':type(exc).__name__,'code':getattr(exc,'response',{}).get('Error',{}).get('Code')}));raise SystemExit(1)
