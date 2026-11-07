from app.analyzer.facts import ModuleFacts
from app.analyzer.tags import ALLOWED_TAGS

FILE_SUMMARY_PROMPT_VERSION = "file_summary_v1"
MODULE_SYNTHESIS_PROMPT_VERSION = "module_synthesis_v1"
EMBEDDING_PROMPT_VERSION = "embedding_v1"
CHAT_PROMPT_VERSION = "chat_v1"

MAX_FILE_CONTENT_CHARS = 50_000


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
        "\nUsing ONLY the facts above (never invent events, plugins, dependencies, GraphQL fields, or classes "
        "not listed), "
        "produce a structured module description:\n"
        "- summary: one or two sentences.\n"
        "- description: a fuller technical/business description.\n"
        "- features: a list of distinct features, each with a `source` that MUST be exactly one of the "
        "file paths or class FQCNs listed above (never a path/class not shown).\n"
        "- integrations: external systems this module integrates with (e.g. payment gateways, ERPs, "
        "marketing platforms), if any are evident from the facts above; omit source if not file-specific.\n"
        f"- tags: zero or more tags chosen EXACTLY from this fixed vocabulary: {sorted(ALLOWED_TAGS)}. "
        "Do not invent new tags.\n"
        "- config_options: any system.xml-style configuration keys evident from the facts above (often empty).\n"
        "- risks: anything that looks risky or fragile, with a severity.\n"
        "- confidence: your confidence (0-1) in this description given the available facts.\n"
        "- pm_text: a business-language paragraph with no class names, for a product manager.\n"
        "- dev_text: a technical paragraph with class names, hooks, and config, for a developer.\n"
        "If something is unknown, say so rather than guessing."
    )

    return "\n".join(lines)
