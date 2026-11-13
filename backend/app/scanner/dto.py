from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiscoveredModule:
    """A module root found during discovery, before any file is parsed."""

    root: Path  # absolute filesystem path to the module's own root
    relative_path: Path  # relative to the repo_root that was scanned
    source_type: str  # "app_code" | "vendor" | "standalone" | "composer_path"


@dataclass
class ModuleXmlResult:
    name: str
    setup_version: str | None
    sequence: list[str] = field(default_factory=list)


@dataclass
class ComposerResult:
    name: str | None
    type: str | None
    license: list[str] | None
    description: str | None = None
    # The package's own declared release version, when composer.json has one — the
    # actively-maintained "what version is this" answer for most real projects,
    # unlike module.xml's setup_version (see hashing/orchestrator's version-source
    # note: setup_version is an internal Magento upgrade-script trigger, commonly
    # left stale at its initial value for the module's whole lifetime once
    # declarative schema removes the need to ever bump it again).
    version: str | None = None
    has_php_requirement: bool = False
    php_constraint: str | None = None
    has_magento_dependency: bool = False
    has_autoload_psr4: bool = False
    has_autoload_files: bool = False
    has_phpunit_dev_dependency: bool = False
    # package name -> raw Composer version constraint string. Phase 10:
    # third-party package requirements, for the CVE and abandoned/outdated
    # dependency checks. Excludes "php" and "ext-*"/"lib-*" platform entries.
    requirements: dict[str, str] = field(default_factory=dict)
    dev_requirements: dict[str, str] = field(default_factory=dict)
    # Already-parsed facts that were never actually surfaced anywhere, parser
    # or API — flagged by a user looking at Ordo_Automation's own real
    # composer.json and asking why homepage/authors/required PHP extensions
    # weren't shown anywhere at all (license had the exact same problem:
    # parsed and stored on Module, but never exposed via the API either).
    homepage: str | None = None
    authors: list[str] = field(default_factory=list)  # "Name <email>" or just "Name"
    php_extensions: list[str] = field(default_factory=list)  # e.g. "ext-openssl", "ext-curl"
    # Deliberately deferred alongside homepage/authors/php_extensions above,
    # then added once actually asked for. scripts: defined script *names*
    # only (not command content -- composer.json is untrusted third-party
    # input, and the content isn't useful for a read-only catalog anyway).
    scripts: list[str] = field(default_factory=list)
    autoload_psr4: dict[str, str] = field(default_factory=dict)  # namespace -> path
    allow_plugins: dict[str, bool] = field(default_factory=dict)  # package name -> allowed


@dataclass
class QualityFinding:
    check_type: str
    # "composer_completeness" | "deprecated_annotation" | "hardcoded_secret"
    # | "security_advisory" | "abandoned_dependency" | "outdated_dependency"
    severity: str  # "blocking" | "warning" | "info"
    file_path: str | None
    line: int | None
    message: str


@dataclass
class DiPreferenceEntry:
    for_type: str
    preference_type: str


@dataclass
class DiPluginEntry:
    intercepted_type: str
    plugin_name: str
    plugin_class: str
    sort_order: int | None
    disabled: bool


@dataclass
class DiVirtualTypeEntry:
    name: str
    virtual_type: str


@dataclass
class DiXmlResult:
    preferences: list[DiPreferenceEntry] = field(default_factory=list)
    plugins: list[DiPluginEntry] = field(default_factory=list)
    virtual_types: list[DiVirtualTypeEntry] = field(default_factory=list)


@dataclass
class EventObserverEntry:
    event_name: str
    observer_name: str
    observer_class: str
    disabled: bool


@dataclass
class CronJobEntry:
    job_name: str
    instance_class: str
    method: str
    schedule: str | None


@dataclass
class WebapiRouteEntry:
    url: str
    http_method: str
    service_class: str
    service_method: str
    acl_resource: str | None


@dataclass
class AclResourceEntry:
    resource_id: str
    title: str | None
    parent_id: str | None


@dataclass
class IndexerEntry:
    indexer_id: str
    view_id: str | None
    class_name: str | None


@dataclass
class MviewEntry:
    view_id: str
    class_name: str | None
    group_name: str | None


@dataclass
class RouteEntry:
    area: str
    route_id: str
    front_name: str


@dataclass
class ConfigFieldEntry:
    section_id: str
    group_id: str
    field_id: str
    label: str | None
    field_type: str | None


@dataclass
class DbTableEntry:
    table_name: str
    comment: str | None
    column_count: int


@dataclass
class DbColumnEntry:
    table_name: str
    column_name: str
    xsi_type: str
    nullable: bool | None


@dataclass
class TestExecutionResult:
    """Outcome of actually running a module's own Test/Unit/ suite via its own
    vendor/bin/phpunit (see check_php_unit_tests) -- distinct from a
    QualityFinding list since pass/fail counts and a coverage percentage
    aren't individually-located findings the way a lint violation is.
    executed=False means there was nothing to run (no real vendor/bin/phpunit
    in this checkout, or no Test/Unit directory), not a failure.
    """

    executed: bool
    tests_run: int = 0
    tests_failed: int = 0
    coverage_percent: float | None = None


@dataclass
class QueueBindingEntry:
    topic: str
    destination: str | None
    consumer_name: str | None
    handler_class: str | None
    handler_method: str | None


@dataclass
class GraphQlFieldEntry:
    operation_type: str  # "Query" | "Mutation" | "Subscription" | "type" (a plain custom type/input definition)
    type_name: str  # the GraphQL type this field belongs to, e.g. "Query" or a custom "CustomOrderOutput"
    field_name: str
    resolver_class: str | None  # from @resolver(class: "...") — Magento's convention for the backing PHP class


@dataclass
class PhpMethodEntry:
    name: str
    start_line: int | None
    end_line: int | None


@dataclass
class PhpClassEntry:
    fqcn: str
    namespace: str | None
    class_name: str
    kind: str  # "class" | "interface" | "trait"
    extends: list[str]
    implements: list[str]
    file_path: str  # relative to the module root
    start_line: int | None
    end_line: int | None
    methods: list[PhpMethodEntry] = field(default_factory=list)
    is_abstract: bool = False
    # Constant name -> literal string value, simple-string-literal constants only
    # (e.g. `const ADMIN_RESOURCE = 'Vendor_Module::foo';`) -- anything else
    # (concatenation, another constant reference, a non-string literal) is
    # unresolvable without evaluating an expression, so it's left out rather
    # than guessed.
    consts: dict[str, str] = field(default_factory=dict)


@dataclass
class PendingAnalysisJob:
    module_id: int
    relative_path: str
    content_hash: str
    module_current_hash: str
