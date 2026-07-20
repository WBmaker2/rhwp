# M100 #2656 완료 보고 — Chrome/Edge 확장 설정 보존

- 이슈: [#2656](https://github.com/edwardkim/rhwp/issues/2656)
- 브랜치: `codex/issue-2656-extension-settings`
- 작성일: 2026-07-21

## 결과

Chrome/Edge 확장에서 사용자가 끈 `한글파일 자동보기(autoOpen=false)`가 storage key 부분
누락, storage 읽기 실패, Service Worker 재시작, 확장 설치·업데이트 수명주기 이후에도 보존될
수 있는 이중 저장·복구 구조를 구현했다.

정적 검사 결과, Chrome 업데이트 자체가 설정을 초기화한다고 단정할 수는 없었다. 대신 설치 시
기본값 재기록, options 초기화 경쟁, 저장 오류 무시, local 복구 부재가 실제 원복처럼 보일 수
있는 코드 결함임을 확인하고 모두 제거했다.

## 주요 변경

- sync의 기존 flat key를 권위 값으로 유지하고 local last-known-good snapshot을 추가했다.
- sync key가 없거나 sync 읽기가 실패한 항목만 local 값으로 복구한다.
- 저장 실패를 성공으로 표시하지 않고 UI를 실제 저장 상태로 되돌린다.
- options 입력은 storage 로드가 끝나기 전까지 비활성화한다.
- 설치·업데이트 이벤트는 사용자 설정을 쓰지 않고 최소 local 진단 메타데이터만 기록한다.
- options, message router, download interceptor가 하나의 settings adapter를 사용한다.
- 저장소·수명주기·options 경쟁/오류·기존 다운로드 동작 회귀 테스트를 추가했다.

세부 원인, 저장소 우선순위, 수동 체크리스트는
[Stage 1](../working/task_m100_2656_stage1.md)에 기록했다.

## 검증

- 변경 JavaScript `node --check`: 통과
- Chrome 확장 테스트: 31 passed, 0 failed
- 확장 dist 계약 테스트: 3 passed, 0 failed
- locale JSON parse: 통과
- source/dist 핵심 모듈 byte 비교: 통과
- `npm --prefix rhwp-chrome run build`: 통과
- `git diff --check`: 통과

자동화된 Chrome 제어는 `chrome://extensions` 내부 URL 접근이 보안 정책으로 차단되어 중단했다.
우회나 사용자 기본 프로필 설치는 수행하지 않았다. 따라서 별도 Chrome 프로필에서 옵션 재진입,
Service Worker 재시작, 비활성화/재활성화, 브라우저 재실행, 압축해제 확장 Reload, 실제 HWP/HWPX
다운로드를 확인해야 한다.

실제 Chrome Web Store 선배포는 필요하지 않다. 업데이트 이벤트의 설정 무변경 계약은 자동
테스트로 검증하며, 동일 경로 압축해제 Reload로 배포 전 수명주기 smoke test를 할 수 있다.
Web Store 업데이트 뒤의 확인은 별도 배포 인수 항목이다.

## 배포 상태

로컬 구현, 테스트, dist 빌드, 문서화까지 완료했다. remote push, PR 생성, GitHub 이슈 코멘트는
저장소 지침에 따라 사용자 승인 전에는 수행하지 않는다.
