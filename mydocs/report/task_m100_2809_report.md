# Task #2809 처리 결과 보고서 — 나눔정렬 마지막 줄과 rhwp 잘림

- 일자: 2026-07-22
- 이슈: [#2809](https://github.com/edwardkim/rhwp/issues/2809)
- 브랜치: `task/2809-distribute-align`
- 기준: `upstream/devel` `58991a768`

## 1. 결론

HWP5 `Alignment::Split`(HWPX `DISTRIBUTE_SPACE`, 한컴 UI의 나눔 정렬)을
일반 `Justify`와 같은 마지막 줄 규칙으로 처리하던 결함을 정정했다. 한 줄짜리
`다 같 이` 문단도 내부 두 공백에 남은 폭을 배분한다. 일반 `Justify`의 마지막 줄과
두 정렬의 강제 줄바꿈 억제는 기존 동작을 유지한다.

추가 실화면 검토에서 PDF는 정상이지만 rhwp WASM 화면의 위쪽 `다 같이` 마지막
글자가 잘리는 현상을 확인했다. 해당 행의 자간 `-50%`가 마지막 glyph advance만
줄이고 실제 ink 폭은 줄이지 않는 것이 원인이었다. `Split`의 slack 계산에 마지막
glyph ink overhang을 반영해 native SVG와 WASM Canvas 양쪽에서 잘림을 제거했다.

검토 중 visual sweep의 `--dpi`가 PDF에만 적용되고 SVG에는 적용되지 않는 문제도
확인해, SVG에 `dpi / 96` zoom을 적용하도록 함께 정정했다.

## 2. 원인과 수정

### 렌더러

기존 판정은 `Justify | Split`을 한 분기로 묶고 마지막 줄이면 공백 분배를 껐다.
이슈 첨부 문단은 `ParaShape ID 6`, HWP5 정렬값 `5`인 `Split`이므로 한 줄 문단에서
분배가 비활성화됐다.

`needs_word_distribution` 헬퍼로 두 정렬을 분리했다.

- `Split`: 강제 줄바꿈이 아니면 마지막 줄도 공백 분배.
- `Justify`: 기존처럼 마지막 줄(머리말·꼬리말 예외)과 강제 줄바꿈에서 억제.
- 음수 자간 `Split`에만 마지막 가시 glyph의 ink/advance 차이를 유효 사용 폭에 반영.
- 일반 `Justify`와 그 밖의 정렬, 자간 0% 행은 기존 계산을 유지.

### visual sweep

`export-svg`의 width/height는 unitless CSS px(96dpi)라 `rsvg-convert --dpi-*`만으로는
출력 크기가 바뀌지 않는다. `--dpi` 옵션값을 `dpi / 96` zoom으로 변환해 SVG에도
적용했다. 기본 96dpi 결과는 동일하고, 144dpi 이상에서 PDF와 SVG가 같은 배율로
생성된다.

## 3. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/renderer/layout/paragraph_layout.rs` | Split/Justify 마지막 줄 판정 분리, 음수 자간 ink overhang 보정, 회귀 테스트 3건 추가 |
| `tests/golden_svg/issue-617/exam-kor-page5.svg` | 한컴 2022 기준과 가까워진 `<보 기>` 나눔정렬 좌표 반영 |
| `scripts/task1274_visual_sweep.py` | `--dpi`를 SVG zoom에도 적용, 0 이하 DPI 거부 |
| `mydocs/plans/task_m100_2809*.md` | 조사·구현 계약 기록 |
| `mydocs/working/task_m100_2809_stage*.md` | 단계별 원인·검증 증적 기록 |
| `rhwp-studio/e2e/issue-2809-split-alignment.test.mjs` | 실제 WASM Canvas와 SVG 좌표 회귀 검증 |
| `samples/issues/2809/*`, `pdf/issue-2809-*.pdf` | 테스트 원본 ZIP/HWP와 정상 기준 PDF |
| `mydocs/pr/assets/task2809/*` | 수정 전·후 PNG, WASM/OVR/visual sweep 전체 증적 |

## 4. 증적

### 이슈 첨부 HWP 2쪽

- 기준 PDF: HWP 2020 변환, 6쪽, SHA-256
  `a73d50620bf8fe96beaff72ba0e40cd34f396ec75de9798ac1fd0402e28f8e2b`.
- 수정 전 첫 라벨 `다/같/이` x:
  `416.2533 / 427.4533 / 438.6533px`.
- 마지막 줄 분배만 적용한 중간 결과:
  `416.2533 / 458.9067 / 501.5600px`.
- 음수 자간 ink overhang 보정 후 native 최종 결과:
  `416.2533 / 454.9067 / 493.5600px`.
- 최종 WASM SVG 결과:
  `416.2533 / 455.2400 / 494.2267px`.
- 위쪽과 아래쪽은 원본 글자모양/LineSeg가 서로 다르다.
  - 위: 자간 `-50%`, `6972HU`, render bbox `93.0px`.
  - 아래: 자간 `0%`, `6872HU`, render bbox `91.0px`.
- 144dpi visual sweep: rhwp `845×1191`, PDF `844×1190`, 후보 `0/1`.
- rhwp Studio 2배율 Canvas: `1126×1587`, E2E assertion `4/4`.
- native 판정 PNG와 WASM Canvas에서 위·아래 `다 같이`의 마지막 글자가 모두
  clip 안에서 온전히 표시됐다. PDF는 변경하지 않은 정상 기준이다.

visual sweep의 전체 잉크 일치 보조값은 `12.95680%`다. Poppler가 한컴 전용 폰트를
대체 렌더한 영향이 커 이 수치 자체는 합격 판정으로 사용하지 않았다. 저장 LineSeg,
문자 좌표, 한컴 화면과 144dpi 판정본의 대상 라벨을 함께 최종 근거로 삼았다.

### 기존 golden 영향

`exam-kor-page5.svg`의 `<보 기>`에 마지막 줄 분배와 overhang 보정 좌표를 반영했다.
HWP 2022 PDF의 좌우 괄호는 `229.44pt / 266.88pt`, 수정 SVG 환산값은
`229.53pt / 268.09pt`다. 기존 golden 오른쪽 `261.64pt`보다 기준에 가까워
의도된 변경으로 판정했다.

### 개체 무회귀

OVR `ovr5` 5개 샘플(KTX, exam_math, 21_언어, aift, biz_plan)의 페이지 수와
개체 수가 유지됐고, 렌더러 커밋 `063061b9d`와 `devel@aa4dc00e5` 비교에서 허용오차
±2px 기준 회귀는 0건이다.

## 5. 검증

- `CARGO_INCREMENTAL=0 cargo test --lib` — `2512 passed; 0 failed; 7 ignored`.
- `CARGO_INCREMENTAL=0 cargo test --test svg_snapshot` — `8 passed; 0 failed`.
- `CARGO_INCREMENTAL=0 cargo clippy --all-targets -- -D warnings` — 통과.
- `cargo fmt --all --check`, `git diff --check` — 통과.
- `python3 -m py_compile scripts/task1274_visual_sweep.py` — 통과.
- visual sweep 96dpi/144dpi 실동작 — 각 `flagged=0/1`.
- `wasm-pack build --target web --out-dir pkg` — 통과.
- `cd rhwp-studio && npm run e2e:issue-2809` — assertion `4/4` 통과.

## 6. 후속

원본·기준·전체 증적의 파일 목록과 SHA-256은
[`mydocs/pr/assets/task2809/README.md`](../pr/assets/task2809/README.md)에 고정했다.
PR 생성 후 검토 번호가 확정되면 사전 검토문서를 `pr_{번호}_review.md`로 전환하고,
커밋 SHA 고정 URL로 PR 본문에 연결한다.
