"""Publish exactly three pre-reviewed v2 pilot candidates; no model calls."""
import argparse,base64,hashlib,json,sys
from pathlib import Path
import boto3
from botocore.config import Config
from build_condition_review_bundle import build
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/condition-v2-publication-state.json'

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['submit','result']);p.add_argument('--confirm-maintenance',action='store_true');p.add_argument('--candidates',type=Path);a=p.parse_args()
    backend=json.loads((ROOT/'infra/.build/backend-state.json').read_text())
    session=boto3.Session(profile_name=backend['profile'],region_name=backend['region'])
    cfg=Config(connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2})
    ssm=session.client('ssm',config=cfg)
    if a.action=='result':
        state=json.loads(STATE.read_text());value=ssm.get_command_invocation(CommandId=state['command_id'],InstanceId=state['instance'])
        output=value.get('StandardOutputContent','').strip()
        parsed=json.loads(output) if output else None
        report={'status':value['Status'],'result':parsed,'stderr_present':bool(value.get('StandardErrorContent'))}
        if value['Status'] in ('Success','Failed'):(Path(state['folder'])/'result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report));return 0 if value['Status'] in ('Success','Pending','InProgress','Delayed') else 1
    if not a.confirm_maintenance:p.error('Use --confirm-maintenance for the brief sync service update')
    if STATE.exists():raise ValueError('Submission already exists; inspect result before any retry')
    if session.client('sts',config=cfg).get_caller_identity()['Account']!='954935267704':raise ValueError('Unexpected AWS account')
    stack=session.client('cloudformation',config=cfg).describe_stacks(StackName=backend['stack'])['Stacks'][0]
    if stack['StackStatus'] not in {'CREATE_COMPLETE','UPDATE_COMPLETE'}:raise ValueError('Stack is not ready')
    instance=next(v['OutputValue'] for v in stack['Outputs'] if v['OutputKey']=='WorkerInstanceId')
    if not a.candidates:raise ValueError('Reviewed candidates file required')
    candidates=json.loads(a.candidates.read_text(encoding='utf-8'))
    if len(candidates)!=3:raise ValueError('Only three pilot candidates are allowed')
    sys.path.insert(0,str(ROOT/'app/backend'))
    from src.repositories.condition_drafts import validate_approval
    from src.services.condition_review import validated_envelope
    for item in candidates:validate_approval(validated_envelope(item['job'],item['review']),item['approval'])
    result=build();folder=Path(result['folder']);archive=folder/'condition-review.zip';stamp=folder.name
    import io,zipfile
    with zipfile.ZipFile(archive) as original:
        members={name:original.read(name) for name in original.namelist() if name!='manifest.json'}
    members['reviewed-pilot.json']=json.dumps(candidates,ensure_ascii=False).encode()
    manifest={name:hashlib.sha256(value).hexdigest() for name,value in members.items()}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as packed:
        for name,value in members.items():packed.writestr(name,value)
        packed.writestr('manifest.json',json.dumps(manifest))
    (folder/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    data=archive.read_bytes();result['sha256']=hashlib.sha256(data).hexdigest()
    s3=session.client('s3',config=Config(signature_version='s3v4',s3={'addressing_style':'virtual'},connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2}))
    key='condition-review-releases/'+stamp+'/condition-review.zip'
    s3.put_object(Bucket=backend['bucket'],Key=key,Body=data,ServerSideEncryption='AES256')
    url=s3.generate_presigned_url('get_object',Params={'Bucket':backend['bucket'],'Key':key},ExpiresIn=900)
    remote="""import hashlib,io,json,os,pathlib,stat,subprocess,urllib.request,zipfile
os.umask(0o077)
try:
 folder=pathlib.Path('/opt/career/condition-releases')/RELEASE_STAMP_VALUE
 folder.mkdir(parents=True,mode=0o700,exist_ok=False)
 with urllib.request.urlopen(DOWNLOAD_URL_VALUE,timeout=30) as response:data=response.read(10*1024*1024+1)
 if len(data)>10*1024*1024 or hashlib.sha256(data).hexdigest()!=PACKAGE_HASH_VALUE:raise ValueError('Package checksum mismatch')
 with zipfile.ZipFile(io.BytesIO(data)) as archive:
  names=archive.namelist()
  if len(names)!=len(set(names)):raise ValueError('Duplicate package path')
  manifest=json.loads(archive.read('manifest.json'))
  if set(names)!=set(manifest)|{'manifest.json'}:raise ValueError('Unexpected package files')
  if sum(m.file_size for m in archive.infolist())>20*1024*1024:raise ValueError('Expanded package too large')
  for member in archive.infolist():
   path=pathlib.PurePosixPath(member.filename)
   if path.is_absolute() or '..' in path.parts or member.file_size>1048576 or stat.S_ISLNK(member.external_attr>>16):raise ValueError('Invalid package path')
   if member.filename!='manifest.json' and hashlib.sha256(archive.read(member)).hexdigest()!=manifest[member.filename]:raise ValueError('File checksum mismatch')
  archive.extractall(folder)
 process=subprocess.run(['/opt/career/venv/bin/python',str(folder/'infra/elasticsearch/install_condition_review_v2.py')],capture_output=True,text=True,timeout=600)
 lines=process.stdout.strip().splitlines()
 report=json.loads(lines[-1]) if lines else {'status':'failed','error_type':'InstallerOutputMissing'}
 print(json.dumps(report))
 raise SystemExit(process.returncode)
except Exception as exc:
 print(json.dumps({'status':'failed','stage':'package_or_installer','error_type':type(exc).__name__}));raise SystemExit(1)
""".replace('RELEASE_STAMP_VALUE',repr(stamp)).replace('DOWNLOAD_URL_VALUE',repr(url)).replace('PACKAGE_HASH_VALUE',repr(result['sha256']))
    encoded=base64.b64encode(remote.encode()).decode()
    command="/opt/career/venv/bin/python -c \"import base64;exec(base64.b64decode('"+encoded+"'))\""
    job=ssm.send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=900,Comment='Publish three reviewed condition pilots with backup and ES readback; no model calls')
    state={'instance':instance,'command_id':job['Command']['CommandId'],'folder':str(folder),'sha256':result['sha256'],'s3_key':key}
    STATE.write_text(json.dumps(state,indent=2),encoding='utf-8')
    print(json.dumps({'status':'submitted','model_calls':0,'new_aws_resources':0}))
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
        print(json.dumps({'status':'stopped','error_type':type(exc).__name__,'code':code}));raise SystemExit(1)
