# Task 5 로컬 구현 결과

**작성일:** 2026-08-01
**브랜치:** `feat/firebase-collaboration-mvp-v1`
**기준:** 현재 로컬 checkout의 pre-push 검증 결과
**범위:** deployment preflight 입력 경계와 release metadata 검증 구현만 수행

## 구현된 내용

1. `staging-preflight` live job이 보호 Environment의 9개 운영 변수를
   `staging_bootstrap_materializer.py --from-environment`로 materialize한다.
2. materializer 결과를 deployment packet에 직접 넘기지 않고,
   `scripts/staging_deployment_manifest.py`가 source commit-bound release metadata와 결합한다.
3. resolver는 project number, Firebase Web App ID와 API key reference, 서비스별 canonical Artifact
   Registry repository, lowercase image digest, task URL, rollback revision을 exact schema로 검증한다.
4. placeholder, raw Firebase API key, 민감 key, source commit 불일치, 잘못된 서비스 image 경로는
   인증 전에 fail-closed한다. 오류 메시지에는 민감한 값 원문을 포함하지 않는다.
5. static/live preflight와 deployment approval packet은 최종
   `artifacts/staging-manifest-deployment-preflight.json`만 사용한다.
6. workflow dispatch에 `release_metadata_path` 입력을 추가했다. metadata가 없으면 packet 생성이나
   WIF 인증을 시작하지 않는다.
7. metadata의 release workflow run/attempt를 GitHub Actions read-only API로 재조회하고, 성공 완료 상태와
   현재 checkout의 `GITHUB_SHA`를 독립적으로 대조한다.
8. 최초 배포에서 rollback revision이 없을 수 있는 계약을 `deploymentStage=initial`과 세 개의
   명시적 `null`로 보정하고, `upgrade`는 실제 revision ID만 허용한다.

## 검증 결과

```text
python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v
213 tests passed

python3 scripts/validate_staging_config.py
staging manifest and configuration templates are valid; no deployment was performed

python3 -m py_compile scripts/staging_deployment_manifest.py \
  scripts/staging_bootstrap_materializer.py scripts/staging_approval_packet.py
PASS

git diff --check
PASS
```

## 외부 Environment 준비 확인

사용자 승인 범위에서 `staging-preflight`에 normalized readiness와 exact하게 일치하는 비밀 아닌
Environment Variable 9개를 등록하고 read-back 검증했다. 검증 결과는 이름·개수·계약 일치 여부만
출력했으며 실제 값 원문은 로그나 문서에 남기지 않았다.

- Environment: `staging-preflight`
- 등록 변수: 9개, normalized readiness와 모두 일치
- WIF read-only secret: 미등록
- 보호 규칙: required reviewer `WBmaker2`, `preventSelfReview=false`, branch policy rule 존재

## 현재 중단 지점

- 실제 source-commit-bound release metadata artifact가 아직 없다.
- `staging-preflight` WIF read-only secret이 없으므로 live preflight를 dispatch하지 않았다.
- 최초 배포 전 rollback revision이 없을 수 있는 충돌은 `deploymentStage=initial`과
  `[null, null, null]`을 사용하는 로컬 계약으로 보정했다. `upgrade` 단계는 실제 revision 세 개를
  계속 요구하며, 임의 ID는 허용하지 않는다.
- infrastructure apply가 Cloud Run service를 만들지 않았으므로 최초 worker `run.app` URL도 아직
  없다. 따라서 worker bootstrap 이후 최종 task URL을 결합하는 2단계 runtime 배포가 필요하다.
- image build/push, Cloud Run/Firebase deployment, IAM/API/WIF/Secret/인프라 mutation은 수행하지
  않았다. (이번 승인으로 적용한 9개 비밀 아닌 Environment Variable 등록은 외부 GitHub 설정 변경이다.)

## 순서 결정

deployment packet은 세 image digest와 rollback revision을 요구한다. 그러므로 deployment approval 뒤에
처음으로 build/push를 수행하는 순서는 성립하지 않는다. 별도 release-candidate 승인 경계에서 immutable
build/push evidence와 source-commit-bound metadata를 먼저 만든 뒤, 이 Task 5 live preflight가 그 metadata를
검증하고 packet을 생성해야 한다. 기존 infrastructure approval record나 `deploymentApproved` 값을 재사용하지
않는다.

## 다음 승인 필요 사항

1. release-candidate build/push와 metadata 생성 방식 승인
2. 별도 read-only WIF provider와 최소 권한 service account를 확정하고
   `staging-preflight` secret 등록 승인
3. metadata와 WIF가 준비된 뒤 live preflight workflow dispatch 승인
4. 생성된 deployment packet의 exact-byte SHA-256 승인
5. 별도 deployment approval record 승인

외부 조치가 필요한 경우 정확한 화면 링크를 함께 제시하고, 사용자가 직접 입력해야 하는 값만 복사 가능한
형식으로 안내한다.
