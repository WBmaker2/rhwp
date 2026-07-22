# Task #2809 검증 증적

이 디렉터리는 PDF가 아닌 rhwp native/WASM 렌더링에서 발생한 나눔정렬 마지막
glyph 잘림을 검증한 증적을 보관한다. 기준 PDF는 정상 비교본이며 변경 대상이 아니다.

## 입력과 기준

| 파일 | 역할 | SHA-256 |
|---|---|---|
| `samples/issues/2809/jubo_20260104.zip` | 이슈 첨부 원본 묶음 | `93ed974ee185d7ff89d3971fedbe04372af2340e1c81d5091c6180b1fc8d3849` |
| `samples/issues/2809/jubo_20260104.hwp` | rhwp 입력 HWP 6쪽 | `3fb2e25a8bd57ec8f2c8b2754613e3e69ace831d441a63f601f6dbea8e79d3ac` |
| `pdf/issue-2809-jubo_20260104-2020.pdf` | 정상 기준 PDF 6쪽 | `a73d50620bf8fe96beaff72ba0e40cd34f396ec75de9798ac1fd0402e28f8e2b` |

## 직접 확인 자료

- `jubo_p2_144dpi_before_overhang_fix_review.png`: 마지막 글자가 우측 clip에 걸린 중간 결과.
- `jubo_p2_144dpi_after_{compare,overlay,review}.png`: 최종 native 144dpi 비교.
- `jubo_p2_wasm_canvas_2x.png`: 최종 `pkg`를 rhwp Studio가 그린 2배율 Canvas.
- `issue-2809-split-alignment-report.html`: WASM E2E assertion 4건 보고서.
- `jubo_p2_96dpi_{compare,overlay,review}.png`: visual sweep DPI 수정 전후 호환 확인용.

## 전체 산출물

| 파일 | 내용 | SHA-256 |
|---|---|---|
| `task2809_visual_sweep_144dpi_final.tar.gz` | SVG 6쪽, render tree 6쪽, PDF/rhwp PNG, 분석 JSON, compare/overlay/review | `1242f55e3138bcb2f476c6697c4dd18aae5302cf9630e093afea93e9e38d09e8` |
| `task2809_ovr_complete.tar.gz` | 렌더러 커밋 `063061b9d` OVR5 전체 산출물 | `6244283aea90f11b479a5c6aa5438bdc5796bf360f52c74cba2ae4812bb1f4b2` |
| `jubo_p2_wasm_canvas_2x.png` | 최종 WASM Canvas | `7f8bbe00e7bdf4b7aada35f5b96302ac3d5158ee51bc834ab4a484324431611c` |
| `issue-2809-split-alignment-report.html` | 최종 E2E HTML | `c88a7958228f5ce5f734d637d874e95ba2e40d664c2712a9a6e9d1e466da5d6e` |

## 재현 명령

```bash
wasm-pack build --target web --out-dir pkg
cd rhwp-studio && npm run e2e:issue-2809
python3 scripts/task1274_visual_sweep.py \
  --key task2809-jubo \
  --hwp samples/issues/2809/jubo_20260104.hwp \
  --pdf pdf/issue-2809-jubo_20260104-2020.pdf \
  --page 2 --dpi 144 \
  --out output/task2809-visual-144-final \
  --rhwp-bin target/debug/rhwp
python3 tools/object_visual_regression.py \
  --preset ovr5 -o output/task2809-ovr-committed --diff-against devel
```

최종 좌표는 native `416.2533 / 454.9067 / 493.5600px`, WASM
`416.2533 / 455.2400 / 494.2267px`이며 마지막 `이`가 셀 clip 안에 있다.
