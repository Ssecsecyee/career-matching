"""User-run build/plan/apply/publish/inspect. No AWS action on import."""
import argparse
import gzip
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import urlopen
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parents[1]
HERE=Path(__file__).resolve().parent
STATE=HERE/'.build'

def digest(data): return hashlib.sha256(data).hexdigest()
def saved(path,value): path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
def session(args):
    import boto3
    return boto3.Session(profile_name=args.profile,region_name=args.region)
def client(sess,name):
    from botocore.config import Config
    return sess.client(name,config=Config(connect_timeout=5,read_timeout=40,retries={'mode':'standard','total_max_attempts':2}))

def build(args):
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder=STATE/stamp
    folder.mkdir(parents=True,exist_ok=False)
    package=folder/'package'
    package.mkdir()
    subprocess.run([sys.executable,'-m','pip','install','-r',str(ROOT/'app/backend/requirements.txt'),
        '--target',str(package),'--platform','manylinux2014_x86_64','--implementation','cp','--python-version','3.11',
        '--only-binary=:all:','--no-compile'],check=True)
    shutil.copytree(ROOT/'app/backend/src',package/'src',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (package/'certs').mkdir()
    with urlopen('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem',timeout=30) as response:
        ca=response.read(1024*1024)
    if b'BEGIN CERTIFICATE' not in ca: raise ValueError('Invalid RDS CA bundle')
    (package/'certs/rds-global.pem').write_bytes(ca)
    zip_path=folder/'backend.zip'
    with ZipFile(zip_path,'w',ZIP_DEFLATED) as archive:
        for path in package.rglob('*'):
            if path.is_file():
                if path.name.startswith('.env') or path.suffix=='.pyc': continue
                archive.write(path,path.relative_to(package).as_posix())
    sql=ROOT/'app/backend/local-data/jumpit_all_v3/jobs.data.sql'
    normalized=ROOT/'app/backend/local-data/jumpit_all_v3/jobs.normalized.json'
    rows=json.loads(normalized.read_text(encoding='utf-8-sig'))
    if not rows or len({row['source_id'] for row in rows})!=len(rows): raise ValueError('Invalid normalized snapshot')
    if sql.read_text(encoding='utf-8-sig').count('INSERT INTO job_postings (') != len(rows):
        raise ValueError('SQL and JSON snapshot counts differ; regenerate data SQL before deployment')
    schema=ROOT/'app/backend/database/schema.sql'
    shutil.copyfile(schema,folder/'schema.sql')
    (folder/'jobs.data.sql.gz').write_bytes(gzip.compress(sql.read_bytes(),mtime=0))
    (folder/'jobs.normalized.json.gz').write_bytes(gzip.compress(normalized.read_bytes(),mtime=0))
    npm=shutil.which('npm.cmd') or shutil.which('npm')
    subprocess.run([npm,'run','build'],cwd=ROOT/'app/frontend',check=True)
    shutil.copytree(ROOT/'app/frontend/dist',folder/'web')
    subprocess.run([sys.executable,str(HERE/'generate_template.py')],check=True)
    manifest={'folder':str(folder),'stamp':stamp,'jobs':len(rows),
              'hashes':{name:digest((folder/name).read_bytes()) for name in ['backend.zip','schema.sql','jobs.data.sql.gz','jobs.normalized.json.gz']}}
    saved(folder/'manifest.json',manifest)
    STATE.mkdir(exist_ok=True)
    saved(STATE/'latest.json',manifest)
    print(json.dumps({'status':'built','jobs':len(rows),'manifest':str(folder/'manifest.json'),'aws_operations':0}))

def preflight(args,sess):
    identity=client(sess,'sts').get_caller_identity()
    rds=client(sess,'rds')
    versions=[]
    for page in rds.get_paginator('describe_db_engine_versions').paginate(Engine='mysql',IncludeAll=False):
        versions += page['DBEngineVersions']
    versions=[v for v in versions if v['EngineVersion'].startswith('8.4.') and v.get('Status')=='available']
    if not versions: raise ValueError('No supported MySQL 8.4 version found in this account/region')
    version=max(versions,key=lambda v:tuple(int(x) for x in v['EngineVersion'].split('.')))['EngineVersion']
    offered=rds.describe_orderable_db_instance_options(Engine='mysql',EngineVersion=version,DBInstanceClass='db.t4g.micro',Vpc=True)['OrderableDBInstanceOptions']
    if not offered: raise ValueError('db.t4g.micro is not offered with the selected MySQL version')
    profiles=[]
    for page in client(sess,'bedrock').get_paginator('list_inference_profiles').paginate():
        profiles += page['inferenceProfileSummaries']
    if not any(p['inferenceProfileId']=='global.anthropic.claude-sonnet-4-6' for p in profiles):
        raise ValueError('Configured Sonnet inference profile is not listed')
    print(json.dumps({'account':identity['Account'],'region':args.region,'mysql_version':version,'sonnet_listed':True,
        'note':'Read-only preflight. Model invocation rights and resource creation rights still need deployment validation.'}))
    return identity['Account'],version

def plan(args):
    if not args.monthly_budget_usd or not args.budget_email: raise ValueError('Provide --monthly-budget-usd and --budget-email before planning paid resources')
    sess=session(args)
    account,version=preflight(args,sess)
    manifest=json.loads((STATE/'latest.json').read_text(encoding='utf-8'))
    folder=Path(manifest['folder'])
    bucket=f'{args.stack}-artifacts-{account}-{args.region}'
    s3=client(sess,'s3')
    from botocore.exceptions import ClientError
    try:
        s3.head_bucket(Bucket=bucket,ExpectedBucketOwner=account)
    except ClientError as exc:
        if exc.response['Error']['Code'] not in {'404','NoSuchBucket','NotFound'}: raise
        s3.create_bucket(Bucket=bucket,CreateBucketConfiguration={'LocationConstraint':args.region})
    s3.put_public_access_block(Bucket=bucket,PublicAccessBlockConfiguration=dict.fromkeys(['BlockPublicAcls','IgnorePublicAcls','BlockPublicPolicy','RestrictPublicBuckets'],True))
    s3.put_bucket_encryption(Bucket=bucket,ServerSideEncryptionConfiguration={'Rules':[{'ApplyServerSideEncryptionByDefault':{'SSEAlgorithm':'AES256'}}]})
    s3.put_bucket_versioning(Bucket=bucket,VersioningConfiguration={'Status':'Enabled'})
    s3.put_bucket_policy(Bucket=bucket,Policy=json.dumps({'Version':'2012-10-17','Statement':[{'Effect':'Deny','Principal':'*','Action':'s3:*','Resource':[f'arn:aws:s3:::{bucket}',f'arn:aws:s3:::{bucket}/*'],'Condition':{'Bool':{'aws:SecureTransport':'false'}}}]}))
    prefix='releases/'+manifest['stamp']
    for name in manifest['hashes']:
        data=(folder/name).read_bytes()
        if digest(data)!=manifest['hashes'][name]: raise ValueError('Build artifact changed after build')
        s3.put_object(Bucket=bucket,Key=prefix+'/'+name,Body=data,ServerSideEncryption='AES256')
    cf=client(sess,'cloudformation')
    contents=(HERE/'template.json').read_text(encoding='utf-8')
    cf.validate_template(TemplateBody=contents)
    parameters={'ArtifactBucket':bucket,'CodeKey':prefix+'/backend.zip','SchemaKey':prefix+'/schema.sql','DataKey':prefix+'/jobs.data.sql.gz',
        'SchemaHash':manifest['hashes']['schema.sql'],'DataHash':manifest['hashes']['jobs.data.sql.gz'],'ExpectedJobs':str(manifest['jobs']),
        'DbEngineVersion':version,'MonthlyBudgetUsd':str(args.monthly_budget_usd),'BudgetEmail':args.budget_email,
        'EnableBootstrap':'true' if args.bootstrap else 'false'}
    kind='UPDATE'
    try:
        existing=cf.describe_stacks(StackName=args.stack)['Stacks'][0]
        previous={p['ParameterKey']:p['ParameterValue'] for p in existing.get('Parameters',[])}
        if 'DbEngineVersion' in previous: parameters['DbEngineVersion']=previous['DbEngineVersion']
    except ClientError as exc:
        if 'does not exist' not in exc.response.get('Error',{}).get('Message',''): raise
        kind='CREATE'
    name='review-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    result=cf.create_change_set(StackName=args.stack,ChangeSetName=name,ChangeSetType=kind,TemplateBody=contents,
        Parameters=[{'ParameterKey':k,'ParameterValue':v} for k,v in parameters.items()],Capabilities=['CAPABILITY_IAM'],
        Tags=[{'Key':'Project','Value':'career-matching'},{'Key':'Purpose','Value':'team-test'}])
    state={'stack':args.stack,'change_set':result['Id'],'region':args.region,'profile':args.profile,'bucket':bucket,'folder':str(folder),'monthly_budget_usd':args.monthly_budget_usd}
    saved(STATE/'deployment.json',state)
    print(json.dumps({'status':'change_set_created_not_executed','stack':args.stack,'change_set':result['Id'],
        'ongoing_resources':['Single-AZ RDS db.t4g.micro + 20GB','4 interface endpoint ENIs (2 services x 2 AZs)','Secrets Manager','S3','CloudFront','Lambda/API/logs/dashboard'],
        'budget_note':'Account-wide email alert only, not a hard spending cap. Artifacts S3 bucket was created/uploaded; application resources have not been created.'},ensure_ascii=False,indent=2))

def state_client(args,name):
    state=json.loads((STATE/'deployment.json').read_text(encoding='utf-8'))
    if args.stack!=state['stack'] or args.region!=state['region'] or args.profile!=state['profile']:
        raise ValueError('Deployment arguments differ from saved plan')
    return state,client(session(args),name)

def outputs(cf,stack):
    return {x['OutputKey']:x['OutputValue'] for x in cf.describe_stacks(StackName=stack)['Stacks'][0].get('Outputs',[])}

def review(args):
    state,cf=state_client(args,'cloudformation')
    result=cf.describe_change_set(ChangeSetName=state['change_set'])
    print(json.dumps({'status':result['Status'],'reason':result.get('StatusReason'),'changes':[
        {k:c['ResourceChange'].get(k) for k in ('Action','LogicalResourceId','ResourceType','Replacement')} for c in result.get('Changes',[])]},indent=2))

def apply(args):
    if not args.confirm_costs: raise ValueError('Review changes and ongoing costs, then pass --confirm-costs explicitly')
    state,cf=state_client(args,'cloudformation')
    change=cf.describe_change_set(ChangeSetName=state['change_set'])
    if change['Status']!='CREATE_COMPLETE': raise ValueError('Change set is not ready; use review')
    cf.execute_change_set(ChangeSetName=state['change_set'])
    print('Deployment started. Run status periodically; do not re-run apply.')

def status(args):
    state,cf=state_client(args,'cloudformation')
    stack=cf.describe_stacks(StackName=args.stack)['Stacks'][0]
    print(json.dumps({'status':stack['StackStatus'],'outputs':outputs(cf,args.stack)},indent=2))

def invoke(args,which,action):
    _,cf=state_client(args,'cloudformation')
    out=outputs(cf,args.stack)
    if which not in out: raise ValueError('Function not present; check stack status and bootstrap setting')
    fn=client(session(args),'lambda')
    if which=='BootstrapFunction':
        from botocore.config import Config
        fn=session(args).client('lambda',config=Config(connect_timeout=5,read_timeout=330,retries={'mode':'standard','total_max_attempts':1}))
    result=fn.invoke(FunctionName=out[which],InvocationType='RequestResponse',Payload=json.dumps({'action':action}).encode())
    body=result['Payload']
    try: text=body.read().decode()
    finally: body.close()
    if result.get('FunctionError'): raise RuntimeError('Lambda failed; inspect function logs without posting credentials')
    print(text)

def publish(args):
    state,cf=state_client(args,'cloudformation')
    out=outputs(cf,args.stack)
    s3=client(session(args),'s3')
    folder=Path(state['folder'])/'web'
    for file in folder.rglob('*'):
        if file.is_file():
            key=file.relative_to(folder).as_posix()
            content_type=mimetypes.guess_type(key)[0] or 'application/octet-stream'
            if key.endswith('.js'): content_type='text/javascript'
            s3.put_object(Bucket=out['WebBucket'],Key=key,Body=file.read_bytes(),ContentType=content_type,
                CacheControl='no-cache' if key in {'index.html','deploy-config.json'} else 'public,max-age=31536000,immutable',ServerSideEncryption='AES256')
    client(session(args),'cloudfront').create_invalidation(DistributionId=out['DistributionId'],InvalidationBatch={
        'Paths':{'Quantity':1,'Items':['/*']},'CallerReference':datetime.now(timezone.utc).isoformat()})
    print(out['WebsiteUrl'])

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','preflight','plan','review','apply','status','initialize','publish','inspect'])
    parser.add_argument('--profile',default='myisb_IsbUsersPS-954935267704')
    parser.add_argument('--region',default='ap-northeast-2',choices=['ap-northeast-2'])
    parser.add_argument('--stack',default='career-matching-test')
    parser.add_argument('--monthly-budget-usd',type=float)
    parser.add_argument('--budget-email')
    parser.add_argument('--bootstrap',action='store_true')
    parser.add_argument('--confirm-costs',action='store_true')
    args=parser.parse_args()
    try:
        if args.action=='preflight': preflight(args,session(args))
        elif args.action=='initialize': invoke(args,'BootstrapFunction','initialize')
        elif args.action=='inspect': invoke(args,'InspectFunction','summary')
        else: globals()[args.action](args)
    except Exception as exc:
        # Avoid printing exception bodies that might contain secret values or user content.
        code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
        print('Stopped: '+code+'. Check prerequisites and the deployment guide.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())
