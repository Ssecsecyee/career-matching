"""Server-side aggregate inspection. Run only using approved SSM commands."""
import json
import sys
from worker import configure
from src.handlers.cloud import inspect_handler

def main():
    if sys.argv[1:]!=['inspect']:raise ValueError('Only aggregate inspection is supported')
    configure()
    print(json.dumps(inspect_handler({'action':'summary'},None),ensure_ascii=False))

if __name__=='__main__':main()
