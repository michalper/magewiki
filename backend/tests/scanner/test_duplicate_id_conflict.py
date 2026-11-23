from dataclasses import dataclass

from app.scanner.duplicate_id_conflict import detect_duplicate_id_conflict

# Direct coverage of the shared algorithm itself (extracted after a
# whole-project code review found 5 call sites -- acl/indexer/mview/widget/
# menu_conflicts.py -- had copied it byte-for-byte). Each of those 5 files
# keeps its own dedicated test suite exercising this through its own
# dataclass/check_type/message; this file is the one place testing the
# shared mechanism on its own terms, with a throwaway row shape.


@dataclass
class _Row:
    module_id: int
    module_name: str
    thing_id: str


def _row(module_id, module_name, thing_id="shared-thing"):
    return _Row(module_id=module_id, module_name=module_name, thing_id=thing_id)


def test_no_conflict_with_a_single_declarer():
    findings = detect_duplicate_id_conflict([_row(1, "Vendor_A")], "thing_id", "thing_conflict", lambda i, w: "x")
    assert findings == []


def test_no_conflict_when_the_same_module_declares_it_twice():
    rows = [_row(1, "Vendor_A"), _row(1, "Vendor_A")]
    findings = detect_duplicate_id_conflict(rows, "thing_id", "thing_conflict", lambda i, w: "x")
    assert findings == []


def test_no_conflict_when_ids_differ():
    rows = [_row(1, "Vendor_A", thing_id="a"), _row(2, "Vendor_B", thing_id="b")]
    findings = detect_duplicate_id_conflict(rows, "thing_id", "thing_conflict", lambda i, w: "x")
    assert findings == []


def test_flags_a_real_cross_module_conflict_and_passes_id_and_who_to_message():
    rows = [_row(1, "Vendor_A"), _row(2, "Vendor_B")]
    seen_args = []

    def message(thing_id, who):
        seen_args.append((thing_id, who))
        return f"conflict on {thing_id}: {who}"

    findings = detect_duplicate_id_conflict(rows, "thing_id", "thing_conflict", message)

    assert {module_id for module_id, _ in findings} == {1, 2}
    for _, finding in findings:
        assert finding.check_type == "thing_conflict"
        assert finding.severity == "warning"
        assert finding.file_path is None
        assert finding.line is None
        assert finding.message == "conflict on shared-thing: Vendor_A, Vendor_B"
    # message() is called once per conflicting group, not once per module.
    assert seen_args == [("shared-thing", "Vendor_A, Vendor_B")]


def test_three_way_conflict_flags_every_distinct_module():
    rows = [_row(1, "Vendor_A"), _row(2, "Vendor_B"), _row(3, "Vendor_C")]
    findings = detect_duplicate_id_conflict(rows, "thing_id", "thing_conflict", lambda i, w: "x")
    assert {module_id for module_id, _ in findings} == {1, 2, 3}
