from datetime import datetime
from decimal import Decimal

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
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
    event_observers: Mapped[list["EventObserver"]] = relationship(
        back_populates="module", cascade="all, delete-orphan"
    )
    graphql_fields: Mapped[list["GraphQlField"]] = relationship(
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
        CheckConstraint(
            "check_type IN ('composer_completeness','deprecated_annotation','hardcoded_secret',"
            "'security_advisory','abandoned_dependency','outdated_dependency',"
            "'phpstan_error','phpmd_issue','phpcs_violation','php_compat_issue',"
            "'magento_php_incompatible','magento_version_blocker')",
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
        CheckConstraint(
            "kind IN ('file_summary','module_synthesis','embedding','chat')", name="ck_analysis_cache_kind"
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
