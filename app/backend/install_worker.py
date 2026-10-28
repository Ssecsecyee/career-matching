"""First boot only: initialize loopback MySQL and a non-root service; never print credentials."""
import gzip
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import time

from src.repositories.aws_secrets import read_secret
from src.handlers.bootstrap import sql_statements

BASE=Path('/opt/career')

def main():
    config=json.loads((BASE/'config.json').read_text(encoding='utf-8'))
    os.environ.update({k:str(v) for k,v in config.items()})
    db=read_secret(config['MYSQL_SECRET_ARN'])
    if db['username']!='career_runtime': raise ValueError('Unexpected DB user')
    root_file=BASE/'mysql-root.env'
    if not root_file.exists():
        fd=os.open(root_file,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as stream:
            stream.write('MYSQL_ROOT_PASSWORD='+secrets.token_hex(32)+'\nMYSQL_DATABASE=career_matching\n')
    root_values=dict(line.split('=',1) for line in root_file.read_text().splitlines())
    # The persistent host directory is on encrypted EBS, not the container writable layer.
    (BASE/'mysql').mkdir(exist_ok=True)
    found=subprocess.run(['docker','container','inspect','career-mysql'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if found.returncode:
        subprocess.run(['docker','run','-d','--name','career-mysql','--restart','unless-stopped',
            '--env-file',str(root_file),'-p','127.0.0.1:3308:3306','-v',str(BASE/'mysql')+':/var/lib/mysql',
            'mysql:8.4','--innodb-buffer-pool-size=268435456','--max-connections=20','--performance-schema=OFF'],check=True,stdout=subprocess.DEVNULL)
    else:
        subprocess.run(['docker','start','career-mysql'],check=True,stdout=subprocess.DEVNULL)
    import pymysql
    for _ in range(90):
        try:
            conn=pymysql.connect(host='127.0.0.1',port=3308,user='root',password=root_values['MYSQL_ROOT_PASSWORD'],
                database='career_matching',charset='utf8mb4',autocommit=True)
            break
        except pymysql.MySQLError: time.sleep(2)
    else: raise RuntimeError('MySQL startup failed')
    try:
        with conn.cursor() as cur:
            for path in [BASE/'app/schema.sql',BASE/'app/jobs.data.sql.gz']:
                data=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
                for statement in sql_statements(data.decode('utf-8-sig')): cur.execute(statement)
            cur.execute("CREATE USER IF NOT EXISTS 'career_runtime'@'%%' IDENTIFIED BY %s",(db['password'],))
            cur.execute("ALTER USER 'career_runtime'@'%%' IDENTIFIED BY %s",(db['password'],))
            for table in ("job_postings", "training_offerings"):
                cur.execute("GRANT SELECT ON career_matching."+table+" TO 'career_runtime'@'%'")
            for table in ['chat_sessions','chat_messages','recommendation_evidence','model_invocations','response_cache']:
                cur.execute('GRANT SELECT,INSERT,UPDATE,DELETE ON career_matching.'+table+" TO 'career_runtime'@'%'")
            cur.execute('SELECT COUNT(*) FROM job_postings')
            if cur.fetchone()[0]<int(config['EXPECTED_JOBS']): raise ValueError('Snapshot import incomplete')
    finally: conn.close()
    found=subprocess.run(['id','career'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if found.returncode: subprocess.run(['useradd','--system','--no-create-home','--shell','/sbin/nologin','career'],check=True)
    user=pwd.getpwnam('career')
    os.chown(BASE/'config.json',user.pw_uid,user.pw_gid)
    os.chmod(BASE/'config.json',0o600)
    unit='''[Unit]
Description=Career queue worker
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service
[Service]
User=career
Group=career
WorkingDirectory=/opt/career/app
ExecStart=/opt/career/venv/bin/python worker.py
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
UMask=0077
[Install]
WantedBy=multi-user.target
'''
    Path('/etc/systemd/system/career-worker.service').write_text(unit)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    subprocess.run(['systemctl','enable','--now','career-worker'],check=True)
    print('Career worker installed; credentials were not printed.')

if __name__=='__main__': main()
