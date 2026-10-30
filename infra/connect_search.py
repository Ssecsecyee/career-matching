"""Deploy a loopback outbox consumer and switch the existing worker search path."""
import argparse,base64,hashlib,json
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from deploy import session,client,outputs
from botocore.config import Config

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/search-sync-release.json'

def save(value):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(value,indent=2),encoding='utf-8')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['build','apply','result','inspect','inspect-result'])
    parser.add_argument('--confirm-maintenance',action='store_true')
    args=parser.parse_args()
    if args.action=='build':
        if STATE.exists() and json.loads(STATE.read_text()).get('command_id'):
            previous=json.loads(STATE.read_text())
            if previous.get('status')!='Failed':raise ValueError('Inspect existing installation before preparing another')
            STATE.rename(STATE.with_name('search-sync-failed-'+previous['stamp']+'.json'))
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower()
        folder=ROOT/'infra/.build'/('sync-'+stamp);folder.mkdir(parents=True,exist_ok=False)
        package=folder/'sync.zip'
        with ZipFile(package,'w',ZIP_DEFLATED) as z:
            for path in (ROOT/'app/backend/src').rglob('*.py'):
                z.write(path,'app/backend/src/'+path.relative_to(ROOT/'app/backend/src').as_posix())
            for name in ('worker.py','server_admin.py'):z.write(ROOT/'app/backend'/name,'app/backend/'+name)
            for name in ('sync_outbox.py','index_snapshot.py'):
                z.write(ROOT/'app/ingestion/search_index'/name,'app/ingestion/search_index/'+name)
            for name in ('install_sync_remote.py','verify_sync_remote.py'):
                z.write(ROOT/'infra/elasticsearch'/name,name)
        value=dict(stamp=stamp,package=str(package),sha256=hashlib.sha256(package.read_bytes()).hexdigest())
        save(value);print(json.dumps({'status':'built','aws_operations':0}));return
    backend=json.loads((ROOT/'infra/.build/backend-state.json').read_text())
    args.profile=backend['profile'];args.region=backend['region'];args.stack=backend['stack']
    sess=session(args);ssm=client(sess,'ssm');state=json.loads(STATE.read_text())
    if args.action=='inspect':
        script=(ROOT/'infra/elasticsearch/inspect_sync_remote.py').read_text(encoding='utf-8')
        encoded=base64.b64encode(script.encode()).decode()
        command='/opt/career/venv/bin/python -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"'
        result=ssm.send_command(InstanceIds=[state['instance']],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=60,Comment='Read-only search sync counters and service state')
        state['inspect_command_id']=result['Command']['CommandId'];save(state)
        print(json.dumps({'status':'inspection_submitted'}));return
    if args.action in ('result','inspect-result'):
        key='command_id' if args.action=='result' else 'inspect_command_id'
        result=ssm.get_command_invocation(InstanceId=state['instance'],CommandId=state[key])
        stdout=result.get('StandardOutputContent','')
        print(json.dumps({'status':result['Status'],'output':stdout,'stderr_present':bool(result.get('StandardErrorContent'))}))
        if args.action=='result' and result['Status'] in ('Success','Failed'):
            state['status']=result['Status'];state['output']=stdout;save(state)
        return
    if not args.confirm_maintenance:raise ValueError('Use --confirm-maintenance for the brief worker restart')
    if state.get('command_id'):raise ValueError('Already submitted; inspect result')
    out=outputs(client(sess,'cloudformation'),args.stack)
    instance=out['WorkerInstanceId']
    desc=client(sess,'ec2').describe_instances(InstanceIds=[instance])['Reservations'][0]['Instances'][0]
    if desc['InstanceType']!='t4g.medium' or desc['State']['Name']!='running':raise ValueError('Expected running expanded host')
    if client(sess,'sts').get_caller_identity()['Account']!='954935267704':raise ValueError('Unexpected account')
    s3=sess.client('s3',region_name=args.region,config=Config(signature_version='s3v4',s3={'addressing_style':'virtual'},connect_timeout=5,read_timeout=30,retries={'mode':'standard','total_max_attempts':2}))
    data=Path(state['package']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=state['sha256']:raise ValueError('Package changed')
    key='search-sync-releases/'+state['stamp']+'/sync.zip'
    s3.put_object(Bucket=backend['bucket'],Key=key,Body=data,ServerSideEncryption='AES256')
    url=s3.generate_presigned_url('get_object',Params={'Bucket':backend['bucket'],'Key':key},ExpiresIn=900)
    script='''import hashlib,io,json,os,pathlib,subprocess,urllib.request,zipfile
os.umask(0o077)
folder=pathlib.Path('/opt/career/sync-releases')/STAMP
folder.mkdir(parents=True,exist_ok=False)
try:
    with urllib.request.urlopen(URL,timeout=30) as r:data=r.read(5*1024*1024+1)
    if len(data)>5*1024*1024 or hashlib.sha256(data).hexdigest()!=CHECKSUM:raise RuntimeError('checksum_failed')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.infolist():
            p=pathlib.PurePosixPath(m.filename)
            if p.is_absolute() or '..' in p.parts or m.file_size>1048576:raise RuntimeError('invalid_archive')
        if sum(m.file_size for m in z.infolist())>5*1024*1024:raise RuntimeError('archive_too_large')
        z.extractall(folder)
    result=subprocess.run(['/opt/career/venv/bin/python',str(folder/'install_sync_remote.py')],capture_output=True,text=True,timeout=800)
    print(result.stdout,flush=True)
    if result.stderr:print(json.dumps({'remote_stderr_present':True}),flush=True)
    raise SystemExit(result.returncode)
except Exception as exc:
    print(json.dumps({'status':'failed','stage':'package_or_installer','error_type':type(exc).__name__}),flush=True)
    raise SystemExit(1)
'''.replace('STAMP',repr(state['stamp'])).replace('URL',repr(url)).replace('CHECKSUM',repr(state['sha256']))
    encoded=base64.b64encode(script.encode()).decode()
    command='/opt/career/venv/bin/python -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"'
    result=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=900,Comment='Requested DB outbox synchronization and internal Elasticsearch search connection')
    state.update(command_id=result['Command']['CommandId'],instance=instance,s3_key=key);save(state)
    print(json.dumps({'status':'submitted','brief_worker_restart':True,'new_ec2':False,'public_search_port':False}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(json.dumps({'status':'stopped','error_type':type(exc).__name__,'code':getattr(exc,'response',{}).get('Error',{}).get('Code')}));raise SystemExit(1)
