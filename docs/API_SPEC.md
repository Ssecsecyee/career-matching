# API 설계

## 2026-10-28 최신 상태와 고용24 전환 계획

이 절의 실행 현황과 전환 방향을 아래의 과거 초안보다 우선한다. 현재 AWS 웹·대화 서버·EC2 MySQL 연결을 검증했으며 RDS와 Elasticsearch는 사용하지 않는다. 점핏 추가 표본 10건은 백업 후 운영 반영해 총 793건이며, 기존 783건의 버전·해시는 유지했다. 신규 10건의 모집 상태는 unknown이다. **고용24 승인 후 소량 표본 검증을 거쳐 AWS 정기 배치 자동화로 전환**한다. 상세 단계와 통과 기준은 [고용24 파이프라인 계획](../app/ingestion/GOYONG24_PIPELINE.md)을 따른다.

### 고용24 수집과 사용자 API 계약

고용24 API 호출은 서버 수집 계층에서만 수행하고 승인 키를 웹에 전달하지 않는다. 목록/상세 URL·필터·페이지·오류 계약은 승인 후 명세로 확정하며 미확인 endpoint를 구현 완료로 적지 않는다. 출처별 어댑터는 공통 배치 계약으로 변환한다. 적재 메시지는 배치 ID·허용된 S3 키·해시·어댑터 버전을 사용하고 임의 SQL/URL 실행을 허용하지 않는다. 사용자 검색·공고 선택에는 source+source_id 식별이 필요하므로 기존 source_id 전용 요청과의 호환/버전 전환을 설계한다.

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


## 체크리스트 및 일반 대화 업데이트
새 웹은 공고 선택에 `grouped: true`를 보내고 `answer_batch`로 조건별 명시적 답변을 저장합니다. 일반 대화와 검색은 Sonnet 라우터에서 구분합니다. 기존 모델 호출 상한은 유지하며 상세 배포·제한사항은 [코드 업데이트 안내](../infra/UPDATE.md)를 참고합니다.


## 교육 DB와 Bedrock 상담 연결 완료 (2026-10-28)

AWS 백엔드 코드 릴리스 `20261028T053143Z`와 웹 교육 참고 카드 배포를 완료했습니다.

- 학습·교육 요청에서 현재 메시지의 기술명과 필수/우대 미충족 조건의 기술명을 추출합니다. 기술명 사전과 별칭을 사용하며 의미 검색은 아직 아닙니다.
- unknown과 met 답변은 부족 역량으로 분류하지 않습니다. 부족 기술이 없으면 사용자 원문에서 언급한 주제를 참고할 수 있지만 부족 역량이라고 단정하지 않습니다.
- 교육 DB는 허용된 출처와 기술 JSON 필드를 매개변수 쿼리로 검색합니다. 최대 20건을 읽어 관련성과 신청 후보 여부로 정렬하고 상위 3건만 상담 입력에 전달합니다. 모델이 SQL을 작성하지 않습니다.
- history.training_retrieval에 교육명·기관·학습 주제·짧은 커리큘럼·지원 조건·표시 자부담·일정·출처·버전을 함께 넣고 기존 Sonnet 상담 호출 1회로 답합니다. 일반 인사나 단순 대화 정리는 교육 DB를 검색하지 않습니다.
- 교육 조회 결과와 근거 기술은 응답 learning_opportunities/learning_search에 저장됩니다. 대화·응답 캐시에도 당시 결과와 출처 버전이 포함됩니다. 현재 요청 재전송 캐시는 기존 10분 정책이며 실시간 교육 변경 무효화 시스템은 미구현입니다.
- 조건 확인 완료 후 미충족 조건이 있으면 교육 참고 카드를 함께 조회합니다. 이 추가 조회 자체는 모델을 호출하지 않습니다. 학습 순서는 사용자가 후속 질문할 때 기존 상담 모델이 답합니다.
- 후속 온라인 여부·비용 질문에는 같은 교육 주제를 유지합니다. 과거 채용 조건 답변을 지우지 않습니다.
- career_runtime에는 training_offerings SELECT만 추가했습니다. 교육 데이터와 기존 채용 데이터는 이번 코드 배포에서 변경하지 않았습니다.
- 현재 교육 7건은 모두 unknown이며 recommendation_eligible=false입니다. 과거 회차/모집 미확인 학습 참고자료로만 표시하고 신청 가능한 교육으로 추천하지 않습니다. 경력·학위는 교육 수료로 대체하지 않습니다.

### 검증
- 전체 백엔드 126개 검사 중 119개 통과, 별도 MySQL 환경이 필요한 7개 생략. 실제 배포 DB 조회는 따로 수행했습니다.
- 프론트엔드 빌드 통과 및 기존 S3·CloudFront 게시 완료.
- 운영 앱 DB 계정으로 React 3건 / RAG 2건 조회 성공, 모두 학습 참고용 처리 확인.
- 합성 사용자 테스트 대화 1건의 실제 Sonnet 호출 성공: HTTP 200, conversation, 교육 카드 3건, 참고용 안내 포함. 테스트 세션도 기존 24시간 보관 정책에 따릅니다.
- 결과 기록: infra/.build/training-grant-result.json, training-verify-result.json, training-smoke-result.json.

### 직접 확인할 질문
`React를 공부하고 싶어. 저장된 교육을 참고해서 기초 → 실습 → 포트폴리오 순서로 알려줘.`
다음으로 `그중 온라인 과정은?`을 입력합니다. 현재 신청 가능한 교육이 확인된 것처럼 답하지 않는지 확인합니다.

### 남은 범위
최신 모집/지원 자격 재확인, 승인된 고용24 교육 API 연동, 기술 동의어 확대·검색 품질 평가, 검색엔진, 학습 추천의 정밀한 분야·수준·시간·비용 필터는 후속 작업입니다.


## 교육 비교 지시어와 React 검색 누락 수정 (2026-10-28)

배포 릴리스: 20261028T055227Z. 프론트엔드 변경·DB 데이터 변경은 없습니다.

### 재현 사례
교육 카드 표시 후 `이중 어떤걸 제일 추천해?`라고 질문하면 선택한 채용공고 하나만 있다고 답했습니다. `React` 단독 검색과 수업 경험을 덧붙인 자연어 검색에서도 0건이 나왔습니다.

### 원인과 수정
- 교육 후속 질문 판별에 `이중`, `이 중`, 일반 비교·추천 표현이 누락되어 training_retrieval을 전달하지 않았습니다. 직전에 표시한 교육 목록과 순서·출처 버전을 그대로 재사용하고 conversation_focus=training을 명시하도록 수정했습니다. 새 공고 요청은 교육 비교로 가로채지 않습니다.
- 채용 키워드 검색 대상에 tech_stacks가 없었습니다. 기술 태그를 포함하고 대소문자를 통일했습니다. 실제 MySQL에서 드러난 JSON 문자열과 텍스트 열의 collation 충돌(1270)을 명시적인 utf8mb4_unicode_ci로 해결했습니다.
- 모델이 skills=[React]와 keyword='React 프론트엔드 개발'을 중복 생성했습니다. 기술명과 일반 직무 라벨만으로 된 복합 키워드는 정규화합니다. 사용자가 명시한 직무·지역과 보안 같은 별도 도메인 조건은 보존합니다. 임의의 모든 검색 조건 완화나 의미 검색은 도입하지 않았습니다.

### 검증
- 백엔드 133개 검사: 126개 통과, 별도 DB 환경 검사 7개 생략.
- 실제 운영 DB에서 react/React/REACT 모두 46건 조회.
- 실제 Sonnet 및 합성 사용자로 자연어 React 공고 검색 → 공고 선택 → 조건별 미충족 응답 → 교육 카드 표시 → '이중 어떤걸 제일 추천해?' 흐름 통과.
- 해당 합성 테스트는 선택된 공고의 조건에 따라 교육 2건을 표시했고 후속 질문에 동일한 출처·버전을 유지했습니다. 실제 교육명을 언급해 비교하고 과거/미검증 참고용 경고를 포함했습니다.
- 결과 파일: infra/.build/followup-regression-result.json. 합성 테스트 대화와 호출 기록은 기존 보관 정책을 따릅니다.
- 검증 중 모델 JSON 출력 형식 오류 1회도 관측했습니다. 이후 전체 흐름은 통과했지만 해당 간헐적 형식 오류의 일반적인 해결까지 검증했다고 주장하지 않습니다.

### 사용자 재확인
웹을 새로고침하고 새 메시지로 요청합니다. 같은 request_id의 재전송은 이전 캐시를 반환할 수 있습니다. 기존 세션에 learning_context가 남아 있다면 교육 비교 후속 질문도 이어갈 수 있습니다.


## 생성 중 답변 전달 배포 보완 (2026-10-28)
실제 Bedrock ConverseStream과 소유자별 중간 텍스트 폴링/타이핑 표시를 배포했습니다. 기존 비동기 작업 구조를 유지하며 브라우저 SSE는 아닙니다. 상세 범위·권한·검증·제한은 docs/STREAMING_RESPONSES.md를 참조합니다.
