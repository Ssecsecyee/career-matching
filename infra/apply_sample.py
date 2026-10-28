"""Explicit one-batch production insertion through SSM; no new AWS resources."""
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
STATE=ROOT/'infra/.build/sample-apply-state.json'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['submit','result'])
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
        if result['Status']=='Success':
            folder=Path(value['folder']);(folder/'result.json').write_text(output,encoding='utf-8')
        return
    if STATE.exists():raise ValueError('A sample submission exists. Inspect its result; do not resubmit automatically.')
    cf=session.client('cloudformation',config=config)
    stack=cf.describe_stacks(StackName=state['stack'])['Stacks'][0]
    if stack['StackStatus'] not in {'CREATE_COMPLETE','UPDATE_COMPLETE'}:raise ValueError('Stack not ready')
    outputs={item['OutputKey']:item['OutputValue'] for item in stack['Outputs']}
    sys.path.insert(0,str(ROOT/'app/ingestion'))
    from incremental_jumpit import prepare
    batch=ROOT/'workspace/incoming/jumpit/jumpit_20261028_094454_quality01'
    rows,_=prepare(batch)
    if len(rows)!=10:raise ValueError('Expected exactly ten sample records')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=ROOT/'infra/.build'/('sample-apply-'+stamp);folder.mkdir(parents=True,exist_ok=False)
    package=folder/'sample.zip'
    with ZipFile(package,'w',ZIP_DEFLATED) as archive:
        for name in ['incremental_jumpit.py','normalize_jumpit.py','normalize_all_jumpit.py','export_mysql_data.py','page_extraction.py','remote_apply_new.py']:
            archive.write(ROOT/'app/ingestion'/name,name)
        archive.write(batch/'manifest.json','batch/manifest.json')
        for path in sorted((batch/'raw/details').glob('*.json')):archive.write(path,'batch/raw/details/'+path.name)
    data=package.read_bytes();checksum=hashlib.sha256(data).hexdigest()
    s3=session.client('s3',region_name=state['region'],config=Config(signature_version='s3v4',s3={'addressing_style':'virtual'},connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2}))
    key='ingestion-samples/'+stamp+'/sample.zip'
    s3.put_object(Bucket=state['bucket'],Key=key,Body=data,ServerSideEncryption='AES256')
    url=s3.generate_presigned_url('get_object',Params={'Bucket':state['bucket'],'Key':key},ExpiresIn=900)
    script="""import hashlib,io,os,pathlib,subprocess,urllib.request,zipfile
os.umask(0o077)
folder=pathlib.Path('/opt/career/ingestion-runs')/STAMP
folder.mkdir(parents=True,mode=0o700,exist_ok=False)
with urllib.request.urlopen(URL,timeout=30) as response:data=response.read(20*1024*1024+1)
if len(data)>20*1024*1024 or hashlib.sha256(data).hexdigest()!=CHECKSUM:raise RuntimeError('Package checksum mismatch')
with zipfile.ZipFile(io.BytesIO(data)) as archive:
    for member in archive.infolist():
        path=pathlib.PurePosixPath(member.filename)
        if path.is_absolute() or '..' in path.parts or member.file_size>4*1024*1024:raise RuntimeError('Invalid package path or size')
    if sum(x.file_size for x in archive.infolist())>50*1024*1024:raise RuntimeError('Expanded package too large')
    archive.extractall(folder)
result=subprocess.run(['/opt/career/venv/bin/python',str(folder/'remote_apply_new.py'),str(folder/'batch')],cwd=folder)
raise SystemExit(result.returncode)
""".replace('STAMP',repr(stamp)).replace('URL',repr(url)).replace('CHECKSUM',repr(checksum))
    encoded=base64.b64encode(script.encode()).decode()
    command="/opt/career/venv/bin/python -c \"import base64; exec(base64.b64decode('"+encoded+"'))\""
    result=ssm.send_command(InstanceIds=[outputs['WorkerInstanceId']],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=300,
        Comment='Requested 10 new jobs only; verified DB backup; temporary least-privilege writer')
    saved={'command_id':result['Command']['CommandId'],'instance_id':outputs['WorkerInstanceId'],'folder':str(folder),'package_sha256':checksum,'s3_key':key,'batch_id':batch.name}
    STATE.write_text(json.dumps(saved,indent=2),encoding='utf-8')
    print(json.dumps({'submitted':True,'command_id':saved['command_id'],'expected_new_jobs':10}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
        print('Sample operation stopped: '+code,file=sys.stderr)
        raise SystemExit(1)
