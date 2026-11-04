"""Explicit daily runner; scheduling itself is not installed by this program."""
import argparse
from datetime import datetime,timedelta
from pathlib import Path
import subprocess
import sys
from work24_collect import KST


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--env-path',type=Path,required=True);ap.add_argument('--catalog',type=Path,required=True);ap.add_argument('--output-root',type=Path,required=True);ap.add_argument('--max-details',type=int,default=20);ap.add_argument('--live',action='store_true');ap.add_argument('--read-db-inventory',action='store_true');args=ap.parse_args()
    if not 1<=args.max_details<=1000:raise ValueError('invalid_detail_limit')
    today=datetime.now(KST).date();run=datetime.now(KST).strftime('daily_%Y%m%dT%H%M%S');output=args.output_root/run
    commands=[['work24_collect.py','--env-path',str(args.env_path),'--catalog',str(args.catalog),'--output',str(output),'--run-id',run,'--start',str(today-timedelta(days=7)),'--end',str(today+timedelta(days=90))],['work24_reconcile.py','--catalog',str(args.catalog),'--output',str(output),'--run-id',run],['work24_details.py','--catalog',str(args.catalog),'--env-path',str(args.env_path),'--output',str(output/'details'),'--max-items',str(args.max_details),'--live']]
    if args.read_db_inventory:
        commands.insert(2,['inventory_work24.py','--output',str(output/'db_inventory.json')])
        commands.insert(3,['work24_export.py','--catalog',str(args.catalog),'--run-id',run,'--db-inventory',str(output/'db_inventory.json'),'--output',str(output/'normalized')])
    if not args.live:
        print('Plan: rolling list inventory -> offline count reconciliation -> bounded pending detail batch. No API/DB calls.');return 0
    root=Path(__file__).resolve().parent
    for command in commands:
        result=subprocess.run([sys.executable,str(root/command[0]),*command[1:]],cwd=root,check=False)
        if result.returncode:return result.returncode
    return 0
if __name__=='__main__':raise SystemExit(main())
