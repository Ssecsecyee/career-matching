# AI 조건 추출·검증·색인 운영

상태: AWS v2 연결·검토한 3건 반영 완료 / 사용자 질문 선정·순위 보강 비활성
기준일: 2026-11-03

## 대상과 비용 경계

MySQL의 모집 상태가 active/unknown이고 마감일 노출 정책을 통과하는 공고만 새 실제 추출 대상이다. 최초 배치 조회와 모델 호출 직전에 재확인한다. ES 문서 부재만으로 마감이라고 판단하지 않는다. 동기화 지연·검색 장애로 빠진 유효 공고는 복구 대상이며, 마감 공고는 새 모델 호출을 하지 않는다. 마감 판정은 원본 recruitment_status를 임의로 변경하는 것이 아니다.

현재 자료는 모집 미확인이 많으므로 노출 가능과 실제 모집 중을 구분한다. 추출 중 마감되는 경합을 완전히 예측할 수는 없으며 소비자가 최신 상태로 최종 노출을 막는다. 이번 고정 회귀 표본에 마감 공고가 포함됐던 비효율을 반복하지 않는다. 이미 저장한 과거 분류는 이력으로 보관하며 마감 시험은 오프라인 fixture로 수행한다.

## 실행 흐름

원문 → Bedrock 강제 도구 출력 → 전체 항목·원문 조각·정확한 인용 검증 → job_condition_review_drafts pending → 별도 원문/의미 검토 → verified → job_condition_reviews와 Outbox 원자 저장 → published → 소비자 → ES 대조.

조건은 최대 3개씩, 원문 조각 총량을 고려해 분할 호출한다. 호출당 출력 상한은 4096토큰이다. 모든 묶음이 성공해야 공고 결과를 반환하고 일부만 저장하지 않는다. 각 원문은 줄/위치별 조각으로 전부 보존한다. 평면 terms와 논리 트리는 별개이며 13개 기술 목록을 8개 자식 트리에 맞춰 자르지 않는다. 불명확한 관계는 unresolved로 보존한다. 의미 완전성까지 자동 입증되는 것은 아니므로 별도 검토가 필요하다.

## 최소 권한과 설정

| 주체 | 범위 |
|---|---|
| 추출 계정 | 원본 SELECT, 기존 분류 SELECT, 대기 테이블 SELECT/INSERT |
| 승인 계정 | 원본 SELECT, 대기 SELECT/INSERT/UPDATE, 승인 결과 SELECT/INSERT, Outbox INSERT |
| 검색 소비자 | 기존 동기화 권한과 승인 분류 SELECT |
| 대화 작업자 | 기존 권한과 승인 분류 SELECT |

추출 계정의 과거 호환 권한이 존재하더라도 공개 CLI의 직접 --apply 발행은 차단한다. 원본 UPDATE/DELETE 권한은 필요 없다. 승인용 자격증명은 서버 보호 파일에만 두며 출력·프롬프트·Git에 넣지 않는다. 호스트 live_calls_allowed=false, ENABLE_AI_CONDITION_SELECTION=false, ENABLE_AI_CONDITION_RANKING=false를 유지한다. 모델 재호출과 기능 활성화는 별도 opt-in이다.

## CMD 예시

```cmd
cd /d C:/AWS_project/career_matching
python app/ingestion/classify_job_conditions.py --limit 2 --output workspace/ingestion-reports/condition_plan_01.json
```

인증·원본 읽기·대기 적재 설정과 ENABLE_LIVE_BEDROCK=true가 준비됐을 때만 실제 추출을 실행한다. 매번 새 출력 경로를 사용한다.

```cmd
python app/ingestion/classify_job_conditions.py --live --stage --limit 2 --output workspace/ingestion-reports/condition_stage_01.json
python app/ingestion/condition_draft_actions.py inspect --draft-id 3 --output workspace/ingestion-reports/draft_3.json
```

승인 manifest는 정확한 후보 해시, 검토자, 각 조건의 source_complete/logic_preserved/label_confirmed와 실제 원문 대조 메모가 필요하다. 모델이 일괄 true로 채우는 것을 검토로 인정하지 않는다. 승인 작업은 승인 전용 계정으로 실행한다.

```cmd
python app/ingestion/condition_draft_actions.py verify --draft-id 3 --approval 검토한_파일.json --output workspace/ingestion-reports/verify_3.json
python app/ingestion/condition_draft_actions.py publish --draft-id 3 --output workspace/ingestion-reports/publish_3.json
```

이미 published인 후보를 반복 발행하지 않는다. publish 성공은 DB+이벤트 저장이며 ES 수신 성공과 다르다. 마감된 공고는 ES 문서 미존재가 정상이다. 유효 공고는 ES 분류/원문/조건 해시를 읽어 대조한다. 현재 예시 draft 3~5는 이미 발행된 이력으로 실행 연습에 쓰지 않는다.

## 배포와 복구

infra/build_condition_review_bundle.py는 코드·매핑·마이그레이션만 묶는다. infra/publish_condition_pilot.py는 별도 원문 대조를 마친 정확히 3개 표본에 한정한 배포 도구이며 일반 대량 배치가 아니다. 설치 전 같은 서버의 MySQL 압축 백업·검증을 수행한다. 서버 밖 백업을 대체하지 않는다.

이미 발행된 v2 이벤트가 있으면 구형 v1 소비자로 단순 복귀하지 않는다. 부분 발행 실패는 새 소비자를 유지해 처리 상태를 대조한다. 검증 실패를 이유로 원문이나 과거 분류를 삭제하지 않는다. 질문 선정/순위 플래그 false로 사용자 적용을 차단할 수 있다.

현재 결과와 실제 사용량: [v2 표본 검증](AI_CONDITION_V2_VERIFICATION_20261103.md). 저장 상태 계약: [추출 대기와 승인](CONDITION_EXTRACTION_STAGING.md). 독립적인 사람 정답 평가: [평가 계획](AI_QUESTION_SELECTION_EVALUATION.md).
