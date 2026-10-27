"""Interactive local MySQL + Bedrock demonstration. Requires explicit --live."""
import argparse
import json
import os
import secrets
import time
from uuid import uuid4

from src.config import load_local_settings
from src.handlers.dialogue import lambda_handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--skills", help="Comma-separated exact skill names; bypass model search planning")
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live to explicitly allow billable Bedrock requests")
    load_local_settings()
    if os.getenv("ENABLE_LIVE_BEDROCK") != "true":
        parser.error("Live Bedrock calls are disabled")
    if not os.getenv("CHAT_API_TOKEN"):
        parser.error("Run prepare_local_mysql.py and start compose.dev.yaml first")
    client_token = secrets.token_hex(32)
    session_id = None

    def send(payload):
        nonlocal session_id
        for attempt in range(3):
            current = dict(payload, request_id=str(uuid4()))
            if session_id:
                current["session_id"] = session_id
            result = lambda_handler({"headers": {"Authorization": "Bearer " + os.environ["CHAT_API_TOKEN"],
                                                 "X-Client-Token": client_token},
                                     "body": json.dumps(current)}, None)
            body = json.loads(result["body"])
            if body.get("session_id"):
                session_id = body["session_id"]
            if result["statusCode"] == 200:
                return body
            if body.get("retryable") and attempt < 2:
                print(body.get("message", "일시 오류"), body.get("error_code", ""))
                if input("실제 호출을 다시 시도할까요? y 입력 시 10초 후 재시도: ").strip().lower() == "y":
                    time.sleep(10)
                    continue
            raise RuntimeError(json.dumps(body, ensure_ascii=False))

    print("저장된 스냅샷 기반 테스트입니다. 현재 모집 중임을 보장하지 않습니다.")
    print("Bedrock 실제 호출 비용이 발생합니다. 종료: Ctrl+C")
    if args.skills:
        skills = [skill.strip() for skill in args.skills.split(",") if skill.strip()]
        result = send({"action": "search", "search_plan": {"skills": skills, "limit": 3}})
    else:
        message = input("찾을 공고 조건: ").strip()
        result = send({"action": "search", "message": message})
    jobs = result.get("candidate_jobs", [])
    if not jobs:
        print("검색 결과 없음. 직무·기술·지역 조건을 줄여 다시 실행하세요.")
        return
    for index, job in enumerate(jobs, 1):
        print(f"{index}. {job['company_name']} / {job['title']} / 상태: {job['recruitment_status']}")
    selection = int(input("확인할 공고 번호: "))
    if not 1 <= selection <= len(jobs):
        raise ValueError("Invalid selection")
    result = send({"action": "select", "source_id": jobs[selection - 1]["source_id"]})
    while result["stage"] in {"checking_required", "checking_preferred"}:
        print("\n구분:", result["requirement_type"])
        print("원문:\n" + result["quote"])
        print("질문:", result["question"])
        answer = input("1 충족 / 2 미충족 / 3 모름: ").strip()
        assessment = {"1": "met", "2": "unmet", "3": "unknown"}.get(answer)
        if assessment is None:
            print("1, 2, 3 중 선택하세요.")
            continue
        detail = input("보충 설명(없으면 Enter): ").strip()
        result = send({"action": "answer", "question_id": result["question_id"],
                       "assessment": assessment, "detail": detail})
        print(result.get("message", ""))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("대화·근거·호출 기록은 MySQL에 저장했습니다. 교육 추천은 아직 연결하지 않았습니다.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, KeyboardInterrupt) as error:
        print("종료:", error)

