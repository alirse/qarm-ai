"""Qarm remote admin gate regression checks. No secrets or network calls."""
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from free_claude_code.api.admin_security import require_loopback_admin


def request(*, host: str, client: str, authorization: str = "", origin: str | None = None, method: str = "GET", proto: str = "https", referer: str | None = None, path: str = "/admin"):
    headers = [(b"host", host.encode()), (b"x-forwarded-proto", proto.encode())]
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    if referer is not None:
        headers.append((b"referer", referer.encode()))
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "client": (client, 1234), "scheme": "http", "server": ("127.0.0.1", 8000)})


def credentials(password: str = "a-strong-test-password-123456") -> str:
    import base64
    return "Basic " + base64.b64encode(f"qarm:{password}".encode()).decode()


def status(request_obj: Request) -> int:
    try:
        require_loopback_admin(request_obj)
    except HTTPException as exc:
        return exc.status_code
    return 200


def test_local_access_unchanged():
    assert status(request(host="127.0.0.1:8000", client="127.0.0.1", proto="http")) == 200


def test_remote_off_by_default(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    assert status(request(host="abc-8000.app.github.dev", client="10.0.0.1", authorization=credentials())) == 403


def test_remote_requires_password_and_https(monkeypatch):
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "a-strong-test-password-123456")
    host = "abc-8000.app.github.dev"
    # The HTML admin page intentionally redirects unauthenticated GETs to login.
    assert status(request(host=host, client="10.0.0.1")) == 307
    assert status(request(host=host, client="10.0.0.1", authorization=credentials("wrong-password"))) == 307
    assert status(request(host=host, client="10.0.0.1", authorization=credentials())) == 200
    assert status(request(host=host, client="10.0.0.1", authorization=credentials(), proto="http")) == 307

    # Admin APIs must still deny access, never redirect unauthorized writes/reads.
    path = "/admin/api/config"
    assert status(request(host=host, client="10.0.0.1", path=path)) == 401
    assert status(request(host=host, client="10.0.0.1", authorization=credentials("wrong-password"), path=path)) == 401
    assert status(request(host=host, client="10.0.0.1", authorization=credentials(), proto="http", path=path)) == 401
    assert status(request(host="attacker.test", client="10.0.0.1", authorization=credentials(), path=path)) == 401


def test_remote_cross_origin_write_denied(monkeypatch):
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "a-strong-test-password-123456")
    host = "abc-8000.app.github.dev"
    assert status(request(host=host, client="10.0.0.1", authorization=credentials(), method="POST")) == 401
    assert status(request(host=host, client="10.0.0.1", authorization=credentials(), method="POST", origin="https://evil.example")) == 401
    assert status(request(host=host, client="10.0.0.1", authorization=credentials(), method="POST", origin=f"https://{host}")) == 200
