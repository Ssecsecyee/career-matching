"""Single host worker. AWS role credentials; no inbound listener or user content logs."""
import json
import os
from pathlib import Path
import time

from src.handlers.dialogue import handle_request
from src.services.progress import ProgressPublisher
from src.handlers.queued import JobStore, aws_client
from src.repositories.aws_secrets import read_secret
from src.repositories.mysql_connection import connect_mysql

CONFIG=Path('/opt/career/config.json')

def configure(path=CONFIG):
    config=json.loads(Path(path).read_text(encoding='utf-8'))
    for key,value in config.items(): os.environ[key]=str(value)
    auth=read_secret(os.environ['CHAT_SECRET_ARN'])
    database=read_secret(os.environ['MYSQL_SECRET_ARN'])
    os.environ.update(CHAT_API_TOKEN=auth['token'],MYSQL_USER=database['username'],MYSQL_PASSWORD=database['password'],
        MYSQL_HOST='127.0.0.1',MYSQL_PORT='3308',MYSQL_DATABASE='career_matching',ENABLE_LIVE_BEDROCK='true',
        CHAT_RUNTIME_ENABLED='true',CHAT_INCLUDE_UNVERIFIED='true',CHAT_RETENTION_HOURS='24',
        MODEL_ID='global.anthropic.claude-sonnet-4-6',BEDROCK_REGION=os.environ['AWS_REGION'])
    # A host role is used; local workstation profile must never be copied here.
    os.environ.pop('AWS_PROFILE',None)

def process(message, store, *, handler=handle_request):
    value=json.loads(message['Body'])
    if set(value)!={'job_id'} or not isinstance(value['job_id'],str) or len(value['job_id'])!=64:
        raise ValueError('Invalid work item')
    row=store.get(value['job_id'])
    if not row or row['expires_at']<=int(time.time()) or row['state']=='done': return
    # One worker is deployed. SQS can redeliver; MySQL request leases and replay cache remain authoritative.
    payload=json.loads(row['payload_json'])
    progress={'on_progress':ProgressPublisher(store,value['job_id'])} if hasattr(store,'progress') and handler is handle_request else {}
    result=handler({'headers':{'Authorization':'Bearer '+os.environ['CHAT_API_TOKEN'],
                              'X-Client-Token':row['client_token']},'body':json.dumps(payload,ensure_ascii=False)},**progress)
    if result['statusCode']==409 and json.loads(result['body']).get('status')=='session_busy_retry_later':
        raise RuntimeError('Existing request is still leased')
    store.complete(value['job_id'],result)

def main():
    configure()
    store=JobStore()
    queue=aws_client('sqs')
    # Long polling exceeds the short HTTP client timeout used by the API.
    import boto3
    from botocore.config import Config
    queue=boto3.Session(region_name=os.environ['AWS_REGION']).client('sqs',config=Config(connect_timeout=3,read_timeout=25,retries={'mode':'standard','total_max_attempts':2}))
    while True:
        try:
            messages=queue.receive_message(QueueUrl=os.environ['WORK_QUEUE_URL'],MaxNumberOfMessages=1,WaitTimeSeconds=20,VisibilityTimeout=180).get('Messages',[])
            for message in messages:
                process(message,store)
                queue.delete_message(QueueUrl=os.environ['WORK_QUEUE_URL'],ReceiptHandle=message['ReceiptHandle'])
        except Exception as exc:
            print('Worker retry: '+type(exc).__name__,flush=True)
            time.sleep(3)

if __name__=='__main__': main()
