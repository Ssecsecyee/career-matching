---
type: verification
id: production-baseline
date: 2026-11-19
status: 부분 확인 — 운영 릴리스 ID·커밋은 모름(팀원 push 대기). GitHub 두 버전 비교는 [코드 확인]
owner: 황승현
responds_to: "EDU-CARE 서비스 신뢰성 검증 고도화 및 후속 실험 실행 보고서" §5 Preflight
---
# Preflight — 검증한 코드와 운영 서비스가 같은가

## 1. 결론
- **운영이 어느 코드인지는 아직 모른다.** [미검증]
  - 11/16 운영 기록에 있는 벡터 검색 코드가 GitHub 어디에도 없다. [코드 확인]
  - 팀원은 "어제 업데이트했다"고 답했지만, 그 변경은 아직 push되지 않았다(11/19 답변, [[questions-for-teammate]]).
- **조건 라벨(V3) 관련 파일 4개는 main과 브랜치 끝에서 같다.** [코드 확인]
  - 그래서 V3 실시간·V3-H·V3-T 결과와 패치는 두 GitHub 버전 모두에 적용된다.
  - 운영에서도 같은지는 모른다.
- **V6·V-E2E는 운영 화면에서 직접 쟀다.** [측정, 운영]
  - 다만 그때 운영이 어느 릴리스였는지는 모른다.
- 운영 코드를 받지 못하면, 운영 화면에서 잰 V6·V-E2E 말고는 모두 "GitHub 코드를 독립 환경에서 잰 결과"로만 보고한다(보고서 §5.3).

## 2. 버전 세 개
| 버전 | 커밋·날짜 | 확인 방법 |
|---|---|---|
| GitHub main | `83f4970` (2026-11-05) | 로컬 `career-matching` main과 같음 [코드 확인] |
| GitHub 브랜치 끝 `feature/copilot-workspace` | `bcc80a2` (2026-11-16) | 로컬 원격 참조로 확인. main보다 77커밋 앞섬 [코드 확인] |
| 운영 | 모름 | 11/16 배포 기록에 벡터 검색(공고 668건, 섹션 벡터 1,336개)이 있음. 그 코드는 GitHub에 없음 |

## 3. 검증이 의존하는 파일 — main 대 브랜치 끝 (11/19, 읽기 전용 `git diff`)
| 파일 | 쓰는 검증 | main ↔ bcc80a2 |
|---|---|---|
| `src/bedrock/question_reviewer.py` (실시간 라벨, `question_runtime_client` 15초·재시도 없음) | V3 실시간, V3-H, V3-T, 패치 | 같음 |
| `src/services/selected_condition_review.py` (서비스 방식 묶음·대체 경로) | V3 실시간 서비스 방식, 패치 | 같음 |
| `src/services/condition_display.py` (화면 라벨) | V3 화면 라벨 채점 | 같음 |
| `src/services/condition_structure.py` (조건 줄 분리) | 모든 조건 정답, V3·V4 | 같음 |
| `src/bedrock/condition_classifier.py`, `services/condition_review.py`, `schemas/condition_review.py` | V3·V4 배치 | 같음 |
| `src/bedrock/client.py` | V7 상담 답변 | **다름**: 상담 시스템 문구 앞에 서비스 캐릭터 소개 한 줄이 붙음 |
| `src/services/dialogue.py`, `context_router.py` | V7 상담 경로 | **다름** |
| `src/services/memory.py`, `consultation.py`, `intent_context.py` | V7 상담 경로 | 같음 |
| `src/schemas/intent.py` | V4b(안 함) | **다름**: `context-intent-v7` → `v8`, 검색어 칸 `text_query` 추가 |
| `src/repositories/elasticsearch_*`, `mysql_training.py`, `services/search_*` | V6(운영 화면으로 잼) | **다름** |

- 11/18 조사에서는 "V3 관련 파일 10개가 같다"고 적었다([[rule-log]] 11/18). 이번에는 평가 코드(`eval/bc_run.py`, `live_run.py`, `v7_questions.py`)가 실제로 불러오는 모듈을 기준으로 다시 확인했다.
- V3 실시간의 서비스 방식 묶음은 평가 코드가 `selected_condition_review.py`를 따라 다시 구현한 것이다. 그 원본 파일도 같다.

## 4. 검증별 적용 범위
| 검증 | 잰 대상 | 운영에도 해당하나 |
|---|---|---|
| V1 중복 공고 | 11/08 DB 스냅샷 1,154건 | 그 시점 데이터 기준. 11/16 운영 DB는 1,262건 |
| V3·V4 배치 | main 코드(브랜치 끝과 같은 파일), 독립 환경 | 운영 파일이 같으면 해당된다 [미검증] |
| V3 실시간 · V3-H · V3-T | main 코드(브랜치 끝과 같은 파일), 독립 환경 | 운영 파일이 같으면 해당된다 [미검증] |
| V7 · V7+ | main 코드, 독립 환경 | 브랜치에서 상담 문구·경로가 바뀌었다. 다시 재지 않았다 [미검증] |
| V6 · V-E2E | 운영 공개 체험 화면(11/19) | 해당 [측정]. 릴리스 ID 모름 |
| V8 회귀 | 저장된 실행 기록 | 해당 없음(평가 코드 자체) |

## 5. 보고서 §5.2 항목별 상태
| 항목 | 상태 |
|---|---|
| 운영 릴리스 ID · 커밋 해시 | 모름 — 팀원에게 요청 |
| GitHub에 없는 변경 | 있음: 벡터 검색, 11/18 업데이트(내용 모름) |
| Bedrock 모델 | 코드 기본값과 문서는 Claude Sonnet 4.6, 서울 리전 [코드 확인]. 운영 환경 변수 값은 [미검증] |
| 프롬프트 버전 | 코드: `selected-question-v1`, 캐시 키 `selected-question-v1:condition-review-v2`, 의도 v7(main)·v8(브랜치). 운영 값은 [미검증] |
| `question_reviewer.py`, `selected_condition_review.py`, `condition_display.py`, 조건 분리기 | main = 브랜치 끝 [코드 확인] |
| 캐시 키 | 프롬프트를 바꿔도 키가 v1로 남는 문제를 찾아 패치에서 v2로 올림 [코드 확인] |
| 검색 백엔드 · 벡터 검색 | 문서상 운영은 Elasticsearch. 벡터 검색이 사용자 검색 순위에 실제로 쓰이는지는 [미검증] |
| 기능 플래그 | 문서상 운영: `ENABLE_LIVE_BEDROCK` 켜짐, `ENABLE_ON_DEMAND_CONDITIONS` 켜짐(11/03부터), `ENABLE_AI_CONDITION_RANKING` 꺼짐. 현재 값은 [미검증] |

## 6. 닫는 방법
1. 팀원에게 받을 것: 운영 릴리스 ID, 그 릴리스의 커밋(또는 push), 위 플래그의 현재 값.
2. 받으면 §3 표의 파일을 운영 커밋과 다시 비교한다(읽기 전용, 무료).
3. 조건 라벨 파일이 다르면, 패치가 그대로 붙는지 `git apply --check`로 확인한다. 그 뒤 해당 측정을 다시 할지 사용자가 정한다(유료).
