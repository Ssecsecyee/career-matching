# 현재 AWS 구성

상태: 배포된 구성 기준 · 기준일: 2026-11-02

| 구성 | 현재 역할·배치 |
|---|---|
| 리전 | 서울 ap-northeast-2 중심, Bedrock은 global 추론 프로필 사용 |
| 웹 | React/Vite 산출물을 비공개 S3와 CloudFront로 제공 |
| API | API Gateway HTTP API와 Python Lambda: 인증·검증·작업 접수·결과 조회 |
| 대화 큐 | SQS 작업 큐와 실패 큐 |
| 임시 작업 상태 | DynamoDB, API 결과 폴링용 |
| 실행 서버 | 기존 t4g.medium EC2 1대, ARM64, 4GiB |
| 기준 DB | 같은 EC2의 MySQL, RDS 사용 안 함 |
| 검색 | 같은 EC2의 직접 설치 Elasticsearch 9.5.5 + Nori, 채용·교육 색인 분리 |
| 모델 | Amazon Bedrock Claude Sonnet, 실제 호출·토큰 이력은 MySQL 기록 |
| 비밀 | Secrets Manager와 서버 보호 설정, 일반·관리자 접근 구분 |
| 운영 접근 | SSM, DB 확인은 필요 시 포트 포워딩 |
| 검색 동기화 | systemd 서비스·타이머가 MySQL Outbox 소비 |

## 연결과 보안 경계

외부 사용자는 웹/API를 이용한다. MySQL은 서버 내부 3308, ES는 127.0.0.1:19200으로 연결한다. 로컬 DB 확인 시 SSM 터널을 사용하며 인터넷에 DB·검색 포트를 열지 않는다. 일반·관리자 토큰 분리는 개인별 로그인이나 작업자 물리 분리를 의미하지 않는다.

## 현재 배포 경로

- 백엔드 코드: infra/update_backend.py build → apply --confirm-maintenance → result.
- 웹: infra/hosting.py publish.
- 인프라 변경: 현재 스택과 변경 세트를 확인한 별도 절차를 따른다. 코드 배포와 리소스 재생성을 혼동하지 않는다.
- 원본·DB 볼륨은 코드 배포로 교체하지 않는다. 복구용 이전 앱 보존과 DB 외부 백업은 별개다.

## 구성 정합성과 운영 한계

실제 EC2는 t4g.medium이나 초기 LaunchTemplate에 t4g.small이 남아 있는 차이가 기록돼 있다. 템플릿을 그대로 재적용하지 말고 안전한 정합화와 교체 여부 검토가 먼저다. 과거 RDS 중심 template.json 구성은 현재 운영 구성이 아니다.

MySQL·ES·작업자의 단일 장애 지점과 자원 경쟁이 있다. 외부 백업·복원 시험·독립 경보의 구축 및 검증 여부를 우선 점검한다. 배포 산출물 S3나 동일 서버의 사본만으로 데이터 복구 보장을 주장하지 않는다. 정식 부하 시험은 미완료다.

## 후속 계획

고용24 승인 후 표본 API 검증, 출처 매핑, 적재·색인 검증을 거쳐 예약 수집 자동화한다. 추가 수집 Lambda·적재 전용 큐 등의 계획을 현재 생성된 리소스로 표현하지 않는다. 신규 비용과 권한은 변경 전에 검토한다.

관련: [아키텍처](ARCHITECTURE.md), [검색 동기화](SEARCH_SYNC.md), [운영 개선](SECURITY_OPERATIONS_ROADMAP.md).
이전 누적 문서는 [보관본](history/20261102_before_current_design/AWS_INFRA.md)에 둔다.
