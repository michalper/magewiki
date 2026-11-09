from collections.abc import Awaitable, Callable
from typing import cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    Chunk,
    DiPlugin,
    DiPreference,
    EventObserver,
    Module,
    ModuleDependency,
    ModuleDocument,
    ModuleQualityFinding,
    PhpClass,
)
from app.search.hybrid import hybrid_search
from app.search.query_rewrite import rewrite_query
from app.search.rerank import rerank_results

# Reranking needs more raw candidates than the final answer to actually have
# something to reorder -- asking a hybrid search for exactly `limit` results
# and then "reranking" them would just reshuffle an already-narrow list.
_RERANK_CANDIDATE_POOL = 20


async def search_modules(session: AsyncSession, query: str, limit: int = 10) -> dict:
    # Two independent, independently-costed optimizations over the same base
    # hybrid_search call -- rewriting reformulates the query *before*
    # retrieval runs, reranking reorders what retrieval found *after*. Each
    # is its own per-query LLM cost decision (see each module's own docstring
    # and docs/architecture.md's "What this doesn't do (yet)" note), so each
    # has its own settings flag rather than one gating the other.
    effective_query = await rewrite_query(session, query) if settings.query_rewrite_enabled else query
    if settings.rerank_enabled:
        candidates = await hybrid_search(session, effective_query, limit=max(limit, _RERANK_CANDIDATE_POOL))
        results = await rerank_results(session, effective_query, candidates, top_k=limit)
    else:
        results = await hybrid_search(session, effective_query, limit=limit)
    return {
        "results": [
            {
                "module_id": r.module_id,
                "module_name": r.module_name,
                "chunk_type": r.chunk_type,
                "relative_path": r.relative_path,
                "text": r.text,
                "score": r.score,
                "semantic_rank": r.semantic_rank,
                "keyword_rank": r.keyword_rank,
                "identifier_rank": r.identifier_rank,
            }
            for r in results
        ]
    }


async def get_module(session: AsyncSession, module_id: int) -> dict:
    module = await session.get(Module, module_id)
    if module is None:
        return {"found": False}

    dependencies = (
        await session.scalars(select(ModuleDependency.depends_on_name).where(ModuleDependency.module_id == module_id))
    ).all()

    result = {
        "found": True,
        "module_id": module.id,
        "name": module.name,
        "state": module.state,
        "enabled": module.enabled,
        "last_scanned_at": module.last_scanned_at.isoformat(),
        "dependencies": list(dependencies),
        "analyzed": False,
    }

    doc_row = await session.scalar(select(ModuleDocument).where(ModuleDocument.module_id == module_id))
    if doc_row is not None:
        doc = doc_row.doc
        result["analyzed"] = True
        result["doc_content_hash"] = doc_row.content_hash
        result["summary"] = doc.get("summary")
        result["description"] = doc.get("description")
        result["features"] = doc.get("features")
        result["integrations"] = doc.get("integrations")
        result["tags"] = doc.get("tags")
        result["pm_text"] = doc.get("pm_text")
        result["dev_text"] = doc.get("dev_text")

    return result


async def get_dependencies(session: AsyncSession, module_id: int) -> dict:
    module = await session.get(Module, module_id)
    if module is None:
        return {"found": False}

    depends_on = (
        await session.scalars(select(ModuleDependency.depends_on_name).where(ModuleDependency.module_id == module_id))
    ).all()
    used_by = (
        await session.scalars(
            select(Module.name)
            .join(ModuleDependency, ModuleDependency.module_id == Module.id)
            .where(ModuleDependency.depends_on_name == module.name)
        )
    ).all()

    return {
        "found": True,
        "module_name": module.name,
        "depends_on": list(depends_on),
        "used_by": list(used_by),
    }


def _escape_like(value: str) -> str:
    """Postgres LIKE/ILIKE treats backslash as its own escape character by default,
    so an unescaped FQCN like Vendor\\Module\\Foo would silently mismatch. Escape
    backslash first, then the two LIKE wildcards, before wrapping in %...%.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def find_by_event(session: AsyncSession, event_name: str) -> dict:
    like = f"%{_escape_like(event_name)}%"
    rows = (
        await session.execute(
            select(EventObserver, Module.name)
            .join(Module, Module.id == EventObserver.module_id)
            .where(EventObserver.event_name.ilike(like))
        )
    ).all()

    return {
        "results": [
            {
                "module_id": observer.module_id,
                "module_name": module_name,
                "event_name": observer.event_name,
                "observer_name": observer.observer_name,
                "observer_class": observer.observer_class,
                "disabled": observer.disabled,
            }
            for observer, module_name in rows
        ]
    }


async def find_by_class(session: AsyncSession, identifier: str) -> dict:
    like = f"%{_escape_like(identifier)}%"

    defined_in = (
        await session.execute(
            select(PhpClass, Module.name)
            .join(Module, Module.id == PhpClass.module_id)
            .where(PhpClass.fqcn.ilike(like) | PhpClass.class_name.ilike(like))
        )
    ).all()
    overridden_by = (
        await session.execute(
            select(DiPreference, Module.name)
            .join(Module, Module.id == DiPreference.module_id)
            .where(DiPreference.for_type.ilike(like))
        )
    ).all()
    plugins_targeting_it = (
        await session.execute(
            select(DiPlugin, Module.name)
            .join(Module, Module.id == DiPlugin.module_id)
            .where(DiPlugin.intercepted_type.ilike(like))
        )
    ).all()
    is_a_plugin_for = (
        await session.execute(
            select(DiPlugin, Module.name)
            .join(Module, Module.id == DiPlugin.module_id)
            .where(DiPlugin.plugin_class.ilike(like))
        )
    ).all()

    return {
        "defined_in": [
            {
                "module_id": c.module_id,
                "module_name": m,
                "fqcn": c.fqcn,
                "file_path": c.file_path,
                "is_plugin": c.is_plugin,
                "is_observer": c.is_observer,
            }
            for c, m in defined_in
        ],
        "overridden_by": [
            {"module_id": p.module_id, "module_name": m, "for_type": p.for_type, "preference_type": p.preference_type}
            for p, m in overridden_by
        ],
        "plugins_targeting_it": [
            {"module_id": p.module_id, "module_name": m, "plugin_class": p.plugin_class, "plugin_name": p.plugin_name}
            for p, m in plugins_targeting_it
        ],
        "is_a_plugin_for": [
            {"module_id": p.module_id, "module_name": m, "intercepted_type": p.intercepted_type, "plugin_name": p.plugin_name}
            for p, m in is_a_plugin_for
        ],
    }


async def read_file(session: AsyncSession, module_id: int, relative_path: str) -> dict:
    chunks = (
        await session.scalars(
            select(Chunk).where(Chunk.module_id == module_id, Chunk.relative_path == relative_path)
        )
    ).all()
    if not chunks:
        return {"found": False}

    module_name = await session.scalar(select(Module.name).where(Module.id == module_id))

    return {
        "found": True,
        "module_name": module_name,
        "chunks": [{"chunk_type": c.chunk_type, "text": c.text} for c in chunks],
    }


async def list_modules(
    session: AsyncSession,
    tags: list[str] | None = None,
    integration: str | None = None,
    status: str | None = None,
    enabled: bool | None = None,
    check_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    query = select(Module, ModuleDocument.doc).outerjoin(ModuleDocument, ModuleDocument.module_id == Module.id)
    if status:
        query = query.where(Module.state == status)
    if enabled is not None:
        query = query.where(Module.enabled == enabled)
    if check_type:
        # A plain IN-subquery, not a join -- a module can have several
        # findings of the same check_type (e.g. 3 hardcoded_secret rows),
        # which would otherwise duplicate that module's own row in the
        # result set.
        query = query.where(
            Module.id.in_(select(ModuleQualityFinding.module_id).where(ModuleQualityFinding.check_type == check_type))
        )

    rows = (await session.execute(query.order_by(Module.name))).all()

    filtered = []
    for row in rows:
        # select(Module, ModuleDocument.doc)'s Row degenerates each element to
        # `object` under mypy (confirmed via reveal_type) — cast() is the
        # type-level fix, zero runtime effect.
        module = cast(Module, row[0])
        doc = cast(dict | None, row[1]) or {}
        if tags:
            doc_tags = {t.get("name") for t in doc.get("tags", [])}
            if not set(tags) & doc_tags:
                continue
        if integration:
            doc_integrations = [i.get("name", "") for i in doc.get("integrations", [])]
            if not any(integration.lower() in name.lower() for name in doc_integrations):
                continue
        filtered.append((module, doc))

    page = filtered[offset : offset + limit]

    finding_counts: dict[int, int] = {}
    if check_type:
        page_ids = [module.id for module, _doc in page]
        count_rows = (
            await session.execute(
                select(ModuleQualityFinding.module_id, func.count())
                .where(ModuleQualityFinding.module_id.in_(page_ids), ModuleQualityFinding.check_type == check_type)
                .group_by(ModuleQualityFinding.module_id)
            )
        ).all()
        finding_counts = dict(count_rows)

    return {
        "total": len(filtered),
        "modules": [
            {
                "module_id": module.id,
                "name": module.name,
                "state": module.state,
                "enabled": module.enabled,
                "tags": [t.get("name") for t in doc.get("tags", [])],
                "integrations": [i.get("name") for i in doc.get("integrations", [])],
                **({"finding_count": finding_counts.get(module.id, 0)} if check_type else {}),
            }
            for module, doc in page
        ],
    }


TOOL_FUNCTIONS: dict[str, Callable[..., Awaitable[dict]]] = {
    "search_modules": search_modules,
    "get_module": get_module,
    "get_dependencies": get_dependencies,
    "find_by_event": find_by_event,
    "find_by_class": find_by_class,
    "read_file": read_file,
    "list_modules": list_modules,
}

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_modules",
            "description": (
                "Hybrid semantic + keyword + identifier search over module/file/method summaries. "
                "Use for open-ended questions like 'do we have a Klaviyo integration?' or 'how does X send data?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Natural-language search query"},
                    "limit": {"type": "integer", "description": "Max results, default 10"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_module",
            "description": (
                "Get full details for one module by id: summary, description, features, integrations, tags, "
                "pm/dev text variants, dependencies, scan status (state, enabled, last_scanned_at)."
            ),
            "parameters": {
                "type": "object",
                "properties": {"module_id": {"type": "integer"}},
                "required": ["module_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_dependencies",
            "description": "Get what a module depends on, and what other modules depend on it.",
            "parameters": {
                "type": "object",
                "properties": {"module_id": {"type": "integer"}},
                "required": ["module_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_by_event",
            "description": "Find which observers listen to a given Magento event name.",
            "parameters": {
                "type": "object",
                "properties": {"event_name": {"type": "string"}},
                "required": ["event_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_by_class",
            "description": (
                "Find where a class/interface is defined, what overrides it (di.xml preference), what plugins "
                "intercept it, and what it is itself a plugin for. Accepts a partial FQCN or class name."
            ),
            "parameters": {
                "type": "object",
                "properties": {"identifier": {"type": "string"}},
                "required": ["identifier"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": (
                "Read the stored summary/source for one file (or a plugin/observer method) of a module, for "
                "citation. Returns found=false if nothing is stored for that exact path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "module_id": {"type": "integer"},
                    "relative_path": {"type": "string"},
                },
                "required": ["module_id", "relative_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_modules",
            "description": (
                "Enumerate modules by tag/integration/status/enabled/check_type, with total count and pagination. "
                "Use for counting/enumeration questions ('how many payment modules', 'which modules have a known "
                "CVE', 'show modules with failing PHPUnit tests') where top-k search can't guarantee completeness. "
                "check_type is one of: composer_completeness, deprecated_annotation, hardcoded_secret, "
                "security_advisory (known CVEs), abandoned_dependency, outdated_dependency, phpstan_error, "
                "phpmd_issue, phpcs_violation, php_compat_issue, magento_php_incompatible, magento_version_blocker, "
                "plugin_conflict, phpmetrics_issue, composer_conflict, webapi_route_conflict, db_schema_conflict, "
                "circular_dependency, license_risk, phpunit_failure. When check_type is set, each returned module "
                "also has a finding_count for that specific check_type."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "integration": {"type": "string"},
                    "status": {"type": "string"},
                    "enabled": {"type": "boolean"},
                    "check_type": {"type": "string"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
                "required": [],
            },
        },
    },
]
