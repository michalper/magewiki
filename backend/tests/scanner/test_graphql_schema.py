from pathlib import Path

from app.scanner.graphql_schema import parse_graphql_schema


def test_parse_graphql_schema_missing_file(tmp_path: Path):
    assert parse_graphql_schema(tmp_path / "schema.graphqls") == []


def test_parse_graphql_schema_extends_query_and_mutation_with_resolver(tmp_path: Path):
    schema = tmp_path / "schema.graphqls"
    schema.write_text(
        r"""
extend type Query {
    customerOrders(filter: String): [Order] @resolver(class: "Vendor\\Module\\Model\\Resolver\\CustomerOrders")
}

extend type Mutation {
    placeCustomOrder(input: CustomOrderInput!): CustomOrderOutput
        @resolver(class: "Vendor\\Module\\Model\\Resolver\\PlaceCustomOrder")
}

type CustomOrderOutput {
    order_id: String
}
""",
        encoding="utf-8",
    )

    entries = parse_graphql_schema(schema)
    by_field = {(e.type_name, e.field_name): e for e in entries}

    query_field = by_field[("Query", "customerOrders")]
    assert query_field.operation_type == "Query"
    assert query_field.resolver_class == "Vendor\\Module\\Model\\Resolver\\CustomerOrders"

    mutation_field = by_field[("Mutation", "placeCustomOrder")]
    assert mutation_field.operation_type == "Mutation"
    assert mutation_field.resolver_class == "Vendor\\Module\\Model\\Resolver\\PlaceCustomOrder"

    custom_type_field = by_field[("CustomOrderOutput", "order_id")]
    assert custom_type_field.operation_type == "type"
    assert custom_type_field.resolver_class is None


def test_parse_graphql_schema_field_without_resolver_directive(tmp_path: Path):
    schema = tmp_path / "schema.graphqls"
    schema.write_text("type Query {\n    simpleField: String\n}\n", encoding="utf-8")

    entries = parse_graphql_schema(schema)
    assert len(entries) == 1
    assert entries[0].resolver_class is None


def test_parse_graphql_schema_malformed_sdl_returns_empty(tmp_path: Path):
    schema = tmp_path / "schema.graphqls"
    schema.write_text("this is not { valid graphql sdl !!!", encoding="utf-8")

    assert parse_graphql_schema(schema) == []


def test_parse_graphql_schema_ignores_a_non_resolver_directive_and_a_non_object_definition(tmp_path: Path):
    schema = tmp_path / "schema.graphqls"
    schema.write_text(
        'scalar CustomScalar\n\ntype Query {\n    field(arg: String): String @deprecated(reason: "unused")\n}\n',
        encoding="utf-8",
    )

    entries = parse_graphql_schema(schema)

    assert len(entries) == 1
    assert entries[0].resolver_class is None
