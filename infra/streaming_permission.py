"""CloudFormation-managed, single-action extension for the existing Sonnet role."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import boto3
from botocore.config import Config

ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/streaming-permission.json'

def review(cf,saved):
    value=cf.describe_change_set(ChangeSetName=saved['change_set'],StackName=saved['stack'])
    changes=[x['ResourceChange'] for x in value.get('Changes',[])]
    allowed=len(changes)==1 and changes[0]['LogicalResourceId']=='WorkerRole' and changes[0]['Action']=='Modify' and changes[0].get('Replacement') in (None,'False')
    return value,allowed

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['plan','review','apply','status']);args=parser.parse_args()
    state=json.loads((ROOT/'infra/.build/backend-state.json').read_text(encoding='utf-8'))
    cf=boto3.Session(profile_name=state['profile'],region_name=state['region']).client('cloudformation',config=Config(connect_timeout=5,read_timeout=30,retries={'mode':'standard','total_max_attempts':2}))
    if args.action=='status':
        stack=cf.describe_stacks(StackName=state['stack'])['Stacks'][0]
        print(json.dumps({'stack_status':stack['StackStatus']}));return
    if args.action=='plan':
        if STATE.exists():raise ValueError('Plan already exists; inspect it')
        stack=cf.describe_stacks(StackName=state['stack'])['Stacks'][0]
        if stack['StackStatus'] not in {'CREATE_COMPLETE','UPDATE_COMPLETE'}:raise ValueError('Stack not ready')
        template=cf.get_template(StackName=state['stack'],TemplateStage='Original')['TemplateBody']
        if isinstance(template,str):template=json.loads(template)
        statements=[stmt for policy in template['Resources']['WorkerRole']['Properties']['Policies'] for stmt in policy['PolicyDocument']['Statement'] if 'bedrock:InvokeModel' in stmt.get('Action',[])]
        if len(statements)!=1:raise ValueError('Unexpected model permission shape')
        stmt=statements[0]
        if 'bedrock:InvokeModelWithResponseStream' in stmt['Action']:
            print(json.dumps({'already_enabled':True}));return
        # Keep exact existing resources and all unrelated permissions unchanged.
        stmt['Action'].append('bedrock:InvokeModelWithResponseStream')
        name='sonnet-stream-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        result=cf.create_change_set(StackName=state['stack'],ChangeSetName=name,ChangeSetType='UPDATE',TemplateBody=json.dumps(template),Parameters=[{'ParameterKey':p['ParameterKey'],'UsePreviousValue':True} for p in stack.get('Parameters',[])],Capabilities=['CAPABILITY_IAM','CAPABILITY_NAMED_IAM'],Description='Enable ConverseStream on existing Sonnet resources only')
        saved={'stack':state['stack'],'change_set':result['Id']}
        STATE.write_text(json.dumps(saved,indent=2),encoding='utf-8')
        print(json.dumps({'planned':True,'expected_resource':'WorkerRole','added_action':'bedrock:InvokeModelWithResponseStream'}));return
    saved=json.loads(STATE.read_text(encoding='utf-8'))
    value,allowed=review(cf,saved)
    if args.action=='review':
        print(json.dumps({'status':value['Status'],'allowed_single_role_change':allowed,'changes':[{'action':c['ResourceChange']['Action'],'resource':c['ResourceChange']['LogicalResourceId'],'replacement':c['ResourceChange'].get('Replacement')} for c in value.get('Changes',[])]}));return
    if not allowed or value['Status']!='CREATE_COMPLETE':raise ValueError('Unexpected or unfinished change set')
    cf.execute_change_set(StackName=saved['stack'],ChangeSetName=saved['change_set'])
    print(json.dumps({'started':True,'scope':'one existing role; no data or server replacement'}))

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Streaming permission stopped: '+getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__),file=sys.stderr)
        raise SystemExit(1)
