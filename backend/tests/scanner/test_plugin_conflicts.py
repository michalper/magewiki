from app.scanner.plugin_conflicts import PluginRow, detect_plugin_conflicts


def _plugin(module_id, module_name, intercepted_type="Vendor\\Module\\Model\\Order", **overrides):
    defaults = {
        "module_id": module_id,
        "module_name": module_name,
        "intercepted_type": intercepted_type,
        "plugin_name": "default",
        "plugin_class": "Vendor\\Plugin\\Default",
        "sort_order": None,
        "disabled": False,
    }
    defaults.update(overrides)
    return PluginRow(**defaults)


def test_no_conflict_with_a_single_plugin():
    plugins = [_plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save")]
    class_methods = {"Vendor\\A\\Plugin\\Save": {"beforeSave"}}

    assert detect_plugin_conflicts(plugins, class_methods) == []


def test_no_conflict_when_both_plugins_are_from_the_same_module():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\One", plugin_name="one"),
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Two", plugin_name="two"),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\One": {"aroundSave"},
        "Vendor\\A\\Plugin\\Two": {"aroundSave"},
    }

    assert detect_plugin_conflicts(plugins, class_methods) == []


def test_no_conflict_when_different_modules_hook_different_methods():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save"),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Delete"),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"beforeSave"},
        "Vendor\\B\\Plugin\\Delete": {"beforeDelete"},
    }

    assert detect_plugin_conflicts(plugins, class_methods) == []


def test_no_conflict_when_one_before_and_one_after_on_different_sort_orders():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save", sort_order=1),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Save", sort_order=2),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"beforeSave"},
        "Vendor\\B\\Plugin\\Save": {"afterSave"},
    }

    assert detect_plugin_conflicts(plugins, class_methods) == []


def test_flags_multiple_around_plugins_from_different_modules_on_the_same_method():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save", plugin_name="a_save"),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Save", plugin_name="b_save"),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"aroundSave"},
        "Vendor\\B\\Plugin\\Save": {"aroundSave"},
    }

    findings = detect_plugin_conflicts(plugins, class_methods)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "plugin_conflict"
        assert finding.severity == "warning"
        assert "around" in finding.message
        assert "Vendor\\A\\Plugin\\Save" in finding.message
        assert "Vendor\\B\\Plugin\\Save" in finding.message


def test_flags_sort_order_collision_across_modules_on_the_same_method():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save", sort_order=5),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Save", sort_order=5),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"beforeSave"},
        "Vendor\\B\\Plugin\\Save": {"beforeSave"},
    }

    findings = detect_plugin_conflicts(plugins, class_methods)

    assert {module_id for module_id, _ in findings} == {1, 2}
    assert "sortOrder" in findings[0][1].message
    assert "(5)" in findings[0][1].message


def test_treats_missing_sort_order_as_the_default_zero_for_collision_detection():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save", sort_order=None),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Save", sort_order=0),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"beforeSave"},
        "Vendor\\B\\Plugin\\Save": {"beforeSave"},
    }

    findings = detect_plugin_conflicts(plugins, class_methods)

    assert len(findings) == 2
    assert "sortOrder unset -> defaults to 0" in findings[0][1].message


def test_ignores_a_disabled_plugin():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save", sort_order=5),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Save", sort_order=5, disabled=True),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"beforeSave"},
        "Vendor\\B\\Plugin\\Save": {"beforeSave"},
    }

    assert detect_plugin_conflicts(plugins, class_methods) == []


def test_skips_a_plugin_whose_class_methods_are_unknown():
    # The plugin class was never found/cataloged (e.g. typo'd FQCN, or a
    # class this scan genuinely never reached) -- deterministic-only, so an
    # uncertain case is left out entirely rather than guessed at.
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save", sort_order=5),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Save", sort_order=5),
    ]
    class_methods = {"Vendor\\A\\Plugin\\Save": {"beforeSave"}}  # Vendor_B's class missing entirely

    assert detect_plugin_conflicts(plugins, class_methods) == []


def test_ignores_a_plugin_class_with_no_recognized_hook_methods():
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Save"),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Save"),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"__construct", "someHelper"},
        "Vendor\\B\\Plugin\\Save": {"beforeSave"},
    }

    assert detect_plugin_conflicts(plugins, class_methods) == []


def test_two_arounds_from_the_same_module_are_not_reported_as_an_around_conflict():
    # Real bug caught against a 751-module production store: module A's own
    # two arounds plus module B's unrelated `after` on the same method made
    # the group span 2 modules overall, but the arounds themselves were both
    # from module A -- must not be reported as "multiple around plugins"
    # (that framing implies the arounds conflict with *each other*, which
    # they don't; only the sortOrder-collision framing below, if it also
    # applies, is actually warranted).
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\One", plugin_name="one", sort_order=1),
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Two", plugin_name="two", sort_order=2),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Three", plugin_name="three", sort_order=3),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\One": {"aroundSave"},
        "Vendor\\A\\Plugin\\Two": {"aroundSave"},
        "Vendor\\B\\Plugin\\Three": {"afterSave"},
    }

    findings = detect_plugin_conflicts(plugins, class_methods)

    assert findings == []  # distinct sort_orders too, so no sortOrder-collision fallback either


def test_different_intercepted_types_do_not_collide_even_with_the_same_method_name():
    plugins = [
        _plugin(1, "Vendor_A", intercepted_type="Vendor\\A\\Model\\Order", plugin_class="Vendor\\A\\Plugin\\Save", sort_order=5),
        _plugin(2, "Vendor_B", intercepted_type="Vendor\\B\\Model\\Quote", plugin_class="Vendor\\B\\Plugin\\Save", sort_order=5),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Save": {"beforeSave"},
        "Vendor\\B\\Plugin\\Save": {"beforeSave"},
    }

    assert detect_plugin_conflicts(plugins, class_methods) == []
