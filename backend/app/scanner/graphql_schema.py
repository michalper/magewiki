from pathlib import Path

from graphql import parse
from graphql.error import GraphQLSyntaxError
from graphql.language import (
    FieldDefinitionNode,
    ObjectTypeDefinitionNode,
    ObjectTypeExtensionNode,
    StringValueNode,
)

from app.scanner.dto import GraphQlFieldEntry

_OPERATION_TYPES = {"Query", "Mutation", "Subscription"}


def _resolver_class(field: FieldDefinitionNode) -> str | None:
    for directive in field.directives or ():
        if directive.name.value != "resolver":
            continue
        for arg in directive.arguments or ():
            if arg.name.value == "class" and isinstance(arg.value, StringValueNode):
                return arg.value.value
    return None


def parse_graphql_schema(path: Path) -> list[GraphQlFieldEntry]:
    """Parse a module's etc/schema.graphqls into structured facts — Query/Mutation/
    Subscription fields a module adds or extends, and custom type definitions, each
    with the backing PHP resolver class from Magento's @resolver(class: "...")
    convention when present. Same role lxml plays for di.xml/events.xml: facts come
    from the parser, not the LLM.
    """
    if not path.is_file():
        return []

    try:
        document = parse(path.read_text(encoding="utf-8", errors="replace"))
    except GraphQLSyntaxError:
        return []

    entries: list[GraphQlFieldEntry] = []
    for definition in document.definitions:
        if not isinstance(definition, (ObjectTypeDefinitionNode, ObjectTypeExtensionNode)):
            continue
        type_name = definition.name.value
        operation_type = type_name if type_name in _OPERATION_TYPES else "type"
        for field in definition.fields or ():
            entries.append(
                GraphQlFieldEntry(
                    operation_type=operation_type,
                    type_name=type_name,
                    field_name=field.name.value,
                    resolver_class=_resolver_class(field),
                )
            )
    return entries
