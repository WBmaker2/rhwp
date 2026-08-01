# Staging infrastructure apply run 16 Secret metadata postcondition 분석

**Run:** [30690383409](https://github.com/WBmaker2/rhwp/actions/runs/30690383409)
**Branch/HEAD:** `feat/firebase-collaboration-mvp-v1` / `e51d052a896b6c02632d3dcb88163804d31e0f87`
**Package SHA-256:** `7bf41669ec4e873965ec9e51e4fc08761397615ac2ef67235cd5cd1b7a84c203`

## 최초 실패

`prepare`, same-run artifact, immutable provenance, OIDC authentication, gcloud setup까지
모두 성공했다. 최초 실패는 executor의 다음 단계다.

`postcondition mismatch for secret-metadata.ensure-collaborationInternal`

Run artifact의 `post-evidence.json`은 다음을 기록한다.

- `failedActionId`: `secret-metadata.ensure-collaborationInternal`
- `failurePhase`: `postcondition-mismatch`
- `writeAttemptedActionId`: 동일 action
- `writeReturnedSuccess`: `true`
- `executedActionIds`: API 11개, service account 4개, Artifact Registry 1개

따라서 Secret metadata write 명령은 성공을 반환했지만, 직후 observer가 원하는 상태로
인정하지 못해 fail-closed로 멈췄다.

## read-only cloud reconciliation

GCP read-only 목록 조회 결과:

- 승인된 API 11개가 모두 enabled 목록에 존재한다.
- 승인된 service account 4개가 모두 존재한다.
- `asia-northeast3/rhwp-staging` Artifact Registry repository가 존재한다.
- `rhwp-collaboration-internal-token-staging` Secret metadata가 존재한다.
- Secret replication은 `automatic`이다.
- Secret version 목록은 비어 있다.
- Secret payload/value는 조회하지 않았다.

Secret Manager list 응답의 resource name은 다음 형식이었다.

`projects/598693744358/secrets/rhwp-collaboration-internal-token-staging`

즉 GCP 응답은 project ID가 아니라 project number를 resource name에 넣는다.

## 코드 원인

현재 executor observer는 Secret의 name을 다음처럼 project ID로 고정 비교한다.

`projects/rhwp-collaboration-staging-001/secrets/rhwp-collaboration-internal-token-staging`

project-scoped `gcloud secrets list --project rhwp-collaboration-staging-001` 결과를
검사하면서도 resource name 내부에 project ID가 있다고 가정한 것이 오류다. Secret은
실제로 생성되었지만 observer가 `incompatible`을 반환한 결정적 계약 버그다.

## 현재 안전 상태

- 이번 run에서는 cloud authentication과 실제 cloud mutation이 실행됐다.
- Secret metadata 생성이 성공 반환되어 부분 mutation이 실제로 발생했다.
- Secret value/version은 생성되지 않았다.
- 자동 delete rollback은 실행하지 않았다.
- 이 상태에서 workflow 재실행 또는 Secret 삭제/수정은 하지 않는다.

## 필요한 수정

observer가 project-scoped list 결과의 `projects/<numeric-project-number>/secrets/<name>`
형식을 검증하도록 수정하고, project scope는 기존 fixed gcloud query로 유지해야 한다.
수정 후에는 다음을 다시 수행해야 한다.

1. 로컬 unit test와 executor observer test 추가
2. 새 commit에 맞춘 WIF workflow SHA와 Protected Environment SHA/tree 갱신
3. 새 attestation/package/declaration 및 별도 SHA 승인
4. 새 workflow dispatch 승인

수정된 observer는 이미 존재하는 Secret을 `already-present-noop`으로 처리해야 하므로,
새 run에서 Secret metadata write를 다시 시도하지 않는 것이 기대 동작이다.

## 승인된 코드 수정 및 로컬 검증 결과

2026-08-01 사용자의 코드 수정 승인을 받아 다음 최소 변경을 적용했다.

- `scripts/staging_infrastructure_apply_executor.py`
  - project-scoped Secret Manager list 응답의 `projects/<numeric-project-number>/secrets/<name>`
    resource name을 허용한다.
  - 승인된 secret 이름과 정확히 일치하는지, `automatic` replication만인지 계속 검증한다.
  - list 명령의 `--project <approved-project-id>` scope는 변경하지 않았다.
- `scripts/tests/test_staging_infrastructure_apply_hardening.py`
  - 숫자형 project number 응답을 present로 인정하는 회귀 테스트를 추가했다.
  - project ID resource name, 다른 secret 이름, 다른 replication은 incompatible로 차단하는 테스트를 추가했다.
  - fixed observer가 project-scoped list query를 유지하는지 테스트를 추가했다.

검증 결과:

- focused hardening tests: 7 passed
- executor tests: 8 passed
- full `scripts/tests` discovery: 201 passed
- `python3 scripts/validate_staging_config.py`: passed
- `py_compile` 및 `git diff --check`: passed

아직 commit/push, WIF·Environment 갱신, 새 package/declaration 생성, workflow 재실행은
수행하지 않았다. 다음 단계는 이 코드 변경의 별도 commit/push 승인 후 새 source binding과
attestation/package/approval cycle을 만드는 것이다.
