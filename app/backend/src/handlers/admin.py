import json
import os
from src.handlers.dialogue import response
from src.services.admin_auth import authenticate
from src.services.admin import execute,serial,validate_admin
from src.services.dialogue import FlowError
from src.repositories.mysql_connection import connect_mysql


def handle_admin(event, *, factory=None):
    auth=authenticate(event.get('headers',{}),os.getenv('CHAT_API_TOKEN',''),os.getenv('ADMIN_API_TOKEN',''))
    if not auth:return response(401,{'status':'unauthorized'})
    if auth[2]!='admin':return response(403,{'status':'admin_required'})
    try:
        payload=validate_admin(json.loads(event.get('body','')))
        def connection():
            user,password=os.getenv('ADMIN_MYSQL_USER'),os.getenv('ADMIN_MYSQL_PASSWORD')
            if not user or not password:raise RuntimeError('admin_database_not_configured')
            return connect_mysql(credentials=(user,password))
        value=execute(factory or connection,payload,auth[0])
        return {'statusCode':200,'headers':{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store'},'body':json.dumps(value,ensure_ascii=False,default=serial)}
    except FlowError as exc:return response(exc.status,{'status':exc.code})
    except (ValueError,TypeError,KeyError):return response(400,{'status':'invalid_admin_request'})
    except Exception as exc:return response(503,{'status':'admin_dependency_failed','error_type':type(exc).__name__})
