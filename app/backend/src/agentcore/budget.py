"""Persistent fail-closed experiment request allowance, not AWS billing measurement."""
import json,os
from pathlib import Path
from src.services.dialogue import FlowError

def reserve(path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    lock=path.with_suffix('.lock')
    try:fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    except FileExistsError:raise FlowError('agentcore_experiment_busy',409)
    try:
        os.close(fd)
        value=json.loads(path.read_text()) if path.exists() else {'reserved_turns':0}
        if value['reserved_turns']>=6:raise FlowError('agentcore_experiment_budget_reached',429)
        value['reserved_turns']+=1
        temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value));os.replace(temp,path)
    finally:lock.unlink(missing_ok=True)
