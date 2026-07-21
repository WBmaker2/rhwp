# planet6897 열린 PR 통합 검토 - Stage 1

## 목적

2026-07-21 기준 planet6897 기여자의 열린 PR #2662, #2663, #2664, #2665,
#2666, #2669, #2671, #2706을 최신 `upstream/devel` 위에서 체리픽해 충돌과
상호작용을 검토한다. 결과는 원본 PR을 직접 병합하지 않고, 필요한 메인터너 보정을
포함한 통합 PR로 제안한다.

## 사전 확인

- 각 원본 PR에 `edwardkim` reviewer를 지정했다.
- 기준점: `upstream/devel`의 #2702 병합 commit `c4e6faa3`.
- 각 PR 본문과 현재 토론을 확인했다. 원본 PR 토론에는 별도 reviewer 피드백이 없다.
- 렌더 영향 PR은 #2665(OOXML chart), #2669(본문 재래핑), #2671(SVG 폰트
  임베딩)이다. #2663은 HWPX/PDF 기준 자료를 추가하므로 시각 검증 대상이다.

## 통합 순서

1. 재현 자료와 단위 회귀: #2662, #2663, #2664.
2. 렌더 로직: #2665, #2669, #2671.
3. 검증 기록: #2666, #2706.
4. 충돌은 최신 `devel`의 동작을 우선해 해결하고, 원 PR의 유효한 의도만 보존한다.

## 메인터너 보정 후보

- #2671: 테스트가 SVG 전체의 임의 `data:font`만 찾으므로, 대상 embedded face의
  `@font-face`가 실제 data URI인지 직접 고정한다.
- #2666: #2627 제출본을 지칭하는 역사적 survey 결과가 현재 병합된 #2702 통합본과
  모순되지 않는지 출처와 잔여 범위를 재확인한다.

## 검증 계획

- focused Rust/Node 회귀 테스트와 `cargo clippy --all-targets -- -D warnings`.
- #2663의 HWPX/PDF 쪽수 및 visual sweep, #2665/#2669/#2671의 대상 렌더 결과.
- 통합 후 전체 `cargo test --profile release-test --tests`.
