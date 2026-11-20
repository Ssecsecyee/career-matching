# 역량평가 이후 추천·우대조건 재개 오류 · 2026-11-20

## 운영에서 확인한 사실
- 오늘 10:11 KST의 두 요청(c15d7342, 6c98dc2b)은 intent_classification의 ModelOutputFormatError로 실패했다.
- 사용자 승인 후 해당 두 원본 모델 출력만 확인했다. 둘 다 action=assessment_control, control=preferred였으나 target=jobs를 반환했다. 계약은 target=selected를 요구해 거부됐다. JSON 코드 블록 자체가 원인은 아니다.
- 원본 대화·모델 문장을 문서나 Git에 복제하지 않는다.

## 코드에서 재현한 문제와 수정
1. 평가 체크포인트의 다른 공고 버튼이 next_results로 연결돼 기존 검색 페이지를 넘겼다. 별도 recommend_jobs 버튼 제어를 추가해 충족 답변 기반 새 검색을 요청한다. 목록 스크롤용 next_results는 유지한다.
2. 역량 기반 검색도 execute_search에서 selected/checks/conditions를 초기화했다. assessment 기반 검색에 한해 선택 공고·질문·답변·조건 검토를 보존하고 새 공고 선택 시 기존 선택 절차로 전환한다.
3. assessment_control의 jobs 대상은 selected로 정규화한다. 해당 행동에만 적용하며 잘못된 control·미지원 대상·추가 필드 검증은 유지한다. 선택 공고가 없으면 기존 확인 안내를 사용한다.
4. 모델 지침에 문답 기반 새 검색과 단순 다음 페이지의 차이, 상담 후 preferred의 selected 계약을 명시했다. 계약 버전 context-intent-v10.

## 검증과 한계
- 충족 답변 기반 검색·선택 공고 제외·답변 보존, 미확인 답변으로 역량 생성 금지, 상담 이후 우대조건 문답 재개, 운영 실패와 같은 코드블록 JSON의 모델 경계 파싱 회귀 테스트를 추가했다.
- 프런트엔드 84개 통과 및 빌드 성공.
- 백엔드 전체 561개 실행: 528개 통과, 31개 건너뜀, 2개 환경 오류(pymysql/boto3 미설치). 기능 assertion 실패는 없다.
- 실제 Bedrock 유료 재호출·운영 상태 변경·배포는 하지 않았다. 실제 모델의 검색 계획 품질은 후속 운영 검증이 필요하다.

## 운영 반영 완료
- 누락 패키지는 별도 로컬 test-deps에 설치했다. 백엔드 재검증: 561개 실행, 530개 통과·31개 조건부 건너뜀, 오류 없음.
- 코드 릴리스 20261120T013028Z로 기존 Lambda 검증기와 EC2 worker를 갱신했다. DB 변경 0, worker active.
- 이번 수정과 무관한 미커밋 search_repair.py 변경은 릴리스 ZIP에서 제외해 기존 HEAD 버전을 유지했다.
- 운영 서버의 배포 코드로 상담 후 우대조건 재개·역량 기반 검색/답변 보존을 모의 검증했다. DB 쓰기·실제 모델 호출 0.
- 프런트엔드 index-BF10CxYh.js 배포 및 공개 HTML/JS 해시 일치 확인. 운영 deploy-config.json 보존.
- CloudFront 무효화 ID5DEZ7DW3ZM6V0OI0KPY6WPE Completed.
- 실제 Bedrock 출력의 품질과 사용자 경험은 별도 실사용 확인 대상이다.
