from tree_sitter import Language, Node, Parser
import tree_sitter_php

_language = Language(tree_sitter_php.language_php())
_parser = Parser(_language)


def parse_php(source: bytes):
    return _parser.parse(source)


def node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def find_all(node: Node, types: set[str]) -> list[Node]:
    acc: list[Node] = []
    _find_all(node, types, acc)
    return acc


def _find_all(node: Node, types: set[str], acc: list[Node]) -> None:
    if node.type in types:
        acc.append(node)
    for child in node.children:
        _find_all(child, types, acc)
