from decimal import Decimal
from types import SimpleNamespace

from app.agent.loop import Source, _collect_sources, _turn_cost


def _usage(prompt_tokens=100, completion_tokens=50) -> SimpleNamespace:
    return SimpleNamespace(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)


def test_turn_cost_uses_litellms_own_cost(monkeypatch):
    monkeypatch.setattr("app.agent.loop.litellm.completion_cost", lambda **k: 0.0021)

    response = SimpleNamespace(usage=_usage())
    tokens_in, tokens_out, cost = _turn_cost(response, "anthropic/claude-haiku-5-5")

    assert (tokens_in, tokens_out) == (100, 50)
    assert cost == Decimal("0.0021")


def test_turn_cost_falls_back_when_litellm_raises(monkeypatch):
    def _raise(**k):
        raise RuntimeError("no pricing data")

    monkeypatch.setattr("app.agent.loop.litellm.completion_cost", _raise)
    monkeypatch.setattr("app.agent.loop.compute_cost_usd", lambda model, tin, tout: Decimal("0.0005"))

    response = SimpleNamespace(usage=_usage())
    _tin, _tout, cost = _turn_cost(response, "m")

    assert cost == Decimal("0.0005")


def test_turn_cost_falls_back_when_litellm_returns_zero(monkeypatch):
    monkeypatch.setattr("app.agent.loop.litellm.completion_cost", lambda **k: 0)
    monkeypatch.setattr("app.agent.loop.compute_cost_usd", lambda model, tin, tout: Decimal("0.0006"))

    response = SimpleNamespace(usage=_usage())
    _tin, _tout, cost = _turn_cost(response, "m")

    assert cost == Decimal("0.0006")


def test_collect_sources_ignores_a_result_with_no_module_id():
    sources: dict[tuple, Source] = {}
    _collect_sources("search_modules", {}, {"results": [{"module_name": "No Id"}]}, sources)
    assert sources == {}


def test_collect_sources_search_modules():
    sources: dict[tuple, Source] = {}
    result = {"results": [{"module_id": 1, "module_name": "Vendor_A", "relative_path": "Foo.php"}]}
    _collect_sources("search_modules", {}, result, sources)
    assert sources == {(1, "Foo.php"): Source(module_id=1, module_name="Vendor_A", relative_path="Foo.php")}


def test_collect_sources_get_module_found():
    sources: dict[tuple, Source] = {}
    _collect_sources("get_module", {}, {"found": True, "module_id": 2, "name": "Vendor_B"}, sources)
    assert sources == {(2, None): Source(module_id=2, module_name="Vendor_B", relative_path=None)}


def test_collect_sources_get_module_not_found():
    sources: dict[tuple, Source] = {}
    _collect_sources("get_module", {}, {"found": False}, sources)
    assert sources == {}


def test_collect_sources_get_dependencies():
    sources: dict[tuple, Source] = {}
    args = {"module_id": 3}
    _collect_sources("get_dependencies", args, {"found": True, "module_name": "Vendor_C"}, sources)
    assert sources == {(3, None): Source(module_id=3, module_name="Vendor_C", relative_path=None)}


def test_collect_sources_find_by_event():
    sources: dict[tuple, Source] = {}
    result = {"results": [{"module_id": 4, "module_name": "Vendor_D"}]}
    _collect_sources("find_by_event", {}, result, sources)
    assert sources == {(4, None): Source(module_id=4, module_name="Vendor_D", relative_path=None)}


def test_collect_sources_find_by_class_covers_every_result_key():
    sources: dict[tuple, Source] = {}
    result = {
        "defined_in": [{"module_id": 1, "module_name": "A"}],
        "overridden_by": [{"module_id": 2, "module_name": "B"}],
        "plugins_targeting_it": [{"module_id": 3, "module_name": "C"}],
        "is_a_plugin_for": [{"module_id": 4, "module_name": "D"}],
    }
    _collect_sources("find_by_class", {}, result, sources)
    assert {k[0] for k in sources} == {1, 2, 3, 4}


def test_collect_sources_unknown_tool_name_is_a_no_op():
    sources: dict[tuple, Source] = {}
    _collect_sources("some_future_tool", {}, {"anything": True}, sources)
    assert sources == {}
