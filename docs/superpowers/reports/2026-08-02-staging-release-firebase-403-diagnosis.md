# Staging release candidate Firebase 403 진단

작성일: 2026-08-02

## 현재 경계

- branch: `feat/firebase-collaboration-mvp-v1`
- HEAD/원격 PR head: `521d7e3403f52c2233ede61aa17a3962a094775d`
- PR #1: Draft / open / 미병합
- PR: <https://github.com/WBmaker2/rhwp/pull/1>
- workflow run: [Staging release candidate #30721931045](https://github.com/WBmaker2/rhwp/actions/runs/30721931045)
- run head SHA: `521d7e3403f52c2233ede61aa17a3962a094775d`

이번 진단 단계에서는 workflow 재실행, API 활성화, 이미지 삭제를 하지 않았다.
이후 사용자 승인으로 최소 IAM 역할 1개를 추가했고, 정책 read-back까지 완료했다.

## 관찰된 실패

실패 job은 `Build and push immutable staging images`이며, 다음 순서까지는 모두
성공했다.

1. source commit binding 확인
2. Workload Identity Federation 인증
3. gcloud / Buildx / Artifact Registry 인증
4. collaboration 이미지 build/push
5. document-api 이미지 build/push
6. document-worker 이미지 build/push

실패한 유일한 단계는 `Resolve immutable image digests and Firebase app identity`이다.
실패 명령은 Firebase Management API의 다음 read-only 요청이다.

```text
GET https://firebase.googleapis.com/v1beta1/projects/rhwp-collaboration-staging-001/webApps
```

로그의 원문 오류는 토큰이나 Authorization header를 남기지 않고 다음으로 요약된다.

```text
curl: (22) The requested URL returned error: 403
```

따라서 self-review나 protected Environment 승인 문제가 아니다. 이 run에서는
Environment 승인이 통과했고 WIF 인증도 통과했다.

## 읽기 전용 검증 결과

### 이미지 push 결과

Artifact Registry에서 source SHA 태그를 다시 조회했고, 세 digest가 존재한다.

| image | digest |
| --- | --- |
| `collaboration:521d7e3403f52c2233ede61aa17a3962a094775d` | `sha256:847d59a6ffad36194293d0a492e9045b6f52f7ba9a9cdb8de2b7ecb3a722ac7d` |
| `document-api:521d7e3403f52c2233ede61aa17a3962a094775d` | `sha256:0861e5c98e7c866f88333350c7a88c004090a628ba128684724285b2dd276377` |
| `document-worker:521d7e3403f52c2233ede61aa17a3962a094775d` | `sha256:694bf5ea748e6e2bf0e8e549a3fa41eb6f7a1cb05f3ce520041a1c4dad984f51` |

### Firebase 상태

- `firebase.googleapis.com`: enabled
- 현재 사용자 인증 + `x-goog-user-project` 헤더로 동일 endpoint를 읽으면 HTTP 200
- 응답의 `apps` 개수: `1`
- 유일한 Web App display name: `rhwp-staging`
- 유일한 Web App ID: `1:598693744358:web:ef670ba1365f30a8117527`

API key 원문, access token, ID token, Authorization header는 출력하거나 파일에
저장하지 않았다.

### release service account IAM

WIF secret 값은 읽지 않았다. 프로젝트의 서비스 계정 목록과 IAM 정책을 읽기 전용으로
확인해 release 주체를 식별했다.

- service account: `rhwp-staging-release-pusher@rhwp-collaboration-staging-001.iam.gserviceaccount.com`
- project-level roles: `roles/viewer`, `roles/firebase.viewer`,
  `roles/serviceusage.serviceUsageConsumer`
- Artifact Registry `rhwp-staging` repository role: `roles/artifactregistry.writer`
- WIF 사용자 바인딩: repository ID 기반 `roles/iam.workloadIdentityUser`

`roles/viewer`와 `roles/firebase.viewer`에는 Firebase Web App 목록 조회에 필요한
`firebase.clients.get`, `firebase.clients.list`, `firebase.projects.get`가 포함된다.
Google 문서도 `roles/firebase.viewer`를 모든 Firebase 서비스에 대한 read-only 역할로
설명한다:
<https://firebase.google.com/docs/projects/iam/roles-predefined-all-products>.

이 조합은 다음 사실과 일치한다.

```text
WIF auth: 성공
Artifact Registry push: 성공
Firebase webApps read as release service account: 403
```

## 확정 진단

현재 실패 원인은 self-review가 아니라 workflow가 `x-goog-user-project`를 지정할 때
필요한 **`serviceusage.services.use` 권한 누락**이었다. Firebase API 자체는 활성화되어
있고, Firebase client read 권한·이미지 push·WIF도 이미 통과했다.

## 이전 IAM 적용 기록

초기 진단에서 사용자의 별도 승인으로 다음 read-only 역할을 적용했다.

```diff
 project: rhwp-collaboration-staging-001
 member: serviceAccount:rhwp-staging-release-pusher@rhwp-collaboration-staging-001.iam.gserviceaccount.com
+ role: roles/firebase.viewer
```

이 역할은 Firebase read-only predefined role이다. API key 원문을 읽는 권한이나
Firebase resource mutation 명령을 workflow에 추가하지 않는다. 적용 후 다음을
read-back한다.

1. project IAM에 위 service account의 `roles/firebase.viewer`가 정확히 존재하는지
2. 기존 `roles/viewer`, Artifact Registry writer, WIF binding이 변경되지 않았는지
3. release workflow의 Firebase `webApps` 조회가 403 없이 통과하는지

이 역할은 이번 403을 해소하지 못했으며, 제거하지 않고 유지한다.

## IAM 적용 결과

사용자 승인 후 다음 diff만 적용했다.

- project: `rhwp-collaboration-staging-001`
- member: `serviceAccount:rhwp-staging-release-pusher@rhwp-collaboration-staging-001.iam.gserviceaccount.com`
- added role: `roles/firebase.viewer`

read-back 결과 release service account의 프로젝트 역할은 `roles/viewer`와
`roles/firebase.viewer` 두 개이며, 조건부 binding은 없다. 다음 외부 설정은 변경되지
않았다.

- Artifact Registry `rhwp-staging`: 기존 `roles/artifactregistry.writer` 유지
- WIF service-account binding: 기존 repository ID 기반 `roles/iam.workloadIdentityUser` 유지
- WIF provider condition/mapping: 변경하지 않음
- GitHub Environment/secret: 변경하지 않음

이제 Firebase `webApps` 403을 해소할 수 있는 IAM read 권한이 반영된 상태다. 실제
workflow에서의 통과 여부는 새 run에서만 확인할 수 있으므로, 별도 dispatch 승인 전에는
재실행하지 않는다.

## `roles/firebase.viewer` 반영 후 새 run

사용자 dispatch 승인 후 [Staging release candidate #30723050441](https://github.com/WBmaker2/rhwp/actions/runs/30723050441)을
`feat/firebase-collaboration-mvp-v1`에서 실행했다.

- head SHA: `521d7e3403f52c2233ede61aa17a3962a094775d`
- prepare job: 성공
- protected build/push job: `staging-release` Environment 승인 완료
- WIF 인증: 성공
- 세 이미지 build/push: 성공
- Firebase `webApps` 조회: 403
- candidate artifact: 미생성

## 재현 후 진단 정정

IAM role 추가 후 새 run에서도 같은 403이 발생했다.

- 새 run: [Staging release candidate #30723050441](https://github.com/WBmaker2/rhwp/actions/runs/30723050441)
- prepare: 성공
- WIF 인증: 성공
- 세 이미지 build/push: 성공
- Firebase `webApps` 조회: 403
- candidate evidence: 미생성

역할 권한을 JSON으로 다시 비교한 결과, Google Cloud의 기본 `roles/viewer`에도 이미
`firebase.clients.get`, `firebase.clients.list`, `firebase.projects.get`가 포함되어
있다. 따라서 이전의 `roles/firebase.viewer` 부족 진단은 불완전했다. 이 역할은 사용자
승인으로 이미 추가되었지만, 이번 403을 해소하지 못했다.

workflow는 REST 요청에 `x-goog-user-project: rhwp-collaboration-staging-001`를
명시한다. Google 문서에 따르면 이 quota/billing project를 지정하려면
`serviceusage.services.use` 권한이 필요하다:
<https://docs.cloud.google.com/docs/authentication/troubleshoot-adc>.

현재 release service account에는 `serviceusage.services.use`가 없었고, 다음 최소 추가
diff가 사용자 승인으로 적용되었다.

- project: `rhwp-collaboration-staging-001`
- member: `serviceAccount:rhwp-staging-release-pusher@rhwp-collaboration-staging-001.iam.gserviceaccount.com`
- applied role: `roles/serviceusage.serviceUsageConsumer`

이 역할은 quota/billing consumer 용도이며 API enablement나 runtime resource mutation
권한을 부여하지 않는다. 정책 read-back에서 release service account의 역할은
`roles/viewer`, `roles/firebase.viewer`, `roles/serviceusage.serviceUsageConsumer`로
확인되었다. `roles/firebase.viewer`를 제거하는 것도 별도 외부 변경이므로 보존한다.

## 승인 후 다음 순서

1. 적용된 IAM role read-back은 완료했다.
2. 별도 workflow dispatch 승인 후 [Staging release candidate workflow](https://github.com/WBmaker2/rhwp/actions/workflows/staging-release-candidate.yml)를 feature branch에서 실행한다.
3. protected `staging-release` Environment 승인이 필요한 경우 해당 run의 직접 링크를 제시한다.
4. 성공한 same-run `staging-release-candidate-evidence` artifact를 원문 바이트 그대로 다운로드한다.
5. artifact digest, run ID/attempt, source commit SHA, 세 image digest, 단일 Firebase Web App ID를 기록한다.
6. candidate evidence 검증 전에는 Cloud Run/Firebase Hosting/Cloud Tasks runtime 배포를 실행하지 않는다.

## 명시적 비수행 항목

- 최신 workflow run: 실패 (`30723908230`)
- IAM 변경: `roles/serviceusage.serviceUsageConsumer` 추가 완료
- API enablement: 하지 않음
- WIF 변경: 하지 않음
- image 삭제/overwrite: 하지 않음
- Cloud Run/Firebase Hosting/Cloud Tasks 배포: 하지 않음
- secret 값/API key/token 기록: 하지 않음

## 최신 dispatch 상태

사용자 승인으로 `roles/serviceusage.serviceUsageConsumer`를 추가한 뒤, 별도
dispatch 승인에 따라 새 run을 실행했다.

- run: [Staging release candidate #30723908230](https://github.com/WBmaker2/rhwp/actions/runs/30723908230)
- event: `workflow_dispatch`
- ref: `feat/firebase-collaboration-mvp-v1`
- source/head SHA: `521d7e3403f52c2233ede61aa17a3962a094775d`
- 확인 시각: `2026-08-01T23:53:58Z`
- 현재 상태: `failure`
- prepare job: 성공 (`91432054127`)
- protected build/push job: 실패 (`91432087826`)
- WIF 인증: 성공
- 세 이미지 build/push: 성공
- Firebase `webApps` 조회: 성공
- candidate evidence: 미생성

## 최신 실패 원인: digest prefix 계약 불일치

이번 run에서는 이전 Firebase 403이 해소되었고, 다음 검증에서 fail-closed로 중단됐다.

```text
collaborationDigest is not a lowercase SHA-256 digest
```

Artifact Registry의 read-only 조회 결과는 표준 digest 접두사를 포함한다.

```text
collaboration:   sha256:f8fc7104011fbdeeda55093a2355c0ac333e180cb8d830d363dc97ae7b3c9a4d
document-api:    sha256:f3d0f5bdb799a914e83d3828ac2b74b08066b74d370036b4a8ee89bf993f6c5a
document-worker: sha256:ed2e4de4b46fb7f0d30bb5aae5cfde7e9c139c8864647ad305a4b96d2ba7fd71
```

workflow는 `sha256:` 접두사를 제거하지 않은 값을 환경 변수로 전달하면서
`[a-f0-9]{64}`만 허용하고 있다. 따라서 이미지 push나 Firebase 권한 문제가 아니다.

### 제안하는 로컬 수정 diff

세 digest 조회 직후 `sha256:` 접두사만 제거하고, 기존의 lowercase 64자리 정규식을
그대로 유지한다. 다른 문자열·알고리즘·길이는 계속 거부한다.

```diff
 collaboration_digest="$(gcloud artifacts docker images describe ... --format='value(image_summary.digest)')"
+collaboration_digest="${collaboration_digest#sha256:}"
 document_api_digest="$(gcloud artifacts docker images describe ... --format='value(image_summary.digest)')"
+document_api_digest="${document_api_digest#sha256:}"
 document_worker_digest="$(gcloud artifacts docker images describe ... --format='value(image_summary.digest)')"
+document_worker_digest="${document_worker_digest#sha256:}"
```

## 승인된 digest 정규화 구현 결과

사용자 구현 승인 후 `.github/workflows/staging-release-candidate.yml`에 작은 shell
helper를 추가했다. helper는 정확히 lowercase `sha256:` 접두사만 제거하고, 이후 기존
`[a-f0-9]{64}` 검증이 계속 최종 형식을 판정한다. 다른 알고리즘·대문자·길이 오류는
그대로 거부된다.

`scripts/tests/test_staging_release_candidate_workflow.py`에는 다음 계약 테스트를
추가했다.

- helper가 존재하는지
- `sha256:` 접두사 제거가 구현되어 있는지
- 세 이미지 digest가 helper를 거치는지
- 기존 엄격한 lowercase 64자리 검증이 유지되는지

검증 결과:

- focused release workflow tests: 7개 통과
- 전체 `scripts/tests`: 220개 통과
- workflow YAML parse: 통과
- Python compile: 통과
- `git diff --check`: 통과
- shell digest normalization smoke test: 통과

현재 수정은 로컬 working tree에만 있으며 아직 commit, push, workflow 재실행하지
않았다. 원격 반영과 새 run dispatch는 별도 승인이 필요하다.

candidate evidence가 생성되기 전에는 runtime 배포를 수행하지 않는다.
