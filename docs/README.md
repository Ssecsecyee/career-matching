# 해!듀케 프로젝트 문서

기준일: 2026-11-20

처음 이어서 작업할 때는 [구현 현황과 다음 작업](CURRENT_STATUS.md)을 읽는다. [문서 전체 목록](INDEX.md)에서 설계·배포·검증 이력을 찾을 수 있다.

## 현재 기준
- [구현 현황·다음 작업](CURRENT_STATUS.md): 배포된 기능, 확인 범위, 개선 우선순위, 테스트 방법.
- [제품 요구](PRD.md), [아키텍처](ARCHITECTURE.md), [AWS 구성](AWS_INFRA.md), [데이터](DATA_MODEL.md), [API](API_SPEC.md), [운영](OPERATIONS.md), [검증](QA_CHECKLIST.md).
- 위 기준 문서에는 이전 추가 기록이 남아 있다. 최신 구현은 코드와 해당 배포 기록을 대조하며, 미정 사항을 확정하지 않는다.

## 최근 변경
- [역량 기반 추천·우대조건 재개](reports/ASSESSMENT_FOLLOWUP_DEBUG_20261120.md)
- [검색/채팅 분리·화면 정리](deployments/UI_FOLLOWUPS_20261120.md)
- [사용 안내·아이콘 디자인](deployments/PRIVACY_GUIDE_ICONS_20261120.md)
- [점핏 갱신](deployments/JUMPIT_UPDATE_20261119.md), [고용24 갱신](deployments/WORK24_NEW_TRAINING_20261119.md)
- [모바일 화면](deployments/MOBILE_WORKSPACE_20261117.md), [TXT 유사 검색](deployments/TXT_SIMILARITY_20261114.md), [0건 벡터 대체](deployments/ZERO_RESULT_VECTOR_20261114.md)

## 문서 관리
과거 자료는 삭제하거나 이름을 바꾸지 않고 이력으로 분류한다. plans는 제안, deployments는 당시 반영, reports는 조사·검증 기록이다. 수집 건수는 관측일을 함께 읽는다. 비밀키·설정·실사용 대화는 커밋하지 않는다.

정리 전 README와 남은 과업은 [보관 폴더](history/20261120_before_document_cleanup/)에 보존했다. 기존 미커밋 자료와 sources/archive/workspace 원본은 별도 보존한다.
