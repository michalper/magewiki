import pytest
from pydantic import ValidationError

from app.analyzer.schemas import FileSummary, Feature, ModuleDoc


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
