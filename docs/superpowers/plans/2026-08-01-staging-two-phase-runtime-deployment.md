# Staging 최초 runtime 배포 2단계 계획

**작성일:** 2026-08-01
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`
**상태:** Phase A 구현 완료, Phase B 승인 대기

## 왜 현재 일괄 배포가 성립하지 않는가

infrastructure apply #18은 API, service account, Artifact Registry, secret metadata만 준비했다.
Cloud Run service는 아직 배포되지 않았다. 그러므로 최초 runtime 배포 전에 다음 값은 실제로 존재하지
않는다.

- Document worker의 실제 `run.app` URL
- parse/export Cloud Tasks target URL
- 기존 Cloud Run rollback revision

현재 deployment manifest가 세 서비스 image digest와 task URL을 모두 요구한 상태에서 먼저 live
preflight를 실행하면, URL을 추측하거나 첫 배포 이후에야 알 수 있는 값을 사전에 요구하게 된다.

## 제안하는 protected 단계

### Phase A — release candidate

- 비보호 prepare가 source commit과 테스트 결과를 기록한다.
- protected build/push job이 OIDC로 세 image를 immutable digest에 push한다.
- same-run artifact에 image digest와 `deploymentStage=initial`을 기록한다.
- 이 단계에서는 Cloud Run/Firebase deploy와 queue mutation을 하지 않는다.

### Phase B — worker bootstrap

- 별도 protected deployment approval 후 worker digest만 사용해 Document worker를 배포한다.
- worker URL과 revision을 read-only로 관찰한다.
- same-run artifact에 worker URL, worker revision, source commit, image digest를 기록한다.
- 실패하면 다음 단계로 진행하지 않는다.

### Phase C — final manifest and preflight

- Phase A와 B의 same-run artifact만 소비한다.
- worker URL로 parse/export task target URL을 만들고, `deploymentStage=initial`이면 이전 revision
  없음 상태를 명시한다.
- static/live read-only preflight와 deployment packet을 생성한다.
- packet이 `ready-for-deployment-approval`이 아니면 runtime 배포를 실행하지 않는다.

### Phase D — remaining runtime and Firebase

- 별도 deployment approval 후 collaboration, document API, Cloud Tasks, Firebase Rules/Hosting을
  protected job에서 순서대로 적용한다.
- 모든 mutation은 승인된 same-run artifact와 digest만 소비한다.
- verify job은 health, auth/privacy, two-tab collaboration, task dispatch를 read-only로 검증한다.

## 불변 결합

- source commit SHA
- release workflow run ID/attempt
- three image digest
- worker bootstrap workflow run ID/attempt
- worker URL와 revision
- final packet exact-byte SHA-256
- deployment approval record SHA/reference

## 안전 경계

- prepare job에는 cloud credential과 `id-token: write`를 부여하지 않는다.
- protected job 이전에는 build/push/deploy/mutation을 실행하지 않는다.
- Environment 변수에 run-bound record나 package를 저장하지 않는다.
- 실제 URL·revision·digest를 추측하거나 임의로 채우지 않는다.
- `cloudMutationApproved=false`, `deploymentApproved=false` 상태에서 workflow dispatch를 실행하지 않는다.

## Phase A 현재 상태와 다음 외부 준비

1. `staging-preflight` 전용 read-only WIF provider와 최소 권한 service account는 준비되었다.
2. release-candidate workflow와 로컬 계약 테스트가 구현되었다.
3. release-candidate push용 protected Environment와 OIDC identity의 exact diff를 read-back해야 한다.
4. Phase A workflow dispatch와 artifact exact-byte SHA-256을 확인한 뒤, Phase B worker bootstrap의
   exact diff와 별도 dispatch 승인을 받는다.
5. Phase B 이후에만 최종 metadata, live preflight, runtime deployment을 진행한다.

이 계획의 Phase A workflow는 Cloud Run/Cloud Tasks/Firebase deploy를 수행하지 않는다. protected
release Environment 안에서만 immutable image build/push와 candidate evidence 생성을 수행하고,
worker bootstrap 이후에 실제 runtime mutation을 별도 단계로 제한한다.
