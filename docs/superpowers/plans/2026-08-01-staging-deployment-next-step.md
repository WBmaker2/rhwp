# Staging Deployment Task 5 재개 계획

**작성일:** 2026-08-01
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`
**선행 성공 run:** [staging infrastructure apply #18](https://github.com/WBmaker2/rhwp/actions/runs/30692137720)
**대상 프로젝트:** `rhwp-collaboration-staging-001`

## 목적

성공한 infrastructure apply 뒤에 staging MVP를 배포할 수 있도록, 배포 전 live preflight와
immutable image/deployment approval 경계를 준비한다. 이 문서는 설계·검토 단계이며, cloud
resource mutation, image build/push, Cloud Run/Firebase deployment를 승인하지 않는다.

## 현재 사실

- Task 4 apply run #18은 `success`와 `apply-complete`였다.
- 승인된 infrastructure record는 `deploymentApproved=false`다.
- 저장소에는 build/push/deploy 전용 workflow가 없다.
- `deploy/staging/staging-manifest.json`은 source template이며 image digest, Firebase app ID,
  project number, worker URL, rollback revision에 placeholder가 있다.
- GitHub Environment `staging-preflight`는 사용자 승인 후 생성되었다.
- 로컬 service tests는 dependency 설치 후 collaboration-server 23개, document-api 39개,
  document-worker 22개, e2e 3개가 통과했다.
- release-derived fields를 exact schema로 검증하는 `scripts/staging_deployment_manifest.py`와 회귀
  테스트를 추가했다. source commit, Artifact Registry 경로, image digest, task URL, rollback ID가
  모두 결합되지 않으면 최종 deployment manifest를 만들지 않는다.
- 최초 Cloud Run 배포 전 rollback revision이 없을 수 있는 계약 충돌은
  `deploymentStage=initial`과 `[null, null, null]`을 명시하는 로컬 계약으로 보정한다. 실제
  교체 배포(`upgrade`)에서는 여전히 concrete revision 세 개를 요구한다.

## 제안 구현 diff

### 1. `staging-preflight` 보호 Environment 준비

`Staging configuration`의 deployment live preflight를 실행하기 전에 다음 설정을 준비한다.

| 항목 | 제안 값 |
|---|---|
| Environment | `staging-preflight` |
| Required reviewers | 최소 1명 |
| Branch restriction | `feat/firebase-collaboration-mvp-v1`만 허용 |
| Environment secrets | `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_PREFLIGHT_SERVICE_ACCOUNT` |
| Environment variables | 실제 운영 값 9개를 직접 복사하지 않고, 승인된 materializer 입력으로만 사용 |
| `id-token: write` | live read-only job에만 허용 |
| Cloud mutation | workflow에 없음 |

Environment 보호 규칙은 적용되었고, 승인된 normalized readiness에서 파생한 9개 비밀 아닌
Environment Variable을 등록·read-back 검증했다. WIF read-only secret은 아직 등록하지 않았다.
secret 원문은 파일·로그·Markdown에 남기지 않는다.

### 2. live preflight 입력 materialization

live job은 repository template을 직접 조회하지 않고 보호 Environment의 승인된 9개 변수로
`staging_bootstrap_materializer.py --from-environment`를 실행해 임시 manifest를 만든다. 이 임시
manifest는 ignored workspace와 artifact에만 저장하고, raw secret/API key는 포함하지 않는다.
workflow dispatch는 `release_metadata_path`를 별도로 받으며, 해당 파일이 없으면 WIF 인증 전에
중단한다.

그 뒤 아래 순서로 read-only 검증한다.

1. bootstrap Environment 값 materialization
2. source-commit-bound release metadata 검증과 최종 manifest materialization
3. static preflight
4. WIF read-only authentication
5. `staging_preflight.py --live`
6. `staging_approval_packet.py --phase deployment`
7. preflight report와 deployment packet artifact 업로드

live packet status가 `ready-for-deployment-approval`이 아니면 다음 단계로 진행하지 않는다.

Bootstrap materializer만으로는 deployment packet을 만들 수 없다. image digest와 rollback revision은
build/release evidence에서 와야 하며, 그 evidence가 없으면 `staging_deployment_manifest.py`가
fail-closed로 종료한다. 따라서 build/push는 deployment approval 뒤가 아니라 별도 release-candidate
승인 경계에서 먼저 immutable evidence를 생성해야 한다. 그 source-commit-bound metadata를 live
preflight가 검증한 뒤에야 deployment packet이 생성된다.

### 3. 별도 deployment approval record

live packet exact-byte SHA-256, image digest, IAM diff, rollback revision, acceptance evidence를
사람이 검토한 뒤에만 `docs/approvals/staging-deployment-approval-record.example.json` 계약으로
별도 record를 만든다. 기존 infrastructure approval record를 재사용하지 않는다.

필수 불변 결합:

- packet exact-byte SHA-256
- source commit SHA
- 세 image `@sha256:` digest
- accepted IAM diff SHA-256
- rollback revision IDs
- deployment workflow run ID/attempt
- `deploymentApproved=true`
- `cloudMutationApproved=true` 여부는 배포 executor 계약에 따라 별도 검증

### 4. 보호된 배포 workflow

별도 workflow는 다음 job 경계를 유지한다.

1. **prepare**: checkout, tests, source/provenance 검증, build metadata 준비. cloud credential 없음.
2. **build/push**: protected `staging-deployment` Environment와 OIDC 이후에만 실행; 세 image를
   immutable digest로 push하고 digest evidence를 생성한다.
3. **deploy**: 승인된 digest와 manifest만 사용해 Cloud Run/Firebase deployment를 수행한다.
4. **verify**: health, Firebase auth/privacy, two-tab collaboration, commit/digest marker를
   read-only로 검증하고 acceptance evidence를 업로드한다.

각 job은 이전 job의 same-run artifact만 소비하며, mutable tag·장기 credential·service-account key를
사용하지 않는다. workflow dispatch 직전에 별도 사용자 승인을 요구한다.

## 중단 조건

- `staging-preflight` Environment와 WIF read-only 설정이 실제 diff와 다름
- live preflight에서 project/billing/forbidden ID/region 불일치
- image digest 또는 rollback revision 미확정
- release metadata가 source commit 또는 approved Artifact Registry 경로와 불일치
- packet status가 `ready-for-deployment-approval`이 아님
- deployment approval record가 없거나 SHA/commit/run 결합이 다름
- precondition/postcondition 또는 acceptance test 실패

## 구현 결과와 현재 중단 지점

로컬 구현 결과:

- `scripts/staging_deployment_manifest.py`가 release metadata의 source commit, project number,
  Firebase Web App ID/API key reference, 서비스별 Artifact Registry 경로, image digest, task URL,
  rollback revision을 exact schema로 검증한다.
- live job은 bootstrap materializer 결과를 deployment packet에 직접 넘기지 않고, resolver가 만든
  `staging-manifest-deployment-preflight.json`만 static/live/packet 단계에 넘긴다.
- release metadata 파일이 없거나 source commit이 다르거나 placeholder/raw API key/민감 key가 있으면
  WIF 인증 전에 fail-closed한다.
- 서비스별 canonical image repository와 artifact transport를 회귀 테스트로 고정했다.

현재 중단 지점:

- repository에는 실제 release metadata가 없으므로 live deployment preflight를 실행하지 않았다.
- `staging-preflight`의 9개 Environment Variable은 normalized readiness와 일치하지만, WIF
  read-only secret은 아직 등록되지 않았다.
- image build/push, Cloud Run/Firebase deployment, cloud mutation은 수행하지 않았다.

## 승인 경계

현재는 immutable release-candidate metadata 준비와 WIF read-only secret 준비가 먼저 필요합니다.
다음 승인은 순서가 분리됩니다.

1. release-candidate build/push와 metadata 생성 방식 승인
2. `staging-preflight` WIF read-only secret 등록 승인
3. release metadata가 준비된 뒤 live preflight workflow dispatch 승인
4. 생성된 deployment packet exact-byte SHA-256 승인
5. `deploymentApproved=true` record 승인
6. deploy workflow dispatch 승인

이 문서 작성과 로컬 테스트에서는 cloud mutation, image build/push, deployment, secret 변경을
수행하지 않는다. 이번 승인 범위에서 적용한 것은 비밀이 아닌 9개 Environment Variable 등록뿐이며,
WIF secret과 release metadata가 준비되기 전에는 live preflight를 dispatch하지 않는다.
