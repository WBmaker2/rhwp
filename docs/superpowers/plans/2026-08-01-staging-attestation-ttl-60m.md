# Staging attestation TTL 60분 변경 계획

**작성일:** 2026-08-01
**대상 브랜치:** `feat/firebase-collaboration-mvp-v1`
**목표:** 수동 승인·보호된 Environment 검토 지연으로 attestation이 만료되는 운영 경합을 줄이기 위해, Environment/WIF operator attestation의 최대 유효기간을 15분에서 60분으로 늘리고 검증 계약·테스트·운영 문서를 함께 갱신한다.

## 현재 진단

- 변경 전 공통 상수 `MAX_ATTESTATION_TTL`은 15분이었다.
- Environment 및 WIF attestation의 `expiresAt`은 이 상수로 생성된다.
- freshness 검증은 관찰 시각부터 상수보다 긴 window를 거부한다.
- 승인 declaration의 만료 상한만 늘려서는 충분하지 않으며, 승인 시각과 Environment/WIF attestation window가 모두 겹쳐야 한다.
- 최근 workflow run #14는 TTL 만료가 아니라 workflow 입력 SHA와 Repository 변수의 exact-byte package SHA 불일치로 `prepare`에서 fail-closed 되었다. 이 변경은 해당 SHA 불일치를 자동으로 해결하지 않는다.

## 구현 범위

1. `MAX_ATTESTATION_TTL`을 60분으로 변경한다.
2. 60분 window의 정상·초과·만료 경계 테스트를 갱신하거나 추가한다.
3. refresh/prepare 운영 문서에 60분 window와 재생성 원칙을 기록한다.
4. 변경 후 focused test, 관련 unittest, 정적 검사를 실행한다.
5. SHA 입력이 필요한 외부 단계는 복사 가능한 Markdown 코드 박스로 제시한다.

## 보안 경계

- TTL을 workflow dispatch 입력이나 Repository 변수로 임의 조정하지 않는다. 소스 계약에 고정된 60분만 허용한다.
- package의 `cloudMutationApproved=false`, `deploymentApproved=false`, `mutationCommands=[]` 불변 조건을 유지한다.
- 이번 작업에서는 GitHub 변수 갱신, Environment 변경, workflow dispatch, WIF/IAM/API/Secret/resource mutation, build/push/deploy를 수행하지 않는다.
- 60분 window를 넘긴 package·attestation·approval은 재사용하지 않고 새로 생성한다.

## 후속 승인 경계

코드 검증이 끝난 뒤에는 새 source commit 기준으로 attestation/package를 다시 생성해야 한다. 새 exact-byte apply-ready SHA 승인, Repository 변수 갱신 승인, workflow dispatch 승인은 각각 별도 단계로 요청한다.

## 구현 결과

- `scripts/staging_infrastructure_operator_attestation.py`의 `MAX_ATTESTATION_TTL`을 60분으로 변경했다.
- Environment/WIF attestation 생성 expiry와 apply executor fixture가 공통 상수를 사용하도록 정렬했다.
- 60분 정각은 허용하고 61분 window는 fail-closed 하는 경계 테스트를 추가·갱신했다.
- `docs/runbooks/staging-infrastructure-bootstrap.md`에 source-level 고정 60분 정책과 만료 시 재생성 원칙을 반영했다.
- 집중 unittest 26개, 전체 Python unittest 198개, `py_compile`, `validate_staging_config.py`, `git diff --check`를 통과했다.
- 커밋, push, Repository/Environment 변수 변경, workflow dispatch, WIF/IAM/API/Secret/resource mutation, build/push/deploy는 수행하지 않았다.
