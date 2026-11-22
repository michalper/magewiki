from app.scanner.circular_dependencies import ModuleDependencyRow, detect_circular_dependencies


def _dep(module_id, module_name, depends_on_name):
    return ModuleDependencyRow(module_id=module_id, module_name=module_name, depends_on_name=depends_on_name)


def test_no_conflict_with_a_simple_chain():
    deps = [_dep(1, "Vendor_A", "Vendor_B"), _dep(2, "Vendor_B", "Vendor_C")]
    assert detect_circular_dependencies(deps) == []


def test_no_conflict_when_a_dependency_points_outside_the_repo():
    deps = [_dep(1, "Vendor_A", "Magento_Catalog")]
    assert detect_circular_dependencies(deps) == []


def test_self_dependency_is_not_flagged():
    deps = [_dep(1, "Vendor_A", "Vendor_A")]
    assert detect_circular_dependencies(deps) == []


def test_flags_a_real_three_module_cycle():
    deps = [
        _dep(1, "Vendor_A", "Vendor_B"),
        _dep(2, "Vendor_B", "Vendor_C"),
        _dep(3, "Vendor_C", "Vendor_A"),
    ]

    findings = detect_circular_dependencies(deps)

    assert {module_id for module_id, _ in findings} == {1, 2, 3}
    for _, finding in findings:
        assert finding.check_type == "circular_dependency"
        assert finding.severity == "warning"
        assert "Vendor_A -> Vendor_B -> Vendor_C -> Vendor_A" in finding.message
        assert "setup:upgrade fails outright" in finding.message


def test_flags_a_direct_two_module_cycle():
    deps = [_dep(1, "Vendor_A", "Vendor_B"), _dep(2, "Vendor_B", "Vendor_A")]

    findings = detect_circular_dependencies(deps)

    assert {module_id for module_id, _ in findings} == {1, 2}


def test_does_not_duplicate_the_same_cycle_reached_from_different_start_nodes():
    deps = [
        _dep(1, "Vendor_A", "Vendor_B"),
        _dep(2, "Vendor_B", "Vendor_C"),
        _dep(3, "Vendor_C", "Vendor_A"),
        _dep(4, "Vendor_D", "Vendor_A"),
    ]

    findings = detect_circular_dependencies(deps)

    assert {module_id for module_id, _ in findings} == {1, 2, 3}


def test_a_chain_deeper_than_pythons_recursion_limit_does_not_crash():
    # Regression test: a real module.xml <sequence> chain in a large fleet
    # (CLAUDE.md's own 760-module reference point) can plausibly approach
    # Python's default recursion limit (1000) -- traversal must be iterative,
    # not a recursive `visit()` closure, or this raises an uncaught
    # RecursionError that fails the *whole* scan, not just this one check.
    depth = 5000
    deps = [_dep(i, f"Vendor_M{i}", f"Vendor_M{i + 1}") for i in range(depth)]

    assert detect_circular_dependencies(deps) == []


def test_a_cycle_at_the_far_end_of_a_long_chain_is_still_found():
    depth = 5000
    deps = [_dep(i, f"Vendor_M{i}", f"Vendor_M{i + 1}") for i in range(depth)]
    deps.append(_dep(depth, f"Vendor_M{depth}", "Vendor_M0"))  # closes the cycle

    findings = detect_circular_dependencies(deps)

    assert {module_id for module_id, _ in findings} == set(range(depth + 1))
