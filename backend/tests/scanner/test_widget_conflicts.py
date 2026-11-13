from app.scanner.widget_conflicts import WidgetRow, detect_widget_id_conflicts


def _widget(module_id, module_name, widget_id="vendor_module_sample"):
    return WidgetRow(module_id=module_id, module_name=module_name, widget_id=widget_id)


def test_no_conflict_with_a_single_declarer():
    assert detect_widget_id_conflicts([_widget(1, "Vendor_A")]) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    widgets = [_widget(1, "Vendor_A"), _widget(1, "Vendor_A")]
    assert detect_widget_id_conflicts(widgets) == []


def test_no_conflict_when_widget_ids_differ():
    widgets = [
        _widget(1, "Vendor_A", widget_id="vendor_a_widget"),
        _widget(2, "Vendor_B", widget_id="vendor_b_widget"),
    ]
    assert detect_widget_id_conflicts(widgets) == []


def test_flags_a_real_cross_module_widget_conflict():
    widgets = [
        _widget(1, "Vendor_A", widget_id="shared_widget"),
        _widget(2, "Vendor_B", widget_id="shared_widget"),
    ]

    findings = detect_widget_id_conflicts(widgets)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "widget_id_conflict"
        assert finding.severity == "warning"
        assert "shared_widget" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message
