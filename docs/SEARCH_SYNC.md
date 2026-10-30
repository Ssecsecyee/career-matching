# DB → Elasticsearch 운영 연결

## 2026-10-30 실제 적용 상태

기존 t4g.medium EC2에서 채용·교육 검색을 Elasticsearch로 전환했다. DB 적재와 같은 트랜잭션에서 작성되는 search_outbox를 systemd 작업자가 소비한다. 작업 종료 후 약 60초 간격으로 재실행하며 실제 처리·장애 시간만큼 지연될 수 있다. 새 EC2나 공개 검색 포트는 추가하지 않았다.

최종 점검: MySQL 공고 942건 보존, 검색 노출 대상 및 ES 문서 825건, 교육 7건. 기존 모집 종료 23건과 추가 기한 경과 94건은 채용 검색에서 제외했다. 교육 7건은 모집 미확인/과거 회차의 학습 참고 자료 구분을 유지한다. Outbox 총 1066건 처리, 대기 0건, ES green, 대화 작업자와 자동 동기화 타이머 정상. 16:38경 가용 메모리 약 2152MiB이며 부하 검증 수치는 아니다.

React 검색 57건·교육 카드 3건을 DB와 재대조했다. 운용 코드에서 검색 장애를 주입해 MySQL 복귀와 다음 요청의 ES 재사용을 검증했다. 정상 0건은 복귀 조건이 아니다. 이 검증에서 Bedrock 호출·사용자 대화 생성은 하지 않았다.

## 처리 방식

1. 적재 트랜잭션이 원본 행과 source_version 및 Outbox 이벤트를 함께 기록한다. 적재를 우회한 수동 SQL 수정은 일반 변경 이벤트를 자동으로 만들지 않는다.
2. 단일 소비자가 MySQL GET_LOCK으로 중복 실행을 방지하고 실행당 최대 200건을 처리한다. 이벤트 본문의 과거 내용을 재생하지 않고 현재 DB 행을 다시 읽는다.
3. source+source_id의 해시를 문서 ID로 사용하고 source_version을 ES 외부 버전으로 적용한다. 같은 버전 재시도와 역순 이벤트를 허용하고 오래된 버전으로 덮어쓰지 않는다.
4. ES 성공 후에만 processed_at을 기록한다. 실패 시 attempt_count와 안전한 오류 유형·재시도 시각만 저장한다. 지연은 30초부터 최대 1시간까지 증가한다. 엔진 자체에 연결할 수 없으면 대기 이벤트를 보존하고 다음 타이머 실행에서 다시 연결한다.
5. 매 실행마다 날짜 경과 및 DB 모집 종료에 해당하는 누락 close 이벤트를 추가한다. close는 검색 노출 제어이며 원문 모집 상태나 원문 확인 시각을 꾸며 갱신하지 않는다.
6. 채용 원본은 삭제하지 않는다. 정확한 시각은 UTC 기준, date_only는 원문 날짜를 보존하고 한국 날짜 기준 다음 날부터 제외한다. 검색 SQL·ES 및 공고 선택 시 DB 확인에서 같은 기준을 적용한다. 상시채용은 기한 경과로 제외하지 않는다.
7. 교육은 별도 색인과 원본 재확인을 유지한다. 과거 회차도 참고 자료로 검색하되 현재 신청 가능한 과정으로 승격하지 않는다.

delete 이벤트는 같은 버전의 오래된 upsert로 문서가 재생성되지 않도록 차단한다. 원본을 물리 삭제해 식별자가 사라지면 소비자는 완료 처리하지 않고 재시도 대상으로 남긴다. 삭제가 필요하면 source+source_id를 보존하는 tombstone/비노출 절차를 먼저 사용해야 한다. 단순 close 이벤트만으로 모집 종료를 추정하지 않고 현재 DB 상태·날짜를 판단한다.

## 실행 파일과 접근 범위

- 소비자: app/ingestion/search_index/sync_outbox.py
- 공통 기한 정책: app/backend/src/services/deadlines.py
- 배포/조회: infra/connect_search.py
- 설치·검증·조회 스크립트: infra/elasticsearch/*sync_remote.py
- 서버 서비스: career-search-sync.service / career-search-sync.timer
- 보호된 서버 설정: /opt/career/search-sync.json (비밀번호 포함, 출력·Git 보관 금지)
- 채용/교육 별칭: career-jobs-read / career-training-read

전용 DB 계정은 공고·교육 SELECT, Outbox SELECT/INSERT 및 처리 상태 세 컬럼 UPDATE만 허용한다. 대화 테이블이나 공고 원본 쓰기·삭제 권한은 없다. 검색은 127.0.0.1:19200만 사용한다. 배포 전 SQL gzip 백업을 생성하고 압축 읽기와 SHA256을 검증했다. 앱·설정 이전 사본과 배포 결과는 서버 release 폴더에 보존한다.

첫 전환 시 서비스 사용자와 설정 파일 소유권 불일치로 시작 실패가 발생했다. 이전 앱을 복원하고 설정 소유권을 복구해 서비스 재개를 확인한 뒤, 소유권 보존을 보완한 패키지로 재배포에 성공했다. 실패 기록은 infra/.build/search-sync-failed-*에 유지한다. 실제 복원 훈련이나 전체 장애 대응 검증이 끝났다는 뜻은 아니다.

## 상태 확인 (사용자 CMD)

```cmd
cd /d C:\AWS_project\career_matching
python infra\connect_search.py inspect
python infra\connect_search.py inspect-result
```

첫 명령 제출 후 두 번째를 실행한다. pending·pending_max_attempts·최근 실행 failed·timer active·worker active·ES health를 본다. oneshot 소비 서비스는 성공 후 inactive/dead가 정상이며 타이머가 active/waiting으로 다음 실행을 기다린다. 마지막 Result=success와 ExecMainStatus=0을 함께 확인한다. 자동 알림은 아직 설치하지 않았으므로 적체·반복 실패는 이 조회와 시스템 로그로 관측한다.

## 검증과 남은 범위

백엔드 173개 중 환경 의존 7개 제외 통과. 별도 로컬 DB·색인에서 신규·수정·중복·역순 close·delete·오래된 upsert·실패 후 지연 재시도·날짜 경과·원본 상태 유지·교육 참고 문서 보존을 검증했다. 시험 DB·색인만 정리했으며 기존 로컬 공고는 유지했다. AWS에서는 실제 대기 이벤트 처리와 타이머 반복 실행·검색 경로·DB 원본 무변경을 확인했다.

고용24 API 수집 자동화는 아직 별도 작업이다. 이번 연결은 DB→검색엔진 자동화이며 원문 수집을 자동화한 결과가 아니다. 대규모 부하 시험과 자동 경보도 남아 있다. 전체 재색인/별칭 교체는 소비자를 멈추고 미처리 변경 경계를 보존하는 별도 절차로 수행해야 한다. 과거 로컬 전체 색인 도구를 운영에서 그대로 실행하지 않는다. 임의 별칭 교체 중 변경 누락 복구를 자동 보장하는 도구는 아직 없다.

이번 배포에는 앞서 로컬 검증한 실패 사용자 입력 선저장 보완도 포함됐다. 502 전체 원인을 해결한 것으로 해석하지 않는다. Git 커밋·푸시는 이번 연결 요청에 포함해 실행하지 않았다.
