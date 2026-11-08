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


def test_an_around_conflict_does_not_suppress_an_unrelated_sort_order_collision():
    # Modules A and B both hook `around` on Save (a real conflict), while
    # modules C and D independently hook before/afterSave with a colliding
    # sortOrder -- two distinct conflicts in the same group, both must be
    # reported, not merged into just the arounds message.
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Around", plugin_name="a"),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Around", plugin_name="b"),
        _plugin(3, "Vendor_C", plugin_class="Vendor\\C\\Plugin\\Before", plugin_name="c", sort_order=5),
        _plugin(4, "Vendor_D", plugin_class="Vendor\\D\\Plugin\\After", plugin_name="d", sort_order=5),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Around": {"aroundSave"},
        "Vendor\\B\\Plugin\\Around": {"aroundSave"},
        "Vendor\\C\\Plugin\\Before": {"beforeSave"},
        "Vendor\\D\\Plugin\\After": {"afterSave"},
    }

    findings = detect_plugin_conflicts(plugins, class_methods)

    messages = {finding.message for _, finding in findings}
    assert len(messages) == 2
    around_message = next(m for m in messages if "around" in m)
    sort_order_message = next(m for m in messages if "sortOrder" in m)
    assert "Vendor\\A\\Plugin\\Around" in around_message
    assert "Vendor\\C\\Plugin\\Before" in sort_order_message
    assert "Vendor\\D\\Plugin\\After" in sort_order_message
    assert "Vendor\\A\\Plugin\\Around" not in sort_order_message

    # Every module in the whole group still gets every emitted message for
    # that group, matching this file's existing per-group attribution.
    assert {module_id for module_id, _ in findings} == {1, 2, 3, 4}


def test_an_around_conflict_with_no_other_entries_produces_only_one_message():
    # The common simple case: just the 2 conflicting arounds, both defaulting
    # to the same sortOrder (0) -- must not also get a redundant, separate
    # sortOrder-collision finding for the identical pair.
    plugins = [
        _plugin(1, "Vendor_A", plugin_class="Vendor\\A\\Plugin\\Around", plugin_name="a"),
        _plugin(2, "Vendor_B", plugin_class="Vendor\\B\\Plugin\\Around", plugin_name="b"),
    ]
    class_methods = {
        "Vendor\\A\\Plugin\\Around": {"aroundSave"},
        "Vendor\\B\\Plugin\\Around": {"aroundSave"},
    }

    findings = detect_plugin_conflicts(plugins, class_methods)

    assert {finding.message for _, finding in findings} == {findings[0][1].message}
    assert "around" in findings[0][1].message


def test_a_plugin_class_declared_against_two_different_intercepted_types_is_skipped():
    # A shared/generic plugin class declared in di.xml against two different
    # intercepted types has no reliable way to attribute a given before/
    # after/around method to the right target -- skip it entirely rather
    # than mis-bucket a method written for one target under the other.
    plugins = [
        _plugin(1, "Vendor_Shared", intercepted_type="Vendor\\A\\Model\\Order", plugin_class="Vendor\\Shared\\Plugin\\Generic", sort_order=5),
        _plugin(1, "Vendor_Shared", intercepted_type="Vendor\\C\\Model\\Quote", plugin_class="Vendor\\Shared\\Plugin\\Generic", sort_order=5),
        _plugin(2, "Vendor_B", intercepted_type="Vendor\\A\\Model\\Order", plugin_class="Vendor\\B\\Plugin\\Save", sort_order=5),
    ]
    class_methods = {
        "Vendor\\Shared\\Plugin\\Generic": {"beforeSave"},
        "Vendor\\B\\Plugin\\Save": {"beforeSave"},
    }

    # Without the fix, Vendor_Shared's beforeSave (really written for
    # Quote::save) would also get bucketed under Order::save purely because
    # the same class is *also* declared against Order elsewhere, falsely
    # colliding with Vendor_B's genuine Order::save hook at the same
    # sortOrder (5) even though Vendor_Shared never really hooks Order.
    findings = detect_plugin_conflicts(plugins, class_methods)
    assert findings == []


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
