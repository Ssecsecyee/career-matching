"""User-run low-cost backend deployment; never provisions anything on import."""
import argparse
from datetime import datetime,timezone
import gzip
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile,ZIP_DEFLATED

from deploy import session,client,outputs
from backend_template import backend_template

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
STATE=HERE/'.build/backend-state.json'
BUILD=HERE/'.build/backend-build.json'

def digest(value):return hashlib.sha256(value).hexdigest()
def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')

def build(args):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=HERE/'.build'/('backend-'+stamp)
    folder.mkdir(parents=True,exist_ok=False)
    rows=json.loads((ROOT/'app/backend/local-data/jumpit_all_v3/jobs.normalized.json').read_text(encoding='utf-8-sig'))
    data=(ROOT/'app/backend/local-data/jumpit_all_v3/jobs.data.sql').read_bytes()
    if data.count(b'INSERT INTO job_postings (')!=len(rows) or not rows:raise ValueError('SQL snapshot count mismatch')
    src=ROOT/'app/backend/src'
    for target,worker in [('api.zip',False),('worker.zip',True)]:
        with ZipFile(folder/target,'w',ZIP_DEFLATED) as archive:
            for path in src.rglob('*.py'):
                archive.write(path,'src/'+path.relative_to(src).as_posix())
            if worker:
                for name in ['worker.py','install_worker.py','server_admin.py']:
                    archive.write(ROOT/'app/backend'/name,name)
                archive.write(ROOT/'app/backend/database/schema.sql','schema.sql')
                archive.writestr('jobs.data.sql.gz',gzip.compress(data,mtime=0))
    (folder/'template.json').write_text(json.dumps(backend_template(),indent=2),encoding='utf-8')
    value={'folder':str(folder),'jobs':len(rows),'stamp':stamp,
           'hashes':{name:digest((folder/name).read_bytes()) for name in ['api.zip','worker.zip']}}
    save(BUILD,value)
    print(json.dumps({'status':'built','jobs':len(rows),'folder':str(folder),'aws_operations':0}))

def preflight(args,sess):
    account=client(sess,'sts').get_caller_identity()['Account']
    ec2=client(sess,'ec2')
    offered=ec2.describe_instance_type_offerings(LocationType='region',Filters=[{'Name':'instance-type','Values':['t4g.small']}])['InstanceTypeOfferings']
    if not offered:raise ValueError('t4g.small unavailable')
    ami=client(sess,'ssm').get_parameter(Name='/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64')['Parameter']['Value']
    images=ec2.describe_images(ImageIds=[ami],Owners=['amazon'])['Images']
    if not images or images[0]['Architecture']!='arm64' or images[0]['RootDeviceType']!='ebs':raise ValueError('Invalid official AMI')
    print(json.dumps({'account':account,'region':args.region,'instance_type':'t4g.small','ami':ami,
        'note':'One host for MySQL + worker. Elasticsearch not included; no inbound ports. Read-only checks only.'}))
    return account,ami

def plan(args):
    from botocore.exceptions import ClientError
    sess=session(args)
    account,ami=preflight(args,sess)
    value=json.loads(BUILD.read_text(encoding='utf-8'))
    folder=Path(value['folder'])
    bucket=f'{args.stack}-artifacts-{account}-{args.region}'
    s3=client(sess,'s3')
    try:s3.head_bucket(Bucket=bucket,ExpectedBucketOwner=account)
    except ClientError as exc:
        if exc.response['Error']['Code'] not in {'404','NoSuchBucket','NotFound'}:raise
        s3.create_bucket(Bucket=bucket,CreateBucketConfiguration={'LocationConstraint':args.region})
    s3.put_public_access_block(Bucket=bucket,PublicAccessBlockConfiguration=dict.fromkeys(['BlockPublicAcls','BlockPublicPolicy','IgnorePublicAcls','RestrictPublicBuckets'],True))
    s3.put_bucket_encryption(Bucket=bucket,ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
    s3.put_bucket_versioning(Bucket=bucket,VersioningConfiguration={'Status':'Enabled'})
    s3.put_bucket_policy(Bucket=bucket,Policy=json.dumps({'Version':'2012-10-17','Statement':[{'Effect':'Deny','Principal':'*','Action':'s3:*',
        'Resource':[f'arn:aws:s3:::{bucket}',f'arn:aws:s3:::{bucket}/*'],'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}))
    prefix='backend/'+value['stamp']
    for name,checksum in value['hashes'].items():
        data=(folder/name).read_bytes()
        if digest(data)!=checksum:raise ValueError('Artifact changed after build')
        s3.put_object(Bucket=bucket,Key=prefix+'/'+name,Body=data,ServerSideEncryption='AES256')
    cf=client(sess,'cloudformation')
    try:
        existing=cf.describe_stacks(StackName=args.stack)['Stacks'][0]
    except ClientError as exc:
        if 'does not exist' not in exc.response.get('Error',{}).get('Message',''):raise
    else:
        if existing['StackStatus'] != 'REVIEW_IN_PROGRESS':
            raise ValueError('Backend stack already exists; do not replace its database host. Use the maintenance guide.')
    body=json.dumps(backend_template())
    cf.validate_template(TemplateBody=body)
    params={'ArtifactBucket':bucket,'WorkerKey':prefix+'/worker.zip','WorkerHash':value['hashes']['worker.zip'],
            'ApiKey':prefix+'/api.zip','AmiId':ami,'ExpectedJobs':str(value['jobs'])}
    result=cf.create_change_set(StackName=args.stack,ChangeSetName='backend-'+value['stamp'],ChangeSetType='CREATE',TemplateBody=body,
        Parameters=[{'ParameterKey':k,'ParameterValue':v} for k,v in params.items()],Capabilities=['CAPABILITY_IAM'],
        Tags=[{'Key':'Project','Value':'career-matching'},{'Key':'Purpose','Value':'low-cost-test'}])
    if STATE.exists():
        previous=json.loads(STATE.read_text(encoding='utf-8'))
        if previous.get('stack')!=args.stack:
            save(STATE.with_name('backend-state-before-'+value['stamp']+'.json'),previous)
    save(STATE,{'stack':args.stack,'profile':args.profile,'region':args.region,'change_set':result['Id'],'bucket':bucket,'folder':str(folder)})
    print(json.dumps({'status':'planned_not_applied','change_set':result['Id'],'fixed_resources':['1 x t4g.small (2GB)','30GB encrypted gp3','1 public IPv4 for outbound only','2 secrets'],
        'usage_resources':['Lambda','HTTP API','SQS','temporary DynamoDB jobs','S3','Bedrock'],
        'excluded':['RDS','Elasticsearch','NAT','interface VPC endpoints'],
        'note':'Artifact S3 bucket was uploaded. Paid backend resources are not created until apply; actual monthly total depends on usage.'},indent=2))

def state(args):
    value=json.loads(STATE.read_text(encoding='utf-8'))
    if (value['stack'],value['profile'],value['region'])!=(args.stack,args.profile,args.region):raise ValueError('Plan arguments differ')
    return value

def review(args):
    value=state(args)
    result=client(session(args),'cloudformation').describe_change_set(ChangeSetName=value['change_set'])
    print(json.dumps({'status':result['Status'],'reason':result.get('StatusReason'),'changes':[
        {k:c['ResourceChange'].get(k) for k in ['Action','LogicalResourceId','ResourceType','Replacement']} for c in result.get('Changes',[])]},indent=2))

def apply(args):
    if not args.confirm_costs:raise ValueError('Review ongoing EC2/EBS/IPv4 costs and use --confirm-costs')
    value=state(args)
    cf=client(session(args),'cloudformation')
    result=cf.describe_change_set(ChangeSetName=value['change_set'])
    if result['Status']!='CREATE_COMPLETE':raise ValueError('Change set not ready')
    cf.execute_change_set(ChangeSetName=value['change_set'])
    print('Backend creation started. Run status, then inspect server bootstrap. Do not re-run apply.')

def status(args):
    state(args)
    cf=client(session(args),'cloudformation')
    stack=cf.describe_stacks(StackName=args.stack)['Stacks'][0]
    print(json.dumps({'status':stack['StackStatus'],'outputs':outputs(cf,args.stack)},indent=2))

def resources(args):
    # Explicit read-only inventory also supports an older failed stack.
    cf=client(session(args),'cloudformation')
    rows=[]
    for page in cf.get_paginator('list_stack_resources').paginate(StackName=args.stack):
        for item in page['StackResourceSummaries']:
            rows.append({key:item.get(key) for key in ('LogicalResourceId','ResourceType','ResourceStatus','PhysicalResourceId')})
    print(json.dumps({'stack':args.stack,'resources':rows,'note':'Read-only inventory; retained resources may still incur charges. External artifact S3 bucket is not listed here.'},indent=2))


def inspect(args):
    state(args)
    sess=session(args)
    out=outputs(client(sess,'cloudformation'),args.stack)
    if not out.get('WorkerInstanceId'):
        print('Backend is not ready. Run backend.py status and wait for CREATE_COMPLETE before inspect.')
        return
    ssm=client(sess,'ssm')
    result=ssm.send_command(InstanceIds=[out['WorkerInstanceId']],DocumentName='AWS-RunShellScript',
        Parameters={'commands':['set -e','systemctl is-active career-worker','/opt/career/venv/bin/python /opt/career/app/server_admin.py inspect']},
        TimeoutSeconds=60,Comment='Career worker status and aggregate DB usage only')
    value=state(args)
    value['inspection_command']=result['Command']['CommandId']
    save(STATE,value)
    print('Inspection submitted. Run inspect-result; output contains counts only, never credentials.')

def inspect_result(args):
    value=state(args)
    if not value.get('inspection_command'):
        print('No inspection was submitted. Wait for CREATE_COMPLETE, then run backend.py inspect first.')
        return
    sess=session(args)
    out=outputs(client(sess,'cloudformation'),args.stack)
    if not out.get('WorkerInstanceId'):
        print('Backend is not ready. Run backend.py status first.')
        return
    result=client(sess,'ssm').get_command_invocation(CommandId=value['inspection_command'],InstanceId=out['WorkerInstanceId'])
    print(json.dumps({'status':result['Status'],'output':result['StandardOutputContent'],'error':result['StandardErrorContent']},ensure_ascii=False,indent=2))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','preflight','plan','review','apply','status','resources','inspect','inspect-result'])
    parser.add_argument('--profile',default='myisb_IsbUsersPS-954935267704')
    parser.add_argument('--region',default='ap-northeast-2',choices=['ap-northeast-2'])
    parser.add_argument('--stack',help='Defaults to the latest saved backend plan, initially career-backend-test')
    parser.add_argument('--confirm-costs',action='store_true')
    args=parser.parse_args()
    try:
        if not args.stack:
            args.stack=json.loads(STATE.read_text(encoding='utf-8')).get('stack','career-backend-test') if STATE.exists() else 'career-backend-test'
        if args.action=='preflight':preflight(args,session(args))
        else:globals()[args.action.replace('-','_')](args)
    except Exception as exc:
        code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
        detail = ' '+str(exc) if type(exc) is ValueError else ''
        print('Stopped: '+code+'.'+detail+' Check BACKEND.md; do not share keys or passwords.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
