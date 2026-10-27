"""No server, credentials or model calls required for the default smoke run."""
import json
from src.handlers.chat import lambda_handler

if __name__ == "__main__":
    event = {"rawPath": "/chat", "requestContext": {"http": {"method": "POST"}},
             "body": json.dumps({"search_plan": {"skills": ["Python"], "limit": 3}})}
    print(json.dumps(lambda_handler(event, None), ensure_ascii=False, indent=2))
