from app.scanner.graphql_conflicts import GraphQlFieldRow, detect_graphql_field_conflicts


def _field(
    module_id,
    module_name,
    operation_type="Query",
    type_name="Query",
    field_name="customField",
    resolver_class="Vendor\\A\\Model\\Resolver\\CustomField",
):
    return GraphQlFieldRow(
        module_id=module_id,
        module_name=module_name,
        operation_type=operation_type,
        type_name=type_name,
        field_name=field_name,
        resolver_class=resolver_class,
    )


def test_no_conflict_with_a_single_declarer():
    fields = [_field(1, "Vendor_A")]
    assert detect_graphql_field_conflicts(fields) == []


def test_no_conflict_when_the_same_module_declares_it_twice_identically():
    fields = [_field(1, "Vendor_A"), _field(1, "Vendor_A")]
    assert detect_graphql_field_conflicts(fields) == []


def test_no_conflict_when_field_names_differ():
    fields = [_field(1, "Vendor_A", field_name="fieldA"), _field(2, "Vendor_B", field_name="fieldB")]
    assert detect_graphql_field_conflicts(fields) == []


def test_no_conflict_when_only_the_type_differs():
    fields = [
        _field(1, "Vendor_A", type_name="Query", operation_type="Query"),
        _field(2, "Vendor_B", type_name="ProductInterface", operation_type="type"),
    ]
    assert detect_graphql_field_conflicts(fields) == []


def test_no_conflict_when_modules_agree_on_the_same_resolver():
    fields = [
        _field(1, "Vendor_A", resolver_class="Vendor\\Shared\\Model\\Resolver\\CustomField"),
        _field(2, "Vendor_B", resolver_class="Vendor\\Shared\\Model\\Resolver\\CustomField"),
    ]
    assert detect_graphql_field_conflicts(fields) == []


def test_flags_a_real_cross_module_graphql_field_conflict():
    fields = [
        _field(1, "Vendor_A", resolver_class="Vendor\\A\\Model\\Resolver\\CustomField"),
        _field(2, "Vendor_B", resolver_class="Vendor\\B\\Model\\Resolver\\CustomField"),
    ]

    findings = detect_graphql_field_conflicts(fields)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "graphql_field_conflict"
        assert finding.severity == "warning"
        assert "Query.customField" in finding.message
        assert "Vendor_A -> Vendor\\A\\Model\\Resolver\\CustomField" in finding.message
        assert "Vendor_B -> Vendor\\B\\Model\\Resolver\\CustomField" in finding.message


def test_flags_a_conflict_when_one_module_has_no_resolver():
    fields = [
        _field(1, "Vendor_A", resolver_class="Vendor\\A\\Model\\Resolver\\CustomField"),
        _field(2, "Vendor_B", resolver_class=None),
    ]

    findings = detect_graphql_field_conflicts(fields)

    assert {module_id for module_id, _ in findings} == {1, 2}
    assert "no resolver" in findings[0][1].message
