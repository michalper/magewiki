from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config import settings
from app.db import Base


class Module(Base):
    __tablename__ = "modules"
    __table_args__ = (
        UniqueConstraint("repo_root", "name", name="uq_modules_repo_root_name"),
        CheckConstraint(
            "state IN ('pending','scanning','analyzing','embedding','up_to_date','failed','paused_budget')",
            name="ck_modules_state",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    repo_root: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text)
    setup_version: Mapped[str | None] = mapped_column(Text)
    composer_name: Mapped[str | None] = mapped_column(Text)
    composer_type: Mapped[str | None] = mapped_column(Text)
    license: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    homepage: Mapped[str | None] = mapped_column(Text)
    authors: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    php_extensions: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    # composer.json facts parsed from the start but never surfaced anywhere --
    # deliberately deferred per CLAUDE.md's "lower-value, more niche fields"
    # note next to the homepage/authors/php_extensions decision above, added
    # once actually asked for. scripts: just the defined script *names* (not
    # their command content -- not useful for a read-only catalog without
    # execution, and composer.json is third-party, untrusted input). autoload
    # map of the real PSR-4 namespace roots. allow_plugins: package name ->
    # whether composer.json explicitly allows it to run as a plugin.
    composer_scripts: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    composer_autoload_psr4: Mapped[dict | None] = mapped_column(JSONB)
    composer_allow_plugins: Mapped[dict | None] = mapped_column(JSONB)
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    last_scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scan_warnings: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")

    # Phase 2: hash/diff + state machine
    state: Mapped[str] = mapped_column(Text, server_default="pending")
    analyzed_hash: Mapped[str | None] = mapped_column(Text)
    current_hash: Mapped[str] = mapped_column(Text, server_default="")
    retry_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    pending_file_count: Mapped[int] = mapped_column(Integer, server_default="0")

    # Phase 9: parser-only quality checks
    has_readme: Mapped[bool] = mapped_column(Boolean, server_default="false")
    has_tests: Mapped[bool] = mapped_column(Boolean, server_default="false")

    # Real PHPUnit execution (see check_php_unit_tests) -- None/None/None
    # means "never executed" (no real Test/Unit + own vendor/bin/phpunit),
    # not "0 tests, 0% coverage".
    phpunit_tests_run: Mapped[int | None] = mapped_column(Integer)
    phpunit_tests_failed: Mapped[int | None] = mapped_column(Integer)
    phpunit_coverage_percent: Mapped[float | None] = mapped_column(Float)

    dependencies: Mapped[list["ModuleDependency"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    php_classes: Mapped[list["PhpClass"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    di_preferences: Mapped[list["DiPreference"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    di_plugins: Mapped[list["DiPlugin"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    di_virtual_types: Mapped[list["DiVirtualType"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    event_observers: Mapped[list["EventObserver"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    graphql_fields: Mapped[list["GraphQlField"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    cron_jobs: Mapped[list["CronJob"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    webapi_routes: Mapped[list["WebapiRoute"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    config_fields: Mapped[list["ConfigField"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    db_tables: Mapped[list["DbTable"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    db_columns: Mapped[list["DbColumn"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    acl_resources: Mapped[list["AclResource"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    queue_bindings: Mapped[list["QueueBinding"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    history_snapshots: Mapped[list["ModuleHistorySnapshot"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    file_hashes: Mapped[list["FileHash"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    chunks: Mapped[list["Chunk"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    quality_findings: Mapped[list["ModuleQualityFinding"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    composer_requirements: Mapped[list["ComposerPackageRequirement"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )


class ModuleDependency(Base):
    __tablename__ = "module_dependencies"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    depends_on_name: Mapped[str] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="dependencies")


class PhpClass(Base):
    __tablename__ = "php_classes"
    __table_args__ = (UniqueConstraint("module_id", "fqcn", name="uq_php_classes_module_fqcn"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    fqcn: Mapped[str] = mapped_column(Text, index=True)
    namespace: Mapped[str | None] = mapped_column(Text)
    class_name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    extends: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    implements: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    file_path: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    is_plugin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_observer: Mapped[bool] = mapped_column(Boolean, default=False)
    role_signals: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")

    module: Mapped[Module] = relationship(back_populates="php_classes")
    methods: Mapped[list["PhpClassMethod"]] = relationship(
        back_populates="php_class", cascade="all, delete-orphan"
    )


class PhpClassMethod(Base):
    __tablename__ = "php_class_methods"

    id: Mapped[int] = mapped_column(primary_key=True)
    class_id: Mapped[int] = mapped_column(ForeignKey("php_classes.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)

    php_class: Mapped[PhpClass] = relationship(back_populates="methods")


class DiPreference(Base):
    __tablename__ = "di_preferences"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    for_type: Mapped[str] = mapped_column(Text)
    preference_type: Mapped[str] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="di_preferences")


class DiPlugin(Base):
    __tablename__ = "di_plugins"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    intercepted_type: Mapped[str] = mapped_column(Text, index=True)
    plugin_name: Mapped[str] = mapped_column(Text)
    plugin_class: Mapped[str] = mapped_column(Text, index=True)
    sort_order: Mapped[int | None] = mapped_column(Integer)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)

    module: Mapped[Module] = relationship(back_populates="di_plugins")


class DiVirtualType(Base):
    __tablename__ = "di_virtual_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text, index=True)
    virtual_type: Mapped[str] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="di_virtual_types")


class EventObserver(Base):
    __tablename__ = "event_observers"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    event_name: Mapped[str] = mapped_column(Text, index=True)
    observer_name: Mapped[str] = mapped_column(Text)
    observer_class: Mapped[str] = mapped_column(Text, index=True)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)

    module: Mapped[Module] = relationship(back_populates="event_observers")


class GraphQlField(Base):
    __tablename__ = "graphql_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    operation_type: Mapped[str] = mapped_column(Text)
    type_name: Mapped[str] = mapped_column(Text, index=True)
    field_name: Mapped[str] = mapped_column(Text)
    resolver_class: Mapped[str | None] = mapped_column(Text, index=True)

    module: Mapped[Module] = relationship(back_populates="graphql_fields")


class CronJob(Base):
    __tablename__ = "cron_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    job_name: Mapped[str] = mapped_column(Text, index=True)
    instance_class: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text)
    schedule: Mapped[str | None] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="cron_jobs")


class WebapiRoute(Base):
    __tablename__ = "webapi_routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text, index=True)
    http_method: Mapped[str] = mapped_column(Text)
    service_class: Mapped[str] = mapped_column(Text)
    service_method: Mapped[str] = mapped_column(Text)
    acl_resource: Mapped[str | None] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="webapi_routes")


class ConfigField(Base):
    __tablename__ = "config_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    section_id: Mapped[str] = mapped_column(Text, index=True)
    group_id: Mapped[str] = mapped_column(Text)
    field_id: Mapped[str] = mapped_column(Text)
    label: Mapped[str | None] = mapped_column(Text)
    field_type: Mapped[str | None] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="config_fields")


class DbTable(Base):
    __tablename__ = "db_tables"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    table_name: Mapped[str] = mapped_column(Text, index=True)
    comment: Mapped[str | None] = mapped_column(Text)
    column_count: Mapped[int] = mapped_column(Integer, default=0)

    module: Mapped[Module] = relationship(back_populates="db_tables")


class AclResource(Base):
    __tablename__ = "acl_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    resource_id: Mapped[str] = mapped_column(Text, index=True)
    title: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[str | None] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="acl_resources")


class DbColumn(Base):
    __tablename__ = "db_columns"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    table_name: Mapped[str] = mapped_column(Text, index=True)
    column_name: Mapped[str] = mapped_column(Text)
    xsi_type: Mapped[str] = mapped_column(Text)
    nullable: Mapped[bool | None] = mapped_column(Boolean)

    module: Mapped[Module] = relationship(back_populates="db_columns")


class QueueBinding(Base):
    __tablename__ = "queue_bindings"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    topic: Mapped[str] = mapped_column(Text, index=True)
    destination: Mapped[str | None] = mapped_column(Text)
    consumer_name: Mapped[str | None] = mapped_column(Text)
    handler_class: Mapped[str | None] = mapped_column(Text)
    handler_method: Mapped[str | None] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="queue_bindings")


class FileHash(Base):
    __tablename__ = "file_hashes"
    __table_args__ = (UniqueConstraint("module_id", "relative_path", name="uq_file_hashes_module_relpath"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)

    module: Mapped[Module] = relationship(back_populates="file_hashes")


class ModuleQualityFinding(Base):
    """One parser-only quality-check finding (Phase 9). Facts come from
    parsers, never AI — see CLAUDE.md anti-hallucination rules. Full-replace
    per scan, same as PhpClass/DiPlugin/EventObserver.
    """

    __tablename__ = "module_quality_findings"
    __table_args__ = (
        # Kept in sync with the cumulative effect of every
        # ck_module_quality_findings_check_type migration (0009 through the
        # latest) -- this text is never applied directly (the real schema
        # always comes from `alembic upgrade head`, confirmed by
        # tests/conftest.py), but it drifted out of sync with the real
        # constraint for a long stretch before this comment was added, so
        # keep it current rather than letting it mislead a future reader.
        CheckConstraint(
            "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
            "'security_advisory','abandoned_dependency','outdated_dependency',"
            "'phpstan_error','phpmd_issue','phpcs_violation','php_compat_issue',"
            "'magento_php_incompatible','magento_version_blocker','plugin_conflict','phpmetrics_issue',"
            "'composer_conflict','webapi_route_conflict','db_schema_conflict','circular_dependency',"
            "'license_risk','phpunit_failure','preference_conflict','cron_job_conflict',"
            "'graphql_field_conflict','acl_resource_conflict','missing_acl')",
            name="ck_module_quality_findings_check_type",
        ),
        CheckConstraint(
            "severity IN ('blocking','warning','info')", name="ck_module_quality_findings_severity"
        ),
        Index("ix_module_quality_findings_module_id", "module_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    check_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str | None] = mapped_column(Text)
    line: Mapped[int | None] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)

    module: Mapped[Module] = relationship(back_populates="quality_findings")


class ComposerPackageRequirement(Base):
    """One third-party `require`/`require-dev` entry from a module's
    composer.json (Phase 10). Separate from `ModuleDependency`, which is
    Magento's own `module.xml` `<sequence>` concept, not a Composer package.
    Full-replace per scan, same pattern as `ModuleQualityFinding`.
    """

    __tablename__ = "composer_package_requirements"
    __table_args__ = (Index("ix_composer_package_requirements_module_id", "module_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    package_name: Mapped[str] = mapped_column(Text)
    constraint: Mapped[str] = mapped_column(Text)
    is_dev: Mapped[bool] = mapped_column(Boolean, default=False)

    module: Mapped[Module] = relationship(back_populates="composer_requirements")


class PackagistCache(Base):
    """A single shared TTL cache for every Packagist-backed check (security
    advisories, abandoned/outdated dependencies) — one table, not one per
    scanner. TTL is enforced at read time by the caller comparing
    `fetched_at` to now, not stored here. Mirrors v1's own `packagist_cache`
    table, confirmed to be shared the same way (see docs/v1-port-roadmap.md).
    """

    __tablename__ = "packagist_cache"

    cache_key: Mapped[str] = mapped_column(Text, primary_key=True)
    response_json: Mapped[dict] = mapped_column(JSONB)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"
    __table_args__ = (
        UniqueConstraint("content_hash", "model", "prompt_version", "kind", name="uq_analysis_cache_key"),
        # Kept in sync with the cumulative effect of every ck_analysis_cache_kind
        # migration (0004 through the latest) for the same reason as
        # ModuleQualityFinding's own CheckConstraint comment above -- this text
        # is never applied directly (alembic upgrade head is the real schema
        # source), but had already drifted out of sync once (missing 'rerank')
        # before this comment was added.
        CheckConstraint(
            "kind IN ('file_summary','module_synthesis','embedding','chat','rerank','query_rewrite')",
            name="ck_analysis_cache_kind",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    content_hash: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    response: Mapped[dict] = mapped_column(JSONB)
    tokens_in: Mapped[int] = mapped_column(Integer)
    tokens_out: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FileAnalysis(Base):
    __tablename__ = "file_analyses"
    __table_args__ = (UniqueConstraint("module_id", "relative_path", name="uq_file_analyses_module_relpath"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    cache_id: Mapped[int] = mapped_column(ForeignKey("analysis_cache.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModuleDocument(Base):
    """AI-synthesized module documentation (jsonb). See app.analyzer.schemas.ModuleDoc for the shape."""

    __tablename__ = "module_docs"

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"), unique=True)
    content_hash: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    cache_id: Mapped[int] = mapped_column(ForeignKey("analysis_cache.id"))
    doc: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Chunk(Base):
    """A unit of the hybrid-search index: one module summary, one file summary, or
    one plugin/observer method's extracted source. See CLAUDE.md "Multi-level index".
    """

    __tablename__ = "chunks"
    __table_args__ = (
        CheckConstraint("chunk_type IN ('module','file','method')", name="ck_chunks_chunk_type"),
        Index("ix_chunks_module_id", "module_id"),
        Index("ix_chunks_module_chunk_type", "module_id", "chunk_type"),
        Index("ix_chunks_relative_path", "relative_path"),
        Index(
            "ix_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_tsv_gin", "tsv", postgresql_using="gin"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    chunk_type: Mapped[str] = mapped_column(Text)
    relative_path: Mapped[str | None] = mapped_column(Text)
    method_id: Mapped[int | None] = mapped_column(ForeignKey("php_class_methods.id", ondelete="CASCADE"))
    content_hash: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    # Must match EMBEDDING_DIMENSIONS / the migrations (see
    # alembic/versions/0013_configurable_embedding_dimension.py) — this is the
    # Python-side type SQLAlchemy uses to build bound-parameter casts, independent of
    # the actual DB column type, so it has to track the same setting or inserts fail
    # with "expected N dimensions" regardless of what the real column accepts.
    embedding: Mapped[list[float]] = mapped_column(Vector(settings.embedding_dimensions))
    tsv: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', text)", persisted=True)
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    module: Mapped[Module] = relationship(back_populates="chunks")


class RuntimeLlmConfig(Base):
    """BYOK override for the LLM/embedding model+key, settable via the /settings
    UI without editing .env or restarting containers. Single-row table (id=1) —
    absence of a row, or a null field, means "use the .env default" (see
    app/runtime_config.py). See CLAUDE.md "LLM" row: BYOK.
    """

    __tablename__ = "runtime_llm_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    llm_model: Mapped[str | None] = mapped_column(Text)
    llm_api_key: Mapped[str | None] = mapped_column(Text)
    llm_api_base: Mapped[str | None] = mapped_column(Text)
    embedding_model: Mapped[str | None] = mapped_column(Text)
    embedding_api_key: Mapped[str | None] = mapped_column(Text)
    embedding_api_base: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModuleHistorySnapshot(Base):
    """Phase 16: one row per module per *change* (not per scan — see
    app/scanner/history.py's dedup logic) so a module/repo page can answer
    "what got better or worse since last scan," not just "what's true right
    now." Written after Phase C's cross-module conflict detection, since
    that's when a module's finding_counts are actually complete for this
    scan. finding_counts mirrors the same dict[check_type, count] shape
    ModuleSummary/RepoSummary already expose, not a full copy of the
    findings themselves.
    """

    __tablename__ = "module_history_snapshots"
    __table_args__ = (Index("ix_module_history_snapshots_module_id", "module_id", "scanned_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    current_hash: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool | None] = mapped_column(Boolean)
    finding_counts: Mapped[dict] = mapped_column(JSONB)

    module: Mapped[Module] = relationship(back_populates="history_snapshots")
