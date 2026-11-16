"""Guardrail against the exact bug class the GET /search budget-bypass finding
was: a new, real, billed litellm.acompletion()/aembedding() call site added
somewhere in app/ without anyone checking whether it's actually covered by the
monthly budget (is_budget_exceeded) before it ships.

This can't be fully automated (whether a given call site is "covered" depends
on whether its caller checks the budget, which varies by call chain -- see the
comment on each entry below), but a new call site changing the exact set below
forces a conscious decision instead of a silent gap: either the new function
checks the budget itself, or the person who called it does, and either way
this test's expected set (with a comment explaining which) has to be updated
by hand for the test to pass again.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
_LITELLM_CALL_METHODS = {"acompletion", "aembedding"}

# (relative path, enclosing function name, litellm method) -> why this call
# site doesn't need its own is_budget_exceeded() check right at the call,
# despite making a real, billed LLM/embedding call.
_KNOWN_CALL_SITES = {
    # Checks is_budget_exceeded() itself, right before this exact call
    # (run_agent's per-round and final-turn checks -- see app/agent/loop.py).
    ("app/agent/loop.py", "run_agent", "acompletion"): "checks budget itself, right before this call",
    # Low-level primitives: budget is checked by every real caller before
    # calling these, not inside them (jobs.py's analyze_file/synthesize_module
    # call is_budget_exceeded() before summarize_file()/synthesize_module_doc(),
    # which are the only callers of these two).
    ("app/analyzer/client.py", "_call_tool_use", "acompletion"): "caller (jobs.py) checks budget first",
    ("app/analyzer/client.py", "_call_plain_json", "acompletion"): "caller (jobs.py) checks budget first",
    # Low-level primitives: every real caller checks budget first --
    # embed_chunks (jobs.py) and embed_query_text's session-aware path
    # (app/analyzer/embeddings.py) both call is_budget_exceeded() before
    # reaching embed_text()/embed_texts_batch().
    ("app/analyzer/embeddings.py", "embed_text", "aembedding"): "caller checks budget first",
    ("app/analyzer/embeddings.py", "embed_texts_batch", "aembedding"): "caller checks budget first",
    # Each checks is_budget_exceeded() itself, right before this call --
    # see test_rewrite_query_falls_back_when_over_budget /
    # test_rerank_results_falls_back_when_over_budget.
    ("app/search/query_rewrite.py", "rewrite_query", "acompletion"): "checks budget itself, right before this call",
    ("app/search/rerank.py", "rerank_results", "acompletion"): "checks budget itself, right before this call",
    # Offline evaluation suite only (judge_faithfulness, run_eval.py) --
    # deliberately not part of the live budget ledger, same as the rest of
    # app/evaluation/'s LLM calls (seed_corpus's own synthesize_module_doc is
    # monkeypatched out in every test and in the real eval run itself budget-
    # checked the normal way via jobs.py, so this is the one genuine
    # exception, not a gap).
    ("app/evaluation/faithfulness.py", "judge_faithfulness", "acompletion"): "offline eval suite, not in the live budget ledger",
}


def _collect_litellm_aliases(tree: ast.Module) -> tuple[set[str], dict[str, str]]:
    """Every name a file could call a real litellm.acompletion()/aembedding()
    through: `module_aliases` for `import litellm [as x]` (x.acompletion(...)
    counts), `function_aliases` for `from litellm import acompletion [as y]`
    (a bare y(...) counts, mapped back to "acompletion"/"aembedding"). Every
    real call site in app/ today uses plain `import litellm` +
    `litellm.acompletion(...)`, but matching only that literal spelling means
    a future `from litellm import aembedding` (a bare call, no `litellm.`
    prefix at all) would silently never be seen by this guardrail at all.
    """
    module_aliases: set[str] = set()
    function_aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "litellm":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module == "litellm":
            for alias in node.names:
                if alias.name in _LITELLM_CALL_METHODS:
                    function_aliases[alias.asname or alias.name] = alias.name
    return module_aliases, function_aliases


def _call_sites_in_source(source: str, relative_path: str) -> set[tuple[str, str, str]]:
    tree = ast.parse(source, filename=relative_path)
    module_aliases, function_aliases = _collect_litellm_aliases(tree)
    found: set[tuple[str, str, str]] = set()

    class _Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.func_stack: list[str] = []

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self.func_stack.append(node.name)
            self.generic_visit(node)
            self.func_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            self.func_stack.append(node.name)
            self.generic_visit(node)
            self.func_stack.pop()

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            litellm_method: str | None = None
            if (
                isinstance(func, ast.Attribute)
                and func.attr in _LITELLM_CALL_METHODS
                and isinstance(func.value, ast.Name)
                and func.value.id in module_aliases
            ):
                litellm_method = func.attr
            elif isinstance(func, ast.Name) and func.id in function_aliases:
                litellm_method = function_aliases[func.id]

            if litellm_method is not None:
                enclosing = self.func_stack[-1] if self.func_stack else "<module>"
                found.add((relative_path, enclosing, litellm_method))
            self.generic_visit(node)

    _Visitor().visit(tree)
    return found


def _find_litellm_call_sites() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in sorted(APP_DIR.rglob("*.py")):
        relative_path = str(path.relative_to(APP_DIR.parent)).replace("\\", "/")
        found |= _call_sites_in_source(path.read_text(encoding="utf-8"), relative_path)
    return found


def test_detects_the_plain_import_litellm_style_every_real_call_site_uses():
    source = """
import litellm

async def caller():
    return await litellm.acompletion(model="x")
"""
    assert _call_sites_in_source(source, "fake.py") == {("fake.py", "caller", "acompletion")}


def test_detects_an_aliased_module_import():
    source = """
import litellm as ll

async def caller():
    return await ll.aembedding(model="x")
"""
    assert _call_sites_in_source(source, "fake.py") == {("fake.py", "caller", "aembedding")}


def test_detects_a_bare_from_import_with_no_litellm_prefix_at_all():
    source = """
from litellm import acompletion

async def caller():
    return await acompletion(model="x")
"""
    assert _call_sites_in_source(source, "fake.py") == {("fake.py", "caller", "acompletion")}


def test_detects_an_aliased_from_import():
    source = """
from litellm import aembedding as embed

async def caller():
    return await embed(model="x")
"""
    assert _call_sites_in_source(source, "fake.py") == {("fake.py", "caller", "aembedding")}


def test_ignores_an_unrelated_module_with_the_same_method_name():
    source = """
import not_litellm

async def caller():
    return await not_litellm.acompletion(model="x")
"""
    assert _call_sites_in_source(source, "fake.py") == set()


def test_every_real_litellm_call_site_is_accounted_for():
    found = _find_litellm_call_sites()
    known = set(_KNOWN_CALL_SITES)

    new_sites = found - known
    assert not new_sites, (
        "New litellm.acompletion()/aembedding() call site(s) found that aren't in this "
        f"test's reviewed allow-list: {sorted(new_sites)}. Before adding it to "
        "_KNOWN_CALL_SITES: confirm this new call site either checks "
        "is_budget_exceeded() itself right before the call, or every real caller "
        "already does -- this is the exact bug class the GET /search budget-bypass "
        "finding was (a real, billed call with no budget check anywhere on its path)."
    )

    removed_sites = known - found
    assert not removed_sites, (
        f"Call site(s) no longer exist in the code: {sorted(removed_sites)}. "
        "Remove them from _KNOWN_CALL_SITES (dead entries make this guardrail "
        "harder to read, and could mask a real removal that should have kept a "
        "budget check alive somewhere else)."
    )
