# 선택한 공고의 조건 질문 정리 운영

상태: AWS 캐시 테이블·권한·선택 시 처리 활성화 완료
기준일: 2026-11-03

## 기본 흐름

신규 적재는 원문과 ES 본문 동기화까지만 수행한다. 공고 선택 → SQL 원문 파싱 → 승인 결과/질문 캐시 확인 → 필요 시 질문 라벨 모델 호출 → 원문 계약 검증 → SQL 질문 캐시 저장 → 문답으로 진행한다. 질문 캐시를 ES에 발행하지 않는다. 대량 분류 작업은 보류한다.

모델은 질문 분류와 짧은 이유만 반환한다. 작은 공고는 한 묶음, 긴 공고는 제한 분할이며 실제 호출마다 model_invocations와 기존 세션 예산을 사용한다. 일반 사용자도 공유하는 캐시에는 공고 원문/정리만 있고 사용자 프로필이나 자기평가가 없다.

## 배포 준비

기존 원본·사용자 답변은 유지한다. 백업 후 app/backend/database/condition_question_cache_migration.sql로 새 캐시 테이블을 만든다. 런타임에는 해당 테이블 SELECT/INSERT만 필요하고 기존 job_postings·job_condition_reviews 조회 권한을 사용한다. 원본 쓰기·Outbox 쓰기 권한을 새로 부여하지 않는다.

관리자가 적절한 DB 환경과 런타임 계정을 확인한 뒤 적용할 SQL 예시:

```sql
GRANT SELECT, INSERT ON career_matching.job_condition_question_cache TO 'career_runtime'@'%';
```

이 문서의 신규 DDL과 런타임 SELECT/INSERT 권한을 AWS에 반영했다. 로컬 격리 MySQL의 별도 테스트 계정으로 최소 권한 동작을 확인했다. 비밀 설정·원본 데이터를 Git에 넣지 않는다.

## 설정

- 코드 기본값은 ENABLE_ON_DEMAND_CONDITIONS=false이며 현재 AWS 작업자는 true로 활성화했다.
- ENABLE_LIVE_BEDROCK=true도 있어야 실제 모델 호출이 가능하다. 캐시 적중은 새 모델 호출이 없다.
- ENABLE_AI_CONDITION_SELECTION은 과거 승인 분류 조회 전용 경로다. on-demand가 켜지면 새 서비스가 승인 조회도 담당한다.
- ENABLE_AI_CONDITION_RANKING은 비활성을 유지한다. 질문 캐시와 검색 순위는 별개다.

코드 배포와 DB 준비를 마친 뒤 유효 공고 1개로 첫 선택·재선택·질문 중단·원문 변경·캐시 장애를 확인한다. 실제 모델 검증은 별도 opt-in 후에만 수행한다. 이번 구현 작업의 유료 호출은 0회다.

## 확인 위치

model_invocations의 purpose=condition_review에서 각 실제 호출의 성공·실패·토큰을 확인한다. job_condition_question_cache에서는 source_snapshot, classification, model_usage와 validation_level=source_contract_only를 확인한다. 이 표시는 원문 연결 검증이며 독립적인 의미 검증이 아니다. 새 캐시의 관리자 UI 전용 조회는 이번 범위에 포함하지 않으며 SQL 도구로 확인할 수 있다.

같은 조건 동시 선택에서 잠금이 사용 중이면 기다리며 모델을 중복 호출하지 않고 원문으로 복귀한다. 실패 결과를 캐시로 저장해 질문을 생략하지 않는다. 기존 답변이 있는 세션은 새 캐시로 자동 재편집하지 않는다.

## 복귀와 과거 경로

ENABLE_ON_DEMAND_CONDITIONS=false로 기존 문답으로 복귀한다. 캐시와 과거 답변을 지우지 않는다. 기존 오프라인 승인 분류/Outbox 소비자는 별도 경로이며 이미 발행된 v2 이벤트가 있는 서버를 구형 v1 소비자로 되돌리지 않는다. 과거 표본은 [v2 기록](AI_CONDITION_V2_VERIFICATION_20261103.md), 질문 캐시 계약은 [선택 시 정리](ON_DEMAND_CONDITION_REVIEW.md)를 따른다.

## 배포 도구와 결과

infra/on_demand_conditions.py submit --confirm-maintenance로 백업·테이블·권한을 준비하고 result로 확인한다. 이어서 기존 infra/update_backend.py build/apply/result로 코드를 배포한다. 코드 해시가 일치한 뒤 on_demand_conditions.py enable --confirm-maintenance와 enable-result로 활성화를 확인한다. 이미 제출된 단계는 반복 실행하지 않는다.

현재 준비·코드 배포·활성화를 모두 완료했다. 작업자와 동기화 타이머 정상, 서로 다른 사용자 2명의 승인 결과 재사용·답변 분리·검증 모델 호출 0회를 확인했다. 새 생성에 대한 실제 모델 품질 시험은 미실행이며 대량 호출은 보류 상태다. 백업은 같은 서버에 있어 외부 백업을 대체하지 않는다. [배포 기록](deployments/20261103_on_demand_conditions.md).
