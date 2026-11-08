from app.sbom import SbomComponentInput, build_cyclonedx_sbom


def _component(**overrides):
    defaults = {
        "name": "Vendor_Module",
        "composer_name": "vendor/module",
        "version": "1.2.3",
        "license": None,
        "homepage": None,
    }
    defaults.update(overrides)
    return SbomComponentInput(**defaults)


def test_builds_a_valid_cyclonedx_envelope():
    sbom = build_cyclonedx_sbom("/stores/store-a", [_component()])

    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert sbom["serialNumber"].startswith("urn:uuid:")
    assert sbom["metadata"]["component"]["name"] == "/stores/store-a"
    assert "timestamp" in sbom["metadata"]


def test_component_uses_composer_name_and_version_and_purl():
    sbom = build_cyclonedx_sbom("/stores/store-a", [_component()])

    component = sbom["components"][0]
    assert component["type"] == "library"
    assert component["name"] == "vendor/module"
    assert component["version"] == "1.2.3"
    assert component["purl"] == "pkg:composer/vendor/module@1.2.3"


def test_falls_back_to_module_name_when_no_composer_name():
    sbom = build_cyclonedx_sbom("/stores/store-a", [_component(composer_name=None)])

    component = sbom["components"][0]
    assert component["name"] == "Vendor_Module"
    assert "purl" not in component


def test_no_purl_without_a_version():
    sbom = build_cyclonedx_sbom("/stores/store-a", [_component(version=None)])

    component = sbom["components"][0]
    assert "version" not in component
    assert "purl" not in component


def test_licenses_and_homepage_are_included_when_present():
    sbom = build_cyclonedx_sbom(
        "/stores/store-a", [_component(license=["OSL-3.0", "AFL-3.0"], homepage="https://example.com")]
    )

    component = sbom["components"][0]
    assert component["licenses"] == [{"license": {"name": "OSL-3.0"}}, {"license": {"name": "AFL-3.0"}}]
    assert component["externalReferences"] == [{"type": "website", "url": "https://example.com"}]


def test_licenses_and_external_references_omitted_when_absent():
    sbom = build_cyclonedx_sbom("/stores/store-a", [_component()])

    component = sbom["components"][0]
    assert "licenses" not in component
    assert "externalReferences" not in component


def test_handles_an_empty_module_list():
    sbom = build_cyclonedx_sbom("/stores/store-a", [])
    assert sbom["components"] == []
