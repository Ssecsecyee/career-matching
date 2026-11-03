# 공고 선택 시 조건 정리

상태: 로컬 구현·격리 MySQL 검증 완료 / AWS 미배포·유료 호출 없음
기준일: 2026-11-03

## 고정 방향
신규·변경 공고는 기존 검증 후 MySQL 원문과 Outbox를 통해 ES에 반영한다. 수집 단계에서 AI로 전량 사전 분류하지 않는다. ES는 공고 후보 검색을 맡고, 사용자가 선택하면 MySQL 최신 원문을 조회해 서버에서 항목·위치를 파싱한다. 질문 정리에 AI가 필요하면 선택한 공고만 처리한다.

AI에는 조건 ID·원문·필수/우대 유형을 주고 질문 분류·짧은 이유만 받는다. 기술 목록·논리식·원문 위치를 다시 생성시키지 않는다. 원문 조각과 미확정 논리는 서버가 보존한다. 조건 20개 이하·원문 14000자 이내면 한 묶음으로 호출한다. 그보다 긴 공고는 최대 6개 항목·원문 약 6000자 단위로 나눈다. 출력이 잘린 경우 더 작은 묶음이 있을 때만 한 차례 분할 재처리한다. 전체 호출 상한은 5회이며 모델 단계 30초 경과 후 새 호출을 시작하지 않는다. 개별 요청은 읽기 제한 15초·SDK 재시도 1회 시도로 기존 세션/SQS 처리 시간을 보호한다. 실제 호출마다 기존 세션 한도·모델 사용량 기록을 적용한다. 형식 실패·누락·원문 불일치·예산 소진은 기존 전체 원문 문답으로 복귀한다. 질문 중단 상태에서는 새 조건 정리를 호출하지 않는다.

## SQL 캐시와 의미 검증 경계
job_condition_question_cache는 공고 ID·조건 해시·질문 정리 정책 버전으로 재사용하는 별도 캐시다. 원문 스냅샷과 구조 검증 결과·모델 사용량을 보관하고 원본을 수정하지 않는다. source_contract_only는 ID·인용·구간 연결 검증을 통과했다는 뜻이며 독립적인 사람 의미 검증이나 ES 발행 승인을 뜻하지 않는다.

기존 job_condition_reviews의 승인된 동일 조건 분류가 있으면 먼저 재사용할 수 있다. job_condition_review_drafts pending 후보는 자동으로 승인하거나 질문 캐시로 끌어오지 않는다. 새 질문 캐시는 기존 승인/Outbox 경로에 넣지 않으므로 사용자 선택마다 ES를 갱신하지 않는다. 이전 표본의 분류와 ES 필드는 과거 검증 결과로 유지하되 새 전량 백필은 실행하지 않는다.

동일 공고·동일 조건의 동시 선택은 MySQL 이름 잠금으로 중복 모델 호출을 막는다. 잠금 대기 때문에 사용자 요청을 길게 묶지 않고 원문으로 복귀한다. 조건이 바뀌면 새 해시로 처리하며 과거 캐시와 이미 저장한 사용자 답변은 유지한다. 호출 전후와 저장 시 최신 원문·모집 상태·마감 여부를 확인한다.

## 설정과 운영
ENABLE_ON_DEMAND_CONDITIONS=false가 기본이며 true일 때 선택 시 처리를 연결한다. 실제 호출에는 기존 ENABLE_LIVE_BEDROCK=true도 필요하다. 승인된 기존 분류만 읽는 ENABLE_AI_CONDITION_SELECTION과 선택 시 생성은 역할이 다르다. ENABLE_AI_CONDITION_RANKING은 비활성을 유지한다.

캐시 테이블 마이그레이션과 runtime의 SELECT/INSERT 권한을 배포 전에 준비한다. 캐시 원본을 UPDATE/DELETE하거나 Outbox INSERT 권한을 새로 줄 필요는 없다. 캐시 저장 실패 시 정리 결과로 질문을 생략하지 않고 원문으로 복귀한다. 모델 호출 기록은 model_invocations, 재사용 원문 정리는 질문 캐시에서 확인한다.

## 검증 항목
선택 전 조건 정리 모델 0회, 첫 선택 생성·저장, 같은/다른 사용자 재선택 시 모델 0회, 조건 변경 시 재생성, 원문·해시 불일치/마감 시 차단, 동시 선택 중복 방지, 묶음별 실제 호출 기록, 출력 잘림·형식 오류·예산 소진 시 원문 복귀, 질문 중단 시 모델 미호출, 캐시 적재로 ES 이벤트가 생기지 않는 것을 검증한다. 원문 인용 검증만으로 의미 정확도를 보장한다고 보고하지 않는다.

## 구현 위치와 현재 검증

- 선택 연결: services/dialogue.py, services/context_router.py, handlers/dialogue.py.
- 질문 전용 모델: bedrock/question_reviewer.py. 기존 전체 추출 condition_classifier.py와 역할을 분리한다.
- 재사용/동시 호출 제어: services/selected_condition_review.py, repositories/condition_question_cache.py.
- 신규 캐시 DDL: database/condition_question_cache_migration.sql과 전체 schema.sql.

전체 로컬 회귀와 격리 MySQL에서 공유 캐시·고유 키·원문 보존·마감 차단·동시 이름 잠금·최소 SELECT/INSERT 권한·Outbox 이벤트 0개를 확인했다. 실제 Bedrock 출력 품질과 지연·비용은 이번에 측정하지 않았으며 새 AWS DB 테이블/권한·기능 플래그도 아직 반영하지 않았다. 초기 테스트는 test_selected_condition_review.py, test_question_reviewer.py, test_condition_question_cache_mysql.py에 있다.

최종 실행: 446개 중 436개 통과·10개 외부 환경 조건 생략. 조건 정리 외의 기존 자연어 의도/검색·상담 모델 호출은 유지한다. 이번 변경으로 일반 검색의 전체 모델 호출이 0회가 되는 것은 아니다. 새 질문 전용 모델은 모의 응답으로만 검증했으며 실제 의미 품질·비용은 미측정이다.
