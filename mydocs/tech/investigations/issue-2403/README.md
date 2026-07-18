---
kind: investigation
status: active
canonical: mydocs/tech/investigations/issue-2403/README.md
last_verified: 2026-07-19
---

# #2403 Stage 1 — Provenance/Profile advisory baseline

- 기준 commit: 생성 시점 devel merge 상태 (커밋 메시지 참조) / 빌드:
  `cargo build --profile release-test`
- 생성·대조: `./scripts/advisory_snapshot.sh <dir>` → 단계 게이트마다 재생성 후
  `diff -r` (advisory — 무변동 기대, Phase P 규정 `plans/refactoring_plan_2026.md` §3·§7)

| 자산 | 파일 | 내용 |
|------|------|------|
| public Rust API 표면 | `advisory/api_surface.txt` (3,034줄) | src pub 선언 정규화 시그니처 목록 (grep 기반 결정적 추출) |
| CLI output 계약 | `advisory/cli_output.txt` | info·dump-pages × HWP5/HWP3/HWPX 대표 3샘플 |
| WASM/render-tree JSON 계약 | `advisory/render_tree_sha256.txt` | export-render-tree p0 구조 해시 3건 |

재현성: 동일 커밋에서 2회 생성 `diff -r` 바이트 동일 검증 완료 (2026-07-19).

## 1단계 재고정 (2026-07-19)

- api_surface 정규화에서 **줄번호 제외**로 스크립트 보정 (무관 필드 추가로 전
  항목이 밀리는 노이즈 — 1단계 실측) 후 baseline 재고정.
- 1단계 의도 delta (검토 완료, 추가 7건뿐 — 이동/제거 0):
  `model/provenance.rs` 신설(SourceFormat/SourceProvenance/
  LayoutCompatibilityProfile + 질의 2), `Document::layout_profile`,
  `pub mod provenance`. CLI output·render-tree 해시는 **무변동**.
