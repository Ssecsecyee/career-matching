# 전체 운영 DB 이식용 추출 기록

2026-11-21 운영 EC2 내부 MySQL `career_matching` 전체를 추출했다. 자료와 비밀값은 Git에 올리지 않고 복원 도구·프롬프트·이 요약만 공유한다.

## 완료

- JSONL 스냅샷: 2026-11-21 22:17:22 KST, 일관된 InnoDB 읽기 전용 트랜잭션.
- 네이티브 SQL 덤프: 같은 서버의 별도 `--single-transaction` 스냅샷. 완료 기록 22:22:00 KST. 두 형식을 동시에 복원하지 않는다.
- MySQL 실제 버전: 8.4.13.
- 전체 14개 테이블, JSONL 합계 419,954행.
- 채용공고 1,381행, 교육 197,318행. 교육은 전체 `training_offerings` 행 수이며 별도 고용24 회차 집계와 혼용하지 않는다.
- 대화 4,927행, 세션 551행, 모델 호출 821행을 포함한 전체 기준 DB. 원문 내용은 이 문서에 복제하지 않는다.
- 압축본: `educare-full-data.tar.gz`, 138,149,556바이트.
- SHA256: `e805fa6ca2997f5e0a45a9da707321e3c0960ee20da0217f63a222609266faae`.
- 압축 해제·모든 manifest 파일의 SHA256/크기·JSONL 전체 행 수 검증 통과.
- 네이티브 SQL gzip 전체 읽기 검증, CREATE TABLE 14개, DROP TABLE 0개 확인.
- 사용자 계정/비밀번호가 저장된 MySQL 시스템 DB와 AWS 인증키는 추출 대상이 아니다. 사용자 대화 등 기준 DB 데이터는 포함되므로 비공개로 관리한다.
- 임시 토큰 인증·루프백 HTTP를 SSM 암호화 터널 안에서 사용해 PC로 직접 전송했다. 이번 목적의 교육 계정 S3 중간 업로드는 수행하지 않았다. 이번에 만든 SSM 포트 전달 세션 2개는 종료했다.

테이블 행 수: admin_audit 0, chat_messages 4,927, chat_sessions 551, intent_decisions 2,218, job_condition_question_cache 54, job_condition_review_drafts 5, job_condition_reviews 3, job_postings 1,381, job_requirements 0, model_invocations 821, recommendation_evidence 620, response_cache 2,423, search_outbox 209,633, training_offerings 197,318.

## 코드·설정 인계

- `infra/migration/`: JSONL/SQL 추출, 해시/행 수 검증, 안전한 압축 해제, 빈 대상 MySQL 복원, 선택적 ES 내보내기/복원, 대상 계정 확인·비공개 업로드·설정 초안.
- `infra/migration/runtime/terminology/`: 기존 로컬 승인 표기 사전·출처·라이선스를 복사해 인계했다. 원래 미커밋 실험 폴더를 변경하거나 전체 커밋하지 않았다. 새 계정의 ES에 적용하기 전 소스/라이선스와 실제 분석기 연결을 검토한다.
- 자료와 `.env`는 별도 전달. Git main만으로 DB 데이터가 내려오지는 않는다.

## 미실행·주의

- 새 AWS 계정 자원 생성·업로드·배포, 새 DB 실제 복원 시험은 미실행.
- 실제 테스트는 타입 보존, 데이터 파일 손상·행 수 불일치 탐지, 압축 경로/심볼릭 링크 방어, 기존 DB/ES 대상 거부, 원격 코드 네임스페이스 회귀 등 10개 통과.
- S3 중간 업로드는 자동 승인 검토가 목적지 명시 승인이 없다는 이유로 거부했다. 이후 사용자가 명시한 ‘현재 SQL 전체를 동료 PC용 압축본으로 준비’ 범위에서 S3를 쓰지 않는 직접 전송으로 완료했다.
- 기존 원문과 ES/벡터를 같은 시점으로 원자적으로 묶은 백업은 아니다. ES 문서·벡터와 모델 가중치는 이번 SQL 압축본에 포함되지 않는다. 새 환경에서 Git 도구·원문·고정 모델로 재구축하고 기능 검증해야 한다.
- 운영 worker의 벡터 런타임은 Git 외부 고정 경로를 참조하므로, `.env` 입력만으로 설치가 끝나지 않는다. 상세 인계 문서와 MCP 프롬프트를 따른다.
- 현재 서비스의 쓰기를 멈추지 않았으므로 이후 신규·변경 데이터는 최종 전환 때 다시 동기화해야 한다. JSONL과 네이티브 SQL의 수집 시각 차이도 보존한다.
