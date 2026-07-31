# Staging Infrastructure Task 4 실행 게이트

**기록일:** 2026-07-31

**상태:** `blocked-before-external-configuration`

**실제 cloud mutation:** 0건

**실제 deployment:** 0건

## 1. 완료한 준비 작업

- Task 3 로컬 통합본 전체 unittest 193개를 다시 실행해 통과했다.
- `scripts/validate_staging_config.py`와 `git diff --check`를 통과했다.
- 기존 Draft PR #1 브랜치에 로컬 커밋을 push했다.
- PR #1은 Draft, open, unmerged 상태를 유지한다.
- 원격 PR HEAD는 `699272d1150b586e84b70a27373faf1028c93fe4`다.
- 실제 repository ID는 `1311079356`, owner ID는 `103619091`로 read-only 확인했다.
- `staging-infrastructure-apply` Environment는 존재하지 않는 것을 read-only 확인했다.
- 실제 plan과 기존 non-mutation approval에서 최신 review package를 ignored 경로에 재생성했다.
- Google Cloud CLI 578.0.0을 설치하고 브라우저 인증을 완료했다.
- 기본 project를 `rhwp-collaboration-staging-001`로 설정하고 project number `598693744358`,
  lifecycle `ACTIVE`를 read-only 확인했다.
- 관련 WIF pool은 현재 0개이며, `rhwp` workload service account는 아직 없음을 read-only 확인했다.
  기존 Firebase 관리 service account는 변경하지 않는다.

## 2. 최신 exact-byte review package

경로:

```text
artifacts/actual-infrastructure-review/task4-2026-07-31/staging-infrastructure-apply-review-package.json
```

SHA-256:

```text
e0df6ffa8b45e2746937a08c1338717f7df0cbd3aa7ac6d6adf09c9abbd2b0d0
```

결합된 근거:

- plan exact-byte SHA-256: `499f9fcfcc23d84518d244a060eaf8c164fbed9f2fc1a53585a7948a906bb93a`
- executor commit: `699272d1150b586e84b70a27373faf1028c93fe4`
- executor tree: `624870545868e8e8ddbdbca9b4803fd6049057e5`
- apply workflow content SHA-256: `3fafec57050c030eea8e1c03e049a73814d3fa17544a28f3a64611613cf3aa41`
- action set SHA-256: `37533885b8e3508cd2170194132fe673c224994f0ea1557f64af40c60899a7f1`
- canonical action set SHA-256: `6b4050cdcf2c6d57447273fdcbf830c16a2d12ff9ee34eafefb0faa27e053f4a`
- 상태: `ready-for-apply-review`
- `cloudMutationApproved=false`
- `deploymentApproved=false`
- `mutationCommands=[]`

이 package는 review evidence이며 apply authority가 아니다. formatter, key sort, pretty-print 또는
재저장하지 않았고 원문 바이트로 digest를 계산했다. `artifacts/`는 Git ignored다.

## 3. Canonical mutation subset

승인 후보는 총 17개 action이다.

- API enable-only 11개:
  `serviceusage.googleapis.com`, `cloudbilling.googleapis.com`, `firebase.googleapis.com`,
  `firestore.googleapis.com`, `firebasestorage.googleapis.com`, `run.googleapis.com`,
  `cloudtasks.googleapis.com`, `artifactregistry.googleapis.com`, `secretmanager.googleapis.com`,
  `iam.googleapis.com`, `iamcredentials.googleapis.com`
- key 생성이 금지된 service account create-if-missing 4개:
  `rhwp-collaboration-staging`, `rhwp-document-api-staging`,
  `rhwp-document-worker-staging`, `rhwp-tasks-staging`
- Artifact Registry repository create-if-missing 1개:
  `asia-northeast3`, `rhwp-staging`, `DOCKER`
- Secret Manager metadata container create-if-missing 1개:
  `rhwp-collaboration-internal-token-staging`, automatic replication, secret version/value 생성 금지

disable, delete, service-account key, secret version/value, build, push, deploy는 subset에 없다.

## 4. 제안 Environment diff

새 Environment `staging-infrastructure-apply`에 필요한 계약은 다음과 같다.

- required reviewer: 최소 1명, 실제 계정은 아직 미결정
- prevent self review: `true`
- administrators bypass: `false`
- protected branches: `false`
- custom branch policies: `true`
- 허용 branch: `feat/firebase-collaboration-mvp-v1` 하나
- 허용 tag: 없음
- secrets: 없음
- long-lived cloud credentials: 없음
- Environment variables: 정확히 13개

```text
GCP_WORKLOAD_IDENTITY_PROVIDER
GCP_DEPLOYER_SERVICE_ACCOUNT
STAGING_PROJECT_ID
STAGING_APPROVED_REPOSITORY
STAGING_APPROVED_REPOSITORY_ID
STAGING_APPROVED_REPOSITORY_OWNER_ID
STAGING_APPROVED_REF
STAGING_APPROVED_WORKFLOW_REF
STAGING_APPROVED_WORKFLOW_SHA
STAGING_APPROVED_WORKFLOW_CONTENT_SHA256
STAGING_APPROVED_EXECUTOR_TREE_SHA
STAGING_APPROVED_APPLY_READY_PACKAGE_JSON
STAGING_APPROVED_MUTATION_APPROVAL_JSON
```

package/approval JSON과 실제 WIF 식별자는 아직 승인되지 않았으므로 변수 값은 설정하지 않았다.

## 5. WIF/IAM 제안 경계

- OIDC issuer: GitHub Actions
- default provider audience mode
- repository: `WBmaker2/rhwp`
- repository ID: `1311079356`
- owner ID: `103619091`
- ref: `refs/heads/feat/firebase-collaboration-mvp-v1`
- workflow ref:
  `WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml@refs/heads/feat/firebase-collaboration-mvp-v1`
- workflow SHA: `699272d1150b586e84b70a27373faf1028c93fe4`
- review workflow는 제외
- deployer service account에만 `roles/iam.workloadIdentityUser`
- broad predefined admin role은 금지
- API enable, service-account create/read/list, Artifact Registry repository create/read,
  Secret metadata create/read에 한정한 custom role 후보만 허용

WIF pool/provider ID와 deployer service-account ID는 실제 운영값이므로 자동 결정하지 않았다.
live before/after IAM diff도 아직 생성하지 않았다.

## 6. Fail-closed 차단 사유

1. Google Cloud CLI 설치·인증은 완료했으나 WIF provider와 deployer service account가 아직 없어 fixed
   read-only WIF/IAM attestation은 생성할 수 없다.
2. 승인된 Ed25519 public key registry diff와 단일 운영자 예외는 구현·검증을 마쳤으며 원격 commit에
   결합한 뒤 새 review package를 생성해야 한다.
3. private key는 사용자 승인에 따라 ignored operator-local 경로의 권한 `0600` 파일로만 보관하며
   tracked source, log, screenshot 또는 artifact에 넣지 않는다.
4. GitHub official GET Environment REST response에는 administrators bypass 상태가 포함되지 않는다.
   승인된 단일 운영자 예외는 이 누락을 `unavailable-in-official-rest`로 기록하도록 구현하며, 관찰된
   `false`로 위장하지 않는다. 필드가 제공될 때 `true` 또는 malformed 값이면 계속 fail-closed한다.
5. required reviewer는 `WBmaker2`, `preventSelfReview=false` 단일 운영자 예외로 승인되었지만 실제
   Environment 설정은 아직 적용하지 않았다. WIF provider와 deployer service account도 승인되지 않았다.
6. 최신 review package exact bytes, Environment diff, WIF/IAM live diff, signing key,
   `cloudMutationApproved=true` record와 workflow dispatch는 각각 별도 승인이 필요하다.

따라서 Environment 생성, variable 등록, WIF/IAM 변경, cloud 인증, workflow dispatch와 canonical
infrastructure mutation은 실행하지 않았다.

## 7. 다음 재개 순서

1. Google Cloud CLI 설치 또는 기존 승인된 read-only operator 실행 환경을 제공한다.
2. private key를 파일에 남기지 않는 signing backend와 immutable public-key onboarding 방식을 설계·승인한다.
3. GitHub UI에서 administrator bypass가 비활성화되었는지 운영자가 확인하고, REST receipt에는 승인된
   `unavailable-in-official-rest` 관찰 예외가 기록되는지 검증한다.
4. required reviewer, WIF pool/provider ID, deployer service-account ID를 사용자가 결정한다.
5. 최신 review package SHA-256과 canonical subset을 승인한다.
6. 실제 Environment/WIF/IAM before/after diff를 생성해 별도로 승인한다.
7. 승인된 외부 설정만 적용하고 signed apply-ready v3 package를 생성한다.
8. `cloudMutationApproved=true` record를 사람이 작성·승인한다.
9. 실제 apply workflow dispatch 직전 별도 승인을 받은 뒤 canonical subset만 실행한다.
10. postcondition 및 artifact exact-byte digest가 모두 일치할 때 Task 4를 완료 처리한다.

Task 5는 시작하지 않는다.

## 8. 단일 운영자 및 admin-bypass 예외 구현 후 최종 package

승인된 단일 운영자와 official REST admin-bypass 관찰 예외를 구현하고 전체 195개 테스트를 통과했다.

- executor commit: `97a83edf1a18dc8b1fe9c7a2f225532b24c190c1`
- executor tree: `f65441f9cb1b6761ca675e08c5ef257425029cfc`
- apply workflow content SHA-256:
  `3fafec57050c030eea8e1c03e049a73814d3fa17544a28f3a64611613cf3aa41`
- corrected review package exact-byte SHA-256:
  `c0ab4ef563b0374aa1c616557cc3a497cb91999fb2866ee96c4da71e3883c24c`
- package 상태: `ready-for-apply-review`
- canonical mutation count: 17
- required reviewer minimum: 1
- reviewer: `WBmaker2`
- prevent self review: `false`
- GitHub UI admin bypass 목표: `false`
- REST observation exception: `unavailable-in-official-rest-only`
- `cloudMutationApproved=false`
- `deploymentApproved=false`
- `mutationCommands=[]`

이전 `e0df6ffa...`, `82e3d843...` package는 superseded다. 잘못 확장된 가짜 full SHA로 생성된
중간 디렉터리는 `INVALID.md`로 명시적으로 폐기했으며 검토·승인·apply 입력으로 사용하지 않는다.
현재 승인 요청 대상은 위 `c0ab4ef5...3c24c` 원문 바이트 하나뿐이다.
