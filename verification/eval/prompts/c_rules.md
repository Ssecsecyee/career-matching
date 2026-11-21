# 추가 판정 규칙
아래 규칙이 위 지시와 다르면 아래 규칙을 따르세요.

## category=skill로 볼 것
- 언어, 프레임워크·라이브러리, DB, 클라우드와 그 서비스(AWS, EKS, RDS, SQS 등), 도구(Git, Jira, Jenkins, Grafana 등), 프로토콜(MQTT, gRPC, WebSocket 등), 방법론·아키텍처(TDD, MSA, CI/CD 등)
- 어학(영어 가능, 비즈니스 일본어 등), 업무 도메인 지식(금융, 반도체, ERP, EMR 등), 기술 범주어(RDBMS, NoSQL, WAS, 메시지 큐 등)

## skill이 아닌 것
- 이름 없는 일반 역량(형상관리, 배치, 캐시, 모니터링, API 설계, 데이터베이스 설계, CS 기초, AI 도구 활용) → other
- 경력 연차 → experience, 학력 → education, 자격증 → certificate, 성향 → attitude
- 제품명·서비스명(자사 서비스 이름), 지급 장비 → other
- 여러 범주가 섞인 조건은 그 조건이 주로 묻는 것 하나를 고르세요.

## terms
- 조건에 적힌 기술 이름을 원문 그대로 모두 parts.terms에 넣으세요. category가 skill이 아니어도 기술 이름이 보이면 넣으세요.
- 회사명이 붙은 제품은 회사 플랫폼도 넣으세요. "AWS SQS/SNS"이면 AWS, SQS, SNS.
- 범주 이름과 제품이 함께 나오면 둘 다 넣으세요. RDBMS와 MySQL, WAS와 JBoss.

## logic (AND/OR)
- 사람이 읽는 의미로 정하세요.
- 한 문장 안에 "중 1개 이상 / 또는 / 혹은 / or / A/B / e.g." 신호가 있거나, 범주 이름 뒤에 제품을 예시로 나열하면("RDBMS(MySQL·MariaDB·Oracle 등)", "메시지큐(SQS, Kafka, RabbitMQ 등)") any입니다.
- 서로 대신할 수 있는 기술만 any로 묶으세요. "등"이 붙어도 하는 일이 다르면 묶지 마세요("Redis, Kafka 등"은 캐시와 메시지 전달). 선후 관계인 기술도 묶지 마세요("Docker, Kubernetes").
- 단순 나열("JAVA, RDBMS, WAS, Linux, Jboss")과 제품 고유 요구("Oracle PL/SQL 및 SQL 기반 쿼리 작성")는 all입니다.
- 읽어도 판단할 수 없을 때만 unresolved로 두세요.
