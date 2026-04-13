"""
Multi-environment configuration system.

Three environments: development, staging, production.
Settings grouped by concern. Singleton via @lru_cache.
Crashes on startup if required values are missing in staging/prod.
"""

from enum import StrEnum
from functools import lru_cache
from typing import Any

from pydantic import AliasChoices, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
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


class TelemetryExporter(StrEnum):
    NONE = "none"
    CONSOLE = "console"
    OTLP = "otlp"


class ObservabilityConfig(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True)

    traces_exporter: TelemetryExporter = Field(
        default=TelemetryExporter.CONSOLE,
        validation_alias=AliasChoices("OTEL_TRACES_EXPORTER", "traces_exporter"),
    )
    metrics_exporter: TelemetryExporter = Field(
        default=TelemetryExporter.CONSOLE,
        validation_alias=AliasChoices("OTEL_METRICS_EXPORTER", "metrics_exporter"),
    )
    logs_exporter: TelemetryExporter = Field(
        default=TelemetryExporter.NONE,
        validation_alias=AliasChoices("OTEL_LOGS_EXPORTER", "logs_exporter"),
    )
    otlp_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_ENDPOINT", "otlp_endpoint"),
    )
    otlp_traces_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
            "otlp_traces_endpoint",
        ),
    )
    otlp_metrics_endpoint: str = Field(
        default="",
        validation_alias=AliasChoices(
            "OTEL_EXPORTER_OTLP_METRICS_ENDPOINT",
            "otlp_metrics_endpoint",
        ),
    )
    otlp_headers: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_HEADERS", "otlp_headers"),
    )
    otlp_insecure: bool = Field(
        default=False,
        validation_alias=AliasChoices("OTEL_EXPORTER_OTLP_INSECURE", "otlp_insecure"),
    )
    sampling_ratio: float = Field(
        default=1.0,
        validation_alias=AliasChoices("OTEL_TRACES_SAMPLER_ARG", "sampling_ratio"),
    )
    bsp_schedule_delay_millis: int = Field(
        default=5000,
        validation_alias=AliasChoices("OTEL_BSP_SCHEDULE_DELAY", "bsp_schedule_delay_millis"),
    )
    bsp_export_timeout_millis: int = Field(
        default=30000,
        validation_alias=AliasChoices(
            "OTEL_BSP_EXPORT_TIMEOUT",
            "bsp_export_timeout_millis",
        ),
    )
    bsp_max_queue_size: int = Field(
        default=2048,
        validation_alias=AliasChoices("OTEL_BSP_MAX_QUEUE_SIZE", "bsp_max_queue_size"),
    )
    bsp_max_export_batch_size: int = Field(
        default=512,
        validation_alias=AliasChoices(
            "OTEL_BSP_MAX_EXPORT_BATCH_SIZE",
            "bsp_max_export_batch_size",
        ),
    )
    metric_export_interval_millis: int = Field(
        default=30000,
        validation_alias=AliasChoices(
            "OTEL_METRIC_EXPORT_INTERVAL",
            "metric_export_interval_millis",
        ),
    )
    excluded_urls: list[str] = Field(
        default_factory=lambda: [
            "/api/v1/health",
            "/api/v1/health/ready",
            "/docs",
            "/openapi.json",
        ],
        validation_alias=AliasChoices(
            "OTEL_PYTHON_FASTAPI_EXCLUDED_URLS",
            "excluded_urls",
        ),
    )
    resource_attributes: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("OTEL_RESOURCE_ATTRIBUTES", "resource_attributes"),
    )
    service_namespace: str = Field(
        default="pfm",
        validation_alias=AliasChoices("OTEL_SERVICE_NAMESPACE", "service_namespace"),
    )
    api_service_name: str = Field(
        default="pfm-api",
        validation_alias=AliasChoices("OTEL_SERVICE_NAME_API", "api_service_name"),
    )
    worker_service_name: str = Field(
        default="pfm-worker",
        validation_alias=AliasChoices("OTEL_SERVICE_NAME_WORKER", "worker_service_name"),
    )
    beat_service_name: str = Field(
        default="pfm-beat",
        validation_alias=AliasChoices("OTEL_SERVICE_NAME_BEAT", "beat_service_name"),
    )
    log_level: str = Field(
        default="DEBUG",
        validation_alias=AliasChoices("OTEL_LOG_LEVEL", "log_level"),
    )
    posthog_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("POSTHOG_API_KEY", "posthog_api_key"),
    )
    posthog_host: str = Field(
        default="https://app.posthog.com",
        validation_alias=AliasChoices("POSTHOG_HOST", "posthog_host"),
    )

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_fields(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        legacy_keys = {"exporter", "endpoint"}
        found = sorted(key for key in legacy_keys if key in values)
        if found:
            raise ValueError(
                "Legacy observability config keys are no longer supported: "
                f"{', '.join(found)}"
            )
        return values

    @field_validator("otlp_headers", "resource_attributes", mode="before")
    @classmethod
    def parse_key_value_strings(cls, value: Any) -> Any:
        if isinstance(value, str):
            parsed: dict[str, str] = {}
            for item in value.split(","):
                if not item.strip():
                    continue
                key, separator, item_value = item.partition("=")
                if not separator:
                    raise ValueError(f"Invalid key=value entry: {item}")
                parsed[key.strip()] = item_value.strip()
            return parsed
        return value

    @field_validator("excluded_urls", mode="before")
    @classmethod
    def parse_excluded_urls(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def normalize_log_level(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().upper()
        return value

    def signal_endpoint(self, signal: str) -> str:
        if signal == "traces":
            return self.otlp_traces_endpoint or self.otlp_endpoint
        if signal == "metrics":
            return self.otlp_metrics_endpoint or self.otlp_endpoint
        raise ValueError(f"Unsupported telemetry signal: {signal}")

    def service_name_for_role(self, process_role: str) -> str:
        if process_role == "api":
            return self.api_service_name
        if process_role == "worker":
            return self.worker_service_name
        if process_role == "beat":
            return self.beat_service_name
        raise ValueError(f"Unsupported telemetry process role: {process_role}")


class RateLimitConfig(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RATE_LIMIT_", extra="ignore")

    default_limit: int = 100
    default_window_seconds: int = 60

    write_limit: int = 30
    write_window_seconds: int = 60

    expensive_limit: int = 10
    expensive_window_seconds: int = 60

    auth_limit: int = 5
    auth_window_seconds: int = 60


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
    rate_limit: RateLimitConfig = RateLimitConfig()

    # App-level
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:8080"]
    public_base_url: str = ""
    request_timeout: int = 30  # seconds
    request_max_body_size: int = 1_048_576  # 1MB
    shutdown_timeout: int = 15  # seconds

    # Engine
    deterministic_confidence_threshold: float = 0.8
    llm_confidence_threshold: float = 0.8
    idempotency_ttl: int = 86400  # 24 hours
    idempotency_retention_seconds: int = 604800  # 7 days
    idempotency_processing_lease_seconds: int = 300  # 5 minutes
    idempotency_cache_ttl_seconds: int = 86400  # 24 hours
    idempotency_cleanup_batch_size: int = 1000

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
            "rate_limit": RateLimitConfig,
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

        if self.observability.logs_exporter != TelemetryExporter.NONE:
            raise ValueError("OTEL_LOGS_EXPORTER must be 'none' in this refactor")

        if self.environment in (Environment.STAGING, Environment.PRODUCTION):
            if self.observability.traces_exporter != TelemetryExporter.OTLP:
                raise ValueError(
                    "OTEL_TRACES_EXPORTER must be 'otlp' in staging/production"
                )
            if self.observability.metrics_exporter != TelemetryExporter.OTLP:
                raise ValueError(
                    "OTEL_METRICS_EXPORTER must be 'otlp' in staging/production"
                )

        for signal, exporter in (
            ("traces", self.observability.traces_exporter),
            ("metrics", self.observability.metrics_exporter),
        ):
            if (
                exporter == TelemetryExporter.OTLP
                and not self.observability.signal_endpoint(signal)
            ):
                raise ValueError(
                    "OTLP endpoints are required for enabled exporters. Missing endpoint "
                    f"for signal: {signal}"
                )

        if not 0 <= self.observability.sampling_ratio <= 1:
            raise ValueError("sampling_ratio must be between 0 and 1")

        if self.request_timeout <= 0:
            raise ValueError("request_timeout must be greater than 0")
        if self.request_max_body_size <= 0:
            raise ValueError("request_max_body_size must be greater than 0")
        if self.shutdown_timeout <= 0:
            raise ValueError("shutdown_timeout must be greater than 0")
        for name in (
            "bsp_schedule_delay_millis",
            "bsp_export_timeout_millis",
            "bsp_max_queue_size",
            "bsp_max_export_batch_size",
            "metric_export_interval_millis",
        ):
            if getattr(self.observability, name) <= 0:
                raise ValueError(f"observability.{name} must be greater than 0")
        for name, value in self.rate_limit.model_dump().items():
            if value <= 0:
                raise ValueError(f"rate_limit.{name} must be greater than 0")
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
