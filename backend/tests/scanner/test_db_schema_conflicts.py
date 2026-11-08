from app.scanner.db_schema_conflicts import DbColumnRow, detect_db_schema_conflicts


def _col(module_id, module_name, table_name="foo_table", column_name="bar", xsi_type="int", nullable=False):
    return DbColumnRow(
        module_id=module_id,
        module_name=module_name,
        table_name=table_name,
        column_name=column_name,
        xsi_type=xsi_type,
        nullable=nullable,
    )


def test_no_conflict_with_a_single_declarer():
    columns = [_col(1, "Vendor_A")]
    assert detect_db_schema_conflicts(columns) == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    columns = [_col(1, "Vendor_A", xsi_type="int"), _col(1, "Vendor_A", xsi_type="int")]
    assert detect_db_schema_conflicts(columns) == []


def test_no_conflict_when_two_modules_agree_on_type_and_nullable():
    columns = [
        _col(1, "Vendor_A", xsi_type="int", nullable=False),
        _col(2, "Vendor_B", xsi_type="int", nullable=False),
    ]
    assert detect_db_schema_conflicts(columns) == []


def test_no_conflict_when_columns_are_on_different_tables():
    columns = [
        _col(1, "Vendor_A", table_name="foo_table", xsi_type="int"),
        _col(2, "Vendor_B", table_name="bar_table", xsi_type="varchar"),
    ]
    assert detect_db_schema_conflicts(columns) == []


def test_flags_a_real_cross_module_type_conflict():
    columns = [
        _col(1, "Vendor_A", xsi_type="int", nullable=False),
        _col(2, "Vendor_B", xsi_type="varchar", nullable=False),
    ]

    findings = detect_db_schema_conflicts(columns)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "db_schema_conflict"
        assert finding.severity == "warning"
        assert "foo_table.bar" in finding.message
        assert "a different xsi:type" in finding.message
        assert "Vendor_A (int, nullable=False)" in finding.message
        assert "Vendor_B (varchar, nullable=False)" in finding.message


def test_flags_a_nullable_only_conflict():
    columns = [
        _col(1, "Vendor_A", xsi_type="int", nullable=False),
        _col(2, "Vendor_B", xsi_type="int", nullable=True),
    ]

    findings = detect_db_schema_conflicts(columns)

    assert len(findings) == 2
    assert "a different nullable value" in findings[0][1].message
    assert "a different xsi:type" not in findings[0][1].message
