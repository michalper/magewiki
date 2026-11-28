from app.scanner.email_template_conflicts import (
    EmailTemplateRow,
    detect_email_template_id_conflicts,
)


def _template(module_id, module_name, template_id="vendor_module_welcome"):
    return EmailTemplateRow(module_id=module_id, module_name=module_name, template_id=template_id)


def test_no_conflict_with_a_single_declarer():
    assert detect_email_template_id_conflicts([_template(1, "Vendor_A")]) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    templates = [_template(1, "Vendor_A"), _template(1, "Vendor_A")]
    assert detect_email_template_id_conflicts(templates) == []


def test_no_conflict_when_template_ids_differ():
    templates = [
        _template(1, "Vendor_A", template_id="vendor_a_welcome"),
        _template(2, "Vendor_B", template_id="vendor_b_welcome"),
    ]
    assert detect_email_template_id_conflicts(templates) == []


def test_flags_a_real_cross_module_template_id_conflict():
    templates = [
        _template(1, "Vendor_A", template_id="shared_template"),
        _template(2, "Vendor_B", template_id="shared_template"),
    ]

    findings = detect_email_template_id_conflicts(templates)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "email_template_id_conflict"
        assert finding.severity == "warning"
        assert "shared_template" in finding.message
        assert "Vendor_A" in finding.message
        assert "Vendor_B" in finding.message
