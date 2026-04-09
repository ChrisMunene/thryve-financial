"""
Multi-environment configuration system.

Three environments: development, staging, production.
Settings grouped by concern. Singleton via @lru_cache.
Crashes on startup if required values are missing in staging/prod.
"""

from enum import Enum
from functools import lru_cache
from typing import Any

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class DatabaseConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DATABASE_", extra="ignore")

    url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/pfm"
    pool_size: int = 5
    max_overflow: int = 5
    echo: bool = False


class RedisConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="ignore")

    url: str = "redis://localhost:6380/0"
    cache_ttl: int = 86400  # 24 hours


class AuthConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", extra="ignore")

    supabase_jwt_secret: SecretStr = SecretStr("")
    supabase_url: str = ""
    supabase_jwks_url: str = ""  # Reserved for future JWKS support


class PlaidConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLAID_", extra="ignore")

    client_id: str = ""
    secret: SecretStr = SecretStr("")
    env: str = "sandbox"


class AnthropicConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ANTHROPIC_", extra="ignore")

    api_key: SecretStr = SecretStr("")
    model: str = "claude-haiku-4-5-20251001"
    max_retries: int = 3


class ObservabilityConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OTEL_", extra="ignore")

    exporter: str = "console"  # "console" or "otlp"
    endpoint: str = ""
    log_level: str = "DEBUG"
    posthog_api_key: str = ""
    posthog_host: str = "https://app.posthog.com"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Environment
    environment: Environment = Environment.DEVELOPMENT

    # Nested config groups
    database: DatabaseConfig = DatabaseConfig()
    redis: RedisConfig = RedisConfig()
    auth: AuthConfig = AuthConfig()
    plaid: PlaidConfig = PlaidConfig()
    anthropic: AnthropicConfig = AnthropicConfig()
    observability: ObservabilityConfig = ObservabilityConfig()

    # App-level
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    rate_limit_default: int = 100  # requests per minute per user
    request_timeout: int = 30  # seconds
    request_max_body_size: int = 1_048_576  # 1MB
    shutdown_timeout: int = 15  # seconds

    # Engine
    deterministic_confidence_threshold: float = 0.8
    llm_confidence_threshold: float = 0.8
    idempotency_ttl: int = 86400  # 24 hours

    @model_validator(mode="before")
    @classmethod
    def load_nested_settings(cls, values: Any) -> Any:
        """Hydrate nested config from env/.env before validation.

        Nested BaseSettings defaults are instantiated at import time, so we
        rebuild them here to ensure runtime environment and `.env` values are
        respected.
        """
        if not isinstance(values, dict):
            values = {}

        env_file = cls.model_config.get("env_file")
        env_file_encoding = cls.model_config.get("env_file_encoding")

        nested_configs = {
            "database": DatabaseConfig,
            "redis": RedisConfig,
            "auth": AuthConfig,
            "plaid": PlaidConfig,
            "anthropic": AnthropicConfig,
            "observability": ObservabilityConfig,
        }

        merged = dict(values)
        for field_name, config_cls in nested_configs.items():
            provided = merged.get(field_name, {})
            if not isinstance(provided, dict):
                continue

            merged[field_name] = config_cls(
                _env_file=env_file,
                _env_file_encoding=env_file_encoding,
                **provided,
            )

        return merged

    @model_validator(mode="after")
    def validate_production_requirements(self) -> "Settings":
        """Crash on startup if required values are missing in staging/production."""
        if self.environment in (Environment.STAGING, Environment.PRODUCTION):
            missing = []
            if not self.auth.supabase_jwt_secret.get_secret_value():
                missing.append("AUTH_SUPABASE_JWT_SECRET")
            if not self.anthropic.api_key.get_secret_value():
                missing.append("ANTHROPIC_API_KEY")
            if not self.plaid.client_id:
                missing.append("PLAID_CLIENT_ID")
            if not self.plaid.secret.get_secret_value():
                missing.append("PLAID_SECRET")
            if missing:
                raise ValueError(
                    f"Missing required config for {self.environment.value}: {', '.join(missing)}"
                )

        if self.observability.exporter == "otlp" and not self.observability.endpoint:
            raise ValueError("OTEL_ENDPOINT is required when OTEL_EXPORTER=otlp")

        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be greater than 0")
        if self.request_max_body_size <= 0:
            raise ValueError("request_max_body_size must be greater than 0")
        if self.shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be greater than 0")
        return self

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, v: str) -> str:
        if isinstance(v, str):
            return v.lower()
        return v

    @field_validator("debug", mode="before")
    @classmethod
    def normalize_debug(cls, v: Any) -> Any:
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in {"release", "prod", "production", "off"}:
                return False
            if normalized in {"debug", "dev", "development", "on"}:
                return True
        return v

    @property
    def is_development(self) -> bool:
        return self.environment == Environment.DEVELOPMENT

    @property
    def is_production(self) -> bool:
        return self.environment == Environment.PRODUCTION


@lru_cache
def get_settings() -> Settings:
    """Singleton settings resolved once at startup."""
    return Settings()
