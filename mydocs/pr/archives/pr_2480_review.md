# PR #2480 검토 기록

| 항목 | 내용 |
|---|---|
| 원 PR | [#2480](https://github.com/edwardkim/rhwp/pull/2480) |
| 작성자 / base | kevin9327 / `devel` |
| 검토자 | @jangster77 (검토 전 지정) |
| 규모 / 검토 스냅샷 | 2026-07-20 GitHub 조회: +36/-4, 1 file, `maintainerCanModify=true`, `mergeStateStatus=BEHIND` (동적 참고값) |
| 범위 | 문단 병합 undo 시 새 문단으로 이관되어야 할 `field_ranges` 보존 |
| 판단 | 누적 통합 PR에 수용 |

## 변경 범위와 통합
- PR 본문은 문단 split/merge undo가 field range를 새 문단으로 옮기지 않아 누름틀 필드가 소실되는 문제를 다룬다.
- PR 코멘트는 검토 시점에 없었다.
- 기여자 원 변경 `b90614163`과 회귀 `e43b74182`를 적용했다.

## 렌더 영향 판정
- 편집 모델의 undo 의미 보정이며 renderer·typeset 변경이 아니다. focused undo 회귀가 직접 근거다.

## 검증
- 누적 통합 브랜치에서 `CARGO_INCREMENTAL=0 cargo test --profile release-test --tests`, `CARGO_INCREMENTAL=0 cargo clippy --all-targets -- -D warnings`, `cargo fmt --all -- --check`, `wasm-pack build --target web --out-dir pkg`를 통과했다.
- [#2417](https://github.com/edwardkim/rhwp/issues/2417) 관련 회귀를 포함한 전체 release-test가 통과했다.

## 리스크와 권고
- split 경로의 field range 소유권만 보정하며, 다른 undo 단위와 섞지 않았다.
- **권고**: 누적 통합 PR에 수용. 최신 통합 PR head의 CI가 성공한 뒤에만 merge한다.

