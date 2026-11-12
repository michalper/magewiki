from app.scanner.admin_acl import find_missing_acl
from app.scanner.dto import PhpClassEntry

_ADMIN_PATH = "Controller/Adminhtml/Index/Index.php"


def _cls(
    class_name,
    file_path=_ADMIN_PATH,
    kind="class",
    extends=None,
    implements=None,
    consts=None,
    is_abstract=False,
):
    return PhpClassEntry(
        fqcn=f"Vendor\\Module\\{class_name}",
        namespace="Vendor\\Module",
        class_name=class_name,
        kind=kind,
        extends=extends or [],
        implements=implements or [],
        file_path=file_path,
        start_line=1,
        end_line=10,
        methods=[],
        is_abstract=is_abstract,
        consts=consts or {},
    )


def test_flags_an_admin_controller_with_no_parent_and_no_admin_resource():
    findings = find_missing_acl([_cls("Index")])

    assert len(findings) == 1
    assert findings[0].check_type == "missing_acl"
    assert findings[0].severity == "warning"
    assert findings[0].file_path == _ADMIN_PATH


def test_does_not_flag_a_controller_with_its_own_admin_resource():
    classes = [_cls("Index", consts={"ADMIN_RESOURCE": "Vendor_Module::index"})]
    assert find_missing_acl(classes) == []


def test_does_not_flag_a_controller_inheriting_admin_resource_via_extends_in_module():
    classes = [
        _cls("AbstractIndex", consts={"ADMIN_RESOURCE": "Vendor_Module::index"}, is_abstract=True),
        _cls("Index", extends=["AbstractIndex"]),
    ]
    assert find_missing_acl(classes) == []


def test_does_not_flag_a_controller_inheriting_admin_resource_via_implements_in_module():
    classes = [
        _cls("AclResourceInterface", kind="interface", consts={"ADMIN_RESOURCE": "Vendor_Module::index"}),
        _cls("Index", implements=["AclResourceInterface"]),
    ]
    assert find_missing_acl(classes) == []


def test_does_not_flag_a_controller_whose_parent_is_outside_the_module():
    # Extends the real \Magento\Backend\App\Action, never parsed by this module's
    # own scan -- unresolvable, so this must be skipped, not flagged.
    classes = [_cls("Index", extends=["Action"])]
    assert find_missing_acl(classes) == []


def test_does_not_flag_an_abstract_controller():
    classes = [_cls("AbstractIndex", is_abstract=True)]
    assert find_missing_acl(classes) == []


def test_does_not_flag_a_non_admin_controller():
    classes = [_cls("Index", file_path="Controller/Index/Index.php")]
    assert find_missing_acl(classes) == []


def test_does_not_flag_an_interface_under_the_admin_controller_path():
    classes = [_cls("SomeInterface", kind="interface")]
    assert find_missing_acl(classes) == []


def test_does_not_flag_when_the_extends_name_is_ambiguous_within_the_module():
    # Two unrelated classes share the bare name "AbstractAction" -- one
    # really is Index's parent (and has no ADMIN_RESOURCE of its own), the
    # other lives under a sibling directory and genuinely does declare one.
    # Resolving the extends clause by bare name alone can't tell which is
    # which, so this must be skipped as unresolvable, not flagged as a
    # concrete gap -- same treatment as a parent class outside the module.
    classes = [
        _cls("AbstractAction", file_path="Controller/Adminhtml/Product/AbstractAction.php", is_abstract=True),
        _cls(
            "AbstractAction",
            file_path="Controller/Adminhtml/Category/AbstractAction.php",
            consts={"ADMIN_RESOURCE": "Vendor_Module::category"},
            is_abstract=True,
        ),
        _cls("Index", extends=["AbstractAction"]),
    ]
    assert find_missing_acl(classes) == []
