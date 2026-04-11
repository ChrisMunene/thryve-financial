"""Tests for multi-environment configuration."""

import pytest

from app.config import Environment, Settings, TelemetryExporter, get_settings


class TestConfigDefaults:
    def test_default_environment_is_development(self):
        settings = Settings(environment="development")
        assert settings.environment == Environment.DEVELOPMENT
        assert settings.is_development
        assert not settings.is_production

    def test_default_database_url(self):
        settings = Settings(environment="development")
        assert "localhost" in settings.database.url
        assert "pfm" in settings.database.url

    def test_default_pool_size_dev(self):
        settings = Settings(environment="development")
        assert settings.database.pool_size == 5
        assert settings.database.max_overflow == 5

    def test_debug_default(self):
        settings = Settings(environment="development")
        assert settings.debug is False


class TestConfigValidation:
    def test_production_requires_auth_secret(self):
        with pytest.raises(ValueError, match="AUTH_SUPABASE_JWT_SECRET"):
            Settings(
                environment="production",
                auth={"supabase_jwt_secret": ""},
                anthropic={"api_key": "sk-test"},
                plaid={"client_id": "test", "secret": "test"},
            )

    def test_production_requires_anthropic_key(self):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            Settings(
                environment="production",
                auth={"supabase_jwt_secret": "secret"},
                anthropic={"api_key": ""},
                plaid={"client_id": "test", "secret": "test"},
            )

    def test_production_requires_plaid_credentials(self):
        with pytest.raises(ValueError, match="PLAID_CLIENT_ID"):
            Settings(
                environment="production",
                auth={"supabase_jwt_secret": "secret"},
                anthropic={"api_key": "sk-test"},
                plaid={"client_id": "", "secret": ""},
            )

    def test_production_requires_otlp_exporters(self):
        with pytest.raises(ValueError, match="OTEL_TRACES_EXPORTER"):
            Settings(
                environment="production",
                auth={"supabase_jwt_secret": "secret"},
                anthropic={"api_key": "sk-test"},
                plaid={"client_id": "test_id", "secret": "test_secret"},
                observability={
                    "traces_exporter": "console",
                    "metrics_exporter": "otlp",
                    "otlp_endpoint": "http://collector:4317",
                },
            )

    def test_otlp_exporter_requires_endpoint(self):
        with pytest.raises(ValueError, match="Missing endpoint for signal: traces"):
            Settings(
                environment="development",
                observability={
                    "traces_exporter": "otlp",
                    "metrics_exporter": "console",
                    "otlp_endpoint": "",
                },
            )

    def test_logs_exporter_must_remain_disabled(self):
        with pytest.raises(ValueError, match="OTEL_LOGS_EXPORTER"):
            Settings(
                environment="development",
                observability={"logs_exporter": "otlp"},
            )

    def test_legacy_observability_keys_are_rejected(self):
        with pytest.raises(ValueError, match="Legacy observability config keys"):
            Settings(
                environment="development",
                observability={"exporter": "otlp", "endpoint": "http://collector:4317"},
            )

    def test_sampling_ratio_must_be_in_range(self):
        with pytest.raises(ValueError, match="sampling_ratio"):
            Settings(
                environment="development",
                observability={"sampling_ratio": 1.5},
            )

    def test_production_valid_config_succeeds(self):
        settings = Settings(
            environment="production",
            auth={"supabase_jwt_secret": "secret", "supabase_url": "https://x.supabase.co"},
            anthropic={"api_key": "sk-test"},
            plaid={"client_id": "test_id", "secret": "test_secret"},
            observability={
                "traces_exporter": "otlp",
                "metrics_exporter": "otlp",
                "otlp_endpoint": "http://collector:4317",
            },
        )
        assert settings.is_production
        assert settings.observability.traces_exporter == TelemetryExporter.OTLP

    def test_development_starts_without_secrets(self):
        settings = Settings(environment="development")
        assert settings.is_development
        assert settings.auth.supabase_jwt_secret.get_secret_value() == ""

    def test_environment_normalized_to_lowercase(self):
        settings = Settings(
            environment="DEVELOPMENT",
            auth={"supabase_jwt_secret": ""},
        )
        assert settings.environment == Environment.DEVELOPMENT

    def test_request_timeout_must_be_positive(self):
        with pytest.raises(ValueError, match="request_timeout"):
            Settings(environment="development", request_timeout=0)

    def test_request_max_body_size_must_be_positive(self):
        with pytest.raises(ValueError, match="request_max_body_size"):
            Settings(environment="development", request_max_body_size=0)

    def test_shutdown_timeout_must_be_positive(self):
        with pytest.raises(ValueError, match="shutdown_timeout"):
            Settings(environment="development", shutdown_timeout=0)

    def test_nested_settings_load_from_dotenv(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "DATABASE_URL=postgresql+asyncpg://from-dotenv/db",
                    "AUTH_SUPABASE_JWT_SECRET=dotenv-secret",
                    "OTEL_TRACES_EXPORTER=otlp",
                    "OTEL_METRICS_EXPORTER=otlp",
                    "OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4317",
                ]
            )
        )
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("AUTH_SUPABASE_JWT_SECRET", raising=False)
        monkeypatch.delenv("OTEL_TRACES_EXPORTER", raising=False)
        monkeypatch.delenv("OTEL_METRICS_EXPORTER", raising=False)
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

        settings = Settings()

        assert settings.database.url == "postgresql+asyncpg://from-dotenv/db"
        assert settings.auth.supabase_jwt_secret.get_secret_value() == "dotenv-secret"
        assert settings.observability.otlp_endpoint == "http://collector:4317"

    def test_debug_accepts_release_string(self):
        settings = Settings(environment="development", debug="release")
        assert settings.debug is False

    def test_excluded_urls_and_resource_attributes_parse_from_strings(self):
        settings = Settings(
            environment="development",
            observability={
                "excluded_urls": "/health,/ready",
                "resource_attributes": "region=us-east-1,cluster=primary",
            },
        )

        assert settings.observability.excluded_urls == ["/health", "/ready"]
        assert settings.observability.resource_attributes == {
            "region": "us-east-1",
            "cluster": "primary",
        }


class TestConfigSingleton:
    def test_get_settings_returns_same_instance(self):
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
        get_settings.cache_clear()


class TestConfigGroups:
    def test_database_config_accessible(self):
        settings = Settings(environment="development")
        assert settings.database.pool_size > 0
        assert settings.database.url.startswith("postgresql")

    def test_redis_config_accessible(self):
        settings = Settings(environment="development")
        assert settings.redis.url.startswith("redis")
        assert settings.redis.cache_ttl > 0

    def test_observability_config_accessible(self):
        settings = Settings(environment="development")
        assert settings.observability.traces_exporter in (
            TelemetryExporter.CONSOLE,
            TelemetryExporter.OTLP,
            TelemetryExporter.NONE,
        )
        assert settings.observability.metrics_exporter in (
            TelemetryExporter.CONSOLE,
            TelemetryExporter.OTLP,
            TelemetryExporter.NONE,
        )
        assert settings.observability.log_level in ("DEBUG", "INFO", "WARNING", "ERROR")

    def test_service_name_lookup(self):
        settings = Settings(environment="development")
        assert settings.observability.service_name_for_role("api") == "pfm-api"
        assert settings.observability.service_name_for_role("worker") == "pfm-worker"
        assert settings.observability.service_name_for_role("beat") == "pfm-beat"
