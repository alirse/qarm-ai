#!/usr/bin/env python3
"""One harmless anonymous live GET test of Qarm's existing DuckDuckGo engine.

No credentials, no search API plan, no LLM, no POST, no retry, no web page
fetches. Only an explicitly fixed public-information test query is sent.
"""

import asyncio
from urllib.parse import urlsplit

from free_claude_code.runtime.web_tools.client import HTTPWebToolsClient

QUERY = "site:sama.gov.sa Saudi Central Bank regulations"


async def main() -> int:
    print("QARM LIVE WEB SEARCH — one public anonymous GET, zero API keys.")
    print("Query:", QUERY)
    try:
        results = await asyncio.wait_for(HTTPWebToolsClient().search(QUERY), timeout=25)
    except Exception as exc:
        print("Live search unavailable:", type(exc).__name__)
        return 2
    safe = [
        result
        for result in results
        if urlsplit(result.url).scheme in {"https", "http"}
        and (urlsplit(result.url).hostname or "").endswith("sama.gov.sa")
    ]
    print(f"Results returned: {len(results)}; Saudi Central Bank domain matches: {len(safe)}")
    for result in safe[:4]:
        print("SOURCE:", result.title[:150], result.url[:250])
    if not safe:
        print("No matching result: engine may be blocked or source results may differ.")
        return 3
    print("LIVE SEARCH VERIFIED: results with source links, no paid search used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
