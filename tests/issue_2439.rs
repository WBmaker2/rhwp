//! Issue #2439: a later para-relative TopAndBottom RowBreak float can be deferred whole to a
//! fresh page by the co-anchored orphan guard. Its placement/exclusion anchor must be rebased to
//! that fresh page; retaining the previous page's `para_start_height` lets following text flow at
//! the top of the new page and overlap the deferred table.
//!
//! The synthetic fixture is narrowed from `issue1663_coanchored_float_orphan.hwpx`:
//! - a preceding paragraph gives the shared float host a non-zero page-local start;
//! - small float A remains on page 1;
//! - page-fitting float B cannot fit the remainder and is deferred whole to page 2;
//! - `AFTER FLOAT` must resume below B's exclusion, never inside B.

use rhwp::renderer::render_tree::{RenderNode, RenderNodeType};
use rhwp::wasm_api::HwpDocument;
use std::fs;
use std::path::Path;

const SAMPLE: &str = "samples/hwpx/issue2439_page_local_float_exclusion.hwpx";
const ZERO_OFFSET_STACK_SAMPLE: &str =
    "samples/issue2439_zero_offset_coanchored_float_exclusion.hwp";
const HOST_PI: usize = 1;
const TABLE_A_CI: usize = 0;
const TABLE_B_CI: usize = 1;

fn load_doc(sample: &str) -> HwpDocument {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join(sample);
    let bytes = fs::read(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    HwpDocument::from_bytes(&bytes).unwrap_or_else(|e| panic!("parse {sample}: {e}"))
}

fn find_table_bbox(
    root: &RenderNode,
    host_para_index: usize,
    control_index: usize,
) -> Option<(f64, f64)> {
    if let RenderNodeType::Table(table) = &root.node_type {
        if table.para_index == Some(host_para_index) && table.control_index == Some(control_index) {
            return Some((root.bbox.y, root.bbox.y + root.bbox.height));
        }
    }
    root.children
        .iter()
        .find_map(|child| find_table_bbox(child, host_para_index, control_index))
}

fn find_text_bbox(root: &RenderNode, needle: &str) -> Option<(f64, f64)> {
    if let RenderNodeType::TextRun(run) = &root.node_type {
        if run.text == needle {
            return Some((root.bbox.y, root.bbox.y + root.bbox.height));
        }
    }
    root.children
        .iter()
        .find_map(|child| find_text_bbox(child, needle))
}

fn find_body_bottom(root: &RenderNode) -> Option<f64> {
    if matches!(root.node_type, RenderNodeType::Body { .. }) {
        return Some(root.bbox.y + root.bbox.height);
    }
    root.children.iter().find_map(find_body_bottom)
}

#[test]
fn deferred_coanchored_float_uses_fresh_page_local_exclusion_anchor() {
    let doc = load_doc(SAMPLE);
    let page1 = doc
        .build_page_render_tree(0)
        .expect("build page 1 render tree");
    let page2 = doc
        .build_page_render_tree(1)
        .expect("build page 2 render tree");

    assert!(
        find_table_bbox(&page1.root, HOST_PI, TABLE_A_CI).is_some(),
        "small preceding float A must remain on page 1",
    );
    assert!(
        find_table_bbox(&page1.root, HOST_PI, TABLE_B_CI).is_none(),
        "page-fitting co-anchored float B must defer whole instead of leaving a fragment on page 1",
    );

    let (table_top, table_bottom) =
        find_table_bbox(&page2.root, HOST_PI, TABLE_B_CI).expect("deferred table B bbox on page 2");
    assert!(
        table_bottom > table_top,
        "deferred table must have positive height: table=[{table_top:.1},{table_bottom:.1}]",
    );

    if let Some((after_top, after_bottom)) = find_text_bbox(&page2.root, "AFTER FLOAT") {
        let body_bottom = find_body_bottom(&page2.root).expect("page 2 body bbox");
        assert!(
            after_top + 0.5 >= table_bottom,
            "following text must resume below the deferred table's fresh-page exclusion: \
             table=[{table_top:.1},{table_bottom:.1}], after_top={after_top:.1}",
        );
        assert!(
            after_bottom <= body_bottom + 0.5,
            "following text must remain inside the page body or paginate later: \
             after=[{after_top:.1},{after_bottom:.1}], body_bottom={body_bottom:.1}",
        );
    } else {
        let later_page_has_text = (2..doc.page_count()).any(|page_index| {
            doc.build_page_render_tree(page_index)
                .ok()
                .and_then(|tree| find_text_bbox(&tree.root, "AFTER FLOAT"))
                .is_some()
        });
        assert!(
            later_page_has_text,
            "following text may move to a later page, but it must not disappear",
        );
    }
}

#[test]
fn zero_offset_coanchored_float_reserves_its_full_zone_for_later_siblings() {
    let doc = load_doc(ZERO_OFFSET_STACK_SAMPLE);
    let page = doc
        .build_page_render_tree(0)
        .expect("build zero-offset stack render tree");

    let (first_top, first_bottom) =
        find_table_bbox(&page.root, 0, 2).expect("zero-offset table A bbox");
    let (second_top, second_bottom) =
        find_table_bbox(&page.root, 0, 3).expect("positive-offset table B bbox");

    assert!(
        first_bottom > first_top && second_bottom > second_top,
        "both co-anchored tables must retain positive height: A=[{first_top:.1},{first_bottom:.1}], \
         B=[{second_top:.1},{second_bottom:.1}]",
    );
    assert!(
        second_top + 0.5 >= first_bottom,
        "a zero-offset first float must reserve an exclusion zone so its positive-offset sibling \
         is stacked below it: A=[{first_top:.1},{first_bottom:.1}], B=[{second_top:.1},{second_bottom:.1}]",
    );
    let (host_text_top, _) =
        find_text_bbox(&page.root, "ISSUE 1510 CENTER TITLE").expect("visible host text bbox");
    assert!(
        host_text_top + 0.5 >= second_bottom,
        "visible host text emitted after the co-anchored table group must resume below the last \
         table: B=[{second_top:.1},{second_bottom:.1}], text_top={host_text_top:.1}",
    );
}
