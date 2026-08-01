# Staging apply attestation refresh plan

**작성일:** 2026-08-01  
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`  
**목표:** 만료된 apply-ready package와 승인 기록을 재사용하지 않고, 현재 보호된 Environment/WIF 상태를 새로 읽어 짧은 유효기간의 package와 run-bound 승인 기록을 준비한다.

**현재 상태:** refresh2 package SHA 승인, workflow dispatch, run-bound 승인 기록, Environment 승인까지 완료했으나 첫 precondition observation permission 부족으로 fail-closed되었다. 첫 write 전 중단했다.

**실패 action:** `api-baseline.ensure-api-01`  
**필요한 read permission:** `serviceusage.services.list`  
**현재 custom role:** `stagingApiEnableOnly`에는 `serviceusage.services.enable`만 포함

**승인된 보정:** API enable action의 fixed precondition observer가 `gcloud services list --enabled`를
사용하므로 `stagingApiEnableOnly`에 read-only `serviceusage.services.list`를 추가한다. disable, delete,
또는 broad service-usage role은 추가하지 않는다. source IAM diff와 live custom role을 함께 갱신한 뒤 새
review/apply-ready SHA를 다시 승인한다.

**새 refresh2 package SHA-256:** `55527367bfe83c5ddbc068b963bceb8ad29b8fcd776824c0e8ae1e0b66c51036`  
**새 attestation window:** `2026-08-01T01:52:01Z`–`2026-08-01T02:07:03Z`

**실패 run:** `30678348900` (attempt 1)  
**실패 시각:** `2026-08-01T01:46:49Z`  
**원인:** Environment attestation 만료 (`2026-08-01T01:45:57Z`)

## 현재 차단 원인

GitHub Environment Variables read 응답에는 apply-ready package 값(약 35KB)이 포함되어 있다. 고정
attestation parser의 단일 JSON 문자열 제한(16KB)을 넘기므로, 값이 필요 없는 Environment 이름 검증도
`strict JSON` 단계에서 fail-closed 된다.

## 안전한 보정

- 고정 GitHub API endpoint는 유지한다.
- Variables endpoint에 고정 `jq` projection을 적용해 `total_count`와 각 변수의 `name`만 반환한다.
- 변수 값, package JSON, approval JSON, 토큰 또는 credential은 attestation 입력·출력·로그에 포함하지 않는다.
- projection된 응답 바이트의 digest만 attestation response digest로 기록한다.
- pagination total, 이름 집합, 중복 검증 및 기존 fail-closed 정책은 유지한다.

## 실행 순서

1. projection argv에 대한 회귀 테스트를 추가한다.
2. 전체 관련 테스트와 정적 검사를 실행한다.
3. 현재 GitHub Environment와 GCP WIF/IAM을 read-only로 다시 attest한다.
4. 새 signed apply-ready package를 ignored `artifacts/` 경로에 생성하고 exact-byte SHA-256을 계산한다.
5. 새 SHA와 package 메타데이터를 사용자에게 제시하고 별도 승인을 받는다. (완료)
6. workflow dispatch 직전 사용자의 별도 실행 승인을 받는다.
7. 새 run ID/attempt에 결합한 승인 기록을 작성하고, attestation validity window 안에서 protected job 승인을 진행한다.
8. attestation 또는 approval expiry를 넘긴 run은 재사용하지 않고 새 package부터 재생성한다.
9. 승인 전에는 workflow dispatch, cloud mutation을 수행하지 않는다.

## 완료 경계

- 새 attestation과 package가 현재 시각 기준 유효하다.
- package는 `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`를 유지한다.
- 새 승인 기록은 사용자의 새 SHA 승인과 실제 새 workflow run/attempt 바인딩 전에는 apply 권한으로 사용하지 않는다.
- cloud resource, IAM, WIF, API, secret, deployment 변경은 0건이다.

## 2026-08-01 recovery run evidence

- Dispatch 승인 후 run `30679968730`, attempt `1`을 생성했다.
- Run URL: https://github.com/WBmaker2/rhwp/actions/runs/30679968730
- `publish-approved-evidence`가 `validate_apply_ready_package` 단계에서
  `operator attestation is invalid or expired`로 fail-closed 되었다.
- `apply` job은 skipped였고, WIF authentication과 executor action은 실행되지 않았다.
- 로그에서 확인된 입력은 이전 run-bound record `approvedRunId=30678904145`와
  이전 package SHA였으며, 새 run의 변수 반영이 job 시작 후에 이루어져 새 입력으로 재사용하지 않는다.
- 따라서 이 run의 cloud resource, IAM, API, secret, deployment mutation은 0건이다.
- 만료된 run-bound record와 package를 폐기하고, 외부 read-only attestation을 다시 실행했다.
- recovery apply-ready package:
  `artifacts/actual-infrastructure-review/task4-apply-ready-2026-08-01-recovery1/staging-infrastructure-apply-ready-package.json`
- recovery package exact-byte SHA-256:
  `3991e6fb677b4377a2a1a47eab3ef0fb24962442bd779547ff7989461f9a6a6a`
- recovery attestation window: `2026-08-01T02:30:20Z`–`2026-08-01T02:45:23Z`
- recovery package remains inert: `cloudMutationApproved=false`,
  `deploymentApproved=false`, `mutationCommands=[]`.

## Recovery stop boundary

The failed run must not be retried or re-run. The recovery SHA requires a fresh,
separate human approval. After that approval, dispatch and run-bound record
creation must be performed in one short sequence so the protected job reads the
fresh package and record before the attestation window expires.

## Recovery run 2

- User approved recovery package SHA `3991e6fb677b4377a2a1a47eab3ef0fb24962442bd779547ff7989461f9a6a6a`.
- New workflow run: `30680387024`, attempt `1`.
- Run URL: https://github.com/WBmaker2/rhwp/actions/runs/30680387024
- Run-bound approval record was locally validated and bound to this run before
  updating `STAGING_APPROVED_APPLY_READY_PACKAGE_JSON` and
  `STAGING_APPROVED_MUTATION_APPROVAL_JSON`.
- The protected `staging-infrastructure-apply` deployment is currently waiting
  for reviewer `WBmaker2`; `apply` has not started.
- No cloud mutation, deployment, API activation, Secret change, or IAM change
  occurred in this recovery run.
