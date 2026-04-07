from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pfm"

    # Redis
    redis_url: str = "redis://localhost:6380/0"

    # LLM
    anthropic_api_key: str = ""

    # Auth
    supabase_jwt_secret: str = ""

    # Plaid
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"

    # Engine settings
    deterministic_confidence_threshold: float = 0.8
    llm_confidence_threshold: float = 0.8
    redis_cache_ttl_seconds: int = 86400  # 24 hours

    # App
    debug: bool = False


settings = Settings()
