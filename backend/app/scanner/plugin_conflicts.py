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
    groups: dict[tuple[str, str], list[_HookEntry]] = defaultdict(list)

    for p in plugins:
        if p.disabled:
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
        message: str | None = None

        # Real bug caught verifying against a 751-module production store: the
        # group-level module_ids check above only guarantees the *group* spans
        # 2+ modules, not that the arounds themselves do -- a group of [module
        # A's around, module A's second around, module B's unrelated `after`]
        # satisfied that gate and got reported as "multiple around plugins"
        # even though both arounds were from the same module (the harmless,
        # same-author case this file already excludes everywhere else).
        if len(arounds) >= 2 and len(around_module_ids) >= 2:
            who = ", ".join(f"{e.plugin_class} ({e.module_name})" for e in arounds)
            message = (
                f"Multiple `around` plugins hook `{intercepted_type}::{target_method}`: "
                f"{who} — execution order between them is not guaranteed and one may "
                f"silently suppress another's behavior."
            )
        else:
            by_sort_order: dict[int, list[_HookEntry]] = defaultdict(list)
            for e in entries:
                by_sort_order[e.sort_order if e.sort_order is not None else 0].append(e)
            colliding = next((group for group in by_sort_order.values() if len({g.module_id for g in group}) >= 2), None)
            if colliding:
                effective_sort_order = colliding[0].sort_order if colliding[0].sort_order is not None else 0
                who = ", ".join(
                    f"{e.plugin_class} ({e.module_name}, {e.kind})"
                    + ("" if e.sort_order is not None else ", sortOrder unset -> defaults to 0")
                    for e in colliding
                )
                message = (
                    f"Plugins from different modules hook `{intercepted_type}::{target_method}` "
                    f"with the same effective sortOrder ({effective_sort_order}): {who} — their "
                    f"relative execution order is ambiguous."
                )

        if message is None:
            continue

        for module_id in module_ids:
            findings.append(
                (module_id, QualityFinding(check_type="plugin_conflict", severity="warning", file_path=None, line=None, message=message))
            )

    return findings
