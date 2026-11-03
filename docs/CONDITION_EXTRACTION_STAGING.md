# 조건 추출 대기와 검증 후 색인

상태: 대기·검토·승인·ES 반영 AWS 표본 완료 / 대량 추출·독립 평가 미완료
기준일: 2026-11-03

## 저장 경계

원문은 job_postings에 유지한다. job_condition_review_drafts는 모델의 추출·분류 후보와 당시 원문 스냅샷, 조건 해시, 후보 해시, 모델 사용량을 보관한다. 후보 삽입은 search_outbox를 만들지 않는다. job_condition_reviews는 검증 후 검색·질문에 사용할 승인 결과 영역이다. 기존 ES 소비자는 승인 결과만 읽고 대기 테이블은 읽지 않는다.

흐름: 원문 → Bedrock → 형식·ID·인용 검사 → draft pending → 원문 전체·세부 항목·AND/OR·라벨 검토 → verified → 승인 결과+Outbox 원자 저장 → published → 기존 소비자 → ES.

## 검증과 승인 계약

자동 검사는 원문 연결·조건 ID 누락/중복·원문 인용·후보 해시를 확인한다. 의미 완전성은 자동 보장하지 않는다. 별도 검토자가 조건마다 source_complete, logic_preserved, label_confirmed와 검토 설명을 작성해야 한다. 후보 해시가 다르거나 한 조건이라도 미검토이면 승인을 거부한다. 이 확인 파일을 모델이 자동으로 true로 채우는 방식은 검증으로 인정하지 않는다.

검토자가 작성한 승인 manifest로 condition_draft_actions.py verify를 실행하고 publish를 별도 실행한다. publish는 최신 DB 조건 해시를 다시 확인하고 기존 승인 결과/Outbox 트랜잭션을 사용한다. 이벤트 저장 후 대기 상태 갱신 전에 중단되더라도 승인 결과 재사용으로 재발행을 막는다. publish는 이벤트 발행 완료이며 ES 소비 성공은 별도로 확인한다.

현재 추출 계정은 대기 테이블 SELECT·INSERT만 허용한다. 승인용 UPDATE 권한은 추가하지 않았다. 운영 검토·발행 도구는 별도 승인 운영 계정으로 실행해야 한다. 대기 결과가 사용자 질문이나 검색에 바로 노출되면 안 된다.

## 실행 도구

- classify_job_conditions.py --live --stage --output 새경로: 실제 호출 후 대기 적재. 기존 --apply 직접 발행은 차단했다.
- condition_draft_actions.py inspect --draft-id ID --output 새경로: 원문·후보·상태를 파일로 확인.
- condition_draft_actions.py verify --draft-id ID --approval 검토파일 --output 새경로: 항목별 검토 기록 저장.
- condition_draft_actions.py publish --draft-id ID --output 새경로: 검증된 결과만 승인 영역과 이벤트에 기록.

live 호출은 별도 opt-in이 필요하며 호스트 설정은 여전히 live_calls_allowed=false다. 배포 묶음에는 새 도구와 마이그레이션을 포함한다. 현재 기존 AWS 추출 도구 release에 새 대기 모듈/CLI를 연결했다. 대화 작업자와 소비자의 실행 경로는 이번 변경에서 바꾸지 않았다.

## 현재 AWS 결과

과거 v1 후보 draft 1·2는 pending으로 유지했다. v2에서 원문 대조·보정한 3건은 draft 3·4·5로 새 저장하고 승인 review 1·2·3과 이벤트를 발행했다. 원문 32개 중 노출 가능한 22개는 ES에서 대조했고, 마감 공고 1건의 10개는 이력만 보존하고 ES에서 제외했다. 마감 여부는 SQL로 사전 판단하며 이후 새 실제 모델 대상에서 제외한다.

현재는 별도 승인 계정과 보호 설정을 추가해 검토·발행을 지원한다. 추출 전용 계정에 대기 UPDATE 권한은 추가하지 않았다. 사용자 질문 선정·검색 순위 보강은 비활성이다. 실제 검증·보정·사용량과 한계는 [v2 결과](AI_CONDITION_V2_VERIFICATION_20261103.md)를 따른다.
