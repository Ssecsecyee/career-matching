"""Create an isolated, tool-restricted AgentCore experiment. No production switch."""
import argparse,json,sys,time
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app/backend'))
from src.agentcore.contracts import SYSTEM,tools
STATE=ROOT/'infra/.build/agentcore-experiment.json'
NAME='career_experiment_20261106'
ROLE='career-agentcore-experiment-20261106'
def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['create','status']);a=p.parse_args()
 s=boto3.Session(profile_name='myisb_IsbUsersPS-954935267704',region_name='ap-northeast-2')
 account=s.client('sts').get_caller_identity()['Account']
 if account!='954935267704':raise ValueError('Unexpected account')
 c=s.client('bedrock-agentcore-control')
 if a.action=='create':
  if STATE.exists():raise ValueError('Existing experiment state; use status')
  iam=s.client('iam');prefix=f'arn:aws:bedrock-agentcore:ap-northeast-2:{account}:'
  trust={'Version':'2012-10-17','Statement':[{'Effect':'Allow','Principal':{'Service':'bedrock-agentcore.amazonaws.com'},'Action':'sts:AssumeRole','Condition':{'StringEquals':{'aws:SourceAccount':account},'ArnLike':{'aws:SourceArn':[prefix+'runtime/*',prefix+'harness/'+NAME+'-*']}}}]}
  try:role=iam.get_role(RoleName=ROLE)['Role']
  except iam.exceptions.NoSuchEntityException:role=iam.create_role(RoleName=ROLE,AssumeRolePolicyDocument=json.dumps(trust),Tags=[{'Key':'Project','Value':'career-agentcore-experiment'}])['Role']
  statements=[{'Effect':'Allow','Action':['bedrock:InvokeModel','bedrock:InvokeModelWithResponseStream'],'Resource':[f'arn:aws:bedrock:*:{account}:inference-profile/global.anthropic.claude-sonnet-4-6','arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6']},
  {'Effect':'Allow','Action':['ecr-public:GetAuthorizationToken','sts:GetServiceBearerToken'],'Resource':'*'},
  {'Effect':'Allow','Action':['logs:CreateLogGroup','logs:DescribeLogStreams','logs:CreateLogStream','logs:PutLogEvents'],'Resource':f'arn:aws:logs:ap-northeast-2:{account}:log-group:/aws/bedrock-agentcore/runtimes/*'},
  {'Effect':'Allow','Action':['bedrock-agentcore:CreateEvent','bedrock-agentcore:DeleteEvent','bedrock-agentcore:GetEvent','bedrock-agentcore:ListEvents','bedrock-agentcore:RetrieveMemoryRecords'],'Resource':prefix+'memory/'+NAME+'-*'}]
  iam.put_role_policy(RoleName=ROLE,PolicyName='CareerExperimentOnly',PolicyDocument=json.dumps({'Version':'2012-10-17','Statement':statements}))
  time.sleep(5)
  result=c.create_harness(harnessName=NAME,executionRoleArn=role['Arn'],systemPrompt=[{'text':SYSTEM}],tools=tools(),allowedTools=['@*/'+t['name'] for t in tools()],model={'bedrockModelConfig':{'modelId':'global.anthropic.claude-sonnet-4-6','maxTokens':900,'apiFormat':'converse_stream'}},memory={'managedMemoryConfiguration':{'eventExpiryDuration':3}},truncation={'strategy':'sliding_window','config':{'slidingWindow':{'messagesCount':6}}},maxIterations=3,maxTokens=900,timeoutSeconds=50,tags={'Project':'career-agentcore-experiment','ExperimentBudgetUSD':'5'})['harness']
  STATE.parent.mkdir(parents=True,exist_ok=True);STATE.write_text(json.dumps({'harness':result,'role':role['Arn'],'approved_budget_usd':5},default=str,indent=2),encoding='utf-8')
  print(json.dumps({'status':'created','harness_id':result.get('harnessId')}))
 else:
  value=json.loads(STATE.read_text(encoding='utf-8'));h=value['harness'];identity=h.get('harnessId') or h['harnessArn'].split('/')[-1]
  result=c.get_harness(harnessId=identity)['harness'];value['harness']=result;STATE.write_text(json.dumps(value,default=str,indent=2),encoding='utf-8')
  print(json.dumps({k:result.get(k) for k in ('harnessId','harnessArn','status','statusReason')}))
if __name__=='__main__':
 try:main()
 except ClientError as e:print(json.dumps({'error':e.response['Error']['Code'],'message':e.response['Error']['Message'][:500]}));raise SystemExit(1)
