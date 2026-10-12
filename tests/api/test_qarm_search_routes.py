"""Zero-billing Qarm private web search contracts; no real network requests."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from free_claude_code.api.qarm_search_routes import (
    QarmSearchRequest,
    _search_query,
    qarm_search_page,
    qarm_web_search,
    router,
)
from free_claude_code.application.web_tools.ports import WebFetchEgressPolicy
from free_claude_code.core.web_tools import WebFetchResult, WebSearchResult


def _request(host="127.0.0.1:8000", client="127.0.0.1"):
    return Request(
        {
            "type": "http",
            "path": "/admin/api/qarm/search",
            "method": "POST",
            "headers": [(b"host", host.encode())],
            "server": ("127.0.0.1", 8000),
            "client": (client, 1234),
            "scheme": "http",
        }
    )


class FakeWeb:
    def __init__(self, results=None, fail=False):
        self.calls = []
        self.result_list = (
            results
            if results is not None
            else [
                WebSearchResult(
                    title="Saudi Central Bank",
                    url="https://www.sama.gov.sa/en-US/Pages/default.aspx",
                ),
                WebSearchResult(
                    title="Financial advice", url="https://example.org/guide"
                ),
            ]
        )
        self.fail = fail

    async def search(self, query):
        self.calls.append(("search", query))
        if self.fail:
            raise TimeoutError("Provider not available")
        return self.result_list

    async def fetch(self, url, *, egress):
        self.calls.append(("fetch", url, egress))
        return WebFetchResult(
            url=url,
            title="Example research",
            media_type="text/plain",
            data="Useful source evidence for the requested topic. " * 100,
        )


def _services(web=None, enabled=True):
    return SimpleNamespace(
        web_tools=web or FakeWeb(),
        requests=SimpleNamespace(
            current_settings=lambda: SimpleNamespace(enable_web_server_tools=enabled)
        ),
    )


def test_routes_only_offer_private_ui_and_search():
    assert {route.path: route.methods for route in router.routes} == {
        "/admin/qarm/search": {"GET"},
        "/admin/api/qarm/search": {"POST"},
        "/admin/api/qarm/search/status": {"GET"},
    }


def test_specific_phrase_site_rendering_and_hostname_validation():
    payload = QarmSearchRequest(
        query="  تمويل   شخصي ",
        exact_phrase="  النسبة السنوية ",
        site="SAMA.GOV.SA",
    )
    assert _search_query(payload) == 'تمويل شخصي "النسبة السنوية" site:sama.gov.sa'
    for data in (
        {"query": "test", "site": "https://example.com/"},
        {"query": "test", "site": "example.com:80"},
        {"query": "test", "site": "bad.local/secret"},
        {"query": "test", "site": "example.com", "paid": True},
        {"query": "test", "exact_phrase": 'bad"quote'},
        {"query": " ", "mode": "deep"},
        {"query": "test", "max_results": 20},
        {"query": "test", "search_engine": "pay-as-you-go"},
    ):
        with pytest.raises(ValidationError):
            QarmSearchRequest(**data)


@pytest.mark.asyncio
async def test_quick_search_uses_existing_free_provider_without_page_fetch(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    web = FakeWeb()
    result = await qarm_web_search(
        QarmSearchRequest(query="specific financing rules", mode="quick"),
        _request(),
        _services(web),
    )
    assert result["result_count"] == 2
    assert web.calls == [("search", "specific financing rules")]
    assert result["answer_generated"] is False
    assert result["billing_enabled"] is False
    assert result["requires_api_key"] is False
    assert result["provider_credits_used"] == 0
    assert result["source_page_reads_attempted"] == 0


@pytest.mark.asyncio
async def test_deep_reads_up_to_three_sources_with_strict_public_https_egress(
    monkeypatch,
):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    web = FakeWeb(
        [
            WebSearchResult(title=f"Source {i}", url=f"https://example.org/{i}")
            for i in range(6)
        ]
    )
    result = await qarm_web_search(
        QarmSearchRequest(query="strong web research", mode="deep", max_results=6),
        _request(),
        _services(web),
    )
    assert result["result_count"] == 6
    assert result["source_page_reads_attempted"] == 3
    assert len([item for item in web.calls if item[0] == "fetch"]) == 3
    assert all(
        egress
        == WebFetchEgressPolicy(
            allow_private_network_targets=False,
            allowed_schemes=frozenset({"https"}),
        )
        for action, _, egress in web.calls[1:]
    )
    assert all(len(row["excerpt"]) <= 2000 for row in result["results"])
    assert result["results"][0]["read_status"] == "read"
    assert result["results"][4]["read_status"] == "not_requested"


@pytest.mark.asyncio
async def test_site_filter_removes_other_domains_and_javascript_links(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    web = FakeWeb(
        [
            WebSearchResult(title="Good", url="https://sama.gov.sa/news"),
            WebSearchResult(title="Subdomain", url="https://info.sama.gov.sa/report"),
            WebSearchResult(title="Unrelated", url="https://evil.example/news"),
            WebSearchResult(title="Spoof", url="https://sama.gov.sa.evil.example"),
            WebSearchResult(title="Bad scheme", url="javascript:alert(1)"),
            WebSearchResult(title="Duplicate", url="https://sama.gov.sa/news#fragment"),
            WebSearchResult(title="Credentials", url="https://hi@sama.gov.sa/news"),
        ]
    )
    result = await qarm_web_search(
        QarmSearchRequest(query="قروض", site="sama.gov.sa", mode="quick"),
        _request(),
        _services(web),
    )
    assert len(result["results"]) == 2
    assert all("sama.gov.sa" in x["url"] for x in result["results"])
    assert web.calls == [("search", "قروض site:sama.gov.sa")]


@pytest.mark.asyncio
async def test_public_search_provider_failure_is_explicit_and_never_paid(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc:
        await qarm_web_search(
            QarmSearchRequest(query="find this"),
            _request(),
            _services(FakeWeb(fail=True)),
        )
    assert exc.value.status_code == 502


@pytest.mark.asyncio
async def test_search_is_disabled_when_original_tools_disabled(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    web = FakeWeb()
    with pytest.raises(HTTPException) as exc:
        await qarm_web_search(
            QarmSearchRequest(query="find this"),
            _request(),
            _services(web, enabled=False),
        )
    assert exc.value.status_code == 503
    assert web.calls == []


@pytest.mark.asyncio
async def test_untrusted_client_cannot_trigger_search(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    web = FakeWeb()
    with pytest.raises(HTTPException) as exc:
        await qarm_web_search(
            QarmSearchRequest(query="find this"),
            _request(host="public.example", client="192.0.2.45"),
            _services(web),
        )
    assert exc.value.status_code == 403
    assert web.calls == []


def test_search_page_protected_and_displays_sources_without_ai_claim(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    html = qarm_search_page(_request()).body.decode("utf-8")
    assert "البحث" in html
    assert "/admin/api/qarm/search" in html
    assert 'id="searchEngine"' in html
    assert "لا يجري حاليًا تلخيصًا بالذكاء الاصطناعي" in html
    assert "textContent=result.excerpt" in html
    with pytest.raises(HTTPException) as exc:
        qarm_search_page(_request(host="public.example", client="192.0.2.45"))
    assert exc.value.status_code == 403
