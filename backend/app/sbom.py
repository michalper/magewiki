import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

_CYCLONEDX_SPEC_VERSION = "1.5"


@dataclass
class SbomComponentInput:
    """One scanned module's identity, as needed to describe it as a CycloneDX
    component — deliberately just the fields a component needs, not the full
    Module ORM row, so build_cyclonedx_sbom() stays pure and easy to unit test.
    """

    name: str
    composer_name: str | None
    version: str | None
    license: list[str] | None
    homepage: str | None


@dataclass
class SbomRequirementInput:
    """One direct, production (non-dev) third-party composer package a
    scanned module requires — already resolved to that module's own bom-ref
    by the caller, so build_cyclonedx_sbom() doesn't need to know how a
    module's bom-ref is computed. No resolved version: composer_package_
    requirements only stores the raw constraint string (e.g. "^7.0"), not a
    specific installed version, so the resulting package component is
    deliberately versionless rather than guessing one.
    """

    module_bom_ref: str
    package_name: str


def _purl(composer_name: str, version: str | None) -> str | None:
    if "/" not in composer_name or not version:
        return None
    vendor, _, package = composer_name.partition("/")
    return f"pkg:composer/{vendor}/{package}@{version}"


def build_cyclonedx_sbom(
    repo_root: str,
    modules: list[SbomComponentInput],
    requirements: list[SbomRequirementInput] | None = None,
) -> dict:
    """Build a CycloneDX 1.5 JSON SBOM (Software Bill of Materials) for every
    module scanned under one repo_root. One "library" component per module —
    using data already parsed and persisted (composer name/version/license/
    homepage), not a new scan or any external call.

    requirements adds a transitive-dependency graph on top: each scanned
    module's own direct, production (non-dev) third-party composer packages
    (already parsed into composer_package_requirements for the CVE/abandoned-
    dependency checks) become their own versionless "library" components,
    plus a `dependencies` section linking each module to the packages it
    requires. Deliberately only one level deep — this project parses a
    package's *name*, never installs it, so it has no way to know that
    package's own further dependencies; "transitive" here means "what a
    scanned module requires," not a fully resolved multi-level tree.
    Omitted (None) reproduces the original flat, graph-less SBOM exactly.
    A requirement whose package_name collides with an already-scanned
    module's own bom-ref is skipped as a separate component — it's the same
    real thing, already present with full version/license/homepage data.
    """
    components = []
    module_bom_refs: set[str] = set()
    for m in modules:
        bom_ref = m.composer_name or m.name
        module_bom_refs.add(bom_ref)
        component: dict = {
            "type": "library",
            "name": bom_ref,
            "bom-ref": bom_ref,
        }
        if m.version:
            component["version"] = m.version
        if m.license:
            component["licenses"] = [{"license": {"name": lic}} for lic in m.license]
        if m.homepage:
            component["externalReferences"] = [{"type": "website", "url": m.homepage}]
        if m.composer_name:
            purl = _purl(m.composer_name, m.version)
            if purl:
                component["purl"] = purl
        components.append(component)

    dependencies: list[dict] = []
    if requirements:
        depends_on: dict[str, set[str]] = {}
        package_names: set[str] = set()
        for r in requirements:
            depends_on.setdefault(r.module_bom_ref, set()).add(r.package_name)
            if r.package_name not in module_bom_refs:
                package_names.add(r.package_name)

        for package_name in sorted(package_names):
            components.append({"type": "library", "name": package_name, "bom-ref": package_name})

        for module_bom_ref in sorted(depends_on):
            dependencies.append(
                {"ref": module_bom_ref, "dependsOn": sorted(depends_on[module_bom_ref])}
            )

    bom: dict = {
        "bomFormat": "CycloneDX",
        "specVersion": _CYCLONEDX_SPEC_VERSION,
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "tools": [{"vendor": "MageWiki-AI", "name": "magewiki", "version": "1.0"}],
            "component": {"type": "application", "name": repo_root},
        },
        "components": components,
    }
    if dependencies:
        bom["dependencies"] = dependencies
    return bom
