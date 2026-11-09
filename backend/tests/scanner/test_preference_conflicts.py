from app.scanner.preference_conflicts import PreferenceRow, detect_preference_conflicts


def _pref(module_id, module_name, for_type="Vendor\\Api\\FooInterface", preference_type="Vendor\\A\\Model\\Foo"):
    return PreferenceRow(module_id=module_id, module_name=module_name, for_type=for_type, preference_type=preference_type)


def test_no_conflict_with_a_single_declarer():
    preferences = [_pref(1, "Vendor_A")]
    assert detect_preference_conflicts(preferences) == []


def test_no_conflict_when_the_same_module_declares_it_twice_identically():
    preferences = [_pref(1, "Vendor_A"), _pref(1, "Vendor_A")]
    assert detect_preference_conflicts(preferences) == []


def test_no_conflict_when_for_types_differ():
    preferences = [
        _pref(1, "Vendor_A", for_type="Vendor\\Api\\FooInterface"),
        _pref(2, "Vendor_B", for_type="Vendor\\Api\\BarInterface"),
    ]
    assert detect_preference_conflicts(preferences) == []


def test_no_conflict_when_modules_agree_on_the_same_implementation():
    preferences = [
        _pref(1, "Vendor_A", preference_type="Vendor\\Shared\\Model\\Foo"),
        _pref(2, "Vendor_B", preference_type="Vendor\\Shared\\Model\\Foo"),
    ]
    assert detect_preference_conflicts(preferences) == []


def test_flags_a_real_cross_module_preference_conflict():
    preferences = [
        _pref(1, "Vendor_A", for_type="Vendor\\Api\\FooInterface", preference_type="Vendor\\A\\Model\\Foo"),
        _pref(2, "Vendor_B", for_type="Vendor\\Api\\FooInterface", preference_type="Vendor\\B\\Model\\Foo"),
    ]

    findings = detect_preference_conflicts(preferences)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "preference_conflict"
        assert finding.severity == "warning"
        assert "Vendor\\Api\\FooInterface" in finding.message
        assert "Vendor_A -> Vendor\\A\\Model\\Foo" in finding.message
        assert "Vendor_B -> Vendor\\B\\Model\\Foo" in finding.message
