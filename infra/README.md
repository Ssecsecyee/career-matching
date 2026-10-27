# AWS 배포와 사용량 확인

현재 상태: 배포 파일 작성 및 로컬 테스트 완료. AWS 로그인·리소스 생성·실제 배포·모델 호출은 이 작업에서 실행하지 않았다. 이전 합의대로 아래 명령은 사용자가 CMD에서 한 줄씩 실행한다.

## 구성과 비용

- 서울 ap-northeast-2, RDS MySQL 8.4 / db.t4g.micro / 20GB gp3 / Single-AZ.
- DB는 비공개. TLS 인증서와 서버 이름을 확인한다. 애플리케이션은 필요한 테이블 권한만 갖는 career_runtime 계정으로 연결한다.
- Python Lambda + HTTP API, React + 비공개 S3 + CloudFront OAC. API 캐시는 비활성화하고 Authorization/X-Client-Token을 전달한다.
- Sonnet만 사용. 세션당 12회 호출 제한과 소유권 검사를 유지한다. 질문/기억의 최대 출력은 1,024토큰이다.
- NAT는 만들지 않는다. Bedrock Runtime과 Secrets Manager 인터페이스 엔드포인트를 각각 두 AZ에 만들어 총 4개 ENI의 시간 요금이 발생한다. S3는 게이트웨이 엔드포인트를 이용한다.
- RDS, 스토리지, 인터페이스 엔드포인트, Secrets Manager, S3, CloudFront, API, Lambda, 로그, 대시보드 비용을 고려한다. 무료나 크레딧 범위 내임을 보장하지 않는다.
- 월 알림 금액과 수신 이메일은 plan 때 직접 정한다. 계정 전체 비용 80% 도달 이메일 알림이다. 실제 지출을 차단하는 상한이 아니며 반영에 지연이 있다.
- 데이터와 일부 상태 리소스는 Retain, DB는 삭제 보호를 적용했다. 스택 삭제만으로 모든 비용이 없어지지 않는다. 원본/DB/백업 삭제는 별도 승인과 확인 후 수행한다.
- 테스트용 공유 접속 코드 인증이다. 정식 서비스 공개 전 사용자 계정 인증·보존/삭제 정책·접근 제한과 운영 보안을 추가 검토한다.

## 1. 읽기 전용 사전 확인

```cmd
conda activate AWS_project
cd /d C:\AWS_project\career_matching
aws sso login --profile myisb_IsbUsersPS-954935267704
python infra\deploy.py preflight
```

preflight는 계정/리전, 실제 제공되는 MySQL 8.4 버전과 db.t4g.micro 조합, Sonnet 프로필 목록만 조회한다. 성공해도 리소스 생성 권한·실제 모델 호출 권한까지 검증한 것은 아니다. 권한 오류는 코드만 표시한다. 지역/조직 정책이 생성 작업을 제한할 수 있다.

## 2. 로컬 빌드와 템플릿 검증

```cmd
python infra\deploy.py build
```

이 명령은 Lambda용 Linux Python 3.11 의존성 설치, 공식 RDS CA 번들 다운로드, React 빌드와 로컬 압축만 수행한다. AWS 리소스는 만들지 않는다. pip/npm 네트워크 접근과 패키지 설치가 필요하다. 파일은 infra/.build/<시각>/에 보관하며 .gitignore에서 제외된다. .env·로컬 키·원본 데이터는 Lambda ZIP에 포함하지 않는다. DB 적재 SQL과 정제 JSON은 별도 비공개 S3 파일로 올린다.

템플릿은 generate_template.py에서 생성한다. cfn-lint/cfn-guard는 현재 환경에 없어 실행하지 못했다. 자동 구조·보안 설정 테스트는 통과했지만 CloudFormation 전체 스키마 검증과 보안 규칙 검사를 대체하지 않는다. 배포 전 검증 도구 설치가 허용되면 다음과 같이 로컬 스키마 검증을 수행한다.

```cmd
python -m pip install cfn-lint==1.57.2
python -m cfnlint infra\template.json --regions ap-northeast-2
```

공식 설치 안내: https://github.com/aws-cloudformation/cfn-lint / https://github.com/aws-cloudformation/cloudformation-guard . cfn-guard 검사와 계정별 사전 검증은 아직 미실행이다. 서비스 validate_template는 plan에서 수행한다. 이 검증만으로 실제 생성 성공을 보장하지 않는다.

## 3. 비용 검토 후 변경 계획 만들기

알림 기준 금액과 이메일을 결정한 뒤 실행한다. 아래 꺾쇠 값은 실제 값으로 바꾼다. 예산이 미정이면 여기서 멈추고 담당자에게 확인한다.

```cmd
python infra\deploy.py plan --bootstrap --monthly-budget-usd <알림기준_USD> --budget-email <수신이메일>
python infra\deploy.py review
```

plan은 배포용 비공개 S3 버킷을 만들고 빌드 파일을 업로드한다. 이 시점부터 S3 저장 비용이 생길 수 있다. 애플리케이션 리소스는 아직 만들지 않고 CloudFormation 변경 세트만 생성한다. review의 status가 CREATE_COMPLETE가 될 때까지 잠시 뒤 재확인한다. 생성/변경/교체 목록과 고정 비용 구성을 검토한다. 초기 설치는 --bootstrap이 필요하다.

## 4. 검토한 계획 적용

```cmd
python infra\deploy.py apply --confirm-costs
python infra\deploy.py status
```

apply는 유료 리소스 생성을 실제 시작한다. 반복 실행하지 않는다. status를 일정 간격으로 확인한다. RDS/CloudFront 생성은 시간이 걸린다. CREATE_COMPLETE 또는 UPDATE_COMPLETE가 된 뒤 다음으로 진행한다. 실패하면 CloudFormation 콘솔 Events의 실패 원인을 확인한다. 권한 부족 때 임의로 관리자 권한을 부여하지 않는다.

## 5. 스키마·데이터 적재와 웹 게시

```cmd
python infra\deploy.py initialize
python infra\deploy.py inspect
python infra\deploy.py publish
```

initialize는 HTTP에 연결되지 않은 IAM 전용 Lambda를 호출한다. 고정 S3 키와 SHA-256을 검증하고 기존 빈 스키마 + 데이터 upsert SQL을 적재한다. 기존 DB를 DROP/TRUNCATE하지 않는다. 정제 JSON과 SQL의 건수 일치를 빌드에서 확인한다. jobs가 예상 783건 이상인지 확인하고, 현재 자료가 최신 모집 상태를 검증한 데이터가 아님을 유지한다. 반복 적재도 upsert지만 실제 업데이트 전 원본 버전을 확인한다.

publish는 웹 파일을 비공개 웹 버킷으로 올리고 CloudFront를 무효화한다. 출력된 HTTPS 주소에서 테스트한다. /api/health는 기본 연결 확인이며 DB와 모델 정상까지 뜻하지 않는다.

status 출력의 AuthSecretArn을 AWS Secrets Manager 콘솔에서 열어 token 필드를 확인하고 웹 접속 코드에 입력한다. 이 코드는 새로 생성한 AWS 테스트용 값이며 로컬 CHAT_API_TOKEN과 다르다. 코드/비밀번호를 채팅이나 문서에 붙여넣지 않는다.

## 6. 사용하면서 확인

1. 웹에서 경험과 희망 직무를 입력한다.
2. 공고 선택 → 항목별 질문 → 충족/미충족/모름 → 최종 결과까지 확인한다.
3. 같은 대화에서 다시 검색하고 기억이 유지되는지 확인한다. 경험 수정 시 기존 답변이 다시 확인되는지 본다.
4. 다음 명령으로 실제 AWS DB 건수와 애플리케이션 모델 사용량을 확인한다.

```cmd
python infra\deploy.py inspect
```

inspect는 IAM 전용 함수로 공고·세션·대화·근거·호출·캐시 건수, 공고 상태별 건수, 모델별 성공/실패 호출 수와 입력/출력/캐시 토큰 합계를 반환한다. 개인 대화 내용이나 비밀번호를 출력하지 않는다. 이것은 애플리케이션 집계이며 청구 금액은 아니다. SDK 재시도와 응답 유실로 청구/기록이 다를 수 있다.

- S3 콘솔: `<스택명>-artifacts-<계정>-ap-northeast-2`의 releases/<시각>/에서 SQL gzip, 정제 JSON gzip, 스키마와 ZIP 확인. status의 WebBucket은 React 빌드 보관용이며 별도 버킷이다.
- RDS 콘솔: status의 DbIdentifier로 상태·연결·스토리지·CPU 등을 확인. 테이블 건수와 대화 저장은 inspect로 확인. 비공개 DB이므로 현재 로컬 DBeaver에서 주소만 입력해 직접 연결되지는 않는다. 필요 시 별도로 승인된 터널을 구성한다.
- CloudWatch 콘솔: DashboardName과 ApiFunction 로그에서 호출/오류/지연을 확인. Bedrock 메트릭은 모델·소스 리전에 따라 차원이 다르므로 비어 있으면 Bedrock namespace에서 ModelId를 선택한다. 토큰 확인의 1차 자료는 inspect의 model_usage다.
- Billing/Cost Explorer: Bedrock/모델 공급자, RDS, VPC 엔드포인트, S3 등 비용을 서비스별 확인. 청구 반영에는 지연이 있을 수 있다. 잔여 크레딧은 Billing의 크레딧 화면과 담당자에게 확인한다.

## 7. 초기 적재 권한 제거

적재 성공과 웹 동작을 확인한 뒤 같은 빌드로 새 plan을 만들되 --bootstrap을 빼고 review/apply한다.

```cmd
python infra\deploy.py plan --monthly-budget-usd <동일한_알림기준_USD> --budget-email <동일한_수신이메일>
python infra\deploy.py review
python infra\deploy.py apply --confirm-costs
```

초기 적재 Lambda와 관리자 비밀 조회 역할을 제거하고 앱/DB는 유지한다. 이후 단순 화면/질문 코드 변경은 build → plan(bootstrap 없음) → review → apply → publish 순서다. 데이터 추가 적재는 별도 검토하여 제한된 적재 작업을 준비한다. 기존 DB 사용자 비밀번호 회전도 별도 절차이며 런타임 비밀 값만 임의로 바꾸면 연결이 끊긴다.

## 다음 대화에 넘길 상태

- 로컬 검색·대화 기억·원문 항목별 질문·MySQL 기록과 Sonnet 호출은 사용자가 실행하며 확인한 상태다. 교육 추천·Elasticsearch·실시간 수집은 미구현이다.
- AWS 코드는 infra/generate_template.py, template.json, deploy.py와 backend의 cloud/bootstrap/aws_secrets에 있다. 로컬 .env는 변경하거나 업로드하지 않는다.
- 배포 단계별 상태는 infra/.build/latest.json, deployment.json에 저장한다. 비밀값은 없지만 계정/리소스 ID가 있으므로 공개 커밋하지 않는다.
- 현재 AWS 실제 생성/연결/모델 호출은 미검증이다. 사용자가 preflight부터 실행하여 권한과 비용 기준을 확인해야 한다.
- 기존 세션 보존은 24시간 설정이다. 만료 데이터 정리는 기존 cleanup_chat.py의 별도 실행/스케줄이 필요하다. 운영 전 정책을 확정한다.
- HTTP API 최대 시간 때문에 AWS의 모델 읽기 제한은 18초·SDK 1회 시도로 조정했다. 장시간 응답이 많으면 비동기 작업+상태 조회 또는 별도 스트리밍 설계를 적용한다. 로컬 설정은 기존 40초/2회다.


## 현재 우선 실행 경로 변경

전체 구성의 월 고정비를 검토한 뒤 웹 주소부터 확보한다. 우선 [HOSTING.md](HOSTING.md)의 hosting.py를 사용한다. 전체 배포 deploy.py apply는 비용 구성 재검토 전 실행하지 않는다. 호스팅 단계에서는 RDS/Elasticsearch/엔드포인트를 생성하지 않는다.


## 현재 백엔드 실행 경로 보완

웹 호스팅 완료 후 저비용 백엔드 연결을 준비했다. 현재 우선안은 서울 t4g.small 단일 서버의 MySQL+Python 작업 코드와 Lambda/HTTP API/SQS/임시 DynamoDB 작업 상태이며 RDS/유료 VPC 엔드포인트는 사용하지 않는다. Elasticsearch는 아직 미포함이다. 기존 전체 배포 대신 infra/BACKEND.md의 backend.py를 따른다. 단일 서버/수동 운영의 한계가 있으며 월 6만 원은 목표이지 비용 상한 보장이 아니다. 실제 서버·DB·Bedrock 연결은 사용자 실행 후 검증해야 한다.
