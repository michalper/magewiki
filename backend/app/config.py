from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://magewiki:changeme@db:5432/magewiki"
    cors_origins: str = "http://localhost:3000"
    redis_url: str = "redis://redis:6379/0"
    llm_model: str = "anthropic/claude-haiku-5-5"
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

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def scan_roots(self) -> list[str]:
        return [
            root
            for root in (self.magewiki_scan_root_1, self.magewiki_scan_root_2, self.magewiki_scan_root_3)
            if root.strip()
        ]


settings = Settings()
