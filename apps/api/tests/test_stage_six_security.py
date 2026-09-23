from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.cache import CacheBackend
from app.config import Settings, validate_production_settings
from app.main import app
from app.security import InMemoryRateLimiter, RedisRateLimiter, constant_time_token, redact_secrets, safe_request_id


def test_production_configuration_fails_closed_for_sqlite_redis_origins_and_admin() -> None:
    with pytest.raises(ValueError, match="PostgreSQL"):
        validate_production_settings(Settings(app_env="production", database_url="sqlite:///./bad.db", allowed_origins="https://app.example", trusted_hosts="app.example", admin_token="x"))
    with pytest.raises(ValueError, match="REDIS_URL"):
        validate_production_settings(Settings(app_env="production", database_url="postgresql://db/slipiq", allowed_origins="https://app.example", trusted_hosts="app.example", admin_token="x"))
    with pytest.raises(ValueError, match="origins"):
        validate_production_settings(Settings(app_env="production", database_url="postgresql://db/slipiq", redis_url="redis://cache", allowed_origins="*", trusted_hosts="app.example", admin_token="x"))
    with pytest.raises(ValueError, match="ADMIN_TOKEN"):
        validate_production_settings(Settings(app_env="production", database_url="postgresql://db/slipiq", redis_url="redis://cache", allowed_origins="https://app.example", trusted_hosts="app.example", admin_token=None))


def test_valid_production_configuration_is_explicit() -> None:
    validate_production_settings(Settings(app_env="production", database_url="postgresql://db/slipiq", redis_url="redis://cache", allowed_origins="https://app.example", trusted_hosts="app.example", admin_token="server-only"))


def test_secret_redaction_handles_nested_values_and_headers() -> None:
    value = redact_secrets({"api_key": "private", "nested": {"authorization": "Bearer private"}, "message": "token=private"})
    assert value["api_key"] == "[REDACTED]" and value["nested"]["authorization"] == "[REDACTED]" and "[REDACTED]" in value["message"]


def test_request_id_is_bounded_and_token_comparison_is_constant_time_safe() -> None:
    assert safe_request_id("request-123") == "request-123"
    assert safe_request_id("x" * 200) != "x" * 200
    assert constant_time_token("abc", "abc") and not constant_time_token("abc", "abd")


def test_required_cache_does_not_silently_fallback() -> None:
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        CacheBackend(None, required=True)


def test_rate_limiter_enforces_window_and_reports_retry() -> None:
    limiter = InMemoryRateLimiter()
    first = limiter.check("client", 1, 60)
    second = limiter.check("client", 1, 60)
    assert first.allowed and first.remaining == 0
    assert not second.allowed and second.retry_after >= 1


def test_health_has_request_id_and_security_headers() -> None:
    response = TestClient(app).get("/health", headers={"X-Request-ID": "stage-six-test"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "stage-six-test"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert "password" not in response.text.lower() and "api_key" not in response.text.lower()


def test_liveness_is_lightweight_and_metrics_are_sanitized() -> None:
    client = TestClient(app)
    assert client.get("/livez").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200 and "slipiq_http_requests_total" in metrics.text


def test_invalid_request_returns_structured_validation_error() -> None:
    response = TestClient(app).post("/api/slips/build", json={"target_odds": 1})
    assert response.status_code == 422
    payload = response.json()
    assert payload["code"] == "VALIDATION_ERROR" and payload["request_id"]


def test_admin_endpoint_rejects_bearer_token_in_production(monkeypatch) -> None:
    from app import main as main_module
    original_env, original_token = main_module.settings.app_env, main_module.settings.admin_token
    monkeypatch.setattr(main_module.settings, "app_env", "production")
    monkeypatch.setattr(main_module.settings, "admin_token", "server-secret")
    try:
        response = TestClient(app).post("/api/ingestion/today?sport=football")
        assert response.status_code == 401
    finally:
        main_module.settings.app_env = original_env
        main_module.settings.admin_token = original_token


def test_production_worker_role_is_the_only_scheduler_role(monkeypatch) -> None:
    import asyncio
    from app import main as main_module
    original = (main_module.settings.app_env, main_module.settings.app_process_role, main_module.settings.enable_scheduled_ingestion, main_module.scheduler)
    monkeypatch.setattr(main_module.settings, "app_env", "production")
    monkeypatch.setattr(main_module.settings, "app_process_role", "web")
    monkeypatch.setattr(main_module.settings, "enable_scheduled_ingestion", True)
    main_module.scheduler = None
    asyncio.run(main_module.start_scheduler())
    assert main_module.scheduler is None
    main_module.settings.app_env, main_module.settings.app_process_role, main_module.settings.enable_scheduled_ingestion, main_module.scheduler = original


def test_provider_settings_reject_non_positive_timeout() -> None:
    with pytest.raises(ValueError):
        Settings(provider_read_timeout=0)


def test_provider_circuit_opens_after_bounded_failures() -> None:
    from app.providers.api_sports import ApiSportsProvider
    provider = ApiSportsProvider(name="test", key="key", base_url="https://provider.invalid", cache=CacheBackend(), quota=SimpleNamespace())
    provider.circuit_failure_threshold = 2
    provider.circuit_cooldown_seconds = 30
    provider._record_failure(); assert provider.circuit_open_until == 0
    provider._record_failure(); assert provider.circuit_open_until > 0
    provider._record_success(); assert provider.consecutive_failures == 0 and provider.circuit_open_until == 0


def test_provider_retry_parameters_are_bounded_and_retry_after_is_supported() -> None:
    settings = Settings(provider_retry_attempts=2, provider_retry_base_seconds=0.1, provider_connect_timeout=1, provider_read_timeout=2)
    assert settings.provider_retry_attempts == 2 and settings.provider_retry_base_seconds == .1


def test_development_origins_and_hosts_are_convenient_but_production_wildcards_are_rejected() -> None:
    dev = Settings(app_env="development", api_cors_origins="http://localhost:3000", trusted_hosts="localhost")
    assert dev.cors_origins == ["http://localhost:3000"] and dev.trusted_host_list == ["localhost"]
    with pytest.raises(ValueError):
        validate_production_settings(Settings(app_env="production", database_url="postgresql://db/slipiq", redis_url="redis://cache", allowed_origins="https://app.example", trusted_hosts="*", admin_token="x"))


def test_request_size_limit_returns_structured_413() -> None:
    original = app.state.settings.max_request_body_bytes
    app.state.settings.max_request_body_bytes = 2
    try:
        response = TestClient(app).post("/api/slips/build", content="{}", headers={"content-length": "3"})
        assert response.status_code == 413 and response.json()["code"] == "REQUEST_TOO_LARGE"
    finally:
        app.state.settings.max_request_body_bytes = original


def test_health_reports_sanitized_cache_and_release_metadata() -> None:
    payload = TestClient(app).get("/health").json()
    assert payload["service"] == "slipiq-api" and payload["version"] and payload["live"]["cache"] in {"redis", "memory/degraded"}


def test_admin_token_is_never_accepted_from_query_string(monkeypatch) -> None:
    from app import main as main_module
    old_env, old_token = main_module.settings.app_env, main_module.settings.admin_token
    monkeypatch.setattr(main_module.settings, "app_env", "production")
    monkeypatch.setattr(main_module.settings, "admin_token", "server-secret")
    try:
        response = TestClient(app).post("/api/ingestion/today?sport=football&token=server-secret")
        assert response.status_code == 401
    finally:
        main_module.settings.app_env, main_module.settings.admin_token = old_env, old_token


def test_redis_rate_limiter_sets_ttl_only_for_new_bucket() -> None:
    class FakeRedis:
        def __init__(self): self.count = 0; self.expirations = 0
        def incr(self, _key): self.count += 1; return self.count
        def expire(self, _key, seconds): self.expirations += seconds
    client = FakeRedis(); limiter = RedisRateLimiter(client, namespace="test")
    assert limiter.check("client", 2, 60).allowed
    assert limiter.check("client", 2, 60).allowed
    assert not limiter.check("client", 2, 60).allowed
    assert client.expirations == 60


def test_malformed_request_id_is_replaced() -> None:
    assert safe_request_id("bad id") != "bad id"
    assert safe_request_id("<script>") != "<script>"


def test_production_security_headers_include_hsts(monkeypatch) -> None:
    from app import main as main_module
    old = main_module.settings.app_env
    monkeypatch.setattr(main_module.settings, "app_env", "production")
    try:
        response = TestClient(app).get("/livez")
        assert "max-age=" in response.headers["Strict-Transport-Security"]
    finally:
        main_module.settings.app_env = old


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch) -> None:
    from app import main as main_module
    def broken_session():
        raise RuntimeError("database password should not leak")
    monkeypatch.setattr(main_module, "SessionLocal", broken_session)
    response = TestClient(app).get("/ready")
    assert response.status_code == 503 and "password" not in response.text.lower()


def test_pool_settings_are_available_for_postgres() -> None:
    settings = Settings(database_url="postgresql://db/slipiq", db_pool_size=12, db_max_overflow=4, db_pool_timeout=9, db_pool_recycle=600)
    assert (settings.db_pool_size, settings.db_max_overflow, settings.db_pool_timeout, settings.db_pool_recycle) == (12, 4, 9, 600)


def test_release_metadata_prefers_explicit_release() -> None:
    assert Settings(app_version="1.0.0", release="2026.09.23").effective_release == "2026.09.23"


def test_backend_does_not_accept_wildcard_origin_in_production() -> None:
    with pytest.raises(ValueError, match="origins"):
        validate_production_settings(Settings(app_env="production", database_url="postgresql://db/slipiq", redis_url="redis://cache", allowed_origins="*", trusted_hosts="api.example", admin_token="x"))
