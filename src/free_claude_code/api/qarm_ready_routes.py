"""Owner-only Qarm readiness page: passive browser diagnostics only.

The page calls existing protected GET status endpoints from the owner's browser.
It does not submit auth codes, test inference, spend credits, or read credentials.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from .admin_security import require_loopback_admin

router = APIRouter()
_READY_PAGE = Path(__file__).resolve().parent / "admin_static" / "qarm_ready.html"


@router.get("/admin/qarm/ready", response_class=HTMLResponse, include_in_schema=False)
def qarm_readiness_page(request: Request) -> HTMLResponse:
    require_loopback_admin(request)
    return HTMLResponse(
        _READY_PAGE.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "img-src 'none'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'"
            ),
        },
    )
