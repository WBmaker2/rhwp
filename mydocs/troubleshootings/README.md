# 트러블슈팅 문서 지도

이 디렉터리는 재현 가능한 증상에 대해 확정된 원인, 적용 가능한 대응, 검증 방법을 보존한다.
새 작업에서는 관련 증상이 있는지 먼저 확인하되, 문서의 코드 위치와 테스트는 현재 `devel`에서
다시 검증한다.

## 최근 분류된 레이아웃·왕복 충실도 항목

- [하단 앵커의 선언 높이와 실측 높이 불일치](bottom_anchor_declared_vs_rendered_height.md)
- [HWPX 표 outMargin과 common.margin 동기화](hwpx_table_out_margin_common_margin_sync.md)
- [micro-grid 셀 여백의 HWPX/HWP5 왕복 불일치](microgrid_cell_margin_roundtrip.md)
- [HWPX visibility와 표 flowWithText 직렬화 보존](hwpx_visibility_and_flow_with_text_serialization.md)
- [deferred RowBreak 표의 분할 예산](deferred_rowbreak_table_split_budget.md)
- [PDF 폰트 리소스 채번 비결정](pdf_font_numbering_nondeterminism.md)

미확정 가설, 잔여 유형 분류, 당시 기준선은 `mydocs/tech/investigations/`에 보존한다.
