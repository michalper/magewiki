from app.scanner.mview_conflicts import MviewRow, detect_mview_conflicts


def _view(module_id, module_name, view_id="vendor_module_sample"):
    return MviewRow(module_id=module_id, module_name=module_name, view_id=view_id)


def test_no_conflict_with_a_single_declarer():
    assert detect_mview_conflicts([_view(1, "Vendor_A")]) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    mviews = [_view(1, "Vendor_A"), _view(1, "Vendor_A")]
    assert detect_mview_conflicts(mviews) == []


def test_no_conflict_when_view_ids_differ():
    mviews = [
        _view(1, "Vendor_A", view_id="vendor_a_view"),
        _view(2, "Vendor_B", view_id="vendor_b_view"),
    ]
    assert detect_mview_conflicts(mviews) == []


def test_flags_a_real_cross_module_mview_conflict():
    mviews = [
        _view(1, "Vendor_A", view_id="shared_view"),
        _view(2, "Vendor_B", view_id="shared_view"),
    ]

    findings = detect_mview_conflicts(mviews)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "view_id_conflict"
        assert finding.severity == "warning"
        assert "shared_view" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message
