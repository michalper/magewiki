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


def _purl(composer_name: str, version: str | None) -> str | None:
    if "/" not in composer_name or not version:
        return None
    vendor, _, package = composer_name.partition("/")
    return f"pkg:composer/{vendor}/{package}@{version}"


def build_cyclonedx_sbom(repo_root: str, modules: list[SbomComponentInput]) -> dict:
    """Build a CycloneDX 1.5 JSON SBOM (Software Bill of Materials) for every
    module scanned under one repo_root. One "library" component per module —
    using data already parsed and persisted (composer name/version/license/
    homepage), not a new scan or any external call. Deliberately a flat
    components list with no `dependencies` graph section (CycloneDX allows
    omitting it) — the existing dependency graph already answers "what does X
    depend on" per module; this just answers "what's actually installed."
    """
    components = []
    for m in modules:
        component: dict = {
            "type": "library",
            "name": m.composer_name or m.name,
            "bom-ref": m.composer_name or m.name,
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

    return {
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
