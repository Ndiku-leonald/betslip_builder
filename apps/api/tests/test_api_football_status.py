import logging

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.main as main_module
import app.providers.api_sports as api_sports_module
from app.cache import MemoryCache
from app.db import Base
from app.models import ProviderHealth, ProviderUsage
from app.providers.api_sports import ApiSportsProvider, ProviderError
from app.quota import QuotaManager


def _provider() -> ApiSportsProvider:
    return ApiSportsProvider(
        name="api-football",
        key="configured-test-key",
        base_url="https://provider.test",
        cache=MemoryCache(),
        quota=QuotaManager(mode="free"),
        retry_attempts=1,
    )


def _mock_response(monkeypatch, payload, *, status_code=200, headers=None):
    calls = []

    class Response:
        def __init__(self):
            self.status_code = status_code
            self.headers = headers or {}

        def json(self):
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

    monkeypatch.setattr(api_sports_module.httpx, "AsyncClient", Client)
    return calls


@pytest.mark.asyncio
async def test_status_discards_account_pii_and_does_not_use_ingestion_accounting(monkeypatch):
    fake_pii = "status-fake-pii@example.invalid"
    fake_secret = "status-fake-token"
    calls = _mock_response(
        monkeypatch,
        {
            "errors": [],
            "response": {
                "account": {"firstname": "Ada", "lastname": "Lovelace", "email": fake_pii, "token": fake_secret, "api_key": fake_secret, "access_token": fake_secret},
                "subscription": {"plan": "free", "active": True, "end": "2026-12-31"},
                "requests": {"current": 26, "limit_day": 100},
            },
        },
    )
    provider = _provider()

    result = await provider.account_status()

    assert result == {
        "provider": "api-football",
        "configured": True,
        "reachable": True,
        "subscription": {"plan": "free", "active": True, "end": "2026-12-31"},
        "requests": {"current": 26, "limit_day": 100, "remaining": 74},
    }
    assert fake_pii not in repr(result) and fake_secret not in repr(result)
    assert calls[0][0] == "https://provider.test/status"
    assert calls[0][1]["headers"] == {"x-apisports-key": "configured-test-key"}
    assert provider.last_request_events == []
    assert provider.calls_today == 0
    assert provider.quota.calls == {}

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        assert db.scalar(select(func.count()).select_from(ProviderUsage)) == 0
        assert db.scalar(select(func.count()).select_from(ProviderHealth)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("subscription", "expected_active", "expected_end"),
    [
        ({"plan": "pro", "active": False, "end": "2025-01-01"}, False, "2025-01-01"),
        ({"plan": "free", "active": False}, False, None),
    ],
)
async def test_status_preserves_safe_inactive_and_expired_operational_fields(monkeypatch, subscription, expected_active, expected_end):
    _mock_response(monkeypatch, {"errors": [], "response": {"subscription": subscription, "requests": {"current": 5, "limit_day": 10}}})
    result = await _provider().account_status()
    assert result["subscription"] == {"plan": subscription["plan"], "active": expected_active, "end": expected_end}
    assert result["requests"] == {"current": 5, "limit_day": 10, "remaining": 5}


@pytest.mark.asyncio
async def test_status_missing_request_fields_are_safe_nulls(monkeypatch):
    _mock_response(monkeypatch, {"errors": [], "response": {"subscription": {"plan": "free", "active": True}}})
    result = await _provider().account_status()
    assert result["requests"] == {"current": None, "limit_day": None, "remaining": None}


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [["opaque"], {"errors": [], "response": "opaque"}])
async def test_status_malformed_response_is_controlled(monkeypatch, payload):
    _mock_response(monkeypatch, payload)
    with pytest.raises(ProviderError) as caught:
        await _provider().account_status()
    diagnostic = caught.value.diagnostic()
    assert diagnostic["reason_code"] == "malformed_response"
    assert diagnostic["error_key"] == "response"
    assert "opaque" not in str(caught.value)
    assert "opaque" not in repr(diagnostic)


@pytest.mark.asyncio
async def test_status_provider_error_reuses_safe_classifier(monkeypatch):
    fake_secret = "SUPER_STATUS_SECRET"
    _mock_response(monkeypatch, {"errors": {"opaque-provider-key": f"api_key={fake_secret} Authorization=Bearer {fake_secret}"}, "response": {}})
    with pytest.raises(ProviderError) as caught:
        await _provider().account_status()
    diagnostic = caught.value.diagnostic()
    assert diagnostic["classification"] == "provider_error"
    assert diagnostic["reason_code"] == "unknown_provider_error"
    assert diagnostic["error_key"] == "unknown_key"
    assert diagnostic["error_shape"] == "object"
    assert fake_secret not in str(caught.value)
    assert fake_secret not in repr(diagnostic)


@pytest.mark.asyncio
async def test_status_transport_error_is_safe_and_not_retried(monkeypatch, caplog):
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
            raise httpx.ConnectError("token=SUPER_STATUS_SECRET", request=httpx.Request("GET", url))

    monkeypatch.setattr(api_sports_module.httpx, "AsyncClient", Client)
    with caplog.at_level(logging.WARNING), pytest.raises(ProviderError) as caught:
        await _provider().account_status()
    assert calls == 1
    assert caught.value.reason_code == "provider_request_failed"
    assert "SUPER_STATUS_SECRET" not in str(caught.value)
    assert "SUPER_STATUS_SECRET" not in caplog.text


def test_status_endpoint_requires_admin_and_returns_only_safe_fields(monkeypatch):
    old_token = main_module.settings.admin_token
    monkeypatch.setattr(main_module.settings, "admin_token", "admin-test-token")

    async def status():
        return {"provider": "api-football", "configured": True, "reachable": True, "subscription": {"plan": "free", "active": True, "end": "2026-12-31"}, "requests": {"current": 26, "limit_day": 100, "remaining": 74}}

    monkeypatch.setattr(main_module.football, "account_status", status)
    client = TestClient(main_module.app)
    assert client.get("/admin/providers/api-football/status").status_code == 401
    response = client.get("/admin/providers/api-football/status", headers={"Authorization": "Bearer admin-test-token"})
    assert response.status_code == 200
    assert response.json()["requests"]["remaining"] == 74
    assert "account" not in response.text.lower()
    assert main_module.settings.admin_token == "admin-test-token"
    monkeypatch.setattr(main_module.settings, "admin_token", old_token)


def test_status_endpoint_returns_controlled_provider_error(monkeypatch, caplog):
    async def status():
        raise ProviderError("api-football", "Provider API error (provider_error)", 200, category="provider_error", reason_code="unknown_provider_error", error_key="unknown_key", error_shape="object", semantic_tags=("auth", "key"), external_request=True, endpoint="status")

    monkeypatch.setattr(main_module.settings, "admin_token", "admin-test-token")
    monkeypatch.setattr(main_module.football, "account_status", status)
    with caplog.at_level(logging.WARNING):
        response = TestClient(main_module.app).get("/admin/providers/api-football/status", headers={"Authorization": "Bearer admin-test-token"})
    assert response.status_code == 503
    body = response.json()
    assert body["diagnostic"]["reason_code"] == "unknown_provider_error"
    assert "raw" not in response.text.lower()
    assert "admin-test-token" not in caplog.text
