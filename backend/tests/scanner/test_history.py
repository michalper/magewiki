from app.scanner.history import ModuleHistoryState, snapshot_changed


def _state(current_hash="hash1", state="up_to_date", enabled=True, finding_counts=None):
    return ModuleHistoryState(
        current_hash=current_hash, state=state, enabled=enabled, finding_counts=finding_counts or {}
    )


def test_no_previous_snapshot_always_changed():
    assert snapshot_changed(None, _state()) is True


def test_identical_state_is_not_changed():
    previous = _state(finding_counts={"phpstan_error": 3})
    current = _state(finding_counts={"phpstan_error": 3})
    assert snapshot_changed(previous, current) is False


def test_hash_change_is_changed():
    previous = _state(current_hash="hash1")
    current = _state(current_hash="hash2")
    assert snapshot_changed(previous, current) is True


def test_state_change_is_changed():
    previous = _state(state="up_to_date")
    current = _state(state="failed")
    assert snapshot_changed(previous, current) is True


def test_enabled_change_is_changed():
    previous = _state(enabled=True)
    current = _state(enabled=False)
    assert snapshot_changed(previous, current) is True


def test_finding_counts_change_is_changed():
    previous = _state(finding_counts={"phpstan_error": 3})
    current = _state(finding_counts={"phpstan_error": 5})
    assert snapshot_changed(previous, current) is True


def test_new_finding_type_appearing_is_changed():
    previous = _state(finding_counts={"phpstan_error": 3})
    current = _state(finding_counts={"phpstan_error": 3, "security_advisory": 1})
    assert snapshot_changed(previous, current) is True
