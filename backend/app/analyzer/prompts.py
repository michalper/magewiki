from app.analyzer.facts import ModuleFacts
from app.analyzer.tags import ALLOWED_TAGS

FILE_SUMMARY_PROMPT_VERSION = "file_summary_v1"
MODULE_SYNTHESIS_PROMPT_VERSION = "module_synthesis_v1"
EMBEDDING_PROMPT_VERSION = "embedding_v1"
CHAT_PROMPT_VERSION = "chat_v1"
RERANK_PROMPT_VERSION = "rerank_v1"
QUERY_REWRITE_PROMPT_VERSION = "query_rewrite_v1"

MAX_FILE_CONTENT_CHARS = 50_000
# Reranking sees many candidates at once (vs. one file per analyze_file call) --
# capped much shorter per candidate to keep the prompt (and its cost) bounded.
# Relevance can usually be judged from the opening of a chunk; the full text is
# still what gets cited to the user afterward, this truncation is only for the
# reranker's own judgment.
MAX_RERANK_CANDIDATE_CHARS = 500


def build_rerank_prompt(query: str, candidates: list[tuple[int, str]]) -> str:
    """candidates: (chunk_id, text) pairs, already in the retriever's own
    (RRF-fused) order -- that order is itself a real signal, so it's presented
    as the starting point to re-rank, not hidden from the model.
    """
    lines = [
        (
            "You are reranking search results for a Magento 2 codebase knowledge base. "
            "Below is a user's query and a numbered list of candidate text chunks, already "
            "ordered by a hybrid retriever's best guess. Reorder them by true relevance to "
            "the query -- a chunk that only superficially shares keywords with the query but "
            "doesn't actually answer it should rank lower than the retriever's guess; a chunk "
            "that's genuinely relevant should rank higher.\n\n"
        ),
        f"Query: {query}\n\n",
        "Candidates:\n",
    ]
    for chunk_id, text in candidates:
        truncated = text[:MAX_RERANK_CANDIDATE_CHARS]
        note = "..." if len(text) > MAX_RERANK_CANDIDATE_CHARS else ""
        lines.append(f"[{chunk_id}] {truncated}{note}\n")
    lines.append(
        "\nReturn every candidate's id (the number in brackets), ordered from most to "
        "least relevant to the query. Include every id exactly once."
    )
    return "".join(lines)


def build_query_rewrite_prompt(query: str) -> str:
    """A different problem from reranking (see rerank's own prompt above):
    this reformulates the query itself, before retrieval ever runs, rather
    than reordering what retrieval already found.
    """
    return (
        "You are rewriting a user's search query for a hybrid (semantic + keyword + "
        "identifier) search engine over a Magento 2 module knowledge base. Rewrite the "
        "query into a clearer, more specific one that will retrieve better results -- "
        "expand vague phrasing, spell out likely technical terms (class names, config "
        "keys, integration names) the user might mean, and translate non-English terms "
        "into their likely English/Magento-ecosystem equivalent. Preserve the original "
        "intent exactly -- never add a constraint, filter, or fact the user didn't ask "
        "for. If the query is already clear and specific, return it unchanged.\n\n"
        f"Original query: {query}\n\n"
        "Return only the rewritten query."
    )


def build_file_summary_prompt(relative_path: str, content: str) -> str:
    truncated = content[:MAX_FILE_CONTENT_CHARS]
    truncation_note = (
        f"\n\n[... truncated, {len(content) - MAX_FILE_CONTENT_CHARS} more characters omitted ...]"
        if len(content) > MAX_FILE_CONTENT_CHARS
        else ""
    )

    return (
        "You are analyzing a single file from a Magento 2 module's source code. "
        "This file may be PHP, XML, or JSON — it could be a class, a plugin, an observer, "
        "a dependency-injection config, an event binding, or module metadata.\n\n"
        f"File path (relative to the module root): {relative_path}\n\n"
        "File content:\n"
        "```\n"
        f"{truncated}{truncation_note}\n"
        "```\n\n"
        "Summarize in 1-3 plain sentences what this file does, in business or technical terms "
        "appropriate to its content. If the file reveals something risky or integration-relevant "
        "(an external HTTP call, a hardcoded credential, direct SQL, a third-party API), note it as "
        "notable_behavior — otherwise leave notable_behavior null. Do not restate structural facts "
        "(class name, namespace) that are obvious from the file itself; focus on what it actually does."
    )


def build_module_synthesis_prompt(facts: ModuleFacts) -> str:
    lines: list[str] = []
    lines.append(f"You are documenting the Magento 2 module `{facts.name}`.")
    if facts.composer_name:
        lines.append(f"Composer package: {facts.composer_name} (type: {facts.composer_type or 'unknown'})")
    if facts.license:
        lines.append(f"License: {', '.join(facts.license)}")
    lines.append(f"Enabled: {facts.enabled if facts.enabled is not None else 'unknown'}")
    lines.append(f"Setup version: {facts.setup_version or 'unknown'}")

    if facts.dependencies:
        lines.append("\nDeclared module dependencies (<sequence> in module.xml):")
        lines.extend(f"- {d}" for d in facts.dependencies)

    if facts.di_preferences:
        lines.append("\nDependency-injection preferences (type overrides, from di.xml):")
        lines.extend(f"- {for_type} -> {pref_type}" for for_type, pref_type in facts.di_preferences)

    if facts.di_plugins:
        lines.append("\nPlugins (from di.xml):")
        lines.extend(
            f"- {name} intercepts {intercepted} via {plugin_class}"
            for intercepted, name, plugin_class in facts.di_plugins
        )

    if facts.di_virtual_types:
        lines.append("\nVirtual types (composed classes, from di.xml):")
        lines.extend(f"- {name} composes {virtual_type}" for name, virtual_type in facts.di_virtual_types)

    if facts.event_observers:
        lines.append("\nEvent observers (from events.xml):")
        lines.extend(
            f"- {name} listens for `{event}` via {observer_class}"
            for event, name, observer_class in facts.event_observers
        )

    if facts.graphql_fields:
        lines.append("\nGraphQL fields (from etc/schema.graphqls):")
        for operation_type, type_name, field_name, resolver_class in facts.graphql_fields:
            resolver_note = f" (resolved by {resolver_class})" if resolver_class else ""
            lines.append(f"- {type_name}.{field_name} [{operation_type}]{resolver_note}")

    if facts.config_fields:
        lines.append("\nAdmin config fields (from etc/adminhtml/system.xml):")
        lines.extend(
            f"- {path}" + (f" ({label})" if label else "") for path, label in facts.config_fields
        )

    if facts.queue_bindings:
        lines.append("\nMessage queue bindings (from communication.xml/queue_topology.xml/queue_consumer.xml):")
        for topic, destination, consumer_name, handler_class, handler_method in facts.queue_bindings:
            dest_note = f" -> queue {destination}" if destination and destination != topic else ""
            handler_note = f" consumed by {handler_class}::{handler_method}" if handler_class else ""
            consumer_note = f" (consumer: {consumer_name})" if consumer_name else ""
            lines.append(f"- {topic}{dest_note}{handler_note}{consumer_note}")

    if facts.db_tables:
        lines.append("\nDatabase tables (from etc/db_schema.xml):")
        for name, comment, column_count in facts.db_tables:
            comment_note = f" — {comment}" if comment else ""
            lines.append(f"- {name} ({column_count} columns){comment_note}")

    if facts.cron_jobs:
        lines.append("\nScheduled cron jobs (from etc/crontab.xml):")
        for name, instance_class, method, schedule in facts.cron_jobs:
            schedule_note = f" [{schedule}]" if schedule else ""
            lines.append(f"- {name} runs {instance_class}::{method}{schedule_note}")

    if facts.webapi_routes:
        lines.append("\nREST endpoints (from etc/webapi.xml):")
        for url, http_method, service_class, service_method, acl_resource in facts.webapi_routes:
            acl_note = f" (ACL: {acl_resource})" if acl_resource else ""
            lines.append(f"- {http_method} {url} -> {service_class}::{service_method}{acl_note}")

    if facts.acl_resources:
        lines.append("\nACL resources (from etc/acl.xml):")
        for resource_id, title, parent_id in facts.acl_resources:
            title_note = f" ({title})" if title else ""
            parent_note = f" under {parent_id}" if parent_id else ""
            lines.append(f"- {resource_id}{title_note}{parent_note}")

    if facts.indexers:
        lines.append("\nIndexers (from etc/indexer.xml):")
        for indexer_id, view_id, class_name in facts.indexers:
            view_note = f" (view: {view_id})" if view_id else ""
            class_note = f" -> {class_name}" if class_name else ""
            lines.append(f"- {indexer_id}{class_note}{view_note}")

    if facts.mviews:
        lines.append("\nMaterialized views (from etc/mview.xml):")
        for view_id, class_name, group_name in facts.mviews:
            class_note = f" -> {class_name}" if class_name else ""
            group_note = f" (group: {group_name})" if group_name else ""
            lines.append(f"- {view_id}{class_note}{group_note}")

    if facts.routes:
        lines.append("\nFrontend/adminhtml routes (from etc/{frontend,adminhtml}/routes.xml):")
        lines.extend(f"- [{area}] {route_id} -> frontName {front_name}" for area, route_id, front_name in facts.routes)

    if facts.widgets:
        lines.append("\nWidgets (from view/widget.xml):")
        lines.extend(f"- {widget_id} -> {class_name}" for widget_id, class_name in facts.widgets)

    if facts.menu_items:
        lines.append("\nAdmin menu items (from etc/adminhtml/menu.xml):")
        lines.extend(
            f"- {menu_item_id}" + (f" ({title})" if title else "") for menu_item_id, title in facts.menu_items
        )

    if facts.cache_types:
        lines.append("\nCache types (from etc/cache.xml):")
        lines.extend(
            f"- {cache_type_id}" + (f" -> {instance}" if instance else "")
            for cache_type_id, instance in facts.cache_types
        )

    if facts.php_classes:
        lines.append("\nPHP classes discovered in this module:")
        for c in facts.php_classes:
            role = []
            if c.is_plugin:
                role.append("plugin")
            if c.is_observer:
                role.append("observer")
            role_str = f" [{', '.join(role)}]" if role else ""
            lines.append(f"- {c.fqcn} ({c.kind}){role_str} — {c.file_path}")

    if facts.file_analyses:
        lines.append("\nPer-file summaries already generated for this module:")
        for fa in facts.file_analyses:
            lines.append(f"- {fa.relative_path}: {fa.file_summary}")
            if fa.notable_behavior:
                lines.append(f"  notable: {fa.notable_behavior}")

    lines.append(
        "\nUsing ONLY the facts above (never invent events, plugins, dependencies, GraphQL fields, ACL resources, "
        "indexers, mviews, routes, widgets, menu items, cache types, or classes not listed), "
        "produce a structured module description:\n"
        "- summary: one or two sentences.\n"
        "- description: a fuller technical/business description.\n"
        "- features: a list of distinct features, each with a `source` that MUST be exactly one of the "
        "file paths or class FQCNs listed above (never a path/class not shown).\n"
        "- integrations: external systems this module integrates with (e.g. payment gateways, ERPs, "
        "marketing platforms), if any are evident from the facts above; omit source if not file-specific.\n"
        f"- tags: zero or more tags chosen EXACTLY from this fixed vocabulary: {sorted(ALLOWED_TAGS)}. "
        "Do not invent new tags.\n"
        "- config_options: one entry per admin config field listed above under \"Admin config fields\" "
        "(path and label exactly as given there); empty if none were listed.\n"
        "- risks: anything that looks risky or fragile, with a severity.\n"
        "- confidence: your confidence (0-1) in this description given the available facts.\n"
        "- pm_text: a business-language paragraph with no class names, for a product manager.\n"
        "- dev_text: a technical paragraph with class names, hooks, and config, for a developer.\n"
        "If something is unknown, say so rather than guessing."
    )

    return "\n".join(lines)
