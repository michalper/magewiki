from app.scanner.indexer_conflicts import IndexerRow, detect_indexer_conflicts


def _idx(module_id, module_name, indexer_id="vendor_module_sample"):
    return IndexerRow(module_id=module_id, module_name=module_name, indexer_id=indexer_id)


def test_no_conflict_with_a_single_declarer():
    assert detect_indexer_conflicts([_idx(1, "Vendor_A")]) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    indexers = [_idx(1, "Vendor_A"), _idx(1, "Vendor_A")]
    assert detect_indexer_conflicts(indexers) == []


def test_no_conflict_when_indexer_ids_differ():
    indexers = [
        _idx(1, "Vendor_A", indexer_id="vendor_a_indexer"),
        _idx(2, "Vendor_B", indexer_id="vendor_b_indexer"),
    ]
    assert detect_indexer_conflicts(indexers) == []


def test_flags_a_real_cross_module_indexer_conflict():
    indexers = [
        _idx(1, "Vendor_A", indexer_id="shared_indexer"),
        _idx(2, "Vendor_B", indexer_id="shared_indexer"),
    ]

    findings = detect_indexer_conflicts(indexers)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "indexer_id_conflict"
        assert finding.severity == "warning"
        assert "shared_indexer" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message
