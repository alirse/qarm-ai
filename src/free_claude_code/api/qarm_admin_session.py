"""Password-backed, short-lived cookie for private Qarm Codespaces administration.

The cookie is scoped to the browser's HTTPS origin. It does not change model
selection or provider rules. Keep the Codespaces forwarded port Private.
"""
import hashlib
import hmac
import os
import secrets
import time
from urllib.parse import urlsplit

from fastapi import Request

COOKIE_NAME = "qarm_admin_session"
MAX_AGE = 3600 * 8


def _password() -> str:
    return os.environ.get("QARM_ADMIN_PASSWORD", "")


def _origin_allowed(origin: str) -> bool:
    try:
        url = urlsplit(origin)
        return (
            url.scheme == "https"
            and bool(url.hostname)
            and url.hostname.endswith(".app.github.dev")
            and url.username is None
            and url.password is None
            and url.port is None
            and not url.path
            and not url.query
            and not url.fragment
        )
    except ValueError:
        return False


def _request_origin(request: Request) -> str | None:
    origin = request.headers.get("origin")
    if origin and _origin_allowed(origin):
        return origin
    referer = request.headers.get("referer", "")
    try:
        url = urlsplit(referer)
        reconstructed = f"{url.scheme}://{url.netloc}"
    except ValueError:
        return None
    return reconstructed if _origin_allowed(reconstructed) else None


def _valid_forwarded_https_origin(origin: str | None) -> bool:
    """Allow browser-observed HTTPS proxy origins only with Fetch Metadata."""
    if not origin:
        return False
    try:
        value = urlsplit(origin)
        return (
            value.scheme == "https"
            and bool(value.hostname)
            and value.username is None
            and value.password is None
            and value.port is None
            and not value.path
            and not value.query
            and not value.fragment
            and value.netloc == value.hostname
        )
    except ValueError:
        return False


def new_cookie(origin: str) -> str:
    password = _password()
    if len(password) < 12 or not _origin_allowed(origin):
        raise ValueError("Owner password and private Codespaces HTTPS origin required")
    timestamp = str(int(time.time()))
    random_id = secrets.token_hex(12)
    payload = f"{timestamp}.{random_id}.{origin}"
    key = hashlib.sha256(("qarm-admin-v1:" + password).encode()).digest()
    signature = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return f"{timestamp}.{random_id}.{signature}"


def valid_cookie(request: Request, *, check_write_origin: bool = True) -> bool:
    password = _password()
    value = request.cookies.get(COOKIE_NAME, "")
    if len(password) < 12:
        return False
    try:
        timestamp, random_id, signature = value.split(".")
        age = time.time() - int(timestamp)
        if age < 0 or age > MAX_AGE or len(random_id) != 24 or len(signature) != 64:
            return False
    except (ValueError, TypeError):
        return False
    # Recover browser origin from the Referer/Origin on writes, or the
    # configured public address on reads. These must match cookie audience.
    origin = os.environ.get("QARM_ADMIN_PUBLIC_ORIGIN", "").rstrip("/")
    if not _origin_allowed(origin):
        return False
    if check_write_origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        request_origin = _request_origin(request)
        if request_origin != origin:
            # Codespaces proxies can alter the public origin.
            # Trust browser-generated same-origin fetch metadata only.
            if not (
                _valid_forwarded_https_origin(request.headers.get("origin"))
                and request.headers.get("sec-fetch-site") == "same-origin"
                and request.headers.get("sec-fetch-mode") in {"cors", "same-origin"}
            ):
                return False
    payload = f"{timestamp}.{random_id}.{origin}"
    key = hashlib.sha256(("qarm-admin-v1:" + password).encode()).digest()
    expected = hmac.new(key, payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature, expected)


def valid_login_password(candidate: str) -> bool:
    password = _password()
    return len(password) >= 12 and hmac.compare_digest(candidate, password)
