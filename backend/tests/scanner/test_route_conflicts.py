from app.scanner.route_conflicts import (
    RouteRow,
    detect_frontname_conflicts,
    detect_route_id_conflicts,
)


def _route(module_id, module_name, area="frontend", route_id="vendor_module", front_name="vendormodule"):
    return RouteRow(module_id=module_id, module_name=module_name, area=area, route_id=route_id, front_name=front_name)


def test_route_id_no_conflict_with_a_single_declarer():
    assert detect_route_id_conflicts([_route(1, "Vendor_A")]) == []


def test_route_id_no_conflict_when_the_same_module_declares_it_twice():
    routes = [_route(1, "Vendor_A"), _route(1, "Vendor_A")]
    assert detect_route_id_conflicts(routes) == []


def test_route_id_no_conflict_across_different_areas():
    # Magento's own uniqueness is scoped per area -- two modules reusing the
    # same id in different areas (frontend vs adminhtml) is not a conflict.
    routes = [
        _route(1, "Vendor_A", area="frontend", route_id="shared"),
        _route(2, "Vendor_B", area="adminhtml", route_id="shared"),
    ]
    assert detect_route_id_conflicts(routes) == []


def test_flags_a_real_cross_module_route_id_conflict():
    routes = [
        _route(1, "Vendor_A", area="frontend", route_id="shared_route"),
        _route(2, "Vendor_B", area="frontend", route_id="shared_route"),
    ]

    findings = detect_route_id_conflicts(routes)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "route_id_conflict"
        assert finding.severity == "warning"
        assert "shared_route" in finding.message
        assert "frontend" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message


def test_frontname_no_conflict_across_different_areas():
    routes = [
        _route(1, "Vendor_A", area="frontend", front_name="shared"),
        _route(2, "Vendor_B", area="adminhtml", front_name="shared"),
    ]
    assert detect_frontname_conflicts(routes) == []


def test_frontname_no_conflict_when_only_route_ids_collide():
    # Same route id, different frontName -- a route_id_conflict, not a
    # frontname_conflict; the two checks are independent.
    routes = [
        _route(1, "Vendor_A", route_id="shared_id", front_name="vendor-a"),
        _route(2, "Vendor_B", route_id="shared_id", front_name="vendor-b"),
    ]
    assert detect_frontname_conflicts(routes) == []


def test_flags_a_real_cross_module_frontname_conflict():
    routes = [
        _route(1, "Vendor_A", area="adminhtml", route_id="vendor_a", front_name="shared_front"),
        _route(2, "Vendor_B", area="adminhtml", route_id="vendor_b", front_name="shared_front"),
    ]

    findings = detect_frontname_conflicts(routes)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "frontname_conflict"
        assert finding.severity == "warning"
        assert "shared_front" in finding.message
        assert "adminhtml" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message
