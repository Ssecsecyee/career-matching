"""Server-side roles. A browser cannot choose its privileges."""
import hashlib
import hmac
import re


def authenticate(headers, user_token, admin_token=''):
    headers={k.lower():v for k,v in headers.items()}
    supplied=headers.get('authorization','')
    client=headers.get('x-client-token','')
    if not isinstance(supplied,str) or not isinstance(client,str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,128}',client):
        return None
    # Equal secrets are a configuration error, never an elevation of normal users.
    if admin_token and (len(admin_token)<32 or hmac.compare_digest(admin_token,user_token)):
        return None
    for role,token in [('admin',admin_token),('user',user_token)]:
        if len(token)>=32 and hmac.compare_digest(supplied,'Bearer '+token):
            return hmac.new(token.encode(),client.encode(),hashlib.sha256).hexdigest(),client,role
    return None
