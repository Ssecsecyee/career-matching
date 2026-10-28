"""Explicit small training sample deployment through existing SSM and S3."""
import argparse
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile,ZIP_DEFLATED
import boto3
from botocore.config import Config

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/training-apply-state.json'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['submit','result'])
    parser.add_argument('--batch',type=Path)
    args=parser.parse_args()
    state=json.loads((ROOT/'infra/.build/backend-state.json').read_text(encoding='utf-8'))
    session=boto3.Session(profile_name=state['profile'],region_name=state['region'])
    config=Config(connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2})
    ssm=session.client('ssm',config=config)
    if args.action=='result':
        value=json.loads(STATE.read_text(encoding='utf-8'))
        result=ssm.get_command_invocation(CommandId=value['command_id'],InstanceId=value['instance_id'])
        output=result.get('StandardOutputContent','')
        print(json.dumps({'status':result['Status'],'output':output,'stderr_present':bool(result.get('StandardErrorContent'))},ensure_ascii=False))
        if result['Status'] in {'Success','Failed','TimedOut','Cancelled'}:
            (Path(value['batch'])/('aws-result.json' if result['Status']=='Success' else 'aws-failed-result.json')).write_text(output,encoding='utf-8')
        return
    if STATE.exists():raise ValueError('Existing submission; inspect result before any resubmission')
    if args.batch is None:raise ValueError('Batch required')
    batch=args.batch.resolve();records=json.loads((batch/'input.json').read_text(encoding='utf-8-sig'))
    sys.path.insert(0,str(ROOT/'app/ingestion'))
    from ingest_training import prepare
    rows=prepare(records)
    stack=session.client('cloudformation',config=config).describe_stacks(StackName=state['stack'])['Stacks'][0]
    if stack['StackStatus'] not in {'CREATE_COMPLETE','UPDATE_COMPLETE'}:raise ValueError('Stack not ready')
    outputs={x['OutputKey']:x['OutputValue'] for x in stack['Outputs']}
    stamp='training-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'infra/.build'/stamp;folder.mkdir(parents=True,exist_ok=False)
    package=folder/'sample.zip'
    with ZipFile(package,'w',ZIP_DEFLATED) as archive:
        for name in ['normalize_training.py','ingest_training.py','remote_apply_training.py']:archive.write(ROOT/'app/ingestion'/name,name)
        archive.write(batch/'input.json','input.json')
    data=package.read_bytes();checksum=hashlib.sha256(data).hexdigest()
    s3=session.client('s3',config=Config(signature_version='s3v4',connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2}))
    key='ingestion-samples/'+stamp+'/sample.zip'
    s3.put_object(Bucket=state['bucket'],Key=key,Body=data,ServerSideEncryption='AES256')
    url=s3.generate_presigned_url('get_object',Params={'Bucket':state['bucket'],'Key':key},ExpiresIn=900)
    script="""import hashlib,io,os,pathlib,subprocess,urllib.request,zipfile
os.umask(0o077)
folder=pathlib.Path('/opt/career/ingestion-runs')/STAMP
folder.mkdir(parents=True,mode=0o700,exist_ok=False)
with urllib.request.urlopen(URL,timeout=30) as response:data=response.read(4*1024*1024+1)
if len(data)>4*1024*1024 or hashlib.sha256(data).hexdigest()!=CHECKSUM:raise RuntimeError('Package checksum mismatch')
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    if len(archive.infolist())!=4:raise RuntimeError('Unexpected package')
    for member in archive.infolist():
        path=pathlib.PurePosixPath(member.filename)
        if path.is_absolute() or len(path.parts)!=1 or member.file_size>1024*1024:raise RuntimeError('Invalid package')
    archive.extractall(folder)
raise SystemExit(subprocess.run(['/opt/career/venv/bin/python',str(folder/'remote_apply_training.py'),str(folder/'input.json')],cwd=folder).returncode)
""".replace('STAMP',repr(stamp)).replace('URL',repr(url)).replace('CHECKSUM',repr(checksum))
    encoded=base64.b64encode(script.encode()).decode()
    command="/opt/career/venv/bin/python -c \"import base64; exec(base64.b64decode('"+encoded+"'))\""
    result=ssm.send_command(InstanceIds=[outputs['WorkerInstanceId']],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=300,Comment='User requested real training sample: backup, new-only transaction and readback tests')
    saved={'command_id':result['Command']['CommandId'],'instance_id':outputs['WorkerInstanceId'],'batch':str(batch),'package_sha256':checksum,'s3_key':key}
    STATE.write_text(json.dumps(saved,indent=2),encoding='utf-8')
    print(json.dumps({'submitted':True,'records':len(rows),'command_id':saved['command_id']}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
        print('Training sample stopped: '+code,file=sys.stderr)
        raise SystemExit(1)
