from app.analyzer.embeddings import (
    build_file_chunk_text,
    build_method_chunk_text,
    build_module_chunk_text,
    hash_text,
)
from app.analyzer.schemas import Feature, Integration, ModuleDoc, Tag


def _doc(**overrides) -> ModuleDoc:
    base = dict(
        summary="A summary.",
        description="A description.",
        features=[Feature(name="Feature A", description="Does A.", source="etc/module.xml")],
        integrations=[Integration(name="Klaviyo", description="Sends events.", source=None)],
        tags=[Tag(name="marketing", source="ai", confidence=0.8)],
        confidence=0.9,
        pm_text="PM text.",
        dev_text="Dev text.",
    )
    base.update(overrides)
    return ModuleDoc.model_validate(base)


def test_build_module_chunk_text_includes_narrative_fields():
    text = build_module_chunk_text(_doc())

    assert "A summary." in text
    assert "A description." in text
    assert "Feature A" in text
    assert "Klaviyo" in text
    assert "marketing" in text
    assert "PM text." in text
    assert "Dev text." in text


def test_build_file_chunk_text_without_notable_behavior():
    text = build_file_chunk_text("Does something.", None)
    assert text == "Does something."


def test_build_file_chunk_text_with_notable_behavior():
    text = build_file_chunk_text("Does something.", "Calls an external API.")
    assert "Does something." in text
    assert "Calls an external API." in text


def test_build_method_chunk_text_includes_fqcn_and_source():
    text = build_method_chunk_text("Vendor\\Module\\Plugin\\Foo", "beforeBar", "public function beforeBar() {}")
    assert "Vendor\\Module\\Plugin\\Foo::beforeBar" in text
    assert "public function beforeBar() {}" in text


def test_hash_text_is_deterministic_and_sensitive_to_content():
    assert hash_text("same") == hash_text("same")
    assert hash_text("same") != hash_text("different")
