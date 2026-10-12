"""Regression tests for Qarm's private browser session."""
import time
from unittest.mock import patch

from starlette.requests import Request

from free_claude_code.api.qarm_admin_session import (
    COOKIE_NAME,
    new_cookie,
    valid_cookie,
    valid_login_password,
)


ORIGIN = "https://sample-8082.app.github.dev"


def _request(cookie: str, method: str = "GET", origin: str | None = None) -> Request:
    headers = [(b"cookie", f"{COOKIE_NAME}={cookie}".encode())]
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request(
        {"type": "http", "method": method, "path": "/admin/api/config",
         "headers": headers, "client": ("192.0.2.1", 12345),
         "server": ("127.0.0.1", 8082), "scheme": "http"}
    )


def test_session_survives_several_get_requests_and_same_origin_post():
    with patch.dict("os.environ", {
        "QARM_ADMIN_PASSWORD": "safe-password-with-24-characters",
        "QARM_ADMIN_PUBLIC_ORIGIN": ORIGIN,
    }):
        token = new_cookie(ORIGIN)
        assert valid_cookie(_request(token))
        assert valid_cookie(_request(token))
        assert valid_cookie(_request(token, "POST", ORIGIN))
        assert not valid_cookie(_request(token, "POST"))
        assert not valid_cookie(_request(token, "POST", "https://other.example"))


def test_session_rejected_after_password_change():
    with patch.dict("os.environ", {
        "QARM_ADMIN_PASSWORD": "safe-password-with-24-characters",
        "QARM_ADMIN_PUBLIC_ORIGIN": ORIGIN,
    }):
        token = new_cookie(ORIGIN)
    with patch.dict("os.environ", {
        "QARM_ADMIN_PASSWORD": "another-safe-password-of-24",
        "QARM_ADMIN_PUBLIC_ORIGIN": ORIGIN,
    }):
        assert not valid_cookie(_request(token))


def test_short_password_disabled():
    with patch.dict("os.environ", {
        "QARM_ADMIN_PASSWORD": "too-short",
        "QARM_ADMIN_PUBLIC_ORIGIN": ORIGIN,
    }):
        assert not valid_login_password("too-short")


def test_other_site_cookie_not_accepted():
    with patch.dict("os.environ", {
        "QARM_ADMIN_PASSWORD": "safe-password-with-24-characters",
        "QARM_ADMIN_PUBLIC_ORIGIN": ORIGIN,
    }):
        token = new_cookie(ORIGIN)
    with patch.dict("os.environ", {
        "QARM_ADMIN_PASSWORD": "safe-password-with-24-characters",
        "QARM_ADMIN_PUBLIC_ORIGIN": "https://other-8082.app.github.dev",
    }):
        assert not valid_cookie(_request(token))
