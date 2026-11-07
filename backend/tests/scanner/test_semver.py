from app.scanner.semver import constraints_overlap


def test_exact_version_overlaps_itself():
    assert constraints_overlap("1.2.3", "1.2.3") is True


def test_exact_version_does_not_overlap_a_different_exact_version():
    assert constraints_overlap("1.2.3", "1.2.4") is False


def test_caret_range_overlaps_an_advisory_range_inside_it():
    # ^1.2.0 means >=1.2.0 <2.0.0
    assert constraints_overlap("^1.2.0", ">=1.5.0,<1.6.0") is True


def test_caret_range_does_not_overlap_a_range_entirely_above_it():
    assert constraints_overlap("^1.0.0", ">=2.0.0,<3.0.0") is False


def test_tilde_range_bumps_the_second_to_last_component():
    # ~1.2.3 means >=1.2.3 <1.3.0
    assert constraints_overlap("~1.2.3", ">=1.2.9,<1.4.0") is True
    assert constraints_overlap("~1.2.3", ">=1.3.0,<1.4.0") is False


def test_wildcard_range():
    # 1.2.* means >=1.2.0 <1.3.0
    assert constraints_overlap("1.2.*", ">=1.2.5,<1.2.9") is True
    assert constraints_overlap("1.2.*", ">=1.3.0") is False


def test_comma_separated_and_condition():
    assert constraints_overlap(">=1.0,<2.0", ">=1.5,<1.6") is True
    assert constraints_overlap(">=1.0,<2.0", ">=2.0,<3.0") is False


def test_or_condition_via_double_pipe():
    assert constraints_overlap("^1.0 || ^3.0", ">=3.5.0,<4.0.0") is True
    assert constraints_overlap("^1.0 || ^3.0", ">=2.0.0,<3.0.0") is False


def test_boundary_is_exclusive_on_caret_upper_bound():
    assert constraints_overlap("^1.0.0", ">=2.0.0") is False
    assert constraints_overlap("^1.0.0", ">=1.9.9") is True


def test_unbounded_wildcard_overlaps_everything():
    assert constraints_overlap("*", "1.0.0") is True


def test_hyphenated_range_means_inclusive_bounds_on_both_ends():
    # Composer's officially-supported "1.0.0 - 2.1.0" syntax, equivalent to
    # ">=1.0.0 <=2.1.0" — previously fell through to the exact-version branch on
    # the bare "-" token and produced an inverted/empty interval (a false
    # "no overlap" even when the ranges genuinely did overlap).
    assert constraints_overlap("1.0.0 - 2.1.0", "2.0.0") is True
    assert constraints_overlap("1.0.0 - 2.1.0", "2.1.0") is True
    assert constraints_overlap("1.0.0 - 2.1.0", "2.1.1") is False
    assert constraints_overlap("1.0.0 - 2.1.0", "0.9.9") is False


def test_hyphenated_range_with_short_versions():
    assert constraints_overlap("1.0 - 2.0", "1.5") is True
    assert constraints_overlap("1.0 - 2.0", "2.5") is False


def test_hyphenated_range_is_unaffected_by_a_prerelease_suffix_dash():
    # The embedded dash in "1.0.0-beta" has no surrounding whitespace, unlike the
    # hyphen-range separator, so it must not be mistaken for one.
    assert constraints_overlap("^1.0.0-beta", ">=1.0.0,<2.0.0") is True
