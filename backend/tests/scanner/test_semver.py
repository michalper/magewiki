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
