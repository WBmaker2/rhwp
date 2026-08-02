# Staging 최초 worker bootstrap 준비 결과

**작성일:** 2026-08-02
**브랜치:** `feat/firebase-collaboration-mvp-v1`
**현재 HEAD:** `789ce3d59834cd6734981862f7c2d429a30bb792`

## 완료한 로컬 구현

- `scripts/staging_worker_bootstrap.py`
  - release-candidate evidence exact key/schema 검증
  - source commit, release run/attempt, artifact server digest 결합
  - 세 image의 canonical repository와 lowercase SHA-256 검증
  - 실제 Storage bucket이 없거나 placeholder이면 fail-closed
  - worker Cloud Run YAML을 임시 출력으로만 렌더링
  - `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]`를 입력 summary에 보존
- `scripts/tests/test_staging_worker_bootstrap.py`
  - 정상 digest-pinned internal worker 렌더링
  - planned/placeholder bucket 거부
  - source/artifact binding 불일치 거부
  - 실패 시 부분 출력 없음
  - prepare credential 분리, protected worker-only workflow 구조 검증
- `.github/workflows/staging-runtime-worker-bootstrap.yml`
  - `prepare`: OIDC·cloud credential 없이 이전 release run의 same-run candidate artifact를 검증
  - `bootstrap`: `staging-runtime-bootstrap` 보호 환경과 OIDC 이후에만 worker service replace
  - worker URL과 ready revision을 관찰해 same-run evidence artifact 생성
  - Cloud Tasks/Firebase Hosting/Rules 및 다른 Cloud Run service mutation은 포함하지 않음

## 검증 결과

```text
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
225 tests passed

python3 -m py_compile scripts/staging_worker_bootstrap.py scripts/tests/test_staging_worker_bootstrap.py
PASS

ruby YAML parse of staging-runtime-worker-bootstrap.yml
PASS

git diff --check
PASS
```

## 현재 외부 상태(read-only)

- candidate run [30725848106](https://github.com/WBmaker2/rhwp/actions/runs/30725848106)은 성공
- candidate evidence artifact는 확인·해시 계산 완료
- Cloud Run service: 0개
- Cloud Tasks queue: 0개
- Storage bucket: 0개
- 따라서 실제 worker URL, ready revision, task target URL은 아직 존재하지 않음
- 이 turn에서 동일한 read-only `gcloud` 목록을 새로 확인하려 했으나, 로컬 sandbox가
  `~/.config/gcloud/credentials.db` 쓰기를 차단해 실행되지 않았다. 인증 파일이나
  gcloud 설정은 변경하지 않았으며, 위 수치는 직전 성공한 read-only snapshot을 기준으로 한다.

## 현재 로컬 readiness/operator 상태

- `artifacts/actual-readiness/staging-bootstrap-readiness.json`: `ready-for-bootstrap-packet`
- `artifacts/actual-operator/staging-bootstrap-operator-status.json`:
  `ready-for-infrastructure-plan`
- 이번 Phase B 준비에서는 readiness/operator 결과를 수정하지 않았고, runtime worker
  bootstrap dispatch도 하지 않았다.

## 외부 변경을 하지 않은 항목

- Firebase Storage bucket 생성 없음
- `staging-runtime-bootstrap` Environment 생성·변경 없음
- runtime WIF provider, runtime service account, IAM 변경 없음
- worker bootstrap workflow dispatch 없음
- Cloud Run, Cloud Tasks, Firebase Hosting/Rules mutation 없음
- token, ID token, Authorization header, password, private key, service-account key,
  Firebase API key 원문, internal flush token 원문 기록 없음

## 다음 외부 승인 경계

workflow를 실행하려면 먼저 다음 exact diff를 별도로 검토해야 한다.

```diff
+ Environment: staging-runtime-bootstrap
+ Required reviewer: 최소 1명
+ Branch restriction: feat/firebase-collaboration-mvp-v1
+ preventSelfReview: false (승인된 단일 운영자 예외 정책과 일치할 때만)
+ Secrets: GCP_RUNTIME_WORKLOAD_IDENTITY_PROVIDER, GCP_RUNTIME_SERVICE_ACCOUNT
+ Variables: STAGING_PROJECT_ID, STAGING_PROJECT_NUMBER, STAGING_REGION,
+            STAGING_STORAGE_BUCKET, DOCUMENT_WORKER_SERVICE_ACCOUNT
+ Cloud role: worker service를 replace할 최소 runtime deploy 권한
+ Service account impersonation: worker runtime service account에만 제한
```

`STAGING_STORAGE_BUCKET`은 실제 관찰된 bucket만 허용하며, local readiness의 planned 값을
observed로 복사하지 않는다. 이 diff와 실제 bucket 생성 방식이 승인되기 전에는 workflow를
dispatch하지 않는다.

## Git 상태

- 계획·구현·보고서는 현재 로컬 작업 트리에만 존재하며 아직 commit/push하지 않음
- release artifact 다운로드 경로는 `.gitignore` 대상
- 기존 사용자 untracked 파일은 건드리지 않음

## 다음 실행에서 반드시 갱신할 결합

현재 release-candidate evidence는 HEAD `789ce3d59834cd6734981862f7c2d429a30bb792`에
묶여 있다. 이 worker bootstrap 구현을 commit/push한 뒤에는 HEAD가 바뀌므로 기존
candidate artifact를 재사용하지 않는다. 새 source SHA로 release-candidate를 먼저
재생성하고 새 run/attempt, artifact server digest, evidence exact-byte SHA를 기록한
다음에 worker bootstrap workflow를 dispatch한다.
