# Task #2809 중간 보고서 — 나눔정렬 마지막 줄과 문단 속성 차이

- 일자: 2026-07-22
- 이슈: [#2809](https://github.com/edwardkim/rhwp/issues/2809)
- 브랜치: `task/2809-distribute-align`
- 기준: `upstream/devel` `58991a768`
- 상태: Stage 2 완료, 실제 rhwp 최종 렌더 경로 분석 필요

## 1. 결론

HWP5 `Alignment::Split`(HWPX `DISTRIBUTE_SPACE`, 한컴 UI의 나눔 정렬)을
일반 `Justify`와 같은 마지막 줄 규칙으로 처리하던 결함을 정정했다. 한 줄짜리
`다 같 이` 문단도 내부 두 공백에 남은 폭을 배분한다. 일반 `Justify`의 마지막 줄과
두 정렬의 강제 줄바꿈 억제는 기존 동작을 유지한다.

추가 실화면 검토에서 문제는 잘림이 아니라 위쪽과 아래쪽 `다 같이` 문단이 rhwp에서
같아 보이는 것임을 재확인했다. 위쪽은 자간 `-50%`/`6972HU`, 아래쪽은 자간
`0%`/`6872HU`로 원문 속성이 다르다. 잘림으로 오인해 추가했던 glyph overhang
보정은 이 차이를 상쇄하므로 제거했다.

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
- 일반 `Justify`와 그 밖의 정렬, 원문 자간과 LineSeg는 기존 값을 유지.

### visual sweep

`export-svg`의 width/height는 unitless CSS px(96dpi)라 `rsvg-convert --dpi-*`만으로는
출력 크기가 바뀌지 않는다. `--dpi` 옵션값을 `dpi / 96` zoom으로 변환해 SVG에도
적용했다. 기본 96dpi 결과는 동일하고, 144dpi 이상에서 PDF와 SVG가 같은 배율로
생성된다.

## 3. 변경 파일

| 파일 | 변경 |
|---|---|
| `src/renderer/layout/paragraph_layout.rs` | Split/Justify 마지막 줄 판정 분리, 회귀 테스트 2건 추가 |
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
- native 위쪽 최종 결과: `416.2533 / 458.9067 / 501.5600px`,
  span `85.3067px`.
- native 아래쪽 최종 결과: `417.5333 / 455.7467 / 493.9600px`,
  span `76.4267px`.
- WASM SVG/페이지 레이어 트리 span: 위 `85.44px`, 아래 `76.693px`.
- 위쪽과 아래쪽은 원본 글자모양/LineSeg가 서로 다르다.
  - 위: 자간 `-50%`, `6972HU`, render bbox `93.0px`.
  - 아래: 자간 `0%`, `6872HU`, render bbox `91.0px`.
- 144dpi visual sweep: rhwp `845×1191`, PDF `844×1190`, 후보 `0/1`.
- rhwp Studio 2배율 Canvas: `1126×1587`, E2E assertion `5/5`.
- rhwp 편집기 페이지 보기 100% 화면을 별도 캡처한 결과, 위·아래 문단은 여전히
  같게 보여 미해결로 판정했다. PDF는 변경하지 않은 정상 기준이다.

visual sweep의 전체 잉크 일치 보조값은 `12.95680%`다. Poppler가 한컴 전용 폰트를
대체 렌더한 영향이 커 이 수치 자체는 합격 판정으로 사용하지 않았다. 저장 LineSeg,
문자 좌표와 실제 화면이 불일치하므로 현재 수치는 중간 진단 근거로만 사용한다.

### 기존 golden 영향

`exam-kor-page5.svg`의 `<보 기>`에 마지막 줄 분배 좌표를 반영했다.
HWP 2022 PDF의 좌우 괄호는 `229.44pt / 266.88pt`, 수정 SVG 환산값은
`229.53pt / 268.84pt`다. 기존 golden 오른쪽 `261.64pt`보다 기준에 가까워
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
- `cd rhwp-studio && npm run e2e:issue-2809` — assertion `5/5` 통과.

## 6. 후속

Stage 3에서 최종 렌더 백엔드의 문자별 위치 재생 경로를 분석하고 실제 화면 픽셀
회귀 검증을 추가한다. 수정 완료 후 원본·기준·전체 증적과 SHA-256을 다시 생성하고
사전 PR 검토를 재개한다.
