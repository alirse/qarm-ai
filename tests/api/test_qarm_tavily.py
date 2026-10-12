"""No-live-network tests for optional free Tavily research and local credit budget."""

from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from free_claude_code.api import qarm_tavily
from free_claude_code.api.qarm_search_routes import (
    QarmSearchRequest,
    qarm_search_status,
    qarm_web_search,
)
from free_claude_code.core.web_tools import WebSearchResult


def _request():
    return Request(
        {
            "type": "http",
            "path": "/admin/api/qarm/search",
            "method": "POST",
            "headers": [(b"host", b"127.0.0.1:8000")],
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
        }
    )


def _free(monkeypatch, tmp_path, *, cap=3):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("QARM_TAVILY_ENABLED", "true")
    monkeypatch.setenv("QARM_TAVILY_FREE_PLAN_CONFIRMED", "true")
    monkeypatch.setenv("TAVILY_API_KEY", "test-non-real-key")
    monkeypatch.setenv("QARM_TAVILY_QUOTA_DB", str(tmp_path / "quota.db"))
    monkeypatch.setenv("QARM_TAVILY_MONTHLY_CAP", str(cap))


def _http(monkeypatch):
    calls = []

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["follow_redirects"] is False
            assert kwargs["trust_env"] is False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def post(self, url, *, json, headers):
            calls.append((url, json, headers))
            return httpx.Response(
                200,
                request=httpx.Request("POST", url),
                json={
                    "results": [
                        {
                            "title": "Central Bank",
                            "url": "https://sama.gov.sa/rules",
                            "content": "Rules and legislation",
                        },
                        {"title": "Spoof", "url": "https://sama.gov.sa.evil.org"},
                    ]
                },
            )

    monkeypatch.setattr(qarm_tavily.httpx, "AsyncClient", Client)
    return calls


def test_tavily_off_by_default_even_with_api_key(monkeypatch, tmp_path):
    monkeypatch.setenv("TAVILY_API_KEY", "test-non-real-key")
    monkeypatch.delenv("QARM_TAVILY_ENABLED", raising=False)
    monkeypatch.setenv("QARM_TAVILY_QUOTA_DB", str(tmp_path / "no-create.db"))
    assert qarm_tavily.tavily_ready() is False
    data = qarm_tavily.tavily_status()
    assert data["configured"] is False
    assert "test-non-real-key" not in str(data)
    assert not (tmp_path / "no-create.db").exists()


@pytest.mark.asyncio
async def test_one_advanced_search_reserves_two_credits(monkeypatch, tmp_path):
    _free(monkeypatch, tmp_path)
    calls = _http(monkeypatch)
    results, cost = await qarm_tavily.tavily_search(
        "قواعد التمويل",
        site="sama.gov.sa",
        mode="deep",
        max_results=5,
    )
    assert cost == 2
    assert results[0]["excerpt"] == "Rules and legislation"
    assert len(calls) == 1
    assert calls[0][0] == "https://api.tavily.com/search"
    assert calls[0][1]["search_depth"] == "advanced"
    assert calls[0][1]["include_domains"] == ["sama.gov.sa"]
    assert calls[0][1]["include_answer"] is False
    assert calls[0][1]["include_raw_content"] is False
    assert calls[0][2]["Authorization"] == "Bearer test-non-real-key"
    assert qarm_tavily.tavily_status()["monthly_local_credits_remaining"] == 1


@pytest.mark.asyncio
async def test_budget_stops_before_fourth_credit(monkeypatch, tmp_path):
    _free(monkeypatch, tmp_path)
    calls = _http(monkeypatch)
    for _ in range(3):
        _, cost = await qarm_tavily.tavily_search(
            "financing", site="", mode="quick", max_results=3
        )
        assert cost == 1
    assert len(calls) == 3
    with pytest.raises(qarm_tavily.TavilyBudgetExceeded):
        await qarm_tavily.tavily_search(
            "financing", site="", mode="quick", max_results=3
        )
    assert len(calls) == 3
    assert qarm_tavily.tavily_status()["monthly_local_credits_remaining"] == 0


@pytest.mark.asyncio
async def test_missing_quota_storage_fails_before_network(monkeypatch, tmp_path):
    _free(monkeypatch, tmp_path)
    calls = _http(monkeypatch)
    monkeypatch.setenv("QARM_TAVILY_QUOTA_DB", "relative/not-safe")
    with pytest.raises(qarm_tavily.TavilyDisabled):
        await qarm_tavily.tavily_search(
            "financing", site="", mode="deep", max_results=3
        )
    assert calls == []


class StubWeb:
    def __init__(self, results=None, *, fail=False):
        self.calls = []
        self.results = [] if results is None else results
        self.fail = fail

    async def search(self, query):
        self.calls.append(query)
        if self.fail:
            raise TimeoutError("simulated DuckDuckGo unavailable")
        return self.results

    async def fetch(self, *_args, **_kwargs):
        pytest.fail("Tavily excerpts must not trigger additional page fetch")


def _services(web):
    return SimpleNamespace(
        web_tools=web,
        requests=SimpleNamespace(
            current_settings=lambda: SimpleNamespace(enable_web_server_tools=True)
        ),
    )


@pytest.mark.asyncio
async def test_auto_stays_duckduckgo_when_results_exist(monkeypatch, tmp_path):
    _free(monkeypatch, tmp_path)
    _http(monkeypatch)
    web = StubWeb([WebSearchResult("Source", "https://sama.gov.sa/law")])
    response = await qarm_web_search(
        QarmSearchRequest(query="laws", mode="quick"),
        _request(),
        _services(web),
    )
    assert response["provider"] == "duckduckgo_lite_public"
    assert response["provider_credits_used"] == 0
    assert qarm_tavily.tavily_status()["monthly_local_credits_reserved"] == 0


@pytest.mark.asyncio
async def test_auto_uses_free_tavily_only_when_duckduckgo_empty(monkeypatch, tmp_path):
    _free(monkeypatch, tmp_path)
    calls = _http(monkeypatch)
    web = StubWeb()
    response = await qarm_web_search(
        QarmSearchRequest(query="قروض", mode="deep", site="sama.gov.sa"),
        _request(),
        _services(web),
    )
    assert len(web.calls) == 1
    assert response["provider"] == "tavily_researcher_free"
    assert response["provider_credits_used"] == 2
    assert response["result_count"] == 1
    assert response["results"][0]["url"] == "https://sama.gov.sa/rules"
    assert response["results"][0]["read_status"] == "provider_excerpt"
    assert response["source_page_reads_attempted"] == 0
    assert response["billing_enabled"] is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_auto_recovers_from_free_provider_failure_without_paid_fallback(
    monkeypatch, tmp_path
):
    _free(monkeypatch, tmp_path, cap=1)
    calls = _http(monkeypatch)
    web = StubWeb(fail=True)
    response = await qarm_web_search(
        QarmSearchRequest(query="test", mode="quick"),
        _request(),
        _services(web),
    )
    assert response["provider"] == "tavily_researcher_free"
    assert len(calls) == 1
    with pytest.raises(HTTPException) as exc:
        await qarm_web_search(
            QarmSearchRequest(query="test", mode="quick"),
            _request(),
            _services(web),
        )
    assert exc.value.status_code == 429
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_explicit_tavily_requires_free_plan_configuration(monkeypatch, tmp_path):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("QARM_TAVILY_ENABLED", raising=False)
    monkeypatch.setenv("QARM_TAVILY_QUOTA_DB", str(tmp_path / "unused.db"))
    with pytest.raises(HTTPException) as exc:
        await qarm_web_search(
            QarmSearchRequest(query="test", search_engine="tavily"),
            _request(),
            _services(StubWeb()),
        )
    assert exc.value.status_code == 503
    assert not (tmp_path / "unused.db").exists()


def test_status_never_exposes_key(monkeypatch, tmp_path):
    _free(monkeypatch, tmp_path)
    data = qarm_search_status(_request())
    assert data["tavily"]["configured"] is True
    assert data["default_provider"] == "duckduckgo_lite_public"
    assert "test-non-real-key" not in str(data)


def test_invalid_caps_never_arm_tavily(monkeypatch, tmp_path):
    _free(monkeypatch, tmp_path)
    monkeypatch.setenv("QARM_TAVILY_MONTHLY_CAP", "1000")
    state = qarm_tavily.tavily_status()
    assert state["configured"] is False
    assert state["error"]
