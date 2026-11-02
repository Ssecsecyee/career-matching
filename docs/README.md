# 채용·교육 매칭 서비스 문서

기준일: 2026-11-02

사용자 대화에서 채용·교육 탐색 의도를 파악하고, 저장 공고 검색과 조건 자기평가·근거 기반 상담을 연결한다. React/CloudFront → API Gateway/Lambda → SQS → EC2 작업자 구조이며 MySQL이 기준 저장소, Elasticsearch가 검색 사본이다. 현재 서버는 MySQL·ES·작업자를 함께 운영하는 t4g.medium이다. 고용24 자동 수집은 후속 계획이다.

## 기준 문서

[제품 요구](PRD.md), [현재 아키텍처](ARCHITECTURE.md), [현재 AWS 구성](AWS_INFRA.md), [데이터](DATA_MODEL.md), [API](API_SPEC.md), [운영](OPERATIONS.md), [검증](QA_CHECKLIST.md).

현재 아키텍처·AWS 본문은 누적 이력을 분리해 갱신했다. 나머지 기준 문서에는 과거 설계와 추가 기록이 남아 있으므로 현재 구현 확인 없이 확정 사실로 사용하지 않는다. 데이터·API 세부 계약은 실제 스키마·검증 코드와 대조한다. 전체 기준 문서 정합화는 남은 작업이다.

## 상세 문서

- [검색 동기화 운영](SEARCH_SYNC.md)
- [저장 답변 조회·수정](SAVED_ANSWERS_REVIEW_PLAN.md)
- [문맥 판단 단일화: AWS 배포 완료](UNIFIED_CONTEXT_ROUTING.md)
- [AI 공고 조건 구조화·검색 반영](AI_CONDITION_CLASSIFICATION.md)
- [AI 조건 분류 실행·운영 준비](AI_CONDITION_RUNBOOK.md)
- [AI 질문 선정 평가 계획](AI_QUESTION_SELECTION_EVALUATION.md)
- [정규식 유지·정리 판단](REGEX_REVIEW.md)
- [보안·운영 후속 작업](SECURITY_OPERATIONS_ROADMAP.md)
- [남은 과업](REMAINING_TASKS.md)

## 관리 원칙

현재 기준 본문에는 현재 구조를 한 번만 설명한다. 계획은 구현·배포와 구분하고 상세 이력은 별도 기록에 둔다. 민감 설정·토큰·실사용자 대화는 문서에 복사하지 않는다. sources·archive 및 기존 workspace 연결 자료를 수정하거나 삭제하지 않는다.

이전 누적 README는 [보관본](history/20261102_before_current_design/README.md)에 보존한다.
