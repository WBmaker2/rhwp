# PR #3241 검토 기록 — imgDim 없는 그림의 적응식 crop 폴백 복원

## 메타와 통합 판단

| 항목 | 내용 |
| --- | --- |
| 원 PR | [#3241](https://github.com/edwardkim/rhwp/pull/3241) |
| 작성자 / 관련 이슈 | `planet6897` / [#3239](https://github.com/edwardkim/rhwp/issues/3239) (open 유지) |
| 원 PR 기준 / head | `devel@1b5950a951f81b70717b6a1e351f643f8cd399b2` / `3847a548aa43cfa232a1c6dce0378464731b96bf` |
| 문서 작성 시점 참고값 | OPEN, non-draft, MERGEABLE/BEHIND, maintainerCanModify=true, reviewer `jangster77`, maintainer 보류·리뷰 코멘트 없음. 원 head CI의 preflight·Lint·Native Skia·8개 default-feature shard·CodeQL·Canvas visual diff·Build & Test 모두 성공 (2026-07-24 조회). |
| 검토 브랜치 / 통합 기준 | `integrate/planet6897-20260724` / `upstream/devel@973de548faedc6709ef862a1a12aa7146c225ac5` |
| 누적 순서 | 2/2 — #3224 → #3241 |
| 체리픽 | `3847a548` → `6ce59e4`; `src/renderer/svg.rs` 자동 병합, 충돌 없음 |
| 최종 merge 조건 | 통합 PR 최신 head의 required CI 성공 및 작업지시자 승인 |

## 관련 이슈와 변경 범위

#3239는 `imgDim`을 보존하지 않는 구형 HWP5의 비-96dpi 스캔 그림에서, 고정 75 HU/px crop 폴백이
원본 이미지를 과소 계산해 확대·절단하는 r22 회귀다. 이 PR은 `compute_image_crop_src`의 우선순위를
`imgDim` → 유효한 crop right/bottom과 디코딩 크기로 계산하는 적응 폴백 → 유효한 기준이 전혀 없을 때의
75 HU/px 최후 폴백으로 바꾼다.

- `src/renderer/svg.rs`: 공유 crop source-rect 계산만 바꾼다. SVG, Native Skia, web canvas가 같은 계산을
  사용하므로 renderer 영향이 있다.
- `src/renderer/svg/tests.rs`: 기존 `imgDim` 부재 가정 2개를 새 의미에 맞추고, #3239의 200dpi TIFF와
  invalid crop의 최후 폴백을 각각 고정한다.
- `samples/issue3239/`: 실제 HWP 입력과 r19 기준 PNG를 추가한다.
- `tools/verify_issue3239.py`: Native Skia `export-png` 결과와 기준 PNG의 diff>40 픽셀 비율을 2% 미만으로
  확인한다. 기본 실행 파일은 Windows식 `target/debug/rhwp.exe`이므로 macOS/Linux에서는 `--exe`를
  명시해야 한다.

## 로컬 검증

모든 cargo 계열 명령은 `CARGO_INCREMENTAL=0`,
`CARGO_TARGET_DIR=target/planet6897-20260724-review`로 순차 실행했다.

| 게이트 | 결과 |
| --- | --- |
| `cargo test --release --lib` | 2,890 passed, 0 failed, 7 ignored |
| `cargo test --profile release-test --tests` | PASS (기본 feature unit·integration suite, `svg_snapshot` 포함) |
| Native Skia 공식 `skia --lib` | 56 passed |
| Native Skia `issue_2225_missing_picture_placeholder` | 2 passed |
| Native Skia `render_p37_direct_pdf_export` | 4 passed |
| `cargo fmt --check` / `cargo clippy --all-targets -- -D warnings` | PASS / warning 없음 |
| `cargo test --doc` | 4 passed, 0 failed, 2 ignored |
| `wasm-pack build --target web` | PASS — 사용자 `pkg/`를 보존하기 위해 `output/pr-review-3241-20260724/pkg`에 생성 |
| `python3 tools/verify_issue3239.py --exe target/planet6897-20260724-review/release/rhwp` | PASS — diff>40 픽셀 비율 0.00% (임계 2.0%) |

## 시각 검증과 증적

원본은 `samples/issue3239/evaluation_form_200dpi_scan.hwp`이며 SHA-256은
`34e5ca1df74196c2ddcfa3b24cbda9cdb0099441dfc7e066d15a780d52668367`이다. HWP 2020 MCP로
한 페이지 A4 기준 PDF `pdf/issue3239/evaluation_form_200dpi_scan-2020.pdf`를 생성했다.

| 기준 PDF 항목 | 값 |
| --- | --- |
| SHA-256 | `c4d53bd1b29f2148b6c300e0b9c5025757dbb82f3ce2f34a47fbf6e97c5ca952` |
| MCP job | `1e57cfac-bd05-409f-b938-c481320b39b6` |
| 서버 결과 / PDF | `run_status=0`, `validation=ok`, 1 page |

PDF/SVG visual sweep은 `output/pr-review-3241-20260724/pr3241-issue3239/{compare,overlay,review}/`에
보존했다. 요청 범위는 원본 1쪽, 자동 후보는 0건이며 overlay 수치는 pixel match 97.38298%,
visual accuracy proxy 0.30334%다. 하지만 이 수치는 **통과 근거로 쓰지 않는다**. SVG가
`data:image/tiff`를 포함하는데 스윕의 SVG rasterizer가 이를 해석하지 못해 `review/review_200.png`의
rhwp 쪽이 비었다. 파일명 `200`도 페이지 번호가 아니라 `200dpi` stem을 잘못 읽은 식별자다.

대신 Native Skia `export-png`를 직접 렌더하고 r19 기준 PNG와 비교했다. 사람이 확인한
`mydocs/pr/assets/pr_3241_planet6897_issue3239_p001_review.png`에는 좌측 Native Skia 결과와 우측 r19
기준이 모두 표시되며, 표·본문·서명 전체가 잘리지 않고 일치한다. 이 비교의 SHA-256은
`8eb7d77e4f3308904037148800a27631f47dfa93d75e28657f62e202d2cc5d53`이다. 이는 #3239가 고친
Native crop 회귀의 직접 증거이며, TIFF data URI를 브라우저/SVG로 재생하는 별도 호환성 문제까지 해결했다는
주장은 아니다.

## 리스크와 권고

- `imgDim`도 없고 crop bounds만 있는 파일은 원본 전체 범위와 의도적 부분 crop을 완전히 구별할 추가
  메타데이터가 없다. 이 PR은 기존 Native Skia의 적응식 해석을 공유 helper로 복원하며, `imgDim` 경로와
  invalid bounds의 75 HU/px 보호 경로를 테스트로 보존했다.
- HWP 2020 PDF는 장기 기준으로 보존했지만, TIFF data URI의 SVG rasterizer 제한 때문에 PDF/SVG 픽셀 수치는
  merge 판단에 사용하지 않았다. 이 제한은 PR이 새로 만든 문제가 아니며 별도 SVG/TIFF 재생 범위다.
- #3239은 통합 merge가 실제로 issue를 해결한 뒤에만 close 여부를 판단한다. merge 전에는 원 이슈와 원 PR을
  변경하지 않는다.

**권고: 수용.** 최신 `devel` 통합 tree에서 코드·Native Skia·WASM과 실제 200dpi HWP 회귀 재현을 모두
확인했다. 원 PR 대신 #3224와 함께 통합 PR을 만들고, 그 최신 CI 성공 뒤 admin merge를 진행한다.
