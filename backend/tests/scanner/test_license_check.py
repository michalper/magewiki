from app.scanner.license_check import check_license_risk


def test_no_finding_when_license_is_missing():
    assert check_license_risk(None) == []


def test_no_finding_when_license_is_an_empty_list():
    assert check_license_risk([]) == []


def test_no_finding_for_a_permissive_license():
    assert check_license_risk(["MIT"]) == []


def test_no_finding_for_magentos_own_dual_license():
    assert check_license_risk(["OSL-3.0", "AFL-3.0"]) == []


def test_flags_gpl():
    findings = check_license_risk(["GPL-3.0"])
    assert len(findings) == 1
    assert findings[0].check_type == "license_risk"
    assert findings[0].severity == "warning"
    assert "GPL-3.0" in findings[0].message


def test_flags_agpl():
    findings = check_license_risk(["AGPL-3.0-only"])
    assert len(findings) == 1
    assert "AGPL-3.0-only" in findings[0].message


def test_flags_sspl():
    findings = check_license_risk(["SSPL-1.0"])
    assert len(findings) == 1


def test_does_not_flag_lgpl():
    assert check_license_risk(["LGPL-3.0"]) == []


def test_matching_is_case_insensitive():
    findings = check_license_risk(["gpl-2.0"])
    assert len(findings) == 1


def test_mixed_license_list_only_names_the_risky_entries():
    findings = check_license_risk(["MIT", "GPL-3.0"])
    assert len(findings) == 1
    assert "MIT" not in findings[0].message
    assert "GPL-3.0" in findings[0].message


def test_one_finding_even_with_multiple_risky_licenses():
    findings = check_license_risk(["GPL-3.0", "AGPL-3.0"])
    assert len(findings) == 1
    assert "GPL-3.0" in findings[0].message
    assert "AGPL-3.0" in findings[0].message
