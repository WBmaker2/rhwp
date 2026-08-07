# Staging Infrastructure Task 3 완료·재개 기록

**기록일:** 2026-07-30

**중단점:** Task 3 완료 직후

**다음 단계:** Task 4 대기

**실제 인프라 변경·배포 상태:** 미실행

## 1. 현재 Git 및 PR 상태

- 저장소: `WBmaker2/rhwp`
- 로컬 경로: `/Users/kimhongnyeon/Dev/codex/rhwp`
- PR 브랜치: `feat/firebase-collaboration-mvp-v1`
- Task 3 로컬 통합 커밋: `60fa8352c300eb703cb674d76a598385cec18fd2`
- 원격 PR #1 HEAD: `2ae37993e09e0a52350f6be639d8341e880f708d`
- PR #1: Draft, open, unmerged
- Task 3 변경은 로컬에만 커밋했으며 원격에는 push하지 않았다.
- 사용자 소유 untracked 경로 `.chatgpt2codex/`는 변경하거나 Git에 추가하지 않았다.

격리된 SDD worktree는 다음 상태로 보존한다.

- 경로: `/Users/kimhongnyeon/Dev/codex/rhwp/.worktrees/staging-deployment-completion`
- 브랜치: `codex/staging-deployment-completion`
- HEAD: `5786f9dd0c172d32c3f1f1e72a2eb2e9ebb66dc0`
- Task 3 구현·수정 범위: `9155285b`부터 `5786f9dd`까지
- 최종 scoped review: Spec PASS, Quality PASS, APPROVED
- SDD ledger: `.superpowers/sdd/2026-07-27-staging-infrastructure-deployment-completion/progress.md`

## 2. Task 3 완료 내용

Task 3의 목적은 실제 외부 변경을 실행하지 않고, 승인된 canonical action만 처리하는
fail-closed infrastructure apply executor와 protected workflow 계약을 구현하는 것이었다.

완료된 핵심 기능은 다음과 같다.

- strict apply approval, readiness, review-policy validation
- GitHub runtime·artifact·commit provenance 결합
- fixed read-only GitHub CLI 및 gcloud 관찰 명령
- read-before/write/read-after와 `already-present-noop` 재실행 계약
- API, service account, Artifact Registry, Secret metadata에 대한 exact-state 검증
- 실패 시 sanitised post-write evidence와 completion marker
- GitHub Environment, WIF, operator attestation validator
- offline Ed25519 operator receipt 서명 및 공개키 registry 검증
- service-account key 부재와 post-write evidence 검사
- protected `staging-infrastructure-apply` workflow
- CLI module invocation과 hardening 회귀 테스트

주요 구현 파일은 다음과 같다.

- `.github/workflows/staging-infrastructure-apply.yml`
- `scripts/staging_infrastructure_apply_approval.py`
- `scripts/staging_infrastructure_apply_executor.py`
- `scripts/staging_infrastructure_apply_provenance.py`
- `scripts/staging_infrastructure_apply_ready.py`
- `scripts/staging_infrastructure_apply_safety.py`
- `scripts/staging_infrastructure_environment_attestation.py`
- `scripts/staging_infrastructure_operator_attestation.py`
- `scripts/staging_infrastructure_operator_signature.py`
- `scripts/staging_infrastructure_wif_attestation.py`
- 관련 runbook, review policy, 예제 record 및 테스트

## 3. 검증 결과

PR 브랜치에 Task 3 순 변경을 통합한 뒤 다음을 다시 실행했다.

```bash
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -q
python3 scripts/validate_staging_config.py
python3 -m py_compile <Task 3 Python modules>
git diff --cached --check
```

결과:

- 전체 unittest: 193개 통과
- staging config validator: 통과
- Task 3 Python module 구문 검사: 통과
- staged diff whitespace 검사: 통과
- 테스트 중 표시된 approval 실패 문구는 invalid-input 및 atomic-publish 실패를 검증하는
  의도된 negative test 출력이며 전체 suite는 `OK`로 종료했다.

## 4. 기존 승인과 현재 효력

사용자가 승인한 infrastructure plan exact-byte SHA-256:

```text
499f9fcfcc23d84518d244a060eaf8c164fbed9f2fc1a53585a7948a906bb93a
```

과거 actual apply review package v1 SHA-256:

```text
3a26cb46d37ff8e65c2bdf3e474ff36623d9fcfb14d22582f68a03f5d656256e
```

Task 3에서 schema와 provenance 계약이 강화되었으므로 과거 v1 package 승인은 실제 apply
권한으로 사용할 수 없다. 최종 executor commit이 원격 PR 브랜치에 존재한 뒤 새 package를
원문 바이트 그대로 생성하고, 새 SHA-256과 설정 diff에 대한 별도 승인을 받아야 한다.

## 5. 의도적으로 유지한 fail-closed 차단

현재 실제 apply promotion은 다음 두 신뢰 조건이 준비되지 않아 의도적으로 차단된다.

1. operator receipt 검증용 Ed25519 공개키 registry가 비어 있다.
2. GitHub Environment REST 응답만으로는 admin bypass 방지 설정을 독립적으로 입증할 수 없다.

사람의 acknowledgement를 이 증거의 대체물로 사용하지 않는다. 다음 작업에서는 지원되는
공개키 등록 절차와 admin bypass를 관찰 가능한 플랫폼 근거로 검증하는 방법을 먼저 결정해야 한다.
검증 가능한 근거가 없으면 actual apply로 진행하지 않는다.

## 6. 다음 작업의 재개 순서

Task 4와 Task 5는 시작하지 않았다. 다음 세션에서는 아래 순서를 따른다.

1. 로컬 branch, HEAD, working tree와 PR #1 Draft/open/unmerged 상태를 재확인한다.
2. 사용자의 원격 push 승인을 확인한 뒤 Task 3 로컬 커밋을 PR 브랜치에 push한다.
3. 원격에 존재하는 최종 executor commit SHA에 결합된 최신 actual apply review package를 생성한다.
4. package exact-byte SHA-256, canonical subset, Environment/WIF/IAM 설정 diff를 제시한다.
5. operator signing public-key onboarding과 관찰 가능한 Environment attestation 방식을 별도로 검토한다.
6. 각 외부 변경에 대한 명시적 승인을 받은 뒤에만 protected Environment, WIF, IAM을 설정한다.
7. `cloudMutationApproved=true` record와 actual apply workflow dispatch 승인을 별도로 받는다.
8. infrastructure apply 및 post-apply evidence가 검증된 뒤에만 Task 5 배포 승인으로 넘어간다.

## 7. 이번 중단점에서 실행하지 않은 작업

- 원격 push 또는 PR 상태 변경
- PR ready 전환, merge, close
- GitHub Environment 또는 variable 변경
- WIF provider, service account, IAM 변경
- GCP/Firebase API 활성화 또는 리소스 생성
- cloud authentication
- actual apply workflow dispatch
- build, image push, Cloud Run/Tasks/Firebase deployment
- secret 원문, credential 또는 service-account key 저장·변경

이번 작업에서 cloud mutation, deployment, secret 변경은 모두 0건이다.

## 8. 승인 경계

Task 3 구현 승인은 소진되었다. 다음 단계의 package 승인, Environment/WIF/IAM 설정,
cloud mutation record, workflow dispatch, infrastructure evidence, deployment는 각각 별도의
승인으로 취급한다. 앞 단계 승인을 뒤 단계 권한으로 확대 해석하지 않는다.
