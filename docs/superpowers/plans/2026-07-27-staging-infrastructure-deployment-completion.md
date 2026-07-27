# Staging Infrastructure Deployment Completion 계획

**작성일:** 2026-07-27  
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`  
**대상 프로젝트:** `rhwp-collaboration-staging-001`  
**실행 방식:** Subagent-Driven Development  
**상태:** 실행 중

## 목적

현재 `ready-for-apply-review` 구현을 실제 staging 배포 검증까지 연결한다. 각 단계는 exact-byte
증거, 최소 권한, protected environment, 사람의 불변 패키지 승인 경계를 유지한다. 승인되지 않은
값을 추측하거나 secret을 파일·로그·artifact에 기록하지 않는다.

## 전역 안전 계약

- PR #1은 Draft·open·미병합 상태를 유지한다.
- actual 값과 승인 자료는 ignored `artifacts/` 또는 기존 ignored local readiness 파일에만 둔다.
- access token, ID token, Authorization header, password, private key, service-account key, secret 원문,
  Firebase API key 원문, internal flush token 원문을 출력하거나 추적하지 않는다.
- 승인 전에는 `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`를 유지한다.
- actual package가 생성된 뒤 그 exact-byte SHA-256과 설정 diff를 사람이 검토하기 전에는 cloud mutation을
  실행하지 않는다.
- actual apply workflow dispatch와 deployment dispatch는 각각 실행 직전의 명시적 승인을 요구한다.
- 오류 또는 계약 불일치는 다음 단계로 진행하지 않고 fail-closed로 중단한다.
- 실제 운영 식별자, IAM principal, WIF claim, reviewer, 승인 시각을 임의로 만들지 않는다.

## Task 1: Actual infrastructure approval validator 계약 충돌 수정

### 목표

`plan.security.secretValuesIncluded=false`처럼 비밀이 없음을 증명하는 명시적 boolean 필드가 generic
sensitive-key 검사에 의해 거부되는 충돌을 최소 범위로 해소한다.

### 구현

- `secretValuesIncluded`는 값이 정확히 `false`일 때만 허용한다.
- `true`, 문자열, 숫자, 객체, 배열, null 및 다른 secret/token/value 계열 키는 계속 거부한다.
- 중첩 위치와 key spelling 변형에 대한 회귀 테스트를 추가한다.
- actual JSON은 테스트 fixture로 복사하지 않고 합성 fixture만 사용한다.

### 완료 조건

- focused tests, 전체 `scripts/tests`, staging validator, `py_compile`, `git diff --check`가 통과한다.
- actual infrastructure approval validator가 실제 plan/approval 입력을 읽고 승인 결과를 생성한다.
- cloud mutation, deployment, secret 변경은 0건이다.

## Task 2: Actual apply review package 생성과 immutable 검토 자료 정리

### 목표

검증된 actual plan/approval 입력으로 non-mutating apply review package를 생성하고 exact-byte digest,
canonical action subset, Environment/WIF/IAM proposed diff를 한 디렉터리에 정리한다.

### 구현

- actual input/output은 ignored `artifacts/` 아래에서만 처리한다.
- source commit, workflow/run provenance, plan digest, review package digest를 기록한다.
- 패키지를 formatter, key sort, pretty-print 또는 재저장하지 않고 원문 바이트로 SHA-256을 계산한다.
- Git 추적 여부와 secret/key 노출 여부를 검사한다.

### 완료 조건

- 상태가 `ready-for-apply-review`다.
- exact-byte digest와 7개 승인 항목의 구체적 diff를 사람이 검토할 수 있다.
- actual mutation approval declaration은 pending이며 승인자·승인 시각을 임의로 채우지 않는다.

## Task 3: Approved actual apply executor와 workflow 구현

### 선행 조건

Task 2의 exact review package SHA-256, canonical action subset, actual Environment/WIF/IAM diff에 대한
사용자의 명시적 승인이 있어야 한다.

### 목표

승인된 action ID만 한 번씩 실행하고, precondition 불일치 시 첫 실패에서 중단하는 apply executor와
protected workflow를 구현한다.

### 구현

- 구조화 action allowlist만 소비하며 shell/argv를 패키지에서 받지 않는다.
- exact package digest, source commit/tree, workflow file SHA, branch, repository immutable ID를 인증 전에
  독립 검증한다.
- protected environment와 OIDC를 apply job에만 사용한다.
- 장기 credential과 service-account key를 사용하지 않는다.
- dry-run/plan evidence와 post-apply observed evidence를 별도로 남긴다.
- build·push·runtime deploy는 infrastructure mutation과 분리한다.

### 완료 조건

- 합성/negative 테스트와 전체 검증이 통과한다.
- 실제 cloud 호출 없이 executor/workflow diff가 검토 가능하다.

## Task 4: Protected Environment, WIF, IAM 및 canonical infrastructure apply

### 선행 조건

- Task 3 구현 리뷰 통과
- actual mutation approval record의 exact digest 일치
- 실제 apply workflow dispatch 직전 사용자 승인

### 실행

- `staging-infrastructure-apply` Environment를 승인된 diff와 정확히 일치하도록 설정한다.
- 실제 GitHub repository/owner/workflow immutable identity를 확인한다.
- WIF provider/service account와 최소 권한 IAM live before/after diff를 확인한 뒤 승인된 변경만 적용한다.
- canonical subset만 적용하고 제외 stage는 실행하지 않는다.
- 실행 artifact와 cloud observed evidence를 다운로드해 exact-byte digest를 기록한다.

### 완료 조건

- 모든 action은 승인된 ID와 일치하고 postcondition을 만족한다.
- 예상 밖 변경, broad IAM, key/secret value 생성이 없다.
- 실패 시 다음 단계로 진행하지 않는다.

## Task 5: Staging build, push, deploy 및 live verification

### 선행 조건

- Task 4 성공
- 별도 `deploymentApproved=true` record
- 실제 deployment workflow dispatch 직전 사용자 승인

### 실행

- 승인된 immutable source commit에서 재현 가능한 build를 수행한다.
- 승인된 registry/repository와 immutable digest로만 push한다.
- staging runtime에 digest-pinned image를 배포한다.
- Firebase/GCP 구성, health, two-tab collaboration, 권한/비밀 노출을 검증한다.
- 배포 URL, image digest, workflow run ID, commit SHA, verification evidence를 기록한다.

### 완료 조건

- staging URL에서 승인된 commit/digest가 동작한다.
- PR #1은 Draft·open·미병합 상태다.
- 계획과 구현/배포 결과 Markdown 보고서가 저장소에 남는다.
- 관련 검증이 모두 통과하고 예상 밖 cloud mutation이 없다.
