# Task #2809 Stage 1 — Split 마지막 줄 분배와 glyph 잘림 정정

- 브랜치: `task/2809-distribute-align`
- 선행: [`task_m100_2809_stage0.md`](task_m100_2809_stage0.md)
- 상태: 완료

## 1. 구현

- `src/renderer/layout/paragraph_layout.rs`
  - `needs_word_distribution` 헬퍼를 추가했다.
  - `Alignment::Split`은 마지막 줄을 포함해 공백 분배를 활성화하되, 기존 강제
    줄바꿈 억제 동작은 유지한다.
  - `Alignment::Justify`는 기존 마지막 줄·강제 줄바꿈 억제 조건을 유지한다.
  - 음수 자간에서는 마지막 glyph의 ink가 advance보다 넓은 차이를 `Split`의 유효
    사용 폭에만 반영해 셀 clip 밖으로 밀리지 않게 했다.
  - 일반 `Justify`와 다른 정렬 경로는 변경하지 않았다.

## 2. 회귀 테스트

- `split_distributes_single_last_line_but_justify_does_not`
  - 한 줄짜리 마지막 줄: Split=true, Justify=false.
  - 일반 Justify 중간 줄=true.
  - 강제 줄바꿈 Split=false로 기존 동작 유지.
- `split_label_assigns_positive_slack_to_interior_spaces`
  - `다 같 이`, 자연폭 30px, 가용폭 90px의 두 내부 공백에 각 30px를 배분.
  - 글자 간격과 dash 간격은 0 유지.
- `split_reserves_last_glyph_ink_when_letter_spacing_is_negative`
  - 음수 자간의 마지막 glyph ink overhang을 포함한 최종 폭이 셀 폭과 일치함.

초기 결과:

```text
3 passed; 0 failed
```

## 3. 이슈 원본 시각 확인

- 수정 전 첫 반복부 `다/같/이`: `416.2533 / 427.4533 / 438.6533px`.
- 마지막 줄 분배만 적용한 중간 결과: `416.2533 / 458.9067 / 501.5600px`.
- 음수 자간 ink overhang 보정 후 native 최종 결과:
  `416.2533 / 454.9067 / 493.5600px`.
- 최종 WASM SVG 결과: `416.2533 / 455.2400 / 494.2267px`.
- 대상 셀 clip: `x=414.3733`, `width=96.6667px`; 좌우 inner 여백을 제외한 전체
  폭에 세 글자가 배치됐다.
- 후반 반복부도 같은 방식으로 셀 전체에 분산됐다.
- 수정 후 SVG를 1.5배(약 144dpi) PNG로 렌더해 HWP 2020 기준 PDF 2쪽과 대조했으며,
  문제 라벨의 좌우 분산이 의미상 일치한다. 시스템 대체 폰트 차이는 본 타스크 범위가 아니다.

### 위쪽/아래쪽 라벨 차이 재확인

- 위쪽 라벨은 `charPrIDRef=4`(자간 `-50%`), `LineSeg.horzsize=6972HU`다.
- 아래쪽 라벨은 `charPrIDRef=11`(자간 `0%`), `LineSeg.horzsize=6872HU`다.
- 따라서 내부 글자 간격은 원문부터 다르며, 수정 후 render tree bbox는 각각
  `93.0px`, `91.0px`로 저장 LineSeg 폭을 따른다.
- 위쪽만 음수 자간 overhang 보정 대상이며 아래쪽 자간 0% 행은 기존 좌표를 유지한다.
- 144dpi native 래스터와 rhwp Studio의 2배율 WASM Canvas에서 위·아래 마지막
  `이`가 모두 온전히 표시됨을 확인했다.

## 4. visual sweep DPI 정정

- `scripts/task1274_visual_sweep.py`의 `--dpi`는 종전 PDF `pdftoppm`에만 적용되고,
  unitless CSS px 크기의 SVG에는 적용되지 않았다.
- SVG 변환에 `dpi / 96` zoom을 함께 적용해 양쪽 래스터를 같은 목표 DPI로 만든다.
- `--dpi 144` 실측:
  - rhwp PNG `845×1191`
  - 기준 PDF PNG `844×1190`
  - 자동 후보 `flagged=0/1`
  - `pixel_match=89.29287%`, `visual_accuracy_proxy=12.95680%`
- 잉크 일치 보조값은 한컴 전용 폰트의 Poppler 대체 렌더 차이가 커 합격 게이트로
  사용하지 않고, 라벨 좌표와 144dpi 육안 판정을 최종 근거로 사용했다.

## 5. 검증 결과

- `CARGO_INCREMENTAL=0 cargo test --lib`: `2512 passed; 0 failed; 7 ignored`.
- `CARGO_INCREMENTAL=0 cargo test --test svg_snapshot`: `8 passed; 0 failed`.
- `CARGO_INCREMENTAL=0 cargo clippy --all-targets -- -D warnings`: 통과.
- `cargo fmt --all --check`: 통과.
- `python3 -m py_compile scripts/task1274_visual_sweep.py`: 통과.
- OVR `--preset ovr5 --diff-against devel`: 5개 샘플, 개체 회귀 0건.
- `wasm-pack build --target web --out-dir pkg`: 통과.
- `cd rhwp-studio && npm run e2e:issue-2809`: assertion 4건 통과,
  Canvas `1126×1587`.

`exam-kor-page5.svg`의 `<보 기>`는 마지막 줄 분배와 overhang 보정을 반영했다.
HWP 2022 기준 PDF 괄호 좌표(`229.44pt / 266.88pt`)와 수정 SVG 환산 좌표
(`229.53pt / 268.09pt`)가 기존 golden 오른쪽(`261.64pt`)보다 가까워 의도된
나눔정렬 정정으로 판정하고 golden을 갱신했다.
