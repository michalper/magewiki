from app.scanner.cache_type_conflicts import CacheTypeRow, detect_cache_type_conflicts


def _type(module_id, module_name, cache_type_id="vendor_module_sample", instance=None):
    return CacheTypeRow(module_id=module_id, module_name=module_name, cache_type_id=cache_type_id, instance=instance)


def test_no_conflict_with_a_single_declarer():
    assert detect_cache_type_conflicts([_type(1, "Vendor_A", instance="Vendor\\A\\Cache")]) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    types = [
        _type(1, "Vendor_A", instance="Vendor\\A\\Cache"),
        _type(1, "Vendor_A", instance="Vendor\\A\\Cache"),
    ]
    assert detect_cache_type_conflicts(types) == []


def test_no_conflict_when_cache_type_ids_differ():
    types = [
        _type(1, "Vendor_A", cache_type_id="vendor_a_cache", instance="Vendor\\A\\Cache"),
        _type(2, "Vendor_B", cache_type_id="vendor_b_cache", instance="Vendor\\B\\Cache"),
    ]
    assert detect_cache_type_conflicts(types) == []


def test_no_conflict_when_both_modules_declare_the_same_instance():
    types = [
        _type(1, "Vendor_A", instance="Vendor\\Shared\\Cache"),
        _type(2, "Vendor_B", instance="Vendor\\Shared\\Cache"),
    ]
    assert detect_cache_type_conflicts(types) == []


def test_no_conflict_when_one_module_only_overrides_cosmetic_attributes():
    # Vendor_B re-declares the same name to override just the label, never
    # setting instance -- a real, intentional pattern, not a disagreement.
    types = [
        _type(1, "Vendor_A", instance="Vendor\\A\\Cache"),
        _type(2, "Vendor_B", instance=None),
    ]
    assert detect_cache_type_conflicts(types) == []


def test_flags_a_real_cross_module_cache_type_conflict():
    types = [
        _type(1, "Vendor_A", cache_type_id="shared_cache", instance="Vendor\\A\\Cache"),
        _type(2, "Vendor_B", cache_type_id="shared_cache", instance="Vendor\\B\\Cache"),
    ]

    findings = detect_cache_type_conflicts(types)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "cache_type_conflict"
        assert finding.severity == "warning"
        assert "shared_cache" in finding.message
        assert "Vendor_A -> Vendor\\A\\Cache" in finding.message
        assert "Vendor_B -> Vendor\\B\\Cache" in finding.message
