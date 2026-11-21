# EDU-CARE 검증 자료 (황승현)

서비스 코드는 한 줄도 바꾸지 않고, 워크플로의 검증 지점을 같은 모델·같은 데이터로 재본 결과입니다.
원본 작업 저장소: `Sean9201/AWS_career_project` (브랜치 `verification-holdout-20261119`, 커밋 `e35da3b`)에서 복사했습니다.

## 폴더
| 경로 | 내용 |
|---|---|
| `docs/eval/` | 검증 계획·결과·판단 기록. 먼저 읽을 것: `final-verification-report.md`, `verification-system-assessment.md` |
| `docs/eval/v3v4-results.md`, `b-vs-c-prompt-diff.md` | 기술 조건 추출: 기존 프롬프트(B) 대 개선 규칙(C), 원래 검사 코드 통과 7/20 → 17/20 |
| `docs/eval/v6-results.md` | 교육 추천(운영 화면): 보여 준 과정 32/32 관련, 관련 과정이 나온 질의 11/20, 놓친 원인(한·영 표기 등) |
| `eval/` | 평가 스크립트, 사람이 만든 정답(라벨), 개선 규칙 프롬프트(`eval/prompts/c_rules.md`) |
| `docs/slides/` | 발표용 슬라이드 이미지(PNG)와 원본 HTML, 비용 그래프 PPTX |

## 주의
- 공고 원문 등 실제 수집 데이터(`data/real/`)는 포함하지 않았습니다. 그래서 `eval/` 스크립트는 이 폴더만으로는 다시 돌아가지 않습니다.
- 정답 파일(`eval/gold.*.json`)에는 원문 대신 위치(span)와 라벨만 있습니다.
- 수치는 공고 20건·질의 20개 규모의 1회 실행 결과입니다. 한계는 각 결과 문서의 "한계" 절에 적어 두었습니다.
