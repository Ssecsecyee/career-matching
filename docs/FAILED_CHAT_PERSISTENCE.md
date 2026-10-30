# 실패한 대화 요청 저장

2026-10-29 로컬 코드 보완 후 2026-10-30 검색 연결 배포에 포함해 AWS 작업자에 적용했다. 백엔드 173개 중 환경 의존 7개 제외 통과. 운영 502 전체 원인이 해결됐다는 뜻은 아니다.

## 기존 원인

기존 MySQLChatStore.finish()는 모델과 대화 처리 전체가 성공한 뒤 사용자/assistant 메시지를 함께 저장했다. 중간 LLM 또는 검색 오류 때 abort()는 세션 lease만 해제해 chat_messages에 사용자 입력이 남지 않았다. model_invocations에는 호출 시작/실패 이력이 별도 트랜잭션으로 남을 수 있었다. 브라우저의 502만으로 Bedrock/파싱/DB/프록시 원인을 확정할 수 없다.

## 변경

- 인증·입력·세션 소유권·lease·예산 검증을 통과한 요청의 사용자 입력을 begin()에서 저장/커밋한다. 그 후 모델을 호출한다.
- chat_messages의 user 행 structured_content._delivery에 received/failed/succeeded와 fingerprint를 기록한다. 실패 시 검증된 error_code와 error_type을 기록하고 원시 예외 본문·키·비밀번호를 넣지 않는다.
- 실패한 요청에 대한 assistant 답변은 생성하지 않는다. 성공할 때만 assistant 메시지를 추가하고 성공 응답 캐시를 저장한다.
- 같은 request_id와 같은 입력은 실패 후 재시도할 수 있고 사용자 행을 중복 생성하지 않는다. 동일 ID에 다른 입력은 409로 거부한다. 완료 후 캐시 재조회는 기존 동작을 유지한다.
- 같은 요청/목적을 다시 모델 호출할 때 attempt_no를 증가시켜 기존 실패 호출 기록을 덮지 않는다. 모델 예산은 실제 시도마다 소모한다.
- 실패·도중 중단 시 대화의 판단/추천 상태를 성공한 것처럼 갱신하지 않는다. 수신만 저장된 입력은 프로세스 강제 종료 시 received로 남을 수 있다. lease 만료 전 중복 요청은 busy다.

DB 구조 변경은 없다. 실패 내용을 볼 때 chat_messages의 structured_content._delivery 및 동일 session_id/request_id의 model_invocations를 함께 확인한다.

```sql
SELECT session_id, idempotency_key AS request_id, role,
       JSON_EXTRACT(structured_content, '$._delivery') AS delivery,
       created_at
FROM chat_messages
WHERE role = 'user'
ORDER BY message_id DESC
LIMIT 30;
```

## 검증

백엔드 166개 테스트 중 환경 의존 7개 제외 통과. 추가로 별도 로컬 MySQL 시험 DB에서 수신 선저장→모델 실패→오류 기록→동일 요청 재시도→성공→캐시 재전송→다른 입력 거부, 사용자/assistant 각각 한 행과 호출 attempt 1 failed/2 succeeded를 확인했다. 모델·AWS 호출 0, 기존 DB 데이터 변경 0. 재현 도구는 app/backend/experiments/verify_failed_message_store.py다.

## 한계와 다음 진단

DB 연결 실패로 begin() 자체가 실행되지 않으면 DB에 기록할 수 없다. API Gateway/Lambda/큐 접수 이전 오류나 worker 강제 종료, 모델 invocation 결과 기록 시 DB 장애도 정상적인 실패 처리와 구분한다. 부분 스트리밍을 완성 답변으로 저장하지 않는다. 기존에 유실된 입력을 과거 모델 호출에서 복원했다고 주장하지 않는다.

운영 502의 원인을 찾으려면 실패 응답 JSON의 request_id/error_code와 model_invocations 및 작업 처리 기록을 대조한다. 이 변경은 메시지 누락의 확인된 저장 순서를 수정한 것이며 모든 502의 원인을 해결한 결과는 아니다.
