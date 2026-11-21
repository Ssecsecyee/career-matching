"""Export via encrypted SSM port forwarding, directly to a local private archive.

No S3 staging, no credentials in the archive, no AWS resources created.
The temporary source HTTP endpoint is loopback-only, token-protected and bounded.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import time
import urllib.request
import urllib.error

from portable_data import sha


def remote_script(source, folder, token, port, resume=False):
    # These strings contain code/paths only. Never print the resulting script/token.
    pre = '''import os,sys,json,base64,gzip,subprocess,hashlib,tarfile
import time as _clock
from datetime import datetime,timezone
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
os.umask(0o077)
sys.path.insert(0,'/opt/career/app')
from worker import configure
configure()
root_values=dict(line.split('=',1) for line in Path('/opt/career/mysql-root.env').read_text().splitlines() if '=' in line)
os.environ['MYSQL_USER']='root'
os.environ['MYSQL_PASSWORD']=root_values['MYSQL_ROOT_PASSWORD']
'''
    pre += 'ns={"__name__":"portable_data"}\nexec(compile(base64.b64decode(' + repr(base64.b64encode(source.encode()).decode()) + "),'<portable_data>','exec'),ns)\nsha=ns['sha'];write_json=ns['write_json']\n"
    if resume:
        pre += "ns['verify'](" + repr(folder) + ")\n"
    else:
        pre += "from types import SimpleNamespace\nns['export'](SimpleNamespace(directory=" + repr(folder) + ",live_worker=False,elasticsearch=''))\n"
    post = '''root=Path(FOLDER)
dump=root/'mysql'/'full.mysql.sql.gz'
with dump.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb') as out:
 p=subprocess.Popen(['docker','exec','career-mysql','sh','-c','MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump --user=root --single-transaction --routines --events --triggers --hex-blob --skip-add-drop-table --set-gtid-purged=OFF --no-tablespaces career_matching'],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
 import shutil
 shutil.copyfileobj(p.stdout,out)
 if p.wait()!=0:raise RuntimeError('Native SQL dump failed')
manifest=json.loads((root/'manifest.json').read_text())
manifest['files']['mysql/full.mysql.sql.gz']={'sha256':sha(dump),'bytes':dump.stat().st_size}
manifest['native_sql_dump_utc']=datetime.now(timezone.utc).isoformat()
manifest['native_sql_consistency']='Separate InnoDB snapshot from JSONL. Final cutover requires a last sync.'
write_json(root/'manifest.json',manifest)
archive=root.with_suffix('.tar.gz')
with tarfile.open(archive,'w:gz') as t:t.add(root,arcname=root.name)
os.chmod(archive,0o600)
meta={'sha256':sha(archive),'bytes':archive.stat().st_size,'tables':[{'name':x['name'],'rows':x['rows']} for x in manifest['tables']],'indices':manifest['indices'],'exported_utc':manifest['created_utc']}
token=TOKEN
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  if self.headers.get('X-Export-Token')!=token:self.send_error(403);return
  if self.path=='/meta':
   data=json.dumps(meta).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
  elif self.path=='/archive':
   self.send_response(200);self.send_header('Content-Length',str(archive.stat().st_size));self.end_headers()
   with archive.open('rb') as f:shutil.copyfileobj(f,self.wfile)
   self.server.complete=True
  else:self.send_error(404)
server=HTTPServer(('127.0.0.1',PORT),Handler);server.timeout=10;server.complete=False
deadline=_clock.monotonic()+1200
while not server.complete and _clock.monotonic()<deadline:server.handle_request()
server.server_close()
print(json.dumps({'status':'transfer_complete' if server.complete else 'transfer_expired','sha256':meta['sha256'],'bytes':meta['bytes'],'tables':meta['tables']}))
'''
    return pre + post.replace('FOLDER', repr(folder)).replace('TOKEN', repr(token)).replace('PORT', str(port))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--profile',required=True);p.add_argument('--region',default='ap-northeast-2')
    p.add_argument('--expected-source-account',required=True);p.add_argument('--instance',required=True)
    p.add_argument('--output',required=True);p.add_argument('--confirm-full-export',action='store_true')
    p.add_argument('--resume-export-folder')
    a=p.parse_args()
    if not a.confirm_full_export:raise ValueError('Full DB contains conversation data; explicit export flag required')
    import boto3
    from botocore.config import Config
    cfg=Config(connect_timeout=10,read_timeout=120,retries={'mode':'standard','total_max_attempts':3})
    sess=boto3.Session(profile_name=a.profile,region_name=a.region)
    if sess.client('sts',config=cfg).get_caller_identity()['Account']!=a.expected_source_account:
        raise ValueError('Source AWS account mismatch')
    out=Path(a.output).resolve();out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():raise ValueError('Output exists; never overwrite an earlier backup')
    from datetime import datetime,timezone
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    folder='/opt/career/migration_exports/'+stamp
    if a.resume_export_folder:
        import re
        if not re.fullmatch(r'/opt/career/migration_exports/\d{8}T\d{6}Z', a.resume_export_folder):
            raise ValueError('Resume only an existing timestamped migration export')
        folder=a.resume_export_folder
    token=secrets.token_urlsafe(32);remote_port=19731
    script=remote_script(Path(__file__).with_name('portable_data.py').read_text(encoding='utf-8'),folder,token,remote_port,bool(a.resume_export_folder))
    cmd="/opt/career/venv/bin/python -c \"import base64;exec(base64.b64decode('"+base64.b64encode(script.encode()).decode()+"'))\""
    ssm=sess.client('ssm',config=cfg)
    command=ssm.send_command(InstanceIds=[a.instance],DocumentName='AWS-RunShellScript',Parameters={'commands':[cmd],'executionTimeout':['3600']},TimeoutSeconds=3600,Comment='Requested full MySQL JSONL and SQL export to local PC over SSM; no S3 upload')['Command']['CommandId']
    print(json.dumps({'status':'export_submitted','command_id':command}),flush=True)
    with socket.socket() as s:s.bind(('127.0.0.1',0));local_port=s.getsockname()[1]
    parameters=json.dumps({'portNumber':[str(remote_port)],'localPortNumber':[str(local_port)]})
    aws=['aws','ssm','start-session','--profile',a.profile,'--region',a.region,'--target',a.instance,'--document-name','AWS-StartPortForwardingSession','--parameters',parameters]
    log=out.with_suffix(out.suffix+'.tunnel.log')
    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    def get(path):
        return urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:'+str(local_port)+path,headers={'X-Export-Token':token}),timeout=180)
    process=None
    try:
        with log.open('wb') as stream:
            process=subprocess.Popen(aws,stdout=stream,stderr=stream,creationflags=creationflags)
            meta=None;deadline=time.monotonic()+1800;last=0
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('SSM tunnel stopped; inspect private tunnel log')
                try:
                    with get('/meta') as r:meta=json.load(r)
                    break
                except (OSError,urllib.error.URLError):
                    if time.monotonic()-last>30:
                        status=ssm.get_command_invocation(CommandId=command,InstanceId=a.instance)
                        if status['Status'] in ('Failed','TimedOut','Cancelled'):
                            raise RuntimeError('Export failed: '+status.get('StandardErrorContent','')[-1000:])
                        print(json.dumps({'status':'waiting_for_export'}),flush=True);last=time.monotonic()
                    time.sleep(2)
            if meta is None:raise TimeoutError('Export did not become ready')
            partial=out.with_suffix(out.suffix+'.partial')
            import shutil
            with get('/archive') as r,partial.open('xb') as f:shutil.copyfileobj(r,f)
            if partial.stat().st_size!=meta['bytes'] or sha(partial)!=meta['sha256']:
                raise RuntimeError('Transferred archive checksum mismatch')
            partial.rename(out);os.chmod(out,0o600)
            out.with_suffix(out.suffix+'.receipt.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'status':'downloaded_verified','file':str(out),'sha256':meta['sha256'],'bytes':meta['bytes'],'tables':meta['tables']}),flush=True)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill()
        # The loopback-only server self-expires. Source export files remain private.


if __name__=='__main__':main()
