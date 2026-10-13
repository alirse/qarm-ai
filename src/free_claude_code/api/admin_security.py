"""Admin access: local-only by default; optional password-protected Codespaces UI."""

import base64
import binascii
import hmac
import ipaddress
import os
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

from .qarm_admin_session import valid_cookie


def _is_loopback_host(host: str | None) -> bool:
    if host is None:
        return False
    normalized = host.strip().strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _origin_is_local(origin: str | None) -> bool:
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and _is_loopback_host(parsed.hostname)
    )


def _authority_is_local(authority: str | None) -> bool:
    if not authority:
        return False
    try:
        parsed = urlsplit(f"//{authority}")
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.username is None
        and parsed.password is None
        and not parsed.path
        and not parsed.query
        and not parsed.fragment
        and _is_loopback_host(parsed.hostname)
    )


def _codespaces_host(authority: str | None) -> str | None:
    """Return the HTTPS Codespaces forwarded host, rejecting spoofed authorities."""
    if not authority:
        return None
    try:
        parsed = urlsplit(f"//{authority}")
        if (
            parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.port is not None
        ):
            return None
    except ValueError:
        return None
    host = parsed.hostname
    if not host or host != host.lower() or not host.endswith(".app.github.dev"):
        return None
    prefix = host[: -len(".app.github.dev")]
    if not prefix or not all(char.isascii() and (char.isalnum() or char == "-") for char in prefix):
        return None
    return host


def _same_origin(origin: str | None, host: str) -> bool:
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        return (
            parsed.scheme == "https"
            and parsed.hostname == host
            and parsed.port is None
            and parsed.username is None
            and parsed.password is None
            and not parsed.path
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _codespaces_authenticated(request: Request) -> bool:
    host = _codespaces_host(request.headers.get("host"))
    password = os.environ.get("QARM_ADMIN_PASSWORD", "")
    if not host or len(password) < 12:
        return False
    if request.headers.get("x-forwarded-proto") != "https":
        return False
    if not _same_origin(request.headers.get("origin"), host):
        return False
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        # Protect state-changing endpoints from browser cross-site requests.
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        if origin is None and (not referer or not referer.startswith(f"https://{host}/")):
            return False
        if referer:
            try:
                ref = urlsplit(referer)
                if ref.scheme != "https" or ref.hostname != host or ref.port is not None:
                    return False
            except ValueError:
                return False
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
        username, supplied = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError, binascii.Error):
        return False
    return hmac.compare_digest(username, "qarm") and hmac.compare_digest(supplied, password)


def require_loopback_admin(request: Request) -> None:
    """Allow local Admin as before, or opt-in authenticated HTTPS Codespaces Admin."""

    client_host = request.client.host if request.client else None
    if (
        _is_loopback_host(client_host)
        and _authority_is_local(request.headers.get("host"))
        and _origin_is_local(request.headers.get("origin"))
    ):
        return
    if valid_cookie(request):
        return
    if _codespaces_authenticated(request):
        return
    # Use a dedicated login page rather than browser Basic Auth prompts.
    if request.method == "GET" and request.url.path in {
        "/admin", "/admin/qarm/chat", "/admin/model_config", "/admin/messaging", "/admin/integrations"
    } and len(os.environ.get("QARM_ADMIN_PASSWORD", "")) >= 12:
        raise HTTPException(status_code=307, headers={"Location": "/admin/login"})
    if len(os.environ.get("QARM_ADMIN_PASSWORD", "")) >= 12:
        raise HTTPException(status_code=401, detail="Qarm owner login required")
    raise HTTPException(status_code=403, detail="Admin UI is local-only")
