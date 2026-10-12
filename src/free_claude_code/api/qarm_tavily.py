"""Optional owner-controlled Tavily Search for Qarm, disabled unless explicitly armed.

This module does not enable paid billing. Only a verified free-plan key may be
activated by owner-controlled environment settings; no key is ever exposed
through the API or GitHub. A locally persisted conservative quota reserves
credits BEFORE any outbound API call (even if the call later fails). This
protects a single stable runtime but is NOT a substitute for Tavily-side free
plan enforcement, especially across server clones/redeployment.
"""

import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

import httpx

_MAX_LOCAL_CAP = 1000
_DEFAULT_LOCAL_CAP = 1000
_API = "https://api.tavily.com/search"


class TavilyDisabled(ValueError):
    """No verified free-plan account or explicit enable signal."""


class TavilyBudgetExceeded(ValueError):
    """Conservative on-disk monthly safety budget exhausted."""


class TavilyUnavailable(ValueError):
    """Provider refused/failed; never try a paid replacement."""


def _cap() -> int:
    try:
        cap = int(os.environ.get("QARM_TAVILY_MONTHLY_CAP", str(_DEFAULT_LOCAL_CAP)))
    except ValueError as exc:
        raise TavilyDisabled("Invalid Tavily monthly cap") from exc
    if not 1 <= cap <= _MAX_LOCAL_CAP:
        raise TavilyDisabled("Tavily cap must be between 1 and 1000")
    return cap


def tavily_ready() -> bool:
    """Fail closed unless owner explicitly confirms a free non-PAYGO key."""
    return (
        os.environ.get("QARM_TAVILY_ENABLED", "").lower() in {"1", "true"}
        and os.environ.get("QARM_TAVILY_FREE_PLAN_CONFIRMED", "").lower()
        in {"1", "true"}
        and bool(os.environ.get("TAVILY_API_KEY", "").strip())
    )


def _db_path() -> Path:
    configured = os.environ.get("QARM_TAVILY_QUOTA_DB", "")
    if configured:
        path = Path(configured)
        if not path.is_absolute():
            raise TavilyDisabled("Quota DB path must be absolute")
        return path
    return Path.home() / ".local" / "state" / "qarm-ai" / "tavily-budget.sqlite3"


def _month() -> str:
    return datetime.now(UTC).strftime("%Y-%m")


def _used() -> int:
    path = _db_path()
    if not path.exists():
        return 0
    with closing(sqlite3.connect(path, timeout=5)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS monthly_usage (month TEXT PRIMARY KEY, credits INTEGER NOT NULL)"
        )
        row = connection.execute(
            "SELECT credits FROM monthly_usage WHERE month = ?", (_month(),)
        ).fetchone()
    return int(row[0]) if row else 0


def tavily_status() -> dict:
    """Expose remaining *local* budget; never expose the key itself."""
    try:
        cap = _cap()
        used = _used()
        ready = tavily_ready()
        error = ""
    except OSError, sqlite3.Error, TavilyDisabled, ValueError:
        cap, used, ready = 0, 0, False
        error = "Local quota unavailable (Tavily blocked)"
    return {
        "provider": "tavily",
        "configured": ready,
        "monthly_local_credit_cap": cap,
        "monthly_local_credits_reserved": used,
        "monthly_local_credits_remaining": max(0, cap - used),
        "monthly_period_utc": _month(),
        "account_free_plan_confirmation_required": True,
        "paid_fallback": False,
        "monthly_provider_balance_verified": False,
        "note": (
            "Local conservative cap, not Tavily account usage. Use a Researcher "
            "free-plan key with PAYGO disabled. It is not safe across multiple "
            "servers or a lost/replaced quota database."
        ),
        "error": error,
    }


def _reserve(cost: int) -> None:
    """Atomic reservation for one server/shared durable SQLite path."""
    if not tavily_ready():
        raise TavilyDisabled("Tavily not enabled with a verified free plan")
    cap = _cap()
    try:
        path = _db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(
            sqlite3.connect(path, timeout=5, isolation_level=None)
        ) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS monthly_usage (month TEXT PRIMARY KEY, credits INTEGER NOT NULL)"
            )
            row = connection.execute(
                "SELECT credits FROM monthly_usage WHERE month = ?", (_month(),)
            ).fetchone()
            used = int(row[0]) if row else 0
            if used + cost > cap:
                connection.execute("ROLLBACK")
                raise TavilyBudgetExceeded("Tavily local free-credit cap reached")
            connection.execute(
                "INSERT INTO monthly_usage (month, credits) VALUES (?, ?) "
                "ON CONFLICT(month) DO UPDATE SET credits=excluded.credits",
                (_month(), used + cost),
            )
            connection.execute("COMMIT")
    except (sqlite3.Error, OSError) as exc:
        raise TavilyUnavailable("Cannot persist local quota; no API call made") from exc


async def tavily_search(
    query: str,
    *,
    site: str,
    mode: str,
    max_results: int,
) -> tuple[list[dict], int]:
    """Perform at most one owner-enabled, pre-budgeted free-plan search."""
    cost = 2 if mode == "deep" else 1
    _reserve(cost)
    # Only now, after durable quota reservation, read the key.
    key = os.environ.get("TAVILY_API_KEY", "").strip()
    payload: dict = {
        "query": query,
        "search_depth": "advanced" if mode == "deep" else "basic",
        "max_results": max_results,
        "include_answer": False,
        "include_raw_content": False,
        "include_images": False,
    }
    if site:
        payload["include_domains"] = [site]
    try:
        async with httpx.AsyncClient(
            timeout=18, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.post(
                _API,
                json=payload,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            if len(response.content) > 1_000_000:
                raise TavilyUnavailable("Tavily response too large")
            data = response.json()
            if not isinstance(data, dict):
                raise TavilyUnavailable("Invalid Tavily response")
            raw = data.get("results", [])
            if not isinstance(raw, list):
                raise TavilyUnavailable("Invalid Tavily result list")
            results = []
            for item in raw[:max_results]:
                if not isinstance(item, dict):
                    continue
                title, url, excerpt = (
                    item.get("title"),
                    item.get("url"),
                    item.get("content"),
                )
                if not isinstance(title, str) or not isinstance(url, str):
                    continue
                results.append(
                    {
                        "title": title[:300],
                        "url": url,
                        "excerpt": excerpt[:2000] if isinstance(excerpt, str) else "",
                    }
                )
            return results, cost
    except (httpx.HTTPError, ValueError) as exc:
        raise TavilyUnavailable("Tavily search unavailable; no retry") from exc
