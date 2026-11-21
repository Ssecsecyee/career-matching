# 범주 판단 보충 규칙
이 규칙은 category를 고를 때만 씁니다. treatment와 reason_code는 위 지시를 그대로 따르세요.

## category=skill로 볼 것
- 언어, 프레임워크·라이브러리, DB, 클라우드와 그 서비스(AWS, EKS, RDS, SQS 등), 도구(Git, Jira, Jenkins, Grafana 등), 프로토콜(MQTT, gRPC, WebSocket 등), 방법론·아키텍처(TDD, MSA, CI/CD 등)
- 어학(영어 가능, 비즈니스 일본어 등), 업무 도메인 지식(금융, 반도체, ERP, EMR 등), 기술 범주어(RDBMS, NoSQL, WAS, 메시지 큐 등)

## skill이 아닌 것
- 이름 없는 일반 역량(형상관리, 배치, 캐시, 모니터링, API 설계, 데이터베이스 설계, CS 기초, AI 도구 활용) → other
- 경력 연차 → experience, 학력 → education, 자격증 → certificate, 성향 → attitude
- 제품명·서비스명(자사 서비스 이름), 지급 장비 → other
- 여러 범주가 섞인 조건도 category는 그 조건이 주로 묻는 것 하나만 고르세요.

## 출력 짝 — 하나라도 어기면 서비스가 그 묶음의 답을 모두 버립니다
- treatment=ask이면 reason_code=verifiable_requirement
- treatment=reference이면 reason_code는 no_restriction, subjective_trait, not_eligibility 중 하나
- treatment=review이면 reason_code=ambiguous
- reason_code=subjective_trait은 category=attitude일 때만 씁니다.
- category를 위 규칙으로 바꿔도 treatment와 reason_code는 위 지시대로 정하세요. 일반 역량을 other로 고른 조건도 확인할 수 있는 요건이면 ask/verifiable_requirement입니다.
