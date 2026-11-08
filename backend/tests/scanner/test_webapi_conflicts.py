from app.scanner.webapi_conflicts import WebapiRouteRow, detect_webapi_route_conflicts


def _route(module_id, module_name, url="/V1/foo", http_method="GET", service_class="Vendor\\Api\\FooInterface", service_method="get"):
    return WebapiRouteRow(
        module_id=module_id,
        module_name=module_name,
        url=url,
        http_method=http_method,
        service_class=service_class,
        service_method=service_method,
    )


def test_no_conflict_with_a_single_declarer():
    routes = [_route(1, "Vendor_A")]
    assert detect_webapi_route_conflicts(routes) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    routes = [_route(1, "Vendor_A", service_method="get"), _route(1, "Vendor_A", service_method="getList")]
    assert detect_webapi_route_conflicts(routes) == []


def test_no_conflict_when_urls_differ():
    routes = [_route(1, "Vendor_A", url="/V1/foo"), _route(2, "Vendor_B", url="/V1/bar")]
    assert detect_webapi_route_conflicts(routes) == []


def test_no_conflict_when_only_the_http_method_differs():
    routes = [
        _route(1, "Vendor_A", url="/V1/foo", http_method="GET"),
        _route(2, "Vendor_B", url="/V1/foo", http_method="POST"),
    ]
    assert detect_webapi_route_conflicts(routes) == []


def test_flags_a_real_cross_module_route_conflict():
    routes = [
        _route(1, "Vendor_A", url="/V1/foo", http_method="POST", service_class="Vendor\\A\\Api\\FooInterface", service_method="save"),
        _route(2, "Vendor_B", url="/V1/foo", http_method="POST", service_class="Vendor\\B\\Api\\FooInterface", service_method="save"),
    ]

    findings = detect_webapi_route_conflicts(routes)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "webapi_route_conflict"
        assert finding.severity == "warning"
        assert "POST /V1/foo" in finding.message
        assert "Vendor_A -> Vendor\\A\\Api\\FooInterface::save" in finding.message
        assert "Vendor_B -> Vendor\\B\\Api\\FooInterface::save" in finding.message


def test_http_method_matching_is_case_insensitive():
    routes = [
        _route(1, "Vendor_A", url="/V1/foo", http_method="post"),
        _route(2, "Vendor_B", url="/V1/foo", http_method="POST"),
    ]
    findings = detect_webapi_route_conflicts(routes)
    assert len(findings) == 2


def test_different_url_path_parameter_names_are_not_treated_as_colliding():
    # Deliberately conservative: /V1/foo/:id and /V1/foo/:bar would collide on
    # a real request, but matching on the literal string only avoids a false
    # positive on two routes this check can't be certain actually collide.
    routes = [
        _route(1, "Vendor_A", url="/V1/foo/:id"),
        _route(2, "Vendor_B", url="/V1/foo/:bar"),
    ]
    assert detect_webapi_route_conflicts(routes) == []
