"""User-run static hosting only. No RDS, Lambda, Elasticsearch or VPC endpoints."""
import argparse
from datetime import datetime, timezone
import json
import mimetypes
import re
from pathlib import Path
import shutil
import subprocess
import sys

from deploy import session, client, outputs
from generate_template import template

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
STATE=HERE/'.build/hosting-state.json'

def hosting_template(api_origin=None):
    full=template()
    keep={'WebBucket','Oac','SecurityHeaders','Distribution','WebPolicy'}
    resources={k:v for k,v in full['Resources'].items() if k in keep}
    config=resources['Distribution']['Properties']['DistributionConfig']
    config['Origins']=[o for o in config['Origins'] if o['Id']=='web']
    config.pop('CacheBehaviors')
    result = {'AWSTemplateFormatVersion':'2010-09-09','Description':'Career React static hosting only. Backend not connected.',
        'Metadata':full['Metadata'],'Resources':resources,
        'Outputs':{k:v for k,v in full['Outputs'].items() if k in {'WebsiteUrl','WebBucket','DistributionId'}}}
    if api_origin:
        validate_origin(api_origin)
        result['Parameters'] = {'ApiOriginDomain': {'Type': 'String', 'AllowedPattern': r'[a-z0-9]+\.execute-api\.ap-northeast-2\.amazonaws\.com'}}
        config['Origins'].append({'Id':'api','DomainName':{'Ref':'ApiOriginDomain'},'CustomOriginConfig':{'OriginProtocolPolicy':'https-only','OriginSSLProtocols':['TLSv1.2']}})
        config['CacheBehaviors'] = [{'PathPattern':'/api/*','TargetOriginId':'api','ViewerProtocolPolicy':'https-only',
            'AllowedMethods':['GET','HEAD','OPTIONS','PUT','PATCH','POST','DELETE'],'CachedMethods':['GET','HEAD'],
            'CachePolicyId':'4135ea2d-6df8-44a3-9df3-4b5a84be39ad','OriginRequestPolicyId':'b689b0a8-53d0-40ab-baf2-68738e2966ac',
            'ResponseHeadersPolicyId':{'Ref':'SecurityHeaders'}}]
        result['Description'] = 'Career React hosting with HTTPS queued backend; API responses are never cached.'
    return result


def validate_origin(value):
    value=value.rstrip('/')
    if not re.fullmatch(r'https://[a-z0-9]+\.execute-api\.ap-northeast-2\.amazonaws\.com',value):
        raise ValueError('Only the deployed Seoul HTTP API endpoint is accepted')
    return value.split('://',1)[1]


def saved(value):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    STATE.write_text(json.dumps(value,indent=2),encoding='utf-8')

def state(args):
    value=json.loads(STATE.read_text(encoding='utf-8'))
    if (value['stack'],value['region'],value['profile'])!=(args.stack,args.region,args.profile):
        raise ValueError('Saved plan arguments differ')
    return value

def plan(args):
    from botocore.exceptions import ClientError
    cf=client(session(args),'cloudformation')
    previous=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    origin=args.api_origin or previous.get('api_origin')
    value=hosting_template(origin)
    body=json.dumps(value)
    STATE.parent.mkdir(parents=True,exist_ok=True)
    (STATE.parent/'hosting-template.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
    cf.validate_template(TemplateBody=body)
    kind='UPDATE'
    try: cf.describe_stacks(StackName=args.stack)
    except ClientError as exc:
        if 'does not exist' not in exc.response.get('Error',{}).get('Message',''): raise
        kind='CREATE'
    name='hosting-'+datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')
    result=cf.create_change_set(StackName=args.stack,ChangeSetName=name,ChangeSetType=kind,TemplateBody=body,
        Tags=[{'Key':'Project','Value':'career-matching'},{'Key':'Purpose','Value':'static-hosting'}],
        Parameters=[{'ParameterKey':'ApiOriginDomain','ParameterValue':validate_origin(origin)}] if origin else [])
    saved({'stack':args.stack,'region':args.region,'profile':args.profile,'change_set':result['Id'],'api_origin':origin})
    print(json.dumps({'status':'planned_not_applied','resources':list(value['Resources']),
        'note':'Static hosting only. S3/CloudFront usage charges may apply after apply; no database or backend.'}))

def review(args):
    value=state(args)
    result=client(session(args),'cloudformation').describe_change_set(ChangeSetName=value['change_set'])
    print(json.dumps({'status':result['Status'],'reason':result.get('StatusReason'),'changes':[
        {k:c['ResourceChange'].get(k) for k in ['Action','LogicalResourceId','ResourceType','Replacement']} for c in result.get('Changes',[])]},indent=2))

def apply(args):
    value=state(args)
    cf=client(session(args),'cloudformation')
    result=cf.describe_change_set(ChangeSetName=value['change_set'])
    if result['Status']!='CREATE_COMPLETE': raise ValueError('Change set not ready; run review')
    cf.execute_change_set(ChangeSetName=value['change_set'])
    print('Hosting creation started. Run status; no RDS or VPC endpoints created.')

def status(args):
    state(args)
    cf=client(session(args),'cloudformation')
    result=cf.describe_stacks(StackName=args.stack)['Stacks'][0]
    print(json.dumps({'status':result['StackStatus'],'outputs':outputs(cf,args.stack)},indent=2))

def publish(args):
    current=state(args)
    sess=session(args)
    cf=client(sess,'cloudformation')
    result=cf.describe_stacks(StackName=args.stack)['Stacks'][0]
    if result['StackStatus'] not in {'CREATE_COMPLETE','UPDATE_COMPLETE'}: raise ValueError('Hosting stack is not ready')
    origin=current.get('api_origin')
    if origin:
        parameters={p['ParameterKey']:p['ParameterValue'] for p in result.get('Parameters',[])}
        if parameters.get('ApiOriginDomain') != validate_origin(origin): raise ValueError('Apply the hosting API change before enabling the chat UI')
    out=outputs(cf,args.stack)
    npm=shutil.which('npm.cmd') or shutil.which('npm')
    subprocess.run([npm,'run','build'],cwd=ROOT/'app/frontend',check=True)
    s3=client(sess,'s3')
    for path in (ROOT/'app/frontend/dist').rglob('*'):
        if not path.is_file(): continue
        key=path.relative_to(ROOT/'app/frontend/dist').as_posix()
        if key=='deploy-config.json': continue
        content_type='text/javascript' if key.endswith('.js') else (mimetypes.guess_type(key)[0] or 'application/octet-stream')
        s3.put_object(Bucket=out['WebBucket'],Key=key,Body=path.read_bytes(),ContentType=content_type,
            CacheControl='no-cache' if key=='index.html' else 'public,max-age=31536000,immutable',ServerSideEncryption='AES256')
    s3.put_object(Bucket=out['WebBucket'],Key='deploy-config.json',Body=json.dumps({'apiEnabled':bool(origin)}).encode(),
        ContentType='application/json',CacheControl='no-store',ServerSideEncryption='AES256')
    client(sess,'cloudfront').create_invalidation(DistributionId=out['DistributionId'],InvalidationBatch={
        'Paths':{'Quantity':1,'Items':['/*']},'CallerReference':datetime.now(timezone.utc).isoformat()})
    print(json.dumps({'url':out['WebsiteUrl'],'backend_connected':bool(origin)}))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['template','plan','review','apply','status','publish'])
    parser.add_argument('--api-origin',help='HTTPS endpoint from backend.py status; preserve existing origin when omitted')
    parser.add_argument('--profile',default='myisb_IsbUsersPS-954935267704')
    parser.add_argument('--region',default='ap-northeast-2',choices=['ap-northeast-2'])
    parser.add_argument('--stack',default='career-matching-web')
    args=parser.parse_args()
    try:
        if args.action=='template':
            STATE.parent.mkdir(parents=True,exist_ok=True)
            (STATE.parent/'hosting-template.json').write_text(json.dumps(hosting_template(args.api_origin),indent=2),encoding='utf-8')
            print('Generated infra/.build/hosting-template.json; no AWS operations.')
        else: globals()[args.action](args)
    except Exception as exc:
        code=getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)
        print('Stopped: '+code+'. Review hosting instructions; do not share credentials.',file=sys.stderr)
        return 1
    return 0

if __name__=='__main__':
    raise SystemExit(main())
