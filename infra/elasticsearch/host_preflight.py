"""Read-only host capacity gate for the agreed same-host Elasticsearch pilot."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

def inspect():
    if sys.platform != 'linux':
        return {'ready':False,'reason':'run_on_linux_host'}
    memory={}
    for line in Path('/proc/meminfo').read_text().splitlines():
        key,value=line.split(':',1)
        memory[key]=int(value.split()[0])
    total=memory['MemTotal']//1024
    available=memory['MemAvailable']//1024
    disk=shutil.disk_usage('/opt/career').free//(1024*1024)
    # Conservative pilot deployment gate, not a measured load guarantee.
    reasons=[]
    if total<3500:reasons.append('host_memory_below_4gb_class')
    if available<2300:reasons.append('insufficient_memory_headroom_for_2gb_container')
    if disk<8192:reasons.append('less_than_8gb_free_disk')
    return {'ready':not reasons,'reasons':reasons,'total_memory_mib':total,
            'available_memory_mib':available,'free_disk_mib':disk,
            'aws_changes':0,'note':'Deployment guard only; load test remains deferred.'}

if __name__=='__main__':
    result=inspect()
    print(json.dumps(result))
    raise SystemExit(0 if result['ready'] else 2)
