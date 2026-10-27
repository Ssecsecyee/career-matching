"""Read only configured AWS secrets; local .env loading remains unchanged."""
import json
import os
import time
from functools import lru_cache
from threading import Lock

_cache = {}
_lock = Lock()

@lru_cache(maxsize=1)
def secrets_client():
    import boto3
    from botocore.config import Config
    return boto3.Session(region_name=os.environ['AWS_REGION']).client('secretsmanager',
        config=Config(connect_timeout=2, read_timeout=3, retries={'mode':'standard','total_max_attempts':1}))

def read_secret(arn):
    with _lock:
        item = _cache.get(arn)
        if item and item[0] > time.monotonic():
            return dict(item[1])
        value = json.loads(secrets_client().get_secret_value(SecretId=arn)['SecretString'])
        if not isinstance(value, dict):
            raise ValueError('Secret must be a JSON object')
        _cache[arn] = (time.monotonic()+60, value)
        return dict(value)

def database_credentials():
    if os.getenv('MYSQL_SECRET_ARN'):
        value = read_secret(os.environ['MYSQL_SECRET_ARN'])
        return value['username'], value['password']
    return os.getenv('MYSQL_USER'), os.getenv('MYSQL_PASSWORD')

def configure_chat():
    value = read_secret(os.environ['CHAT_SECRET_ARN'])
    token = value.get('token')
    if not isinstance(token,str) or len(token)<32:
        raise ValueError('Invalid chat secret')
    os.environ['CHAT_API_TOKEN'] = token
