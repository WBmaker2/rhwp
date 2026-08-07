# Staging Architecture and Deployment Runbook Implementation Plan

**Goal:** 현재 구현된 Firebase 공동 편집 MVP를 기준으로 staging architecture 설계와 승인 기반 deployment runbook을 작성한다.

**Scope:** 문서화만 수행한다. Firebase/GCP 리소스, billing, API, IAM, Secret Manager, Cloud Tasks, Cloud Run, Firebase Hosting, Rules와 Indexes를 생성·변경·배포하지 않는다.

**Branch:** `feat/firebase-collaboration-mvp-v1`  
**PR:** Draft PR `#1` → `devel`

## Constraints

- [x] PR을 Draft로 유지한다.
- [x] merge 또는 deploy를 수행하지 않는다.
- [x] 기본 리전 계약은 `asia-northeast3`으로 유지하고 실제 적용 전 승인 항목으로 둔다.
- [x] 서비스 이름은 기존 template과 일치시킨다.
- [x] queue 이름은 `rhwp-parse-staging`, `rhwp-export-staging`을 사용한다.
- [x] 업로드 계약 `0 < 파일 크기 ≤ 200 MiB`와 이미지 최대 20 MiB를 유지한다.
- [x] secret 원문과 service account key를 저장소에 기록하지 않는다.

## Task 1 — Baseline 확인

- [x] 기준 head `f9f1e8e09efcf8cb0fad955ce66eca02728a3f2d`에서 모든 workflow 성공을 확인했다.
- [x] PR이 open, Draft, not merged, mergeable 상태임을 확인했다.
- [x] 기존 staging environment와 Cloud Run template을 확인했다.
- [x] Document API, Collaboration server, Document worker의 실제 Firebase/GCP 접근 범위를 확인했다.

## Task 2 — Staging architecture 설계

**Created:** `docs/superpowers/specs/2026-07-26-staging-architecture-design.md`

- [x] 배포 전 설계 기준과 non-goal을 정의했다.
- [x] browser, Firebase, 3개 Cloud Run service와 2개 Cloud Tasks queue의 topology를 작성했다.
- [x] 로그인, upload/parse, realtime collaboration, export 데이터 흐름을 작성했다.
- [x] project, region, service, queue, service account, secret, budget naming contract를 정의했다.
- [x] public browser endpoint와 private worker trust boundary를 정의했다.
- [x] runtime identity별 Firestore, Storage, Tasks, Run, Secret IAM matrix를 작성했다.
- [x] 기존 template의 concurrency, timeout, CPU, memory, min/max scale 값을 반영했다.
- [x] 비용, logging, monitoring, retention과 budget alert 원칙을 정의했다.
- [x] 실패 모드와 배포 전·후 acceptance criteria를 작성했다.
- [x] 다음 machine-readable manifest의 필수 interface를 정의했다.

## Task 3 — Deployment runbook

**Created:** `docs/runbooks/staging-deployment.md`

- [x] 명시적 승인 없이는 실행하지 않는 safety gate를 작성했다.
- [x] project, billing, region, IAM, secret, queue, budget, digest approval packet을 작성했다.
- [x] mutation 전 read-only project/account/resource 확인 절차를 작성했다.
- [x] project/API → Firebase → Artifact Registry → service account/IAM → Secret → queue → Cloud Run → Firebase deploy 순서를 작성했다.
- [x] 각 단계에 precondition, action, verification, stop condition과 rollback을 작성했다.
- [x] worker unauthenticated denial과 Cloud Tasks OIDC 검증을 포함했다.
- [x] Google sign-in, Rules, 200 MiB 경계, ACL, snapshot denial 검증을 포함했다.
- [x] upload → parse → collaboration → restart/recovery → export → HWPX re-import acceptance flow를 작성했다.
- [x] traffic rollback, queue pause, Hosting/Rules rollback, secret version rollback 절차를 작성했다.
- [x] 배포 완료 기록 양식을 작성했다.

## Task 4 — 설계 검수 결과

- [x] 서비스와 queue 이름이 기존 template과 일치한다.
- [x] `asia-northeast3`이 Cloud Run, Cloud Tasks, Firestore와 Storage에서 지원되는 리전임을 공식 문서로 확인했다.
- [x] worker ingress `internal`, concurrency 1, timeout 900s, 2 CPU, 2Gi를 반영했다.
- [x] Collaboration timeout 3600s와 WebSocket reconnect 요구를 반영했다.
- [x] secret은 `rhwp-collaboration-internal-token-staging`의 Secret Manager reference만 사용했다.
- [x] 실제 project ID, credential, secret value와 production domain을 기록하지 않았다.
- [x] cloud mutation 또는 deployment를 수행하지 않았다.

## Pre-deployment findings

### 1. Cloud Tasks dispatch deadline

현재 task payload는 `dispatchDeadline`을 지정하지 않아 HTTP task 기본값 600초가 적용되지만 worker timeout은 900초다. 실제 staging 배포 전에 다음 중 하나를 구현하고 테스트해야 한다.

- 권고: task payload에 `dispatchDeadline=900s` 추가
- 대안: worker timeout을 600초 이하로 낮추고 200 MiB acceptance 재검증

### 2. Collaboration internal flush

Document API는 identity token과 internal token을 보내지만 현재 Collaboration handler가 직접 강제하는 값은 internal token이다. browser WSS 때문에 같은 Cloud Run service를 전체 private로 만들 수 없다.

- staging 선택: single public service + high-entropy internal token 제한을 명시적으로 승인
- 강화 선택: internal flush를 별도 private service 또는 endpoint로 분리

production 전에는 private 분리를 별도 설계·구현하는 것을 권고한다.

## Permanent files

- `docs/superpowers/plans/2026-07-26-staging-architecture-runbook.md`
- `docs/superpowers/specs/2026-07-26-staging-architecture-design.md`
- `docs/runbooks/staging-deployment.md`

## Final verification gate

이 커밋을 최종 파일 head로 사용한다. 이후 repository 파일은 더 수정하지 않는다.

- [ ] 최종 head의 `Staging configuration` workflow 성공 확인
- [ ] 최종 head의 `CI` 성공 확인
- [ ] 최종 head의 `CodeQL` 성공 확인
- [ ] 최종 head의 나머지 PR workflow 실패 없음 확인
- [ ] Draft PR body를 최종 head와 문서 경로로 metadata-only 갱신
- [ ] PR이 open, Draft, not merged 상태인지 최종 확인

## Next implementation unit

1. staging architecture를 machine-readable manifest로 분리한다.
2. 실제 리소스를 변경하지 않는 read-only preflight validator를 구현한다.
3. `workflow_dispatch`에서 validator를 실행하고 결과 artifact를 생성한다.
4. project, region, IAM, secret, queue와 원화 budget 변경 내역을 사용자에게 제시한다.
5. 명시적 승인 이후에만 staging mutation과 deployment를 수행한다.
