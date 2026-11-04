from pathlib import Path

from tree_sitter import Node

from app.scanner.php_parser import find_all, node_text, parse_php


def _strip_quotes(text: str) -> str:
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        return text[1:-1]
    return text


def _array_pairs(array_node: Node, source: bytes) -> list[tuple[Node, Node]]:
    pairs = []
    for child in array_node.children:
        if child.type != "array_element_initializer":
            continue
        if len(child.children) >= 3 and node_text(child.children[1], source) == "=>":
            pairs.append((child.children[0], child.children[2]))
    return pairs


def parse_config_php(path: Path) -> dict[str, bool] | None:
    """Parse Magento's app/etc/config.php and return the 'modules' enabled map.

    Returns None if the file is missing or doesn't contain a parseable
    'modules' array — callers should treat that the same as "file absent".
    """
    if not path.is_file():
        return None

    source = path.read_bytes()
    tree = parse_php(source)

    return_statements = find_all(tree.root_node, {"return_statement"})
    if not return_statements:
        return None

    top_arrays = find_all(return_statements[0], {"array_creation_expression"})
    if not top_arrays:
        return None

    for key_node, value_node in _array_pairs(top_arrays[0], source):
        if _strip_quotes(node_text(key_node, source)) != "modules":
            continue
        if value_node.type != "array_creation_expression":
            return None

        modules: dict[str, bool] = {}
        for module_key_node, module_value_node in _array_pairs(value_node, source):
            module_name = _strip_quotes(node_text(module_key_node, source))
            value_text = node_text(module_value_node, source).strip()
            if value_text not in ("0", "1"):
                continue
            modules[module_name] = value_text == "1"
        return modules

    return None
