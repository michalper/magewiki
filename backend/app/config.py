from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://magewiki:changeme@db:5432/magewiki"
    cors_origins: str = "http://localhost:3000"
    redis_url: str = "redis://redis:6379/0"
    llm_model: str = "anthropic/claude-haiku-5-5"
    llm_monthly_budget_usd: float = 20.0
    anthropic_api_key: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
