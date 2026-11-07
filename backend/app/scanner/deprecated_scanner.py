import re
from pathlib import Path

from tree_sitter import Node

from app.scanner.discovery import walk_module_source_files
from app.scanner.dto import QualityFinding
from app.scanner.php_parser import node_text, parse_php

_DEPRECATED_RE = re.compile(r"@deprecated\b", re.IGNORECASE)

# Scoped to declarations that carry a clear "name" field tree-sitter-php
# exposes consistently — properties/consts use a different shape and aren't
# covered here.
_DECLARATION_TYPES = {
    "class_declaration",
    "interface_declaration",
    "trait_declaration",
    "method_declaration",
    "function_definition",
}


def _symbol_name(node: Node, source: bytes) -> str:
    name_node = node.child_by_field_name("name")
    return node_text(name_node, source) if name_node is not None else node.type


def _scan_file(path: Path, relative_file_path: str) -> list[QualityFinding]:
    source = path.read_bytes()
    tree = parse_php(source)
    findings: list[QualityFinding] = []

    def walk(node: Node) -> None:
        for child in node.children:
            if child.type in _DECLARATION_TYPES:
                comment = child.prev_sibling
                if (
                    comment is not None
                    and comment.type == "comment"
                    and _DEPRECATED_RE.search(node_text(comment, source))
                ):
                    findings.append(
                        QualityFinding(
                            check_type="deprecated_annotation",
                            severity="warning",
                            file_path=relative_file_path,
                            line=child.start_point[0] + 1,
                            message=f"@deprecated: {_symbol_name(child, source)}",
                        )
                    )
            walk(child)

    walk(tree.root_node)
    return findings


def scan_deprecated_annotations(module_root: Path) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for php_file in walk_module_source_files(module_root):
        relative_file_path = str(php_file.relative_to(module_root))
        try:
            findings.extend(_scan_file(php_file, relative_file_path))
        except (SyntaxError, UnicodeDecodeError, OSError):
            continue
    return findings
