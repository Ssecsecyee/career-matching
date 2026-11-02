"""Offline approval and publication of immutable extraction drafts; no model calls."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'app/backend'))
from src.config import load_local_settings
from src.repositories.condition_drafts import ConditionDraftStore

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['inspect','verify','publish'])
    p.add_argument('--draft-id',type=int,required=True);p.add_argument('--approval',type=Path)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.draft_id<1 or a.output.exists():p.error('Use a positive ID and a new output path')
    load_local_settings()
    from incremental_jumpit import connect
    store=ConditionDraftStore(connect)
    if a.action=='verify':
        if not a.approval:p.error('A source-reviewed approval manifest is required')
        result=store.verify(a.draft_id,json.loads(a.approval.read_text(encoding='utf-8')))
    elif a.action=='publish':result=store.publish(a.draft_id)
    else:result=store.inspect(a.draft_id)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({'status':'completed','action':a.action,'draft_id':a.draft_id,'model_calls':0}))
    return 0
if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'status':'failed','error_type':type(exc).__name__}));raise SystemExit(1)
