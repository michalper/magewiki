from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding


@dataclass
class ModuleDependencyRow:
    module_id: int
    module_name: str
    depends_on_name: str


def detect_circular_dependencies(deps: list[ModuleDependencyRow]) -> list[tuple[int, QualityFinding]]:
    """Circular module.xml <sequence> dependencies: module A sequenced after B,
    sequenced after C, sequenced after A. Real impact, not theoretical --
    Magento's own setup:upgrade explicitly detects this and fails outright
    ("Circular sequence reference ... detected"); the store genuinely can't be
    installed or upgraded until the cycle is broken, unlike the other
    cross-module conflicts in this file, which merge to an ambiguous-but-
    working result.

    A node with no outgoing <sequence> edge of its own can never close a
    cycle, so the graph is built purely from dependency rows (no separate
    query for every module in the repo needed). Self-references
    (module depending on itself) are dropped before traversal -- a pointless
    edge, not a cross-module conflict. One representative cycle path is
    reported per distinct cycle found via DFS (white/gray/black coloring);
    like the other checks in this file, this doesn't attempt to enumerate
    every possible cycle in a graph with multiple overlapping ones, only to
    flag a concrete, certain one.
    """
    edges: dict[str, set[str]] = defaultdict(set)
    name_to_id: dict[str, int] = {}
    for d in deps:
        name_to_id[d.module_name] = d.module_id
        if d.depends_on_name != d.module_name:
            edges[d.module_name].add(d.depends_on_name)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = defaultdict(int)
    path: list[str] = []
    cycles: list[list[str]] = []
    seen: set[frozenset[str]] = set()

    def visit(node: str) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in edges.get(node, ()):
            if color[neighbor] == GRAY:
                idx = path.index(neighbor)
                cycle = [*path[idx:], neighbor]
                key = frozenset(cycle[:-1])
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
            elif color[neighbor] == WHITE:
                visit(neighbor)
        path.pop()
        color[node] = BLACK

    for node in list(edges):
        if color[node] == WHITE:
            visit(node)

    findings: list[tuple[int, QualityFinding]] = []
    for cycle in cycles:
        involved_ids = {name_to_id[name] for name in cycle[:-1] if name in name_to_id}
        if len(involved_ids) < 2:
            continue  # the names that closed the cycle weren't all real, scanned modules

        chain = " -> ".join(cycle)
        message = (
            f"Circular module.xml <sequence> dependency: {chain} — Magento's setup:upgrade "
            "fails outright on a circular sequence; the store can't be installed or upgraded "
            "until this cycle is broken."
        )
        for module_id in involved_ids:
            findings.append(
                (
                    module_id,
                    QualityFinding(
                        check_type="circular_dependency",
                        severity="warning",
                        file_path=None,
                        line=None,
                        message=message,
                    ),
                )
            )

    return findings
