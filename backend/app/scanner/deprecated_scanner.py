import re

from tree_sitter import Node

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


def _scan_source(source: bytes, relative_file_path: str) -> list[QualityFinding]:
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


def scan_deprecated_annotations(php_sources: dict[str, bytes]) -> list[QualityFinding]:
    """Takes the module's already-read file bytes (see discovery.py's
    read_module_source_files, the single place every file is read from disk
    per scan) instead of re-walking and re-reading every file itself. No
    try/except here, unlike the old disk-reading version: tree-sitter is
    error-tolerant by construction (malformed syntax becomes an ERROR node,
    never an exception) and node_text() decodes with errors="replace", so
    there's nothing left for _scan_source() to raise on already-in-memory
    bytes -- the only exception the old code actually caught was a disk-level
    OSError for a file that vanished mid-walk, which can't happen here since
    nothing in this function touches disk anymore.
    """
    findings: list[QualityFinding] = []
    for relative_file_path, source in php_sources.items():
        findings.extend(_scan_source(source, relative_file_path))
    return findings
