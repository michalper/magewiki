from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiscoveredModule:
    """A module root found during discovery, before any file is parsed."""

    root: Path  # absolute filesystem path to the module's own root
    relative_path: Path  # relative to the repo_root that was scanned
    source_type: str  # "app_code" | "vendor" | "standalone"


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
class DiXmlResult:
    preferences: list[DiPreferenceEntry] = field(default_factory=list)
    plugins: list[DiPluginEntry] = field(default_factory=list)


@dataclass
class EventObserverEntry:
    event_name: str
    observer_name: str
    observer_class: str
    disabled: bool


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
