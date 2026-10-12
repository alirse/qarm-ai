"""Private Qarm web research: reuse FCC's free web_search and SSRF-safe web_fetch.

No LLM synthesis, billable search provider, API credentials, or auto fallback.
Search queries and the URLs in deep mode are transmitted to public services.
"""

import asyncio
import re
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from free_claude_code.application.web_tools.ports import WebFetchEgressPolicy
from free_claude_code.core.web_tools import WebFetchResult, WebSearchResult

from .admin_security import require_loopback_admin
from .dependencies import get_services
from .ports import ApiServices
from .qarm_tavily import (
    TavilyBudgetExceeded,
    TavilyDisabled,
    TavilyUnavailable,
    tavily_ready,
    tavily_search,
    tavily_status,
)

router = APIRouter()
_PAGE = Path(__file__).resolve().parent / "admin_static" / "qarm_search.html"
_HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


class QarmSearchRequest(BaseModel):
    """Bounded user search criteria; unexpected billing flags are rejected."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=2, max_length=260)
    exact_phrase: str = Field(default="", max_length=120)
    site: str = Field(default="", max_length=253)
    mode: str = Field(default="deep", pattern="^(quick|deep)$")
    max_results: int = Field(default=8, ge=1, le=10)
    search_engine: str = Field(default="auto", pattern="^(auto|duckduckgo|tavily)$")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        value = " ".join(value.split())
        if len(value) < 2:
            raise ValueError("Search query cannot be empty")
        return value

    @field_validator("exact_phrase")
    @classmethod
    def validate_phrase(cls, value: str) -> str:
        # Never add unescaped quotes into the exact-phrase search operator.
        value = " ".join(value.split())
        if '"' in value or "\\" in value:
            raise ValueError("Exact phrase cannot contain quotes or backslashes")
        return value

    @field_validator("site")
    @classmethod
    def validate_site(cls, value: str) -> str:
        value = value.strip().lower().rstrip(".")
        if not value:
            return ""
        if any(part in value for part in (":", "/", "\\", "@", "*", "#", "?")):
            raise ValueError("Use a hostname without scheme, path or port")
        try:
            value = value.encode("idna").decode("ascii")
        except UnicodeError as exc:
            raise ValueError("Invalid site domain") from exc
        labels = value.split(".")
        if (
            len(labels) < 2
            or len(value) > 253
            or any(not _HOST_LABEL.fullmatch(part) for part in labels)
        ):
            raise ValueError("Invalid site hostname")
        return value


def _search_query(payload: QarmSearchRequest) -> str:
    parts = [payload.query]
    if payload.exact_phrase:
        parts.append(f'"{payload.exact_phrase}"')
    if payload.site:
        parts.append(f"site:{payload.site}")
    return " ".join(parts)


def _eligible_url(url: str, site: str) -> bool:
    try:
        value = urlsplit(url)
        host = value.hostname
        return bool(
            value.scheme in {"https", "http"}
            and host
            and not value.username
            and not value.password
            and value.port is None
            and (not site or host.lower() == site or host.lower().endswith("." + site))
        )
    except ValueError:
        return False


async def _preview(item: WebSearchResult, services: ApiServices) -> tuple[str, str]:
    """Read an HTTPS page using existing pinned-DNS/redirect SSRF safeguards."""
    if urlsplit(item.url).scheme != "https":
        return "", "https_required"
    try:
        page: WebFetchResult = await asyncio.wait_for(
            services.web_tools.fetch(
                item.url,
                egress=WebFetchEgressPolicy(
                    allow_private_network_targets=False,
                    allowed_schemes=frozenset({"https"}),
                ),
            ),
            timeout=22,
        )
        if not _eligible_url(page.url, ""):
            return "", "unsafe_redirect"
        snippet = " ".join(page.data.split())[:2000]
        return snippet, "read" if snippet else "empty"
    except Exception:
        # The search result link is still useful even if a site refuses fetching.
        return "", "unavailable"


@router.get("/admin/qarm/search", response_class=HTMLResponse, include_in_schema=False)
def qarm_search_page(request: Request) -> HTMLResponse:
    """Owner-only independent research UI. No network fetch to render the page."""
    require_loopback_admin(request)
    return HTMLResponse(
        _PAGE.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/admin/api/qarm/search/status")
def qarm_search_status(request: Request) -> dict:
    """Show Tavily readiness and conservative local quota without secrets."""
    require_loopback_admin(request)
    return {
        "default_provider": "duckduckgo_lite_public",
        "auto_uses_tavily_only_if_free_provider_fails": True,
        "tavily": tavily_status(),
        "billable_provider_enabled": False,
    }


@router.post("/admin/api/qarm/search")
async def qarm_web_search(
    payload: QarmSearchRequest,
    request: Request,
    services: ApiServices = Depends(get_services),
) -> dict:
    """Free DuckDuckGo first; optional bounded Tavily when explicitly configured."""
    require_loopback_admin(request)
    if not services.requests.current_settings().enable_web_server_tools:
        raise HTTPException(status_code=503, detail="Qarm web tools disabled")
    if payload.search_engine == "tavily" and not tavily_ready():
        raise HTTPException(
            status_code=503,
            detail="Tavily disabled: owner must configure a free Researcher key",
        )

    rendered_query = _search_query(payload)
    candidates: list[WebSearchResult] = []
    if payload.search_engine != "tavily":
        try:
            candidates = await asyncio.wait_for(
                services.web_tools.search(rendered_query), timeout=22
            )
        except Exception:
            if payload.search_engine == "duckduckgo" or not tavily_ready():
                raise HTTPException(
                    status_code=502, detail="Public search temporarily unavailable"
                ) from None

    items: list[WebSearchResult] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not _eligible_url(candidate.url, payload.site):
            continue
        key = candidate.url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        items.append(candidate)
        if len(items) >= payload.max_results:
            break

    provider_used = "duckduckgo_lite_public"
    consumed = 0
    enriched: dict[str, str] = {}
    if (
        not items
        and payload.search_engine in {"auto", "tavily"}
        and tavily_ready()
    ):
        try:
            tavily_items, consumed = await tavily_search(
                rendered_query,
                site=payload.site,
                mode=payload.mode,
                max_results=payload.max_results,
            )
        except TavilyBudgetExceeded as exc:
            raise HTTPException(
                status_code=429,
                detail="Tavily local free-credit limit reached; paid fallback blocked",
            ) from exc
        except (TavilyDisabled, TavilyUnavailable) as exc:
            raise HTTPException(
                status_code=502, detail="Tavily unavailable; no paid fallback"
            ) from exc
        provider_used = "tavily_researcher_free"
        for item in tavily_items:
            url = item["url"]
            if not _eligible_url(url, payload.site):
                continue
            key = url.split("#", 1)[0]
            if key in seen:
                continue
            seen.add(key)
            items.append(WebSearchResult(title=item["title"], url=url))
            enriched[url] = item["excerpt"]
            if len(items) >= payload.max_results:
                break

    previews: list[tuple[str, str]] = []
    to_read = (
        min(3, len(items))
        if payload.mode == "deep" and provider_used == "duckduckgo_lite_public"
        else 0
    )
    if to_read:
        previews = list(
            await asyncio.gather(
                *(_preview(item, services) for item in items[:to_read])
            )
        )
    results = [
        {
            "title": item.title[:300],
            "url": item.url,
            "excerpt": (
                enriched.get(item.url, "")
                if provider_used == "tavily_researcher_free"
                else previews[index][0] if index < len(previews) else ""
            ),
            "read_status": (
                "provider_excerpt" if provider_used == "tavily_researcher_free"
                else previews[index][1] if index < len(previews)
                else "not_requested"
            ),
        }
        for index, item in enumerate(items)
    ]
    return {
        "query": rendered_query,
        "mode": payload.mode,
        "provider": provider_used,
        "results": results,
        "result_count": len(results),
        "source_page_reads_attempted": to_read,
        "answer_generated": False,
        "billing_enabled": False,
        "requires_api_key": provider_used == "tavily_researcher_free",
        "provider_credits_used": consumed,
        "warning": (
            "Public results and excerpts are untrusted. Tavily local quota "
            "is conservative, not a live provider billing guarantee; keep "
            "Researcher free plan and PAYGO disabled."
            if provider_used == "tavily_researcher_free"
            else "DuckDuckGo HTML results are best effort; sources are untrusted."
        ),
    }
