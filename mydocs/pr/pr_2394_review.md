# PR #2394 검토 — document-scoped CanvasKit auto 선택 (seo-rii 5번째)

- Refs #536, P34~P36 후속 (P37 계열). 58파일 +5,540/−281
- 본질: 브라우저 기본 요청 canvas2d → **auto** — fail-closed preflight 가
  문서 전체 단위로 CanvasKit 적합성을 판정(page/work/blocker/font 상한 내
  bounded 스캔, 전체 JSON/리소스 복제 없음)해 적합 revision 만 CanvasKit,
  나머지는 이유를 남기고 문서 전체 Canvas2D. per-op/mid-page 혼합 fallback
  없음. 명시적 override(renderer=canvas2d/canvaskit) 유지.

## 검토 소견

- **fail-closed 설계 일관**: 부적합·불완전·리소스/폰트 준비 실패·초기화 오류
  전부 Canvas2D 수렴 — 조용한 부분 렌더 없음. #2372 direct PDF 와 같은 결.
- **경계 규율**: unsupported op 신규 구현 없음, native Skia/PDF/SVG 불변,
  전체 corpus hard gate 승격 없음(대표 5종만) — "하지 않는 것" 명시.
- **Rust 측**: read_bin_data_limited 등 상한 있는 스트림 읽기(초과 시 명시
  에러), canvaskit_policy.rs typed preflight, wasm_api 질의 1 추가.
- **계약 테스트**: 선택 흐름 자체를 소스 가드로 고정 (auto→preflight→
  ensureCanvasKitRenderer 경로, fallback reason 스키마).
- **e2e/MANIFEST**: 신규 파일 없음, 72=72 정합. #2403 parser 변경과 자동
  병합 — 스위트로 상호작용 무결 확인.

## 잔여 질의 1건 (게이트 완화)

`renderer_baseline_manifest.json` table-core(hwp_table_test.hwp)
inkMaskMaxDiffRatio **0.0185→0.019** (+2.7% 상대) — 커밋("harden VS Code
package contracts")·본문 모두 근거 서술 없음. CanvasKit AA 차이 추정이나
시각 예산 완화는 근거 필수 — 컨트리뷰터 질의 대상.

## 로컬 재실증 (merged tree, devel 충돌 0)

| 게이트 | 결과 |
|--------|------|
| cargo fmt/clippy --all-targets -D warnings | 통과 / 0 |
| 전체 스위트(release-test) | 실패 0 |
| studio: npm ci→tsc→test→build | tsc OK / 388/388 / 빌드 OK |
| npm/editor node --test | 18/18 |
| CI (Render Diff·readiness 포함) | 전 항목 green |

## 판정 대기

1. 컨트리뷰터 질의(임계 완화 근거) 회신
2. **작업지시자 브라우저 시각 확인** — 기본 백엔드 선택 변경이므로 관례상
   최종 판정. `cd rhwp-studio && npm run dev` 후 대표 문서(표 중심 +
   이미지 중심 각 1)에서 auto 선택 백엔드 확인 (진단: 콘솔 renderer
   selection 로그 / F12).
