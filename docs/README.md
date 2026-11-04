# 채용·교육 매칭 서비스 문서

기준일: 2026-11-04

사용자 대화에서 채용·교육 탐색 의도를 파악하고, 저장 공고 검색과 조건 자기평가·근거 기반 상담을 연결한다. React/CloudFront → API Gateway/Lambda → SQS → EC2 작업자 구조이며 MySQL이 기준 저장소, Elasticsearch가 검색 사본이다. 현재 서버는 MySQL·ES·작업자를 함께 운영하는 t4g.medium이다. 고용24 교육의 초회 적재·검색 연결은 완료했고 매일 자동 수집·적재 예약은 후속 계획이다.

## 기준 문서

[제품 요구](PRD.md), [현재 아키텍처](ARCHITECTURE.md), [현재 AWS 구성](AWS_INFRA.md), [데이터](DATA_MODEL.md), [API](API_SPEC.md), [운영](OPERATIONS.md), [검증](QA_CHECKLIST.md).

현재 아키텍처·AWS 본문은 누적 이력을 분리해 갱신했다. 나머지 기준 문서에는 과거 설계와 추가 기록이 남아 있으므로 현재 구현 확인 없이 확정 사실로 사용하지 않는다. 데이터·API 세부 계약은 실제 스키마·검증 코드와 대조한다. 전체 기준 문서 정합화는 남은 작업이다.

## 상세 문서

- [교육 탐색 문맥·검색 기준 확인](plans/TRAINING_CONTEXT_AND_SEARCH_REVIEW.md)

- [고용24 교육 초회 적재·운영 검색 확인](deployments/WORK24_INITIAL_IMPORT.md)

- [검색 동기화 운영](SEARCH_SYNC.md)
- [저장 답변 조회·수정](SAVED_ANSWERS_REVIEW_PLAN.md)
- [문맥 판단 단일화: AWS 배포 완료](UNIFIED_CONTEXT_ROUTING.md)
- [선택한 공고의 SQL 조건 정리·공유 캐시](ON_DEMAND_CONDITION_REVIEW.md)
- [AI 공고 조건 구조화·검색 반영](AI_CONDITION_CLASSIFICATION.md)
- [AI 조건 분류 실행·운영 준비](AI_CONDITION_RUNBOOK.md)
- [AI 질문 선정 평가 계획](AI_QUESTION_SELECTION_EVALUATION.md)
- [정규식 유지·정리 판단](REGEX_REVIEW.md)
- [보안·운영 후속 작업](SECURITY_OPERATIONS_ROADMAP.md)
- [남은 과업](REMAINING_TASKS.md)

## 검토 중인 전환·실험

- [후속 우선순위와 전체 품질 평가](plans/NEXT_PRIORITIES_AND_EVALUATION.md): 일일 자동화·교육 보완·단계별 평가·사람인 승인 후 전환.

- [고용24 수집·설정·일일 운영 절차](plans/WORK24_BULK_INCREMENTAL_PIPELINE.md): .env 분리, 계획 확인과 실제 실행 구분, 증분 및 운영 연결 경계.
- [고용24 훈련·NCS 저장 구조](plans/WORK24_TRAINING_NCS_MODEL.md): 통합 교육과 분류 연결 설계, DB 마이그레이션 전.
- [고용24 개인 권한 중심 범위](plans/WORK24_PERSONAL_SCOPE.md): 채용 API 전환 보류, 훈련·분류·직업/직무 정보 우선. 교육 초회 운영 적재·검색 연결 완료, 일일 자동 수집·적재 예약 전.

- [AgentCore Harness 전환 계획](plans/AGENTCORE_HARNESS_ADOPTION.md): 제안 단계. 기존 검색·DB·검증을 도구로 재사용하고 문맥/도구 선택만 비교한다.
- [Harness 비교 실험](plans/AGENTCORE_HARNESS_EXPERIMENT.md): 별도 smoke 5개 + 고정 50개 시나리오 설계. 평가셋/실행기·AWS 리소스·실측 결과는 아직 없다.

## 관리 원칙

현재 기준 본문에는 현재 구조를 한 번만 설명한다. 계획은 구현·배포와 구분하고 상세 이력은 별도 기록에 둔다. 민감 설정·토큰·실사용자 대화는 문서에 복사하지 않는다. sources·archive 및 기존 workspace 연결 자료를 수정하거나 삭제하지 않는다.

이전 누적 README는 [보관본](history/20261102_before_current_design/README.md)에 보존한다.
