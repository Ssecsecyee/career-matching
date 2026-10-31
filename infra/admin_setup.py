"""Prepare admin DB/audit and distinct token using existing resources. No token output."""
import argparse,base64,hashlib,io,json,secrets
from datetime import datetime,timezone
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
from deploy import session,client,outputs
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'infra/.build/admin-setup.json'

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','result']);args=p.parse_args()
 state=json.loads((ROOT/'infra/.build/backend-state.json').read_text())
 from types import SimpleNamespace
 sess=session(SimpleNamespace(profile=state['profile'],region=state['region']));ssm=client(sess,'ssm')
 if args.action=='result':
  value=json.loads(STATE.read_text());r=ssm.get_command_invocation(CommandId=value['command_id'],InstanceId=value['instance_id'])
  print(json.dumps({'status':r['Status'],'output':r.get('StandardOutputContent',''),'stderr_present':bool(r.get('StandardErrorContent'))}))
  if r['Status']=='Success':
   sm=client(sess,'secretsmanager');secret=json.loads(sm.get_secret_value(SecretId=value['auth_secret_arn'])['SecretString'])
   if 'admin_token' not in secret:
    secret['admin_token']=secrets.token_urlsafe(48);sm.put_secret_value(SecretId=value['auth_secret_arn'],SecretString=json.dumps(secret))
   if len(secret.get('admin_token',''))<32 or secret['admin_token']==secret['token']:raise ValueError('Distinct admin token required')
   value['prepared']=True;STATE.write_text(json.dumps(value,indent=2))
   print(json.dumps({'admin_token_ready':True,'location':'Existing AuthSecret / admin_token. Value not displayed.'}))
  return
 if STATE.exists():raise ValueError('Existing setup: inspect result before resubmitting')
 stack=client(sess,'cloudformation').describe_stacks(StackName=state['stack'])['Stacks'][0]
 out={x['OutputKey']:x['OutputValue'] for x in stack['Outputs']}
 buf=io.BytesIO()
 with ZipFile(buf,'w',ZIP_DEFLATED) as z:
  for source,name in [('infra/remote_setup_admin.py','remote_setup_admin.py'),('app/backend/database/schema.sql','schema.sql'),('app/backend/database/admin_migration.sql','admin_migration.sql'),('app/backend/src/services/admin.py','admin_service.py'),('app/backend/src/repositories/mysql_chat.py','mysql_chat.py'),('app/ingestion/search_index/sync_outbox.py','sync_outbox.py')]:z.write(ROOT/source,name)
 data=buf.getvalue();stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');key='admin-setup/'+stamp+'/package.zip'
 s3=client(sess,'s3');s3.put_object(Bucket=state['bucket'],Key=key,Body=data,ServerSideEncryption='AES256')
 url=s3.generate_presigned_url('get_object',Params={'Bucket':state['bucket'],'Key':key},ExpiresIn=900)
 script='''import io,os,pathlib,hashlib,subprocess,urllib.request,zipfile
os.umask(0o077);folder=pathlib.Path('/opt/career/admin-setup')/STAMP;folder.mkdir(parents=True,exist_ok=False)
data=urllib.request.urlopen(URL,timeout=30).read(5*1024*1024+1)
assert hashlib.sha256(data).hexdigest()==HASH
with zipfile.ZipFile(io.BytesIO(data)) as z:
 for m in z.infolist():
  p=pathlib.PurePosixPath(m.filename);assert not p.is_absolute() and '..' not in p.parts and m.file_size<1024*1024
 z.extractall(folder)
raise SystemExit(subprocess.run(['/opt/career/venv/bin/python',str(folder/'remote_setup_admin.py')],cwd=folder).returncode)
'''.replace('STAMP',repr(stamp)).replace('URL',repr(url)).replace('HASH',repr(hashlib.sha256(data).hexdigest()))
 encoded=base64.b64encode(script.encode()).decode()
 r=ssm.send_command(InstanceIds=[out['WorkerInstanceId']],DocumentName='AWS-RunShellScript',Parameters={'commands':['/opt/career/venv/bin/python -c "import base64;exec(base64.b64decode(\''+encoded+'\'))"']},TimeoutSeconds=300,Comment='Admin setup: isolated validation, DB backup, audit table and minimal DB grants')
 STATE.write_text(json.dumps({'command_id':r['Command']['CommandId'],'instance_id':out['WorkerInstanceId'],'auth_secret_arn':out['AuthSecretArn'],'package_sha256':hashlib.sha256(data).hexdigest(),'stamp':stamp},indent=2))
 print(json.dumps({'submitted':True,'model_calls':0,'new_aws_resources':0}))

if __name__=='__main__':
 try:main()
 except Exception as exc:
  print(json.dumps({'status':'failed','error_code':getattr(exc,'response',{}).get('Error',{}).get('Code',type(exc).__name__)}));raise SystemExit(1)
