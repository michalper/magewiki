import re
from collections import defaultdict
from dataclasses import dataclass

from app.scanner.dto import QualityFinding

# Magento's own plugin-method convention: a plugin class intercepts a target
# method by defining before<Method>/after<Method>/around<Method> on itself.
# di.xml never declares which method a plugin targets or which of the three
# kinds it is — only which class it intercepts — so that has to be derived
# from the plugin class's own method names.
_HOOK_METHOD_RE = re.compile(r"^(before|after|around)([A-Z]\w*)$")


@dataclass
class PluginRow:
    module_id: int
    module_name: str
    intercepted_type: str
    plugin_name: str
    plugin_class: str
    sort_order: int | None
    disabled: bool


@dataclass
class _HookEntry:
    module_id: int
    module_name: str
    plugin_name: str
    plugin_class: str
    kind: str  # "before" | "after" | "around"
    sort_order: int | None


def _target_method(hook_method_name: str) -> str | None:
    match = _HOOK_METHOD_RE.match(hook_method_name)
    if not match:
        return None
    _kind, rest = match.groups()
    return rest[0].lower() + rest[1:]


def _hook_kind(hook_method_name: str) -> str | None:
    match = _HOOK_METHOD_RE.match(hook_method_name)
    return match.group(1) if match else None


def detect_plugin_conflicts(
    plugins: list[PluginRow], class_methods: dict[str, set[str]]
) -> list[tuple[int, QualityFinding]]:
    """Cross-module plugin conflicts: two or more modules each hooking the same
    (intercepted type, target method) pair, where either multiple `around`
    plugins are involved (execution order between arounds is unreliable and
    one can silently suppress another's behavior) or the group's effective
    sortOrder values collide (ambiguous relative ordering). A plugin whose
    class's methods aren't known (not found in `class_methods`) is skipped
    rather than guessed at — this is a deterministic, parser-derived check,
    not an AI guess, so an uncertain case is left out rather than flagged.

    Returns one (module_id, QualityFinding) pair per module involved in each
    flagged conflict, so it surfaces on every affected module's own page.
    """
    # A plugin class's methods are catalogued once per class, with no way to
    # tell which specific method was written for which target -- fine when a
    # class is only ever declared against one intercepted_type (its methods
    # unambiguously belong to it), but a shared/generic plugin class declared
    # in di.xml against two *different* intercepted types (e.g. a logging
    # plugin hooking many unrelated save() methods across types) has no
    # reliable way to attribute a given beforeX/afterX/aroundX method to the
    # right one of those targets. Same "an uncertain case is left out rather
    # than flagged" principle already applied to a class with no known
    # methods at all -- skip bucketing entirely for such a class rather than
    # guess, which previously attributed a method written for one target to
    # every other target the same class also happens to be declared against.
    class_to_intercepted_types: dict[str, set[str]] = defaultdict(set)
    for p in plugins:
        if not p.disabled:
            class_to_intercepted_types[p.plugin_class].add(p.intercepted_type)
    ambiguous_classes = {cls for cls, types in class_to_intercepted_types.items() if len(types) > 1}

    groups: dict[tuple[str, str], list[_HookEntry]] = defaultdict(list)

    for p in plugins:
        if p.disabled:
            continue
        if p.plugin_class in ambiguous_classes:
            continue
        methods = class_methods.get(p.plugin_class)
        if not methods:
            continue
        for method_name in methods:
            kind = _hook_kind(method_name)
            target = _target_method(method_name)
            if kind is None or target is None:
                continue
            groups[(p.intercepted_type, target.lower())].append(
                _HookEntry(
                    module_id=p.module_id,
                    module_name=p.module_name,
                    plugin_name=p.plugin_name,
                    plugin_class=p.plugin_class,
                    kind=kind,
                    sort_order=p.sort_order,
                )
            )

    findings: list[tuple[int, QualityFinding]] = []

    for (intercepted_type, target_method), entries in groups.items():
        module_ids = {e.module_id for e in entries}
        if len(module_ids) < 2:
            continue  # same-author overlap -- not a cross-module conflict

        arounds = [e for e in entries if e.kind == "around"]
        around_module_ids = {e.module_id for e in arounds}
        messages: list[str] = []

        # Real bug caught verifying against a 751-module production store: the
        # group-level module_ids check above only guarantees the *group* spans
        # 2+ modules, not that the arounds themselves do -- a group of [module
        # A's around, module A's second around, module B's unrelated `after`]
        # satisfied that gate and got reported as "multiple around plugins"
        # even though both arounds were from the same module (the harmless,
        # same-author case this file already excludes everywhere else).
        has_arounds_conflict = len(arounds) >= 2 and len(around_module_ids) >= 2
        if has_arounds_conflict:
            who = ", ".join(f"{e.plugin_class} ({e.module_name})" for e in arounds)
            messages.append(
                f"Multiple `around` plugins hook `{intercepted_type}::{target_method}`: "
                f"{who} — execution order between them is not guaranteed and one may "
                f"silently suppress another's behavior."
            )

        # The sortOrder-collision check runs independently of the arounds check
        # above, not as its `else` branch — an arounds conflict between modules
        # A and B must not suppress an unrelated, equally real sortOrder
        # collision between modules C and D hooking the same method. Once an
        # arounds conflict is already reported, re-scan only the rest of the
        # group (excluding the reported arounds) so the common simple case
        # (just those same 2 arounds, defaulting to the same sortOrder 0)
        # doesn't also get a redundant second finding for the identical pair.
        remaining = [e for e in entries if e not in arounds] if has_arounds_conflict else entries
        by_sort_order: dict[int, list[_HookEntry]] = defaultdict(list)
        for e in remaining:
            by_sort_order[e.sort_order if e.sort_order is not None else 0].append(e)
        colliding = next((group for group in by_sort_order.values() if len({g.module_id for g in group}) >= 2), None)
        if colliding:
            effective_sort_order = colliding[0].sort_order if colliding[0].sort_order is not None else 0
            who = ", ".join(
                f"{e.plugin_class} ({e.module_name}, {e.kind})"
                + ("" if e.sort_order is not None else ", sortOrder unset -> defaults to 0")
                for e in colliding
            )
            messages.append(
                f"Plugins from different modules hook `{intercepted_type}::{target_method}` "
                f"with the same effective sortOrder ({effective_sort_order}): {who} — their "
                f"relative execution order is ambiguous."
            )

        for message in messages:
            for module_id in module_ids:
                findings.append(
                    (module_id, QualityFinding(check_type="plugin_conflict", severity="warning", file_path=None, line=None, message=message))
                )

    return findings
