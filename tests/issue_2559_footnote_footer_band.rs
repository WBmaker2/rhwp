//! Issue #2559: 각주가 빈 꼬리말 밴드를 쓰지 못해 장문 문서가 과다 분할되는 회귀.
//!
//! 한글 기준은 92쪽이며, 수정 전 rhwp는 98쪽이었다. 현재 94쪽은 빈 꼬리말 밴드
//! 회수로 해소되는 +4쪽을 고정한다. 남은 +2쪽은 별도 조판 원인으로 추적한다.

use rhwp::wasm_api::HwpDocument;
use std::fs;
use std::path::Path;

#[test]
fn research_report_reclaims_empty_footer_band_for_footnotes() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("samples/issue2559/1341000_research_report_footnotes.hwp");
    let bytes = fs::read(&path).unwrap_or_else(|err| panic!("read {}: {err}", path.display()));
    let document = HwpDocument::from_bytes(&bytes)
        .unwrap_or_else(|err| panic!("parse {}: {err:?}", path.display()));

    assert_eq!(
        document.page_count(),
        94,
        "#2559 샘플은 한글 92쪽, 수정 전 98쪽이었다. 98쪽 부근이면 빈 꼬리말 밴드 회수 회귀이며, \
         92쪽에 도달하면 남은 별도 원인을 해소한 것이므로 기준을 재검토해야 한다. 실측 {}쪽.",
        document.page_count()
    );
}
