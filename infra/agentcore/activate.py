"""Activate only the admin experiment, preserving existing config and DB."""
import json,base64
from pathlib import Path
import boto3
ROOT=Path(__file__).resolve().parents[2]
STATE=ROOT/'infra/.build/agentcore-experiment.json'
s=boto3.Session(profile_name='myisb_IsbUsersPS-954935267704',region_name='ap-northeast-2')
v=json.loads(STATE.read_text(encoding='utf-8'));arn=v['harness']['arn']
cf=s.client('cloudformation');out={x['OutputKey']:x['OutputValue'] for x in cf.describe_stacks(StackName='career-backend-test-v2')['Stacks'][0]['Outputs']}
instance=out['WorkerInstanceId'];ec2=s.client('ec2');profile=ec2.describe_instances(InstanceIds=[instance])['Reservations'][0]['Instances'][0]['IamInstanceProfile']['Arn'].split('/')[-1]
iam=s.client('iam');role=iam.get_instance_profile(InstanceProfileName=profile)['InstanceProfile']['Roles'][0]['RoleName']
iam.put_role_policy(RoleName=role,PolicyName='CareerAgentCoreExperimentInvoke',PolicyDocument=json.dumps({'Version':'2012-10-17','Statement':[{'Effect':'Allow','Action':['bedrock-agentcore:InvokeHarness','bedrock-agentcore:InvokeAgentRuntime'],'Resource':arn}]}))
script="""import json,pathlib,subprocess,boto3,os,pwd
p=pathlib.Path('/opt/career/config.json')
v=json.loads(p.read_text());v.update(ENABLE_AGENTCORE_EXPERIMENT='true',AGENTCORE_HARNESS_ARN=__HARNESS_ARN__,AGENTCORE_BUDGET_PATH='/opt/career/agentcore-experiment/budget.json')
b=p.with_name('config-before-agentcore.json')
if not b.exists():b.write_bytes(p.read_bytes());b.chmod(0o600)
p.write_text(json.dumps(v));p.chmod(0o600)
owner=pwd.getpwnam('career');folder=p.parent/'agentcore-experiment';folder.mkdir(exist_ok=True);folder.chmod(0o700);os.chown(folder,owner.pw_uid,owner.pw_gid)
if 'InvokeHarness' not in boto3.Session(region_name='ap-northeast-2').client('bedrock-agentcore').meta.service_model.operation_names:
 subprocess.run(['/opt/career/venv/bin/pip','install','boto3==1.43.119'],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['systemctl','restart','career-worker'],check=True)
print(json.dumps({'experiment_enabled':True,'admin_only':True,'turn_allowance':6}))
""".replace('__HARNESS_ARN__',repr(arn))
encoded=base64.b64encode(script.encode()).decode()
command='/opt/career/venv/bin/python -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"'
r=s.client('ssm').send_command(InstanceIds=[instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[command]},TimeoutSeconds=90)
v.update(activation_command=r['Command']['CommandId'],instance_id=instance);STATE.write_text(json.dumps(v,indent=2,default=str),encoding='utf-8')
print('Admin-only experiment activation submitted.')
