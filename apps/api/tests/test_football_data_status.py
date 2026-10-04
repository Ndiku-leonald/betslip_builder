import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
import app.providers.football_data as provider_module
from app.cache import MemoryCache
from app.providers.football_data import FootballDataProvider
from app.quota import QuotaManager


def _provider() -> FootballDataProvider:
    return FootballDataProvider(
        "football-data-secret",
        base_url="https://provider.test/v4",
        cache=MemoryCache(),
        quota=QuotaManager(mode="standard"),
        timeout=1.0,
    )


def _mock_response(monkeypatch, payload, *, status_code=200, headers=None, error=None):
    calls = []

    class Response:
        def __init__(self):
            self.status_code = status_code
            self.headers = headers or {}

        def json(self):
            if error is not None:
                raise error
            return payload

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return Response()

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", Client)
    return calls


@pytest.mark.asyncio
async def test_status_success_is_authenticated_usable_and_reads_only_safe_rate_headers(monkeypatch):
    secret = "RESPONSE_SECRET status-fake@example.invalid"
    calls = _mock_response(
        monkeypatch,
        {"matches": [], "account": {"email": secret, "token": secret}},
        headers={
            "X-RequestsAvailable": "9",
            "X-RequestCounter-Reset": "21",
            "X-Authenticated-Client": "account-owner@example.invalid",
        },
    )
    provider = _provider()
    provider.calls_today = 7
    provider.last_error = "existing provider state"
    provider.consecutive_failures = 3
    provider.circuit_open_until = 123.0
    previous_state = (provider.calls_today, provider.last_error, provider.consecutive_failures, provider.circuit_open_until, dict(provider.quota.calls))

    result = await provider.status_diagnostic()

    assert result == {
        "provider": "football-data.org",
        "configured": True,
        "reachable": True,
        "authenticated": True,
        "available": True,
        "http_status": 200,
        "classification": "successful_usable_response",
        "reason_code": "authenticated_matches_response",
        "rate_limit_remaining": 9,
        "rate_limit_reset_seconds": 21,
    }
    assert secret not in repr(result)
    assert calls == [("https://provider.test/v4/matches", {"headers": {"X-Auth-Token": "football-data-secret"}})]
    assert (provider.calls_today, provider.last_error, provider.consecutive_failures, provider.circuit_open_until, provider.quota.calls) == previous_state


@pytest.mark.asyncio
async def test_status_does_not_reserve_local_quota_or_mutate_ingestion_accounting(monkeypatch):
    reservations = []

    def reserve(*args):
        reservations.append(args)
        raise AssertionError("status diagnostics must not use ingestion quota")

    provider = FootballDataProvider(
        "configured",
        cache=MemoryCache(),
        quota=QuotaManager(mode="free", daily_limits={"football-data.org": 1}, reserve_callback=reserve),
    )
    calls = _mock_response(monkeypatch, {"matches": []})

    result = await provider.status_diagnostic()

    assert result["available"] is True
    assert calls and len(calls) == 1
    assert reservations == []
    assert provider.quota.calls == {}
    assert provider.calls_today == 0


@pytest.mark.asyncio
async def test_status_not_configured_makes_no_request(monkeypatch):
    provider = FootballDataProvider(None, cache=MemoryCache(), quota=QuotaManager(mode="standard"))
    calls = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, *args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("unconfigured diagnostic must not call the provider")

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", Client)
    result = await provider.status_diagnostic()
    assert result["classification"] == "not_configured"
    assert result["reason_code"] == "provider_not_configured"
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "classification", "reason_code", "authenticated"),
    [
        (401, "authentication_failure", "authentication_failed", False),
        (403, "plan_restricted", "restricted_resource", None),
    ],
)
async def test_status_classifies_authentication_and_plan_access_failures(monkeypatch, status_code, classification, reason_code, authenticated):
    calls = _mock_response(monkeypatch, {"error": "sensitive response text"}, status_code=status_code)
    result = await _provider().status_diagnostic()
    assert result["classification"] == classification
    assert result["reason_code"] == reason_code
    assert result["authenticated"] is authenticated
    assert result["http_status"] == status_code
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("headers", "classification", "reason_code"),
    [
        ({}, "rate_limited", "provider_rate_limited"),
        ({"X-RequestsAvailable": "0", "X-RequestCounter-Reset": "30"}, "quota_exhausted", "rate_limit_exhausted"),
    ],
)
async def test_status_distinguishes_rate_limit_and_exhaustion(monkeypatch, headers, classification, reason_code):
    _mock_response(monkeypatch, {"error": "do not expose"}, status_code=429, headers=headers)
    result = await _provider().status_diagnostic()
    assert result["classification"] == classification
    assert result["reason_code"] == reason_code
    assert result["authenticated"] is True
    assert result["available"] is False
    assert result["rate_limit_remaining"] == (0 if headers.get("X-RequestsAvailable") == "0" else None)


@pytest.mark.asyncio
async def test_status_classifies_provider_unavailable_without_raw_error(monkeypatch):
    secret = "5xx-secret-token"
    _mock_response(monkeypatch, {"error": secret}, status_code=503)
    result = await _provider().status_diagnostic()
    assert result["classification"] == "provider_unavailable"
    assert result["reason_code"] == "provider_http_5xx"
    assert secret not in repr(result)


@pytest.mark.asyncio
async def test_status_classifies_timeout_without_retry_or_secret_leak(monkeypatch):
    calls = 0

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url, **kwargs):
            nonlocal calls
            calls += 1
            raise httpx.ReadTimeout("token=timeout-secret", request=httpx.Request("GET", url))

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", Client)
    result = await _provider().status_diagnostic()
    assert calls == 1
    assert result["classification"] == "transport_failure"
    assert result["reason_code"] == "provider_timeout"
    assert "timeout-secret" not in repr(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"matches": "not-a-list"}, {"response": {"email": "pii@example.invalid"}}])
async def test_status_classifies_malformed_response_without_body_or_pii(monkeypatch, payload):
    _mock_response(monkeypatch, payload)
    result = await _provider().status_diagnostic()
    assert result["classification"] == "malformed_response"
    assert result["reason_code"] == "matches_payload_malformed"
    assert "pii@example.invalid" not in repr(result)


def test_status_route_is_admin_protected_and_returns_only_safe_fields(monkeypatch):
    old_token = main_module.settings.admin_token
    monkeypatch.setattr(main_module.settings, "admin_token", "admin-test-token")

    async def status():
        return {
            "provider": "football-data.org",
            "configured": True,
            "reachable": True,
            "authenticated": True,
            "available": True,
            "http_status": 200,
            "classification": "successful_usable_response",
            "reason_code": "authenticated_matches_response",
            "rate_limit_remaining": 9,
            "rate_limit_reset_seconds": 21,
        }

    monkeypatch.setattr(main_module.football_data, "status_diagnostic", status)
    client = TestClient(main_module.app)
    assert client.get("/admin/providers/football-data/status").status_code == 401
    response = client.get("/admin/providers/football-data/status", headers={"Authorization": "Bearer admin-test-token"})
    assert response.status_code == 200
    assert set(response.json()) == {"provider", "configured", "reachable", "authenticated", "available", "http_status", "classification", "reason_code", "rate_limit_remaining", "rate_limit_reset_seconds"}
    assert "admin-test-token" not in response.text
    assert main_module.settings.admin_token == "admin-test-token"
    monkeypatch.setattr(main_module.settings, "admin_token", old_token)
