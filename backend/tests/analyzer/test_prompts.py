from app.analyzer.facts import FileAnalysisFact, ModuleFacts, PhpClassFact
from app.analyzer.prompts import (
    MAX_FILE_CONTENT_CHARS,
    build_file_summary_prompt,
    build_module_synthesis_prompt,
)


def _bare_facts(**overrides) -> ModuleFacts:
    defaults = {
        "name": "Vendor_Module", "composer_name": None, "composer_type": None,
        "license": None, "enabled": None, "setup_version": None,
    }
    defaults.update(overrides)
    return ModuleFacts(**defaults)


def test_build_file_summary_prompt_includes_the_full_content_when_short():
    prompt = build_file_summary_prompt("Plugin/SamplePlugin.php", "<?php class SamplePlugin {}")
    assert "Plugin/SamplePlugin.php" in prompt
    assert "<?php class SamplePlugin {}" in prompt
    assert "truncated" not in prompt


def test_build_file_summary_prompt_truncates_long_content():
    content = "x" * (MAX_FILE_CONTENT_CHARS + 100)
    prompt = build_file_summary_prompt("Big.php", content)
    assert "truncated, 100 more characters omitted" in prompt
    assert content not in prompt


def test_build_module_synthesis_prompt_minimal_facts():
    prompt = build_module_synthesis_prompt(_bare_facts())
    assert "Vendor_Module" in prompt
    assert "Enabled: unknown" in prompt
    assert "Setup version: unknown" in prompt
    assert "Declared module dependencies" not in prompt
    assert "PHP classes discovered" not in prompt
    assert "Per-file summaries" not in prompt


def test_build_module_synthesis_prompt_with_composer_license_and_enabled_known():
    prompt = build_module_synthesis_prompt(
        _bare_facts(composer_name="vendor/module", composer_type="magento2-module", license=["MIT"], enabled=True)
    )
    assert "Composer package: vendor/module (type: magento2-module)" in prompt
    assert "License: MIT" in prompt
    assert "Enabled: True" in prompt


def test_build_module_synthesis_prompt_with_composer_type_unknown():
    prompt = build_module_synthesis_prompt(_bare_facts(composer_name="vendor/module", composer_type=None))
    assert "Composer package: vendor/module (type: unknown)" in prompt


def test_build_module_synthesis_prompt_includes_every_fact_category_when_populated():
    facts = _bare_facts(
        dependencies=["Magento_Sales"],
        di_preferences=[("Magento\\Sales\\Api\\OrderRepositoryInterface", "Vendor\\Module\\Model\\OrderRepository")],
        di_plugins=[("Magento\\Sales\\Model\\Order", "SamplePlugin", "Vendor\\Module\\Plugin\\SamplePlugin")],
        di_virtual_types=[("CustomGrid", "Magento\\Ui\\DataProvider\\DataProvider")],
        event_observers=[("sales_order_save_after", "SampleObserver", "Vendor\\Module\\Observer\\SampleObserver")],
        graphql_fields=[("Query", "Query", "customAttribute", "Vendor\\Module\\Resolver\\CustomAttribute")],
        config_fields=[("section/group/field", "Enabled"), ("section/group/other", None)],
        queue_bindings=[
            ("vendor.module.topic", "vendor.module.queue", "vendorModuleConsumer", "Vendor\\Module\\Consumer", "process"),
            ("same.topic", "same.topic", None, None, None),
        ],
        db_tables=[("vendor_module_table", "Stores stuff", 5), ("vendor_module_other", None, 2)],
        cron_jobs=[("vendor_module_cron", "Vendor\\Module\\Cron\\Run", "execute", "0 0 * * *"), ("no_schedule", "C", "m", None)],
        webapi_routes=[
            ("/V1/vendor-module/resource", "GET", "Vendor\\Module\\Api\\ResourceInterface", "get", "Vendor_Module::view"),
            ("/V1/vendor-module/open", "POST", "Vendor\\Module\\Api\\OpenInterface", "create", None),
        ],
        acl_resources=[
            ("Vendor_Module::sample", "Sample", "Magento_Backend::stores"),
            ("Vendor_Module::bare", None, None),
        ],
        indexers=[
            ("vendor_module_indexer", "vendor_module_view", "Vendor\\Module\\Model\\Indexer\\Sample"),
            ("vendor_module_bare", None, None),
        ],
        mviews=[
            ("vendor_module_view", "Vendor\\Module\\Model\\Indexer\\Sample", "indexer"),
            ("vendor_module_bare_view", None, None),
        ],
        routes=[("frontend", "vendor_module", "vendormodule"), ("adminhtml", "vendor_module_admin", "vendormodule/admin")],
        widgets=[("vendor_module_widget", "Vendor\\Module\\Block\\Widget\\Sample")],
        menu_items=[("vendor_module_menu", "Sample Menu"), ("vendor_module_bare_menu", None)],
        cache_types=[
            ("vendor_module_cache", "Vendor\\Module\\Model\\Cache\\Type"),
            ("vendor_module_bare_cache", None),
        ],
        php_classes=[
            PhpClassFact(
                fqcn="Vendor\\Module\\Plugin\\SamplePlugin", class_name="SamplePlugin", kind="class",
                file_path="Plugin/SamplePlugin.php", is_plugin=True, is_observer=False,
                extends=[], implements=[], methods=["beforeSave"],
            ),
            PhpClassFact(
                fqcn="Vendor\\Module\\Model\\Plain", class_name="Plain", kind="class",
                file_path="Model/Plain.php", is_plugin=False, is_observer=False,
                extends=[], implements=[], methods=[],
            ),
        ],
        file_analyses=[
            FileAnalysisFact(relative_path="Plugin/SamplePlugin.php", file_summary="Blocks checkout.", notable_behavior="Calls an external API."),
            FileAnalysisFact(relative_path="Model/Plain.php", file_summary="A plain model.", notable_behavior=None),
        ],
    )

    prompt = build_module_synthesis_prompt(facts)

    assert "- Magento_Sales" in prompt
    assert "- Magento\\Sales\\Api\\OrderRepositoryInterface -> Vendor\\Module\\Model\\OrderRepository" in prompt
    assert "- SamplePlugin intercepts Magento\\Sales\\Model\\Order via Vendor\\Module\\Plugin\\SamplePlugin" in prompt
    assert "- CustomGrid composes Magento\\Ui\\DataProvider\\DataProvider" in prompt
    assert "- SampleObserver listens for `sales_order_save_after` via Vendor\\Module\\Observer\\SampleObserver" in prompt
    assert "- Query.customAttribute [Query] (resolved by Vendor\\Module\\Resolver\\CustomAttribute)" in prompt
    assert "- section/group/field (Enabled)" in prompt
    assert "- section/group/other" in prompt and "- section/group/other (" not in prompt
    assert "- vendor.module.topic -> queue vendor.module.queue consumed by Vendor\\Module\\Consumer::process (consumer: vendorModuleConsumer)" in prompt
    assert "- same.topic" in prompt and "-> queue" not in prompt.split("- same.topic")[1].split("\n")[0]
    assert "- vendor_module_table (5 columns) — Stores stuff" in prompt
    assert "- vendor_module_other (2 columns)" in prompt
    assert "- vendor_module_cron runs Vendor\\Module\\Cron\\Run::execute [0 0 * * *]" in prompt
    assert "- no_schedule runs C::m" in prompt
    assert "- GET /V1/vendor-module/resource -> Vendor\\Module\\Api\\ResourceInterface::get (ACL: Vendor_Module::view)" in prompt
    assert "- POST /V1/vendor-module/open -> Vendor\\Module\\Api\\OpenInterface::create" in prompt
    assert "- Vendor_Module::sample (Sample) under Magento_Backend::stores" in prompt
    assert "- Vendor_Module::bare" in prompt and "- Vendor_Module::bare (" not in prompt
    assert "- vendor_module_indexer -> Vendor\\Module\\Model\\Indexer\\Sample (view: vendor_module_view)" in prompt
    assert "- vendor_module_bare" in prompt and "- vendor_module_bare ->" not in prompt
    assert "- vendor_module_view -> Vendor\\Module\\Model\\Indexer\\Sample (group: indexer)" in prompt
    assert "- vendor_module_bare_view" in prompt and "- vendor_module_bare_view ->" not in prompt
    assert "- [frontend] vendor_module -> frontName vendormodule" in prompt
    assert "- [adminhtml] vendor_module_admin -> frontName vendormodule/admin" in prompt
    assert "- vendor_module_widget -> Vendor\\Module\\Block\\Widget\\Sample" in prompt
    assert "- vendor_module_menu (Sample Menu)" in prompt
    assert "- vendor_module_bare_menu" in prompt and "- vendor_module_bare_menu (" not in prompt
    assert "- vendor_module_cache -> Vendor\\Module\\Model\\Cache\\Type" in prompt
    assert "- vendor_module_bare_cache" in prompt and "- vendor_module_bare_cache ->" not in prompt
    assert "- Vendor\\Module\\Plugin\\SamplePlugin (class) [plugin] — Plugin/SamplePlugin.php" in prompt
    assert "- Vendor\\Module\\Model\\Plain (class) — Model/Plain.php" in prompt
    assert "- Plugin/SamplePlugin.php: Blocks checkout." in prompt
    assert "  notable: Calls an external API." in prompt
    assert "- Model/Plain.php: A plain model." in prompt


def test_build_module_synthesis_prompt_marks_an_observer_role_too():
    facts = _bare_facts(
        php_classes=[
            PhpClassFact(
                fqcn="Vendor\\Module\\Observer\\Both", class_name="Both", kind="class",
                file_path="Observer/Both.php", is_plugin=True, is_observer=True,
                extends=[], implements=[], methods=[],
            )
        ]
    )
    prompt = build_module_synthesis_prompt(facts)
    assert "[plugin, observer]" in prompt
