from app.sbom import SbomComponentInput, SbomRequirementInput, build_cyclonedx_sbom


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


def test_no_dependencies_section_when_requirements_is_omitted():
    sbom = build_cyclonedx_sbom("/stores/store-a", [_component()])
    assert "dependencies" not in sbom


def test_no_dependencies_section_when_requirements_is_an_empty_list():
    sbom = build_cyclonedx_sbom("/stores/store-a", [_component()], [])
    assert "dependencies" not in sbom


def test_requirements_add_versionless_package_components_and_a_dependency_edge():
    sbom = build_cyclonedx_sbom(
        "/stores/store-a",
        [_component()],
        [SbomRequirementInput(module_bom_ref="vendor/module", package_name="guzzlehttp/guzzle")],
    )

    names = {c["name"] for c in sbom["components"]}
    assert names == {"vendor/module", "guzzlehttp/guzzle"}
    package_component = next(c for c in sbom["components"] if c["name"] == "guzzlehttp/guzzle")
    assert "version" not in package_component
    assert sbom["dependencies"] == [{"ref": "vendor/module", "dependsOn": ["guzzlehttp/guzzle"]}]


def test_multiple_modules_requiring_the_same_package_share_one_component():
    sbom = build_cyclonedx_sbom(
        "/stores/store-a",
        [_component(), _component(name="Other_Module", composer_name="vendor/other")],
        [
            SbomRequirementInput(module_bom_ref="vendor/module", package_name="guzzlehttp/guzzle"),
            SbomRequirementInput(module_bom_ref="vendor/other", package_name="guzzlehttp/guzzle"),
        ],
    )

    package_components = [c for c in sbom["components"] if c["name"] == "guzzlehttp/guzzle"]
    assert len(package_components) == 1
    assert sorted(sbom["dependencies"], key=lambda d: d["ref"]) == [
        {"ref": "vendor/module", "dependsOn": ["guzzlehttp/guzzle"]},
        {"ref": "vendor/other", "dependsOn": ["guzzlehttp/guzzle"]},
    ]


def test_a_requirement_matching_an_already_scanned_module_is_not_duplicated_as_a_package():
    sbom = build_cyclonedx_sbom(
        "/stores/store-a",
        [_component(), _component(name="Other_Module", composer_name="vendor/other")],
        [SbomRequirementInput(module_bom_ref="vendor/module", package_name="vendor/other")],
    )

    assert len(sbom["components"]) == 2
    assert sbom["dependencies"] == [{"ref": "vendor/module", "dependsOn": ["vendor/other"]}]
