# planet6897 열린 PR 통합 검토 - Stage 3

## 목적

통합 브랜치가 각 원 PR의 본문과 후속 코멘트에서 약속한 범위를 유지하는지, 전체
회귀·WASM·브라우저·Windows 검증으로 최종 확인한다. 이 단계에서는 PR review 문서,
오늘할일, 원격 push를 만들지 않는다.

## 검증 범위

1. `CARGO_INCREMENTAL=0 cargo test --profile release-test --tests`와
   `CARGO_INCREMENTAL=0 cargo clippy --all-targets -- -D warnings`를 수행한다.
2. `rhwp-studio` WASM build와 #2664 TypeScript 단위 테스트를 수행한다.
3. #2671의 `export-svg --embed-fonts` 산출물을 Blink 기반 브라우저에서 직접
   렌더링해 BinData 글꼴 data URI가 실제로 사용 가능한지 확인한다.
4. `win10-ted`의 기본 SSH 셸, cmd, PowerShell에서 한양 4종 identity 아티팩트
   검증 스크립트를 수행하고, 필요한 개발 도구 설치 내역을 기록한다.
5. #2663/#2665/#2669 visual sweep의 잔여와 원 PR 범위를 구분해 최종 리뷰의
   merge 판단 근거로 정리한다.

## 완료 기준

- 전체 Rust 회귀와 clippy, WASM build, Node 단위 테스트가 성공한다.
- 브라우저 SVG 렌더에서 임베디드 글꼴이 두부 문자나 로컬 폴백 없이 표시된다.
- Windows 3개 셸 검증의 결과가 일치한다.
- 잔여 조판 fidelity가 구현 범위를 넘어서는 경우에도, 원 PR 본문에 이미 명시된
  비목표인지 구분해 merge 보류 여부를 판단할 수 있다.
