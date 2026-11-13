from app.scanner.virtual_type_conflicts import VirtualTypeRow, detect_virtual_type_conflicts


def _vt(module_id, module_name, name="Vendor\\Shared\\VirtualFoo", virtual_type="Vendor\\A\\Model\\Foo"):
    return VirtualTypeRow(module_id=module_id, module_name=module_name, name=name, virtual_type=virtual_type)


def test_no_conflict_with_a_single_declarer():
    virtual_types = [_vt(1, "Vendor_A")]
    assert detect_virtual_type_conflicts(virtual_types) == []


def test_no_conflict_when_the_same_module_declares_it_twice_identically():
    virtual_types = [_vt(1, "Vendor_A"), _vt(1, "Vendor_A")]
    assert detect_virtual_type_conflicts(virtual_types) == []


def test_no_conflict_when_names_differ():
    virtual_types = [
        _vt(1, "Vendor_A", name="Vendor\\Shared\\VirtualFoo"),
        _vt(2, "Vendor_B", name="Vendor\\Shared\\VirtualBar"),
    ]
    assert detect_virtual_type_conflicts(virtual_types) == []


def test_no_conflict_when_modules_agree_on_the_same_backing_type():
    virtual_types = [
        _vt(1, "Vendor_A", virtual_type="Vendor\\Shared\\Model\\Foo"),
        _vt(2, "Vendor_B", virtual_type="Vendor\\Shared\\Model\\Foo"),
    ]
    assert detect_virtual_type_conflicts(virtual_types) == []


def test_flags_a_real_cross_module_virtual_type_conflict():
    virtual_types = [
        _vt(1, "Vendor_A", name="Vendor\\Shared\\VirtualFoo", virtual_type="Vendor\\A\\Model\\Foo"),
        _vt(2, "Vendor_B", name="Vendor\\Shared\\VirtualFoo", virtual_type="Vendor\\B\\Model\\Foo"),
    ]

    findings = detect_virtual_type_conflicts(virtual_types)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "virtual_type_conflict"
        assert finding.severity == "warning"
        assert "Vendor\\Shared\\VirtualFoo" in finding.message
        assert "Vendor_A -> Vendor\\A\\Model\\Foo" in finding.message
        assert "Vendor_B -> Vendor\\B\\Model\\Foo" in finding.message
