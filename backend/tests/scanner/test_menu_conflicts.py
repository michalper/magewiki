from app.scanner.menu_conflicts import MenuItemRow, detect_menu_item_id_conflicts


def _item(module_id, module_name, menu_item_id="vendor_module_sample"):
    return MenuItemRow(module_id=module_id, module_name=module_name, menu_item_id=menu_item_id)


def test_no_conflict_with_a_single_declarer():
    assert detect_menu_item_id_conflicts([_item(1, "Vendor_A")]) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    items = [_item(1, "Vendor_A"), _item(1, "Vendor_A")]
    assert detect_menu_item_id_conflicts(items) == []


def test_no_conflict_when_menu_item_ids_differ():
    items = [
        _item(1, "Vendor_A", menu_item_id="vendor_a_menu"),
        _item(2, "Vendor_B", menu_item_id="vendor_b_menu"),
    ]
    assert detect_menu_item_id_conflicts(items) == []


def test_flags_a_real_cross_module_menu_item_conflict():
    items = [
        _item(1, "Vendor_A", menu_item_id="shared_menu_item"),
        _item(2, "Vendor_B", menu_item_id="shared_menu_item"),
    ]

    findings = detect_menu_item_id_conflicts(items)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "menu_item_id_conflict"
        assert finding.severity == "warning"
        assert "shared_menu_item" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message
