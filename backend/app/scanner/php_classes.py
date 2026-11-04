from pathlib import Path

from tree_sitter import Node

from app.scanner.discovery import walk_module_php_files
from app.scanner.dto import PhpClassEntry, PhpMethodEntry
from app.scanner.php_parser import find_all, node_text, parse_php

_DECLARATION_TYPES = {"class_declaration", "interface_declaration", "trait_declaration"}
_KIND_BY_NODE_TYPE = {
    "class_declaration": "class",
    "interface_declaration": "interface",
    "trait_declaration": "trait",
}


def _names_in_clause(clause: Node, source: bytes) -> list[str]:
    return [node_text(c, source) for c in clause.children if c.type in ("name", "qualified_name")]


def _file_namespace(root: Node, source: bytes) -> str | None:
    namespaces = find_all(root, {"namespace_definition"})
    if not namespaces:
        return None
    name_node = next((c for c in namespaces[0].children if c.type == "namespace_name"), None)
    return node_text(name_node, source) if name_node is not None else None


def _extract_methods(class_body: Node, source: bytes) -> list[PhpMethodEntry]:
    methods = []
    for method_node in find_all(class_body, {"method_declaration"}):
        name_node = method_node.child_by_field_name("name")
        if name_node is None:
            continue
        methods.append(
            PhpMethodEntry(
                name=node_text(name_node, source),
                start_line=method_node.start_point[0] + 1,
                end_line=method_node.end_point[0] + 1,
            )
        )
    return methods


def parse_php_file(path: Path, relative_file_path: str) -> list[PhpClassEntry]:
    source = path.read_bytes()
    tree = parse_php(source)
    namespace = _file_namespace(tree.root_node, source)

    entries: list[PhpClassEntry] = []
    for decl in find_all(tree.root_node, _DECLARATION_TYPES):
        name_node = decl.child_by_field_name("name")
        if name_node is None:
            continue
        class_name = node_text(name_node, source)

        extends: list[str] = []
        implements: list[str] = []
        for child in decl.children:
            if child.type == "base_clause":
                extends.extend(_names_in_clause(child, source))
            elif child.type == "class_interface_clause":
                implements.extend(_names_in_clause(child, source))

        body = decl.child_by_field_name("body")
        methods = _extract_methods(body, source) if body is not None else []

        entries.append(
            PhpClassEntry(
                fqcn=f"{namespace}\\{class_name}" if namespace else class_name,
                namespace=namespace,
                class_name=class_name,
                kind=_KIND_BY_NODE_TYPE[decl.type],
                extends=extends,
                implements=implements,
                file_path=relative_file_path,
                start_line=decl.start_point[0] + 1,
                end_line=decl.end_point[0] + 1,
                methods=methods,
            )
        )

    return entries


def catalog_module_classes(module_root: Path) -> list[PhpClassEntry]:
    entries: list[PhpClassEntry] = []
    for php_file in walk_module_php_files(module_root):
        relative_file_path = str(php_file.relative_to(module_root))
        try:
            entries.extend(parse_php_file(php_file, relative_file_path))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
    return entries
