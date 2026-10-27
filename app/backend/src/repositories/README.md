# DB 연결 경계

jobs.py의 인터페이스에 맞춰 MySQL 또는 확정된 DB 어댑터를 추가한다. 현재 JSON 어댑터는 로컬 검색 검증용이며 영구 대화 저장소가 아니다.

실제 DB 연결 시 매개변수 바인딩, 사용자 범위, 세션 버전 동시성 제어, 응답·근거·상태 트랜잭션, Outbox, 캐시 무효화와 만료 정리 작업을 구현한다. SQL 기준은 ../../database/schema.sql이다. 기존 PostgreSQL API를 자동 변경하지 않는다.

## MySQL 어댑터 추가

mysql_jobs.py는 job_postings의 매개변수 검색·상세 조회 어댑터다. mysql_connection.py는 명시적 MYSQL 설정과 원격 TLS 인증을 요구한다. 아직 운영 handler에 연결하지 않았다. 대화 저장·API 인증·추가 질문·AWS 배포는 후속 구현이다. 기존 17개 테스트와 MySQL 8.4의 783건 적재·재적재·원문 대조를 통과했고 보고서는 app/backend/local-data/jumpit_all_v3/mysql_verification_report.json에 있다.
