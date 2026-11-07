import pytest
from pydantic import ValidationError

from app.analyzer.schemas import Feature, FileSummary, ModuleDoc, Tag


def _valid_doc_payload(source: str) -> dict:
    return {
        "summary": "Blocks checkout over credit limit.",
        "description": "A plugin that intercepts order placement.",
        "features": [{"name": "Credit limit check", "description": "Blocks checkout.", "source": source}],
        "integrations": [],
        "tags": [],
        "config_options": [],
        "risks": [],
        "confidence": 0.8,
        "pm_text": "Prevents customers from ordering over their credit limit.",
        "dev_text": "Plugin on CartManagementInterface::placeOrder.",
    }


def test_file_summary_minimal():
    summary = FileSummary(file_summary="Does something.", notable_behavior=None)
    assert summary.notable_behavior is None


def test_module_doc_accepts_known_source():
    known = {"Plugin/SampleCheckoutPlugin.php"}
    doc = ModuleDoc.model_validate(
        _valid_doc_payload("Plugin/SampleCheckoutPlugin.php"), context={"known_sources": known}
    )
    assert doc.features[0].source == "Plugin/SampleCheckoutPlugin.php"


def test_module_doc_rejects_unknown_source():
    known = {"Plugin/SampleCheckoutPlugin.php"}
    with pytest.raises(ValidationError):
        ModuleDoc.model_validate(_valid_doc_payload("Some/Made/Up/File.php"), context={"known_sources": known})


def test_module_doc_skips_validation_without_context():
    # No known_sources provided -> validation is not enforced (used in tests that
    # don't care about source provenance).
    doc = ModuleDoc.model_validate(_valid_doc_payload("anything.php"))
    assert isinstance(doc.features[0], Feature)


def test_module_doc_rejects_any_source_when_known_sources_is_empty():
    # A config-only/XML-only module has zero known files/classes (known_sources()
    # returns an empty set) -> every claimed source must be rejected, not waved
    # through as if validation weren't requested at all.
    with pytest.raises(ValidationError):
        ModuleDoc.model_validate(_valid_doc_payload("anything.php"), context={"known_sources": set()})


def test_module_doc_accepts_a_known_config_option_path():
    payload = _valid_doc_payload("anything.php")
    payload["config_options"] = [{"path": "section/group/field", "label": "Enabled"}]
    doc = ModuleDoc.model_validate(payload, context={"known_config_paths": {"section/group/field"}})
    assert doc.config_options[0].path == "section/group/field"


def test_module_doc_rejects_a_hallucinated_config_option_path():
    # config_options is documented as "keys from system.xml" — a parser fact, not
    # an AI claim — same anti-hallucination contract as features/integrations.
    payload = _valid_doc_payload("anything.php")
    payload["config_options"] = [{"path": "made/up/field", "label": "Not real"}]
    with pytest.raises(ValidationError):
        ModuleDoc.model_validate(payload, context={"known_config_paths": {"section/group/field"}})


def test_module_doc_skips_config_option_validation_when_key_absent():
    # known_sources alone (without known_config_paths) must not enforce the
    # config_options check — each key opts into its own check independently.
    payload = _valid_doc_payload("anything.php")
    payload["config_options"] = [{"path": "made/up/field", "label": "Not real"}]
    doc = ModuleDoc.model_validate(payload, context={"known_sources": {"anything.php"}})
    assert doc.config_options[0].path == "made/up/field"


def test_tag_coerces_a_bare_string_into_an_ai_sourced_tag():
    tag = Tag.model_validate("payments")
    assert tag == Tag(name="payments", source="ai", confidence=0.5)


def test_module_doc_coerces_bare_string_tags():
    payload = _valid_doc_payload("anything.php")
    payload["tags"] = ["payments", "search"]
    doc = ModuleDoc.model_validate(payload)
    assert [t.name for t in doc.tags] == ["payments", "search"]
    assert all(t.source == "ai" and t.confidence == 0.5 for t in doc.tags)


# Real production samples captured from a 760-module store's last_error column
# (synthesis failures that slipped past the Tag-coercion fix above) — exact
# shapes, not paraphrased, so the fix is verified against what the model
# actually emits rather than a hypothesized shape.
REAL_REJECTED_TAGS_SAMPLES = [
    {"name": "b2b", "source": "ai", "confidence": 0.0},
    {"name": "admin-tools", "source": "ai", "confidence": 0.3},
    {"name": "b2b"},
    {"name": "checkout", "source": "ai", "confidence": 0.0},
]


@pytest.mark.parametrize("sample", REAL_REJECTED_TAGS_SAMPLES)
def test_module_doc_coerces_rejected_tags_given_as_tag_objects(sample):
    payload = _valid_doc_payload("anything.php")
    payload["rejected_tags"] = [sample]
    doc = ModuleDoc.model_validate(payload)
    assert doc.rejected_tags == [sample["name"]]


def test_module_doc_parses_a_stringified_features_list():
    payload = _valid_doc_payload("anything.php")
    # Real production sample's exact bug shape: the whole list JSON-encoded as a
    # string instead of emitted as nested JSON — here with well-formed Feature
    # items, to isolate the string->list recovery from the separate, unrelated
    # data-quality issue the real sample also had (mismatched inner field names).
    payload["features"] = (
        '[{"name": "Query compare list", "description": "Adds a GraphQL query.", "source": "anything.php"}]'
    )
    doc = ModuleDoc.model_validate(payload)
    assert doc.features[0].name == "Query compare list"


def test_module_doc_leaves_a_non_json_string_list_field_as_is():
    # A genuinely malformed string must still surface its real validation error,
    # not be silently swallowed by the recovery attempt.
    payload = _valid_doc_payload("anything.php")
    payload["features"] = "not valid json"
    with pytest.raises(ValidationError):
        ModuleDoc.model_validate(payload)
