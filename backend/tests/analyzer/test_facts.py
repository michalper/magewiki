from app.analyzer.facts import ModuleFacts, known_config_paths, known_sources


def _bare_facts(**overrides) -> ModuleFacts:
    defaults = dict(
        name="Vendor_Module", composer_name=None, composer_type=None, license=None, enabled=None, setup_version=None
    )
    defaults.update(overrides)
    return ModuleFacts(**defaults)


def test_known_config_paths_returns_parsed_system_xml_field_paths():
    facts = _bare_facts(config_fields=[("section/group/field", "Enabled"), ("other/group/field", None)])
    assert known_config_paths(facts) == {"section/group/field", "other/group/field"}


def test_known_config_paths_is_empty_for_a_module_with_no_system_xml():
    assert known_config_paths(_bare_facts()) == set()


def test_known_sources_is_unaffected_by_config_fields():
    facts = _bare_facts(config_fields=[("section/group/field", "Enabled")])
    assert known_sources(facts) == set()
