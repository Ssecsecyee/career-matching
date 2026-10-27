# API 설계

수정일: 2026-10-28. 아래 /chat은 목표 계약이다. 현재 로컬 API의 /jobs/search, /categories, /jobs/{id}와 구분한다.

## 사용자 API

POST /chat

요청: message, session_id(첫 요청 생략 가능), profile_patch, selected_job_ids, answers[{question_id, requirement_id, answer}], idempotency_key.

응답: request_id, session_id, stage, status, message, candidate_jobs, selected_job_ids, questions, requirement_checks, skill_gaps, learning_opportunities, evidence_ids, data_version, last_verified_at.

필수 입력과 선택 입력은 상태별 스키마로 정의한다. 사용자·세션 소유권을 검사한다. 클라이언트가 보낸 임의 requirement_id를 신뢰하지 않는다.

## 상태

- need_profile: 검색 조건 추가 확인.
- choose_job: 입력 예산상 상세를 모두 분석하기 어려워 선택 요청.
- checking_required: 자격요건 미확인 항목 질문.
- checking_preferred: 필수 조건 충족 확인 후 우대사항 질문.
- gap_guidance: 미충족 조건과 대안 안내.
- completed: 공고 적합성 설명과 교육 연결.
- no_results / search_error / model_error / budget_exceeded: 실패 원인 구분.

## 처리

인증 → 세션 조회 → Bedrock 검색 계획 또는 답변 구조화 → 검증 → DB/검색엔진 조회 → 근거·버전 확인 → 입력 예산 계산 → 질문 또는 결과 생성 → 검증 → 세션 저장.

Bedrock이 만든 SQL·DSL을 직접 실행하지 않는다. 검색 계획은 허용된 직무·기술·지역·상태·개수만 포함한다. DB 검색과 Elasticsearch 검색은 같은 논리 계약을 사용한다.

## 후보 선택

후보 공고 수가 3개 이상이며 예상 토큰 예산을 초과하면 요약 카드만 반환하고 선택을 요청한다. 기업 수와 공고 수를 혼동하지 않는다. 선택 후 상세를 조회한다. 임계값·선택 개수 상한은 설정값으로 관리한다.

## 보안·오류

브라우저에 DB·검색엔진 비밀값을 전달하지 않는다. Bedrock 호출은 서버 IAM 역할을 사용한다. 타임아웃·재시도·출력 상한을 설정한다. 긴 작업의 비동기 접수/상태 조회는 실측 후 도입한다. 같은 요청 재전송으로 대화 상태와 비용이 중복되지 않게 처리한다.

## 대화·근거·캐시 저장 보완 (2026-10-28)

모든 대화 조회와 캐시 조회는 인증된 소유 범위를 검증한다. 재전송 요청은 idempotency_key와 state_version으로 중복 상태 전이를 방지한다. 응답의 추천 이유는 당시 source_version과 근거 인용에 연결한다. 캐시 적중 여부는 운영 이벤트로 기록하되 클라이언트에 내부 캐시 키나 다른 사용자 정보를 노출하지 않는다.

## 로컬 MySQL 대화 구현

새 진입점은 src.handlers.dialogue.lambda_handler이며 공유 테스트 Bearer 토큰·클라이언트 토큰으로 보호한다. action=search/select/answer/remember, request_id, session_id를 사용한다. 사용자가 met/unmet/unknown을 명시하며 원문 목록 항목별 조건과 원문을 함께 확인한다. DIALOGUE_LOCAL.md의 실제 계약을 따른다. 기존 src.handlers.chat은 운영 차단을 유지한다. 정식 인증과 AWS 네트워크 배치는 아직 미완료다.


## 2026-10-28 로컬 대화 기억 구현

실제 로컬 API는 search/select/answer/remember를 지원한다. remember는 session_id/request_id/message(최대 2,000자)를 받으며 이전 조건 확인을 무효화한다. 동일 세션 search는 기억을 유지한다. 질문 응답에 progress(answered,total), memory(facts,statement_count,scope,basis)를 추가했다. 최종 응답에 unconfirmed_count를 제공한다. unknown은 미확인으로 남긴 채 다음 항목으로 진행한다.
