# Staging 최초 worker bootstrap 준비 계획

**작성일:** 2026-08-02
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`
**범위:** Phase A release-candidate evidence를 입력으로 받는 Phase B worker bootstrap의 로컬 계약과 보호된 workflow 준비

## 목적

release-candidate run `30725848106`은 세 image digest와 Firebase Web App ID를 확정했지만,
현재 staging project에는 Cloud Run service, Cloud Tasks queue, Storage bucket이 없다. 최초
runtime 배포 전에 실제 worker URL과 revision을 추측하지 않도록, worker만 별도 protected 단계에서
배포하고 관찰 evidence를 생성한다.

## 구현 범위

1. candidate evidence의 exact schema, source commit, release run/attempt, artifact digest를
   fail-closed로 검증하는 로컬 helper를 추가한다.
2. verified worker digest와 실제 운영 bucket을 사용해 Cloud Run worker YAML을 임시 경로에
   렌더링한다. raw secret/API key와 unresolved placeholder를 허용하지 않는다.
3. `staging-runtime-bootstrap` protected workflow를 추가한다.
   - `prepare`: credential 없이 candidate artifact를 읽고 검증한다.
   - `bootstrap`: 보호 환경 승인과 OIDC 이후에만 `gcloud run services replace`를 실행한다.
   - worker service 외의 Cloud Run service, Cloud Tasks, Firebase Hosting/Rules는 변경하지 않는다.
   - 성공 후 worker URL과 revision을 same-run artifact로 기록한다.
4. workflow 구조·helper 회귀 테스트를 추가한다.
5. exact Environment/GCP 설정 diff와 실행 전 중단 조건을 Markdown으로 남긴다.

## 외부 변경 승인 경계

구현과 로컬 테스트만으로는 다음을 실행하지 않는다.

- Firebase Storage bucket 생성
- `staging-runtime-bootstrap` Environment 생성·변경
- runtime WIF provider/서비스 계정/IAM 변경
- workflow dispatch
- Cloud Run, Cloud Tasks, Firebase Hosting/Rules mutation

현재 `gcloud storage buckets list`가 비어 있으므로 local readiness의 planned bucket을
observed 값으로 복사하지 않는다.
실제 bucket 생성 또는 확인 후에만 workflow 입력으로 허용한다.

## 실행 후 불변 결합

- candidate workflow run ID/attempt
- candidate artifact server digest
- candidate evidence exact-byte SHA-256
- source commit SHA
- worker image repository와 lowercase SHA-256 digest
- observed Storage bucket
- bootstrap workflow run ID/attempt
- worker URL와 latest ready revision

어느 결합도 일치하지 않으면 후속 final manifest/live preflight로 진행하지 않는다.

## source commit 갱신 주의

현재 candidate evidence는 `789ce3d59834cd6734981862f7c2d429a30bb792`에 묶여 있다. 이
로컬 구현을 commit/push하면 workflow checkout의 HEAD가 새 SHA가 되므로 기존 candidate
artifact를 재사용할 수 없다. push 후에는 새 source SHA로 release-candidate를 다시
생성하고, 새 run ID·attempt·artifact digest·evidence exact-byte SHA를 다시 결합한 뒤에만
worker bootstrap dispatch를 검토한다.

## 예상 산출물

- `scripts/staging_worker_bootstrap.py`
- `scripts/tests/test_staging_worker_bootstrap.py`
- `.github/workflows/staging-runtime-worker-bootstrap.yml`
- `docs/superpowers/reports/2026-08-02-staging-worker-bootstrap-preparation.md`

## 다음 승인 요청

로컬 구현·테스트가 끝난 뒤 별도로 다음을 승인받는다.

1. 이 로컬 구현 파일만 feature branch에 commit/push
2. 새 HEAD에 대한 release-candidate 재실행 및 새 artifact 결합
3. 실제 Firebase Storage bucket 생성/확인 방식과 bucket 이름
4. `staging-runtime-bootstrap` Environment 및 WIF/IAM exact diff
5. 새 run-bound evidence를 사용하는 worker bootstrap workflow dispatch
