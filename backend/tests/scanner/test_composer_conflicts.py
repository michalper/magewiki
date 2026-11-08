from app.scanner.composer_conflicts import ComposerRequirementRow, detect_composer_conflicts


def _req(module_id, module_name, package_name="vendor/pkg", constraint="^1.0"):
    return ComposerRequirementRow(
        module_id=module_id, module_name=module_name, package_name=package_name, constraint=constraint
    )


def test_no_conflict_with_a_single_requirer():
    requirements = [_req(1, "Vendor_A")]
    assert detect_composer_conflicts(requirements) == []


def test_no_conflict_when_the_same_module_requires_it_twice():
    requirements = [_req(1, "Vendor_A", constraint="^1.0"), _req(1, "Vendor_A", constraint="^2.0")]
    assert detect_composer_conflicts(requirements) == []


def test_a_module_requiring_the_same_package_twice_does_not_self_conflict_when_a_third_module_is_present():
    """Same scenario as test_no_conflict_when_the_same_module_requires_it_twice,
    but with a second module's own requirement present too -- that earlier test's
    two rows share one module_id, so the function's outer "fewer than 2 distinct
    requirers" guard already returns before ever reaching the pairwise loop.
    Adding Vendor_B's row here means the outer guard passes (2 distinct modules),
    forcing the pairwise loop to actually walk Vendor_A's own two rows against
    each other -- which must be skipped as a self-pair, not misreported as a
    conflict with itself, while Vendor_A-vs-Vendor_B is still compared normally.
    """
    requirements = [
        _req(1, "Vendor_A", constraint="^1.0"),
        _req(1, "Vendor_A", constraint="^1.5"),
        _req(2, "Vendor_B", constraint="^1.0"),
    ]
    assert detect_composer_conflicts(requirements) == []


def test_no_conflict_when_ranges_overlap():
    requirements = [_req(1, "Vendor_A", constraint=">=1.0,<2.0"), _req(2, "Vendor_B", constraint=">=1.5,<3.0")]
    assert detect_composer_conflicts(requirements) == []


def test_flags_a_real_version_conflict_across_two_modules():
    requirements = [_req(1, "Vendor_A", constraint="^6.0"), _req(2, "Vendor_B", constraint="^7.0")]

    findings = detect_composer_conflicts(requirements)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "composer_conflict"
        assert finding.severity == "warning"
        assert "vendor/pkg" in finding.message
        assert "Vendor_A requires ^6.0" in finding.message
        assert "Vendor_B requires ^7.0" in finding.message


def test_different_packages_never_collide_with_each_other():
    requirements = [
        _req(1, "Vendor_A", package_name="vendor/a", constraint="^6.0"),
        _req(2, "Vendor_B", package_name="vendor/b", constraint="^7.0"),
    ]
    assert detect_composer_conflicts(requirements) == []


def test_flags_a_magento_package_conflict_not_just_third_party_libraries():
    # Magento's own packages are deliberately not excluded -- a
    # magento/module-* version mismatch between two extensions is a real,
    # common conflict, and this check never calls Packagist (unlike the CVE
    # check, which does exclude them for an unrelated reason).
    requirements = [
        _req(1, "Vendor_A", package_name="magento/module-catalog", constraint="~102.0"),
        _req(2, "Vendor_B", package_name="magento/module-catalog", constraint="~103.0"),
    ]
    findings = detect_composer_conflicts(requirements)
    assert len(findings) == 2


def test_three_way_requirement_only_flags_the_actually_conflicting_pair():
    requirements = [
        _req(1, "Vendor_A", constraint=">=1.0,<2.0"),
        _req(2, "Vendor_B", constraint=">=1.5,<2.5"),  # overlaps both A and C
        _req(3, "Vendor_C", constraint=">=2.0,<3.0"),  # does not overlap A
    ]

    findings = detect_composer_conflicts(requirements)
    conflicting_module_ids = {module_id for module_id, _ in findings}

    assert conflicting_module_ids == {1, 3}
