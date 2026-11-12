from app.scanner.dto import PhpClassEntry, QualityFinding

_ADMIN_CONTROLLER_PATH_MARKER = "Controller/Adminhtml/"
_ADMIN_RESOURCE_CONST = "ADMIN_RESOURCE"
_MAX_RESOLUTION_HOPS = 20  # generous ceiling against a pathological extends/implements cycle


def _resolves_admin_resource(entry: PhpClassEntry, by_name: dict[str, PhpClassEntry]) -> bool | None:
    """Whether `entry` (or something it extends/implements, resolved only
    within this module's own class catalog) declares ADMIN_RESOURCE.

    Returns True (found), False (fully resolved in-module, never found -- a
    concrete, certain gap), or None (the chain reaches a class/interface name
    not in this module's own catalog -- e.g. the real
    \\Magento\\Backend\\App\\Action -- so it's ambiguous and must not be
    flagged; see admin_acl.py's module docstring-equivalent reasoning in the
    plan this implements).
    """
    seen: set[str] = set()
    queue: list[str] = [entry.class_name]
    hops = 0
    while queue:
        hops += 1
        if hops > _MAX_RESOLUTION_HOPS:
            return None  # pathological chain -- bail out conservatively, don't flag
        name = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)

        current = entry if name == entry.class_name else by_name.get(name)
        if current is None:
            return None  # a referenced parent/interface isn't in this module -- unresolvable

        if _ADMIN_RESOURCE_CONST in current.consts:
            return True

        queue.extend(current.extends)
        queue.extend(current.implements)

    return False  # fully resolved in-module, ADMIN_RESOURCE never found anywhere in the chain


def find_missing_acl(classes: list[PhpClassEntry]) -> list[QualityFinding]:
    """A Controller/Adminhtml/* class with no resolvable ADMIN_RESOURCE
    constant -- a real Magento security footgun: that admin action is
    reachable by any logged-in admin, not just one with a specific
    permission. Deliberately conservative, same "flag a concrete, certain
    conflict" pragmatism as the cross-module conflict checks: PHP constants
    are inherited, and resolving a `use`-aliased parent class name to its
    real FQCN isn't infrastructure this project has, so only extends/
    implements chains fully resolvable within this same module are ever
    flagged -- a class whose parent lives outside the module (e.g. the real
    base \\Magento\\Backend\\App\\Action) is always skipped, not flagged,
    because it genuinely can't be known either way from this module alone.
    An abstract class is also skipped outright -- it's never dispatched as
    an admin action directly, only a concrete subclass is, and Magento's own
    base admin-controller classes are commonly abstract with no
    ADMIN_RESOURCE of their own by design (concrete subclasses supply it).
    """
    by_name = {c.class_name: c for c in classes}

    findings: list[QualityFinding] = []
    for entry in classes:
        if (
            entry.kind != "class"
            or entry.is_abstract
            or _ADMIN_CONTROLLER_PATH_MARKER not in entry.file_path
        ):
            continue
        if _resolves_admin_resource(entry, by_name) is False:
            findings.append(
                QualityFinding(
                    check_type="missing_acl",
                    severity="warning",
                    file_path=entry.file_path,
                    line=entry.start_line,
                    message=(
                        f"{entry.fqcn} is under Controller/Adminhtml but declares no resolvable "
                        "ADMIN_RESOURCE constant -- it may be reachable by any logged-in admin."
                    ),
                )
            )
    return findings
