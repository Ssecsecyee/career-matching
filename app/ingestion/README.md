# 수집·정제 작업

normalize_jumpit.py는 보유 상세 JSON을 정규화하는 오프라인 도구다. 네트워크 요청, DB 입력, S3 업로드가 없다. 현재는 주요 섹션 추출이며 화면 전체와의 대조·미확인 섹션 추가 수집은 후속 작업이다.

```powershell
python normalize_jumpit.py --input "기존 raw/details 경로" --output "새 출력 경로/jobs.normalized.json"
```

기존 파일 덮어쓰기를 거부한다. 원본 전체를 raw_detail로 보존한다. application_notes는 화면 대조 전 생성하지 않는다. 수집 시각은 provenance와 결합하기 전 null이며 날짜는 원문 문자열을 보존한다. 현재 데이터의 모집 상태는 최신 확인 전 unknown이므로 로컬 검색에서 제외된다. 데이터 존재와 현재 모집 중을 혼동하지 않는다.

다음 구현: 783개 원본과 provenance 결합·중복 버전 선택, 상세 누락 조사, 출처 허용 범위 확인 후 추가 수집, UTC 날짜 검증, DB upsert/Outbox, S3 저장, Elasticsearch 부분 실패 재시도. 기존 수집 코드는 ../../workspace/api추출테스트에 유지한다. 교육 수집은 이용 범위 확인 후 별도 어댑터로 구현한다.

## 전체 스냅샷 정제 보완

normalize_all_jumpit.py는 기존 병합본의 공고 ID 집합을 기준으로 모든 수집 폴더의 상세와 provenance를 결합한다. 같은 ID는 최신 수집 시각의 상세를 선택한다. 파일 수정 시각을 수집 시각으로 쓰지 않는다. 원문 시각은 한국 시각으로 해석해 UTC로 정규화한다. 저장된 마감일 경과는 closed, 공개 여부에 문제가 있으면 unavailable, 나머지는 unknown이다. 최신 웹 모집 상태를 확인한 결과가 아니다.

CMD 실행:

```cmd
cd /d C:\AWS_project\career_matching\app\ingestion
python normalize_all_jumpit.py --output-dir "C:\AWS_project\career_matching\app\backend\local-data\jumpit_all_v2"
```

출력: jobs.normalized.json, normalization_report.json. 출력 폴더는 새 이름이어야 한다. 기대 건수·실제 건수·상태별 건수·누락 섹션·상세/수집 이력 오류를 보고한다. complete=false이면 종료 코드 2이며 보고서를 확인한다. 현재 보유 원본 기준이며 신규 수집·DB 입력·S3 업로드는 없다.

관측한 본문 버전 수는 로컬 추적용이다. 운영 DB의 영구 증가 버전은 적재 트랜잭션에서 별도로 관리해야 한다. 지원 유의사항이 원본에 독립적으로 없으면 확인 필요로 남기며 화면 전체를 수집했다는 의미가 아니다.

## MySQL 최초 적재용 파일 준비

export_mysql_data.py는 정제 JSON을 별도 데이터 INSERT 파일로 변환한다. 기존 빈 schema.sql은 변경하지 않는다. 실제 MySQL 연결·S3 업로드는 하지 않는다. 저장된 모집 상태와 원본 전체를 보존하며 필수/우대 문장을 의미 단위로 해석하는 모델 작업은 수행하지 않는다.

CMD:

```cmd
python export_mysql_data.py --input "C:\AWS_project\career_matching\app\backend\local-data\jumpit_all_v3\jobs.normalized.json" --output "C:\AWS_project\career_matching\app\backend\local-data\jumpit_all_v3\jobs.data.sql"
```

파일은 새 경로에만 생성한다. 같은 출처·ID는 중복 생성하지 않으며 오래된 스냅샷으로 최신 DB 값을 덮지 않도록 조건부 갱신한다. 문자열은 UTF-8 hex literal로 저장해 따옴표·역슬래시·원문 SQL 문구를 데이터로 취급한다. 시각은 UTC로 기록한다.

실제 적재는 대상 DB에 schema.sql을 먼저 적용하고 생성된 jobs.data.sql을 실행하는 별도 단계다. root/관리자 비밀번호를 명령행이나 문서에 넣지 않는다. 최초 적재 보조용이며 DB 갱신과 Outbox를 연결하는 운영 동기화 코드는 아직 아니다. 추가 테스트 4개는 작성만 했으며 실행하지 않았다.


## 증분 적재 추가
운영 증분 갱신은 신규 `incremental_jumpit.py`를 사용한다. 기존 SQL 내보내기는 최초 적재 보조용이다. 설정·권한·안전한 미리보기는 [INCREMENTAL.md](INCREMENTAL.md), 수집 결과 규격은 [수집 담당 프롬프트](../../docs/JUMPIT_INCREMENTAL_COLLECTOR_PROMPT.md)를 참고한다. 실제 운영 적용·S3 업로드·예약 수집은 아직 수행하지 않았다.


## 고용24 API 승인 후 전환
[소량 추출부터 AWS 정기 배치까지의 계획](GOYONG24_PIPELINE.md)을 따른다. 현재 점핏용 incremental_jumpit.py를 고용24에 그대로 적용하지 않으며 출처 어댑터와 공통 적재 계층을 분리한다. 고용24 운영 수집·정기 실행은 아직 미구현이다.
