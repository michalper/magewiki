from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

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
    file_hashes: Mapped[list["FileHash"]] = relationship(
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


class FileHash(Base):
    __tablename__ = "file_hashes"
    __table_args__ = (UniqueConstraint("module_id", "relative_path", name="uq_file_hashes_module_relpath"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(ForeignKey("modules.id", ondelete="CASCADE"))
    relative_path: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)

    module: Mapped[Module] = relationship(back_populates="file_hashes")


class AnalysisCache(Base):
    __tablename__ = "analysis_cache"
    __table_args__ = (
        UniqueConstraint("content_hash", "model", "prompt_version", "kind", name="uq_analysis_cache_key"),
        CheckConstraint("kind IN ('file_summary','module_synthesis')", name="ck_analysis_cache_kind"),
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
