# 검색 품질 비교 실험

## 2026-10-30 성능 검증 지표 추가 계획

아래 783건·18개 구조화 질의 실험은 과거 탐색 자료다. 후속 지표에는 검색과 대화·근거·운영 측정을 구분하고 새 스냅샷 baseline을 기록한다. 기존 실험만으로 최신 Nori 운영 검색·대화 기억·근거 저장·동시 사용자 성능을 검증한 것으로 취급하지 않는다.

정의·분모·측정 구간·산출물·통과 기준은 [성능 검증 지표 계획](PERFORMANCE_EVALUATION_PLAN.md)을 따른다. 문서 추가 단계이며 평가기 구현·새 성능 측정·부하 실행은 하지 않았다.


## 목적과 범위

동의어 정규화의 효과와 Elasticsearch 검색 방식의 효과를 분리해 검증한다. 운영 검색 교체나 AWS 배포는 하지 않는다. 로컬에 저장된 783건 스냅샷을 사용하며, 현재 운영 DB의 최신 데이터 전체를 평가하는 실험은 아니다.

## 비교군

| 비교군 | 처리 |
|---|---|
| sql_current | 실제 MySQLJobRepository의 SQL과 필터 사용 |
| sql_aliases | 같은 SQL에 고정된 기술명 동의어 적용 |
| elasticsearch | 같은 동의어와 필터, cross_fields AND 검색과 BM25 순위 |

18개 고정 검색 계획을 사용한다. React 대소문자·한국어·별칭, Python·MySQL·Postgres, 서울 지역, 복수 기술 AND, 직무 복합 표현, 없는 기술을 포함한다. Bedrock의 자연어 의도 분류는 우회한다. 따라서 이 결과로 LLM 파싱이나 대화 기억이 개선됐다고 해석하지 않는다. 현재 서비스의 자연어 정규화 전체를 재현한 평가도 아니다.

## 실행

프로젝트 최상단 CMD에서 실행한다. Docker Desktop과 프로젝트 Python 환경의 pymysql이 필요하다. Elasticsearch 공식 9.5.5 이미지가 없으면 최초 내려받기에 시간이 걸린다.

```cmd
python app\backend\experiments\search_quality.py
```

실험은 별도 MySQL 컨테이너와 Elasticsearch 컨테이너를 만든다. 로컬 19208·19200 포트만 사용하며, 운영 .env나 AWS 자격 증명을 읽지 않는다. 포트 충돌 시 기존 서비스를 중단하지 말고 실험 포트를 변경한다. 기존 MySQL 컨테이너와 볼륨은 사용하지 않는다. 종료 시 이 실험이 만든 컨테이너만 제거한다. 비정상 강제 종료 시 이름이 career-search-eval-로 시작하는 해당 실행의 컨테이너를 확인한다.

Elasticsearch 인증 비활성화는 루프백에만 노출되는 공개 스냅샷의 임시 실험 설정이다. 운영 설정으로 사용하지 않는다. 다운로드한 이미지는 재실험을 위해 남는다.

## 산출물과 평가

`workspace/search-eval/<UTC 실행시각>/`에 manifest.json, results.json, REPORT.md, judgments.csv를 저장한다. 이 폴더는 Git에서 제외된다. 매니페스트에 원본 SHA-256·검색 조건·별칭·버전·기준 시각을 기록한다.

1. REPORT.md에서 결과 건수와 검색 누락 차이를 확인한다. 증가한 건수를 품질 향상으로 단정하지 않는다.
2. judgments.csv는 비교군·점수를 숨기고 결과 합집합을 섞은 평가 목록이다. 각 query_id의 검색 의도와 원문을 보고 0=무관, 1=약한 관련, 2=관련, 3=매우 적합으로 전부 평가한다. 기술 태그는 관련성 근거 일부이며 신입 적합성을 보장하지 않는다.
3. 입력 후 아래 명령으로 P@5, nDCG@5, reciprocal rank@5를 계산한다. 빈 등급이 있으면 계산을 거부한다.

```cmd
python app\backend\experiments\score_search_quality.py workspace\search-eval\실행폴더
```

관련 판정은 2점 이상이다. 전체 DB 정답을 모두 판정하지 않았으므로 전역 Recall은 계산하지 않는다. 정답이 없는 질의의 nDCG는 미정으로 남긴다. 동일 평가자 기준을 유지하고 가능하면 두 사람이 독립 판정한 뒤 불일치를 합의한다.

## 해석 제한과 다음 단계

Elasticsearch는 standard 분석기를 사용한다. 한국어 형태소 Nori·오타 허용·임베딩 검색은 아직 적용하지 않는다. SQL은 최신순, Elasticsearch는 BM25 다음 source_id순이다. 이 실험은 순위 변경도 포함한 방식 비교이며 토큰화 하나의 인과 효과만 측정하지 않는다.

마감·모집 상태는 저장된 스냅샷 기준이다. unknown을 포함하며 현재 채용 중이라는 증거가 아니다. SQL은 조회 시각, Elasticsearch는 색인 시각에 마감 필터를 적용하므로 경계 시각을 지나는 데이터가 있으면 재검토해야 한다.

지연 시간은 준비 호출 이후 5회 단일 클라이언트 측정이며 고정 비교군 순서다. 운영 성능이나 동시 접속 처리량의 근거로 사용하지 않는다. 초기 탐색용 질문에 맞춰 튜닝한 뒤에는 별도 미사용 질문 세트로 재평가한다. 사람이 판정한 관련성 점수와 필터 정확도를 확인한 뒤 도입을 결정한다.

설정 근거: [Elastic multi_match 문서](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-multi-match-query), [BM25 기본 유사도](https://www.elastic.co/docs/reference/elasticsearch/index-settings/similarity).
