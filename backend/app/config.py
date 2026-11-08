from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://magewiki:changeme@db:5432/magewiki"
    cors_origins: str = "http://localhost:3000"
    redis_url: str = "redis://redis:6379/0"
    llm_model: str = "anthropic/claude-haiku-5-5"
    # Module-level synthesis asks for a much larger, stricter structured JSON object
    # than per-file summaries — empirically LLM_MODEL's cheap default (haiku) omits
    # required ModuleDoc fields even after corrective retries, at real fleet scale
    # (~340/760 modules in one real store). Empty means "same as LLM_MODEL" (no
    # behavior change); set to a stronger model to use it for synthesis only, while
    # analyze_file's per-file summaries stay on the cheap default. Must use the same
    # provider as LLM_MODEL — it reuses LLM_MODEL's api_key/api_base unchanged.
    synthesis_model: str = ""
    llm_monthly_budget_usd: float = 20.0
    anthropic_api_key: str = ""
    embedding_model: str = "openai/text-embedding-3-small"
    # The chunks.embedding pgvector column's dimension is fixed at migration time
    # (see alembic/versions/0013_configurable_embedding_dimension.py) — must match
    # whatever EMBEDDING_MODEL actually outputs. 1536 = OpenAI text-embedding-3-small/
    # -ada-002; 1024 = bge-m3 (Ollama). Changing this requires re-running migrations
    # and a full re-embed (old vectors are in a different, incompatible vector space).
    embedding_dimensions: int = 1536
    openai_api_key: str = ""
    webhook_hmac_secret: str = ""
    ollama_base_url: str = ""
    php_analyzer_url: str = "http://php-analyzer:8080"
    # General-purpose scan roots (see CLAUDE.md "Scan, cron, and cost control" decision
    # note) — distinct from MAGEWIKI_ORDO_FIXTURE_PATH/MAGEWIKI_MAGENTO_FIXTURE_PATH,
    # which name one specific repo each for tests/eval. Numbered, not a comma list,
    # because docker-compose.yml can't loop over a variable-length volumes section.
    magewiki_scan_root_1: str = ""
    magewiki_scan_root_2: str = ""
    magewiki_scan_root_3: str = ""
    # What counts as a "risky" (strong-copyleft) license for
    # app/scanner/license_check.py's license_risk finding is a legal/business
    # judgment call that varies by operator -- GPL/AGPL/SSPL is just the
    # project's own default (see that module's own comment for why). Empty
    # disables the check entirely rather than falling back to the default --
    # an operator who's already reviewed their fleet's licenses and decided
    # none of this matters to them should be able to turn it off outright.
    license_risk_prefixes: str = "GPL-,AGPL-,SSPL-"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def license_risk_prefix_tuple(self) -> tuple[str, ...]:
        return tuple(p.strip().upper() for p in self.license_risk_prefixes.split(",") if p.strip())

    @property
    def scan_roots(self) -> list[str]:
        return [
            root
            for root in (self.magewiki_scan_root_1, self.magewiki_scan_root_2, self.magewiki_scan_root_3)
            if root.strip()
        ]

    def is_within_scan_roots(self, path: str) -> bool:
        """The actual access-control check for POST /scan[/stream] and
        POST /webhooks/scan — scan_roots elsewhere is just UI/error-message text.
        Fails closed: if no scan roots are configured, nothing is scannable, rather
        than falling back to "anything the container can see is fair game."
        """
        try:
            resolved = Path(path).resolve()
        except OSError:
            return False
        for root in self.scan_roots:
            resolved_root = Path(root).resolve()
            if resolved == resolved_root or resolved.is_relative_to(resolved_root):
                return True
        return False


settings = Settings()
