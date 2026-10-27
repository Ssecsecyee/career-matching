# 저비용 백엔드: 현재 실행 경로

현재 웹 주소: https://d1elpjlek4sj83.cloudfront.net . 기존 호스팅 스택 career-matching-web은 유지한다. 예전 전체 RDS 배포 deploy.py apply는 사용하지 않는다.

## 구성

CloudFront → HTTPS HTTP API/Lambda → SQS 대기열 → EC2 작업 서버 → MySQL/Bedrock. Lambda는 모델을 기다리지 않고 요청 번호를 반환하며 화면은 같은 출처의 /api/jobs/<번호>를 조회한다. 다른 사용자의 결과를 읽지 못하도록 토큰 소유권을 검사한다. 대기열 중복 전달은 기존 MySQL 요청 잠금/응답 재사용으로 처리한다.

- 서울, Amazon Linux 2023 ARM, t4g.small 2GB 한 대. MySQL 8.4 Docker와 Python 작업 코드를 함께 운영한다. Elasticsearch는 아직 넣지 않았다. 추가 시 메모리/사양/비용을 재검토한다.
- 30GB 암호화 gp3 디스크에 MySQL 데이터를 저장한다. 컨테이너 삭제가 곧 DB 삭제가 되지 않도록 호스트 디렉터리를 사용한다. DB 서버와 디스크는 자동 삭제하지 않는다.
- 외부에서 서버로 들어오는 포트는 없다. MySQL은 서버 내부 127.0.0.1:3308에만 공개한다. 역할 자격증명·SSM을 사용하며 SSH 키/22번 포트를 만들지 않는다. 공인 IPv4는 외부 AWS API와 패키지 다운로드를 위한 송신 경로에 필요하다.
- RDS, NAT, 유료 인터페이스 VPC 엔드포인트는 만들지 않는다. 고정비는 EC2·EBS·공인 IPv4·비밀정보 저장소가 중심이다. Lambda/API/SQS/임시 DynamoDB 작업/S3/Bedrock 등은 사용량 비용이 더해진다. 월 6만 원은 목표이며 사용량·환율·세금·크레딧에 따라 달라진다. 무료나 상한을 보장하지 않는다.
- DynamoDB는 임시 작업 상태/결과만 저장하며 24시간 TTL과 논리 만료 검사를 적용한다. 원래 공고·대화·기억·근거·호출 기록의 기준 DB는 MySQL이다. 임시 TTL 삭제는 즉시 실행이 아닐 수 있다.
- Sonnet만 사용하고 세션당 12회 호출 제한을 유지한다. 서버의 CPU 크레딧 모드는 standard로 설정해 surplus CPU 과금을 피한다. 사용이 많으면 성능이 제한될 수 있다.
- 단일 서버 장애 시 서비스가 중단될 수 있는 팀 테스트 구성이다. 자동 DB 백업/복구 훈련/사용자 계정 인증/장기 운영 보안은 운영 전 추가해야 한다. 종료·교체 전 DB 백업이 필요하며 Retain만으로 장애 복구나 백업이 보장되지는 않는다.

## 1. 읽기 전용 사전 확인

CMD에서 한 줄씩:

```cmd
conda activate AWS_project
cd /d C:\AWS_project\career_matching
python infra\backend.py preflight
```

계정/서버 사양 제공 여부/공식 AMI만 조회한다. 생성 권한·실제 모델 호출·서버 초기화 성공까지 보장하지 않는다. SSO 만료 시 기존 프로필로 aws sso login을 먼저 한다. 이 단계는 서버를 생성하지 않는다.

## 2. 로컬 패키지와 검증

```cmd
python infra\backend.py build
```

AWS 업로드 없이 api.zip, worker.zip과 템플릿을 infra/.build/backend-<시각>/에 생성한다. 공고 783건의 기존 SQL을 포함하며 스키마와 정제 JSON의 수를 대조한다. .env, SSO 키, 로컬 DB 비밀번호는 포함하지 않는다. worker.zip은 비공개 배포 버킷에만 보관하며 공개 웹 버킷에는 올리지 않는다.

출력된 폴더의 template.json을 cfn-lint로 확인한다. 다음 경로는 실제 build 출력 폴더로 바꾼다.

```cmd
cfn-lint "infra\.build\backend-<시각>\template.json" --regions ap-northeast-2
```

로컬 구성 검사·보안 설정 단위 테스트는 완료했다. cfn-guard 보안 규칙 검사는 미실행이며 실제 계정 내 생성과 Linux 초기화는 사용자 배포 후 검증한다.

## 3. 계획 검토 후 서버 생성

```cmd
python infra\backend.py plan
python infra\backend.py review
```

plan은 비공개 배포 S3 버킷을 만들고 패키지를 업로드한 뒤 변경 세트만 생성한다. 아직 EC2 등 백엔드 리소스는 생성하지 않는다. S3 저장 비용은 이 단계부터 생길 수 있다. review에서 CREATE_COMPLETE와 추가될 리소스를 확인한다. RDS/NAT/VPC 엔드포인트/Elasticsearch가 없고 EC2 한 대만 있는지 확인한다.

```cmd
python infra\backend.py apply --confirm-costs
python infra\backend.py status
```

apply가 실제 유료 자원 생성을 시작한다. 반복하지 않는다. CREATE_COMPLETE가 되어도 Linux의 Docker/DB 초기화는 아직 진행 중일 수 있다. 시스템 관리와 대기열/API 권한이 교육 계정에서 막히면 관리자 권한을 임의로 추가하지 않고 오류를 확인한다. Retain 설정 때문에 롤백/스택 삭제 후 서버·디스크·비밀정보 등이 남아 비용이 계속 발생할 수 있다.

## 4. 서버와 DB 준비 확인

```cmd
python infra\backend.py inspect
python infra\backend.py inspect-result
```

inspect는 고정된 SSM 점검 명령만 전송한다. inspect-result에서 Success, active, MySQL 공고 783건 이상 및 집계 JSON을 확인한다. 접속 코드나 비밀번호를 출력하지 않는다. 서버가 SSM에 등록되지 않았거나 초기화가 진행 중이면 기다린 뒤 다시 점검한다. 실패 시 AWS EC2/SSM 콘솔에서 원인을 확인하며 cloud-init 로그 전체에는 설치 정보가 있으므로 무분별하게 채팅에 공유하지 않는다.

후속 대화의 실제 모델 호출 뒤에도 이 명령으로 세션/대화/근거/캐시 건수와 모델별 입력·출력·캐시 토큰을 확인한다. 청구 금액·크레딧 잔액은 Billing/Cost Explorer에서 별도로 확인한다.

## 5. 기존 웹 주소에 API 연결

backend.py status가 출력한 ApiEndpoint 값을 사용한다. 아래 예시 주소를 실제 출력으로 바꾼다. HTTPS 서울 HTTP API 주소만 허용한다.

```cmd
python infra\hosting.py plan --api-origin https://<실제_API_ID>.execute-api.ap-northeast-2.amazonaws.com
python infra\hosting.py review
python infra\hosting.py apply
python infra\hosting.py status
```

이번에는 기존 CloudFront 배포를 갱신해 /api/*만 API Gateway로 보낸다. API 응답 캐시는 끄고 Authorization과 X-Client-Token을 전달한다. UPDATE_COMPLETE 이후:

```cmd
python infra\hosting.py publish
```

기존 웹 주소가 유지되며 backend_connected=true를 출력한다. publish는 API 경로 변경이 실제 적용됐는지 먼저 확인한다. 서버 준비 확인 없이 화면 연결을 먼저 활성화하지 않는다. 이후 hosting.py plan에서 api-origin을 생략해도 저장된 API 연결을 유지한다.

## 6. 사용자 테스트

Secrets Manager 콘솔에서 backend.py status의 AuthSecretArn을 열어 token 필드를 확인한다. 이 값을 웹의 접속 코드에만 입력한다. 로컬 접속 코드와 다르다. 비밀값을 채팅·문서·Git에 붙이지 않는다.

1. 경험과 희망 직무를 자연어로 입력 → 후보 공고 선택.
2. 조건을 항목별로 확인. 모름은 미확인으로 남는지 본다.
3. 같은 대화에서 재검색하고 기억 유지·동일 조건 질문 생략·경험 정정을 확인.
4. inspect/inspect-result로 실제 MySQL 저장과 Bedrock 토큰 집계 확인.
5. SQS DeadLetters에 메시지가 쌓이면 서버/권한 오류를 점검한다. 큐에 대기한 요청은 새로고침 후에도 실행될 수 있으므로 중복으로 새 요청을 반복하지 않는다.

현재 화면은 최대 약 2분간 상태를 확인한다. 늦어지면 동일 요청 ID로 재확인하고 새 모델 호출을 임의로 추가하지 않는다. 별도 스트리밍과 교육 추천은 미구현이다.

## 유지보수와 데이터 보호

- infra/.build/backend-state.json과 backend-build.json에 진행 상태와 비밀이 아닌 리소스 ID를 저장한다.
- 이미 생성한 서버를 backend.py plan/apply로 무심코 교체하지 못하도록 새 서버 계획을 차단한다. 앱/모델 프롬프트 수정은 서버 코드의 안전한 갱신과 Lambda 패키지 업데이트 절차를 별도로 준비한다. DB 백업 없이 서버를 교체하지 않는다.
- 원래 로컬 MySQL 컨테이너/볼륨과 이전 실험 자료는 건드리지 않았다. AWS에는 공고 SQL 스냅샷만 처음 적재하며 로컬 테스트의 개인정보성 대화 기록은 이전하지 않는다.
- 24시간 만료된 MySQL 기록의 실제 삭제 스케줄은 별도 구현/운영이 필요하다. DynamoDB 작업 TTL과 혼동하지 않는다.
- 운영 전에는 DB 백업·복구/패치/디스크 모니터링/공유 토큰 대체 인증/월 사용량 제한을 추가한다. 비용 상한 자동 차단은 구현하지 않았다.


## SQS 정책 실패 복구 준비

최초 배포의 QueuePolicy가 두 ARN을 한 문장에 사용해 SQS가 거부했다. WorkQueuePolicy/DeadLettersPolicy로 분리해 각각 자기 큐 ARN 하나만 가리키도록 수정했다. TLS 차단 정책은 유지한다. ROLLBACK_COMPLETE 스택은 단순 apply로 재시도하지 않는다. `python infra/backend.py resources`로 DELETE_SKIPPED 등 보존 리소스와 실제 서버 유무를 먼저 확인한 뒤 재배포/정리 방식을 정한다. 조회만 수행하며 기존 스택이나 서버를 삭제하지 않는다. 외부 아티팩트 버킷은 CloudFormation 리소스 목록에 포함되지 않는다.


### 실패 스택 목록 확인 후 재시도

실패 스택의 EC2 Worker는 목록에 없고 비밀정보 2개, Jobs 테이블, VPC/Subnet/보안 그룹은 DELETE_SKIPPED로 남았다. 목록은 infra/.build/failed-backend-retained-resources.json에 기록했다. 삭제는 수행하지 않았다. 수정 정책으로 다른 스택 career-backend-test-v2에 plan을 만든다. plan 성공 후 기본 스택은 저장된 v2를 자동 사용하며 이전 상태 파일은 별도로 보관한다.

```cmd
python infra\backend.py plan --stack career-backend-test-v2
python infra\backend.py review
```

review 검토 후 apply --confirm-costs, status, inspect 순서다. 실패 스택은 ROLLBACK_COMPLETE이므로 같은 apply로 재실행하지 않는다. 기존 보존 리소스의 비용/정리는 복구 이후 별도로 확인한다. 옛 스택 목록은 `python infra/backend.py resources --stack career-backend-test`로 조회할 수 있다. 기존 CloudFront 호스팅은 변경하지 않는다.
