use rhwp::collaboration::{NodeKind, StableId};

#[test]
fn stable_id_is_deterministic_for_same_source_and_path() {
    let first = StableId::for_node("sha256:abc", NodeKind::Paragraph, &[0, 4]);
    let second = StableId::for_node("sha256:abc", NodeKind::Paragraph, &[0, 4]);

    assert_eq!(first, second);
}

#[test]
fn stable_id_changes_when_node_path_changes() {
    let first = StableId::for_node("sha256:abc", NodeKind::Cell, &[0, 2, 1]);
    let second = StableId::for_node("sha256:abc", NodeKind::Cell, &[0, 2, 2]);

    assert_ne!(first, second);
}
