# Staging Infrastructure Apply Review Package 구현 계획

**작성일:** 2026-07-27  
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`  
**상태:** 구현 승인됨, 실제 cloud mutation 미승인  
**선행 계획:** `docs/superpowers/plans/2026-07-27-staging-infrastructure-execution-gates.md`

> **Security review amendment (2026-07-27):** 이 문서는 canonical 계획입니다. caller-declared executor
> commit, Environment bypass 지원, WIF immutable claim, artifact transport은 실제 값·지원 증거가 승인되기
> 전까지 apply 근거나 provenance가 아닙니다.

## 1. 목표

기존 infrastructure plan review 결과를 실제 apply로 바로 연결하지 않고, 다음 7개 독립 게이트를
사람이 exact-byte 증거와 설정 diff로 검토할 수 있는 하나의 비밀 없는 apply review package로 만든다.

1. `mutation-architecture`
2. `actual-evidence-transport`
3. `canonical-mutation-subset`
4. `staging-infrastructure-apply-environment`
5. `wif-identity-and-least-privilege-iam-diff`
6. `cloud-mutation-approval-record`
7. `apply-workflow-dispatch`

이번 구현의 완료 상태는 `ready-for-apply-review`다. 실제 GitHub Environment 생성·수정, WIF/IAM 변경,
cloud authentication, GCP/Firebase API 호출, resource mutation, build·push·deploy는 수행하지 않는다.

## 2. 고정 안전 경계

- 실제 운영 값과 actual approval package는 `artifacts/` 아래에만 둔다.
- tracked 예시와 workflow test fixture는 합성 값만 사용한다.
- access token, ID token, Authorization header, password, private key, service-account key, secret 원문,
  Firebase API key 원문, internal flush token 원문을 입력·출력·로그에 허용하지 않는다.
- apply review package는 shell string, executable argv, credential, token, secret value를 포함하지 않는다.
- 실제 executor가 생기기 전까지 모든 산출물은
  `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`를 유지한다.
- production-like project, unknown stage/action, digest 불일치, 승인 누락, broad IAM role, secret version/value
  작업은 첫 실패에서 차단한다.
- 자동 rollback delete, API disable, project/billing relink, service-account key 생성, secret version 생성·조회,
  Firebase foundation 생성, Firestore/Storage/Hosting 생성, Cloud Run/Tasks 배포는 canonical subset에서 제외한다.

## 3. Mutation architecture

```text
actual plan bytes
  + plan-review approval
  + canonical action manifest
        |
        v
apply review package builder (인증 없음, mutation 없음)
        |
        +-- exact input digests
        +-- caller-declared, unverified executor commit
        +-- canonical eligible action subset
        +-- protected-environment specification
        +-- WIF/IAM proposed diff
        +-- required approval declarations
        |
        v
human review / protected environment approval
        |
        v
future executor (이번 구현 범위 밖)
```

builder는 기존 plan/action/approval 검증기를 다시 사용하며 caller가 넣은 `approved=true`만 신뢰하지 않는다.
plan raw bytes, plan object digest, approval result, action manifest를 다시 결합하고 caller-declared 40자리
commit SHA를 기록한다. 미래 executor는 인증 전에 branch membership, commit object/tree, apply workflow content를
독립 검증해야 하며 이 입력을 immutable provenance로 취급하지 않는다.

## 4. Actual evidence transport

검토 package는 GitHub Actions artifact `staging-infrastructure-apply-review`에 합성 증거만 기록한다.

- actual run provenance나 source-run identity를 package에 기록하거나 신뢰하지 않는다.
- upload 전 `staging-infrastructure-apply-review-package.json`의 exact-byte SHA-256을 계산한다.
- artifact 안에는 package JSON/Markdown과 digest declaration만 포함한다.
- actual plan/approval/manifest는 저장소에 commit하지 않는다.
- workflow는 repository-relative tracked path를 actual evidence 입력으로 받지 않는다.
- 실제 evidence 전달 방식은 향후 별도 승인된 GitHub artifact download/attestation 단계가 추가되기 전까지
  synthetic review package 생성만 허용한다.

따라서 이번 workflow는 실제 apply 입력을 받거나 cloud 인증을 요청하지 않는다.

## 5. Canonical mutation subset

검토 가능한 mutation 후보는 다음 네 stage의 구조화 action만 포함한다.

| Stage | 허용 후보 | 명시적 제외 |
| --- | --- | --- |
| `api-baseline` | allowlist API enable 후보 | disable, allowlist 밖 API |
| `service-accounts` | dedicated service-account create 후보 | key 생성, broad role 부여 |
| `artifact-registry` | staging-only Docker repository create 후보 | delete, mutable tag/deploy |
| `secret-metadata` | secret metadata/name create 후보 | secret value/version create·read·print |

`project-billing`, `firebase-foundation`, `budget-guardrails`는 manual/irreversible decision으로 유지한다.
`iam-bindings`는 actual resource existence와 exact live before/after diff 전까지 deferred다.
`cloud-run-prerequisites`, `cloud-tasks-prerequisites`, `post-bootstrap-evidence`는 mutation subset에서 제외한다.

각 후보는 `actionId`, `stageId`, `resourceKind`, `resourceIdentifier`, `desiredState`,
`preconditionEvidence`, `rollbackDisposition`만 가진다. command/argv는 만들지 않는다.

## 6. Protected Environment 설정 diff

이번 구현은 다음 desired state를 JSON/Markdown으로 출력하지만 GitHub에 적용하지 않는다.

```diff
+ Environment: staging-infrastructure-apply
+ Required reviewers: >= 1
+ Prevent self-review: true
+ Can admins bypass: false (지원 여부는 실제 apply 전 검증)
+ Deployment branch policy: protected_branches=false, custom_branch_policies=true
+ Branch policies: [{name: feat/firebase-collaboration-mvp-v1, type: branch}]
+ Tag policies: []
+ Secrets: none
+ Long-lived cloud credentials: none
+ permissions.contents: read
+ permissions.actions: read
+ permissions.id-token: write   # future apply job에서만, 현재 review job에는 없음
+ Environment variables:
+   GCP_WORKLOAD_IDENTITY_PROVIDER
+   GCP_DEPLOYER_SERVICE_ACCOUNT
+   STAGING_PROJECT_ID
```

세 변수와 admin-bypass setting의 실제 지원 여부는 자동 결정하지 않는다. `supportVerificationStatus`
가 `required-before-apply`인 동안에는 unsupported 또는 unverified 상태가 approval/apply를 fail-closed로 막는다.

## 7. WIF identity와 최소권한 IAM diff

proposed diff는 credential 없이 claim template과 최소 permission을 포함한다. actual immutable IDs/SHA가
unresolved이면 `applicable=false`이고 final condition이 아니다.

```diff
+ Attribute mapping:
+   google.subject=assertion.sub
+   attribute.repository=assertion.repository
+   attribute.ref=assertion.ref
+   attribute.workflow_ref=assertion.workflow_ref
+   attribute.repository_id=assertion.repository_id
+   attribute.repository_owner_id=assertion.repository_owner_id
+   attribute.workflow_sha=assertion.workflow_sha
+ Final condition requires approved repository_id, repository_owner_id, reviewed workflow_sha,
+   ref=refs/heads/feat/firebase-collaboration-mvp-v1,
+   workflow_ref=WBmaker2/rhwp/.github/workflows/staging-infrastructure-apply.yml@refs/heads/feat/firebase-collaboration-mvp-v1
+ Current template: applicable=false; review workflow explicitly excluded
+ WIF principal -> deployer service account:
+   roles/iam.workloadIdentityUser (service-account scope)
+ Deployer service account candidate roles:
+   custom API enable-only, service-account create-only, Artifact Registry create/read,
+   Secret Manager metadata create/read/list permission sets (all project scope)
```

`roles/owner`, `roles/editor`, broad admin role, service-account key, billing IAM, project creator/deleter,
Firebase Admin, Cloud Run Admin, Cloud Tasks Admin은 금지한다. create/enable permission은 project scope가
필요하므로 IAM scope만으로 identifier를 제한한다고 주장하지 않는다. actual live project-scope before/after
diff와 executor의 exact action ID/resource/precondition allowlist가 별도 승인·강제되기 전에는 최종 diff가 아니다.

## 8. Cloud mutation approval record

새 예시 schema `rhwp.staging-infrastructure-mutation-approval/v1`을 정의한다.

- exact review package SHA-256
- plan SHA-256과 plan object SHA-256
- caller-declared, unverified executor commit SHA
- project ID
- canonical action IDs와 ordered stage IDs
- environment/WIF/IAM diff acknowledgement
- rollback acknowledgement
- `cloudMutationApproved`
- `deploymentApproved=false`

tracked example은 `decision=pending`, `cloudMutationApproved=false`, 승인자·시각 공란을 유지한다.
실제 approved record는 사람의 package 검토 후 ignored `artifacts/`에만 작성한다.

## 9. Apply workflow dispatch

`.github/workflows/staging-infrastructure-apply-review.yml`을 추가한다.

- `pull_request`: 테스트와 synthetic review package만 생성한다.
- `workflow_dispatch`: `mode=review-package`만 허용한다.
- permissions는 `contents: read`; `id-token: write` 없음.
- environment를 참조하지 않는다.
- cloud SDK 설치, auth action, `gcloud`, `firebase`, `curl` cloud API 호출이 없다.
- artifact `staging-infrastructure-apply-review`만 업로드한다.

실제 `mode=apply`, protected environment, OIDC 권한, cloud executor step은 이번 구현에 추가하지 않는다.
향후 exact package 승인 뒤 별도 사용자 승인을 받아 독립 diff로 추가한다.

## 10. 구현 파일

| 파일 | 변경 |
| --- | --- |
| `scripts/staging_infrastructure_apply_review.py` | exact provenance 검증과 review package 생성 |
| `scripts/staging_infrastructure_apply_review_paths.py` | input/output/marker/temp alias·symlink·special-file fail-closed 검증 |
| `scripts/staging_infrastructure_apply_review_policy.py` | non-applied Environment, WIF immutable claim, least-privilege IAM policy specification |
| `scripts/staging_infrastructure_synthetic_fixture.py` | workflow가 test 모듈 없이 사용하는 tracked non-secret synthetic evidence fixture |
| `scripts/tests/test_staging_infrastructure_apply_review.py` | TDD 계약·공격 입력·workflow 안전성 |
| `scripts/tests/test_staging_infrastructure_apply_review_policy.py` | Environment/WIF immutable-input 계약과 hardlink·direct/ancestor symlink subprocess 회귀 |
| `docs/approvals/staging-infrastructure-mutation-approval-record.example.json` | pending 합성 예시 |
| `.github/workflows/staging-infrastructure-apply-review.yml` | non-mutating review artifact workflow |
| `docs/runbooks/staging-infrastructure-bootstrap.md` | review-package 단계와 남은 실제 apply 승인 경계 |
| `docs/superpowers/reports/2026-07-27-staging-infrastructure-apply-review-package-result.md` | 구현·검증 결과 |

한 파일이 500줄에 접근하면 validation/rendering을 별도 모듈로 분리한다.

## 11. TDD와 검증

1. RED: valid evidence가 deterministic package를 생성하는 테스트
2. RED: raw plan byte mismatch, action reorder/tamper, production-like project, unsafe key, unknown action 차단
3. RED: canonical subset이 네 eligible stage만 포함하는지 검증
4. RED: environment/WIF/IAM spec이 broad role·credential·실제 값 없이 생성되는지 검증
5. RED: pending approval example이 실제 승인으로 오인되지 않는지 검증
6. RED: workflow에 cloud auth, `id-token: write`, environment, mutation CLI가 없는지 검증
7. GREEN: 최소 구현
8. 전체 `scripts/tests`와 `validate_staging_config.py`, `py_compile`, `git diff --check`
9. 보안 리뷰: secret leakage, provenance bypass, command injection, path/special-file 입력, workflow permission 확인

## 12. 완료 조건과 다음 승인

완료 시:

- status는 `ready-for-apply-review`
- actual cloud mutation은 0건
- actual environment/WIF/IAM 변경은 0건
- review package와 pending approval declaration을 사람이 검토할 수 있음

그 뒤에도 실제 apply 전에는 다음을 별도로 제시하고 승인받아야 한다.

1. actual review package exact-byte SHA-256
2. actual environment 설정 화면 diff
3. actual WIF provider/service-account identifier와 live IAM before/after diff
4. actual canonical action subset
5. 사람이 작성한 `cloudMutationApproved=true` record
6. 실제 apply workflow diff
7. 실제 workflow dispatch
