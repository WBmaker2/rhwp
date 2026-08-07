# Fresh preflight Environment 값 로그 노출 방지 계획

작성일: 2026-08-06 (Asia/Seoul)

## 목표

`staging-config-validate.yml`의 deployment live preflight가 GitHub Environment 변수 9개를 step-level `env`로 선언하면서 `STAGING_INTERNAL_FLUSH_DECISION` 원문을 Actions log에 출력하는 문제를 제거합니다. 승인된 운영값은 변경하거나 추측하지 않고, workflow runner 내부에서만 materializer에 전달합니다.

## 설계

1. live job의 materializer step은 `GITHUB_TOKEN`으로 보호 Environment 변수 REST API를 조회하지 않습니다.
2. 보호 Environment 변수는 step-level `env`로 runner에 주입하되, inline Python이 값을 JSON stdin으로만 materializer에 전달합니다. JSON은 로그 표준출력으로 내보내지 않습니다.
3. materializer에 JSON stdin 입력 모드를 추가합니다. 입력은 기존 9개 `STAGING_*` 키를 가진 객체이며, 기존 schema/승인 decision 검증을 그대로 적용합니다.
4. `gh api` 응답이나 decision 값을 로그·artifact·report에 출력하지 않습니다.
5. 누락 변수, schema 오류, 승인 decision 불일치 시 즉시 fail-closed합니다. Environment 변수 API를 `GITHUB_TOKEN`으로 조회하는 우회는 사용하지 않습니다.
6. 기존 `staging-bootstrap`의 9개 Environment Variable 계약과 `--from-environment` 경로는 유지합니다.

## 검증

- JSON stdin materializer 단위 테스트
- workflow contract test에서 live materializer에 step-level `STAGING_*: ${{ vars.* }}`가 없고 `gh api` stdin 경로가 있는지 확인
- 전체 `scripts/tests` 및 `validate_staging_config.py`
- `git diff --check`
- 수정 commit/push 후 `staging-preflight` WIF provider의 `attribute.workflow_sha`를 새 HEAD로 갱신
- fresh preflight를 실행하기 전에 release run `31100043557` 및 worker run `31101493543`의 `headSha`가 새 HEAD와 일치하는지 확인
- source-bound artifact가 이전 HEAD에 묶여 있으면, 해당 증거를 새 HEAD에서 재생성하기 전까지 fresh preflight를 실행하지 않음

## 외부 경계

이 수정은 GitHub workflow source와 WIF provider source-binding만 변경합니다. fresh preflight 자체는 read-only GCP/Firebase query이며, preflight 성공만으로 deployment mutation을 실행하지 않습니다. release/worker evidence는 source commit에 묶여 있으므로 새 HEAD와 불일치하면 재생성 승인 없이 우회하지 않습니다.
