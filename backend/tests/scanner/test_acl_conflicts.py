from app.scanner.acl_conflicts import AclResourceRow, detect_acl_resource_conflicts


def _res(module_id, module_name, resource_id="Vendor_Module::foo"):
    return AclResourceRow(module_id=module_id, module_name=module_name, resource_id=resource_id)


def test_no_conflict_with_a_single_declarer():
    assert detect_acl_resource_conflicts([_res(1, "Vendor_A")]) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    resources = [_res(1, "Vendor_A"), _res(1, "Vendor_A")]
    assert detect_acl_resource_conflicts(resources) == []


def test_no_conflict_when_resource_ids_differ():
    resources = [
        _res(1, "Vendor_A", resource_id="Vendor_A::foo"),
        _res(2, "Vendor_B", resource_id="Vendor_B::bar"),
    ]
    assert detect_acl_resource_conflicts(resources) == []


def test_flags_a_real_cross_module_acl_resource_conflict():
    resources = [
        _res(1, "Vendor_A", resource_id="Vendor_Module::shared"),
        _res(2, "Vendor_B", resource_id="Vendor_Module::shared"),
    ]

    findings = detect_acl_resource_conflicts(resources)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "acl_resource_conflict"
        assert finding.severity == "warning"
        assert "Vendor_Module::shared" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message
