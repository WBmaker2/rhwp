# Staging Infrastructure 단일 운영자 예외 구현 계획

**작성일:** 2026-07-31

**대상:** `staging-infrastructure-apply` protected Environment 계약

**승인:** 사용자가 `WBmaker2`, `preventSelfReview=false` 단일 운영자 예외와 operator public-key
registry onboarding 및 official REST admin-bypass 관찰 예외를 명시적으로 승인함

## 목적

승인 가능한 GitHub 사용자가 `WBmaker2` 한 명뿐인 현재 저장소에서 same-run evidence publication을
유지한다. Required reviewer 자체를 제거하지 않고 `WBmaker2`를 reviewer로 유지하되 self review를
허용한다. Administrator bypass 금지, exact-byte 승인, run binding, WIF/IAM 및 dispatch 별도 승인은
완화하지 않는다.

## 구현

1. protected Environment review spec의 `preventSelfReview`를 `false`로 변경한다.
2. Environment operator attestation이 required reviewer 최소 1명과 `prevent_self_review=false`를
   정확히 검증하도록 변경한다.
3. attestation canonical observed contract와 합성 테스트를 같은 값으로 갱신한다.
4. 승인된 Ed25519 public key와 exact PEM SHA-256만 immutable source registry에 추가한다.
5. private key는 ignored operator-local 경로에 권한 `0600`으로만 보관하고 Git·로그·artifact에 넣지 않는다.
6. runbook과 Task 4 gate 문서에 단일 운영자 예외 및 잔여 위험을 기록한다.
7. 실제 정책 목표 `canAdminsBypass=false`와 REST 관찰 결과를 분리한다. 공식 GET Environment 응답에서
   필드가 정확히 누락된 경우에만 `unavailable-in-official-rest`를 기록하고, 값이 `true`, `null` 또는
   다른 형태로 존재하면 fail-closed한다.
8. Environment attestation/query schema를 새 버전으로 올리고 이전 schema를 apply-ready 입력으로
   재사용하지 않는다.

## 유지하는 안전 경계

- required reviewer 최소 1명
- reviewer `WBmaker2`
- GitHub UI의 `canAdminsBypass=false` 설정 요구
- REST가 값을 제공하면 정확히 `false`만 허용
- REST 필드 누락 예외는 단일 운영자 계약에서만 허용하며 사람의 `false` 진술로 바꿔 기록하지 않음
- protected branch policy는 feature branch 하나만 허용
- secrets와 long-lived cloud credentials 없음
- `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]` 유지
- Environment/WIF/IAM 변경과 workflow dispatch는 별도 승인 전 미실행
- admin-bypass 외 모든 Environment/WIF 관찰 불가 상태는 promotion fail-closed

## 검증

- 실제 pinned public key와 operator-local private key의 Ed25519 preflight
- Environment attestation focused tests
- apply review, hardening, executor focused tests
- 전체 `scripts/tests`
- staging configuration validator
- `py_compile`, `git diff --check`

변경 후 executor commit과 review package digest가 달라지므로 기존 package 승인은 실제 apply 권한으로
재사용하지 않는다. 새 원격 commit에서 package를 재생성하고 다시 exact-byte 승인을 받는다.
