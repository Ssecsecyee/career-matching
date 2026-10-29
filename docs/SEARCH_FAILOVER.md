# Elasticsearch 미응답 시 MySQL 자동 복귀

2026-10-29 사용자 결정. 이 문서는 이전의 자동 복귀 미사용 설명보다 우선한다.

Elasticsearch 선택 시 채용·교육 검색을 먼저 엔진에 요청하고, 연결 거부·연결 끊김·네트워크 시간 초과·엔진 검색 timed_out 또는 HTTP 502/503/504에 한해 같은 구조화 검색 조건으로 기존 MySQL 검색을 한 번 실행한다. 중복 Bedrock 호출이나 DB 쓰기는 없다.

정상 0건, HTTP 400/401/403/404/429, 인증서 오류, 잘못된 JSON·색인 매핑·쿼리, 검증 한도 초과와 부분 샤드 실패는 자동 복귀하지 않는다. MySQL 최신성 확인 단계에서 발생한 DB 오류도 검색엔진 미응답으로 취급하지 않는다. 복귀한 MySQL마저 실패하면 기존 의존 기능 오류로 반환한다.

한 요청에서 최대 한 번 복귀하며 다음 요청에서는 Elasticsearch를 다시 시도한다. 별도 circuit breaker/장애 유지 캐시는 아직 없다. 지속 장애 시 각 요청이 엔진 timeout을 기다릴 수 있으며, 요청 timeout은 현재 최대 10초/엔진 query timeout 5초다.

MySQL은 기존 LIKE/기술 태그 검색이므로 엔진의 동의어·본문 순위와 결과가 다를 수 있다. 새 synonym 변환을 복귀 시 임의로 추가하지 않는다. 교육의 모집 미확인/학습 참고용 표시는 기존 DB 판정을 그대로 유지한다.

복귀는 민감정보 없는 고정 이벤트 search_backend_fallback으로 로그에 남긴다. 채용 검색 응답은 search_backend(mysql/elasticsearch), search_degraded(true/false)를 포함한다. 교육 카드의 retrieval_basis는 mysql_fallback_elasticsearch_unavailable로 표시된다. 현재 프론트엔드에 별도 복귀 배너는 없다. 일반 채팅 응답 전체가 항상 이 메타데이터를 표시하는 것은 아니다.

검증: 엔진을 중단하지 않고 연결 실패를 주입해 실제 로컬 MySQL 채용 42건/교육 3개 카드 복귀, 다음 요청 실제 Elasticsearch 채용 42건 재연결 확인. 모델 호출·DB 쓰기 0. 정상 0건 비복귀·일반 오류 전달·교육 미확인 유지·오류 분류 회귀 테스트 포함 총 166개 중 환경 의존 7개 제외 통과.

코드 push는 AWS 배포가 아니다. 로컬 dev.py는 변경을 감지해 재시작하며 직접 실행 서버는 재시작해야 한다. AWS 운영은 별도 배포 전까지 기존 MySQL 구성이다.
