"""Passive Qarm readiness UI: no auth calls, model inference or expenses."""

import shutil
import subprocess
from html.parser import HTMLParser

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from free_claude_code.api.qarm_ready_routes import (
    qarm_readiness_page,
    router,
)


def _request(host="127.0.0.1:8000", client="127.0.0.1"):
    return Request(
        {
            "type": "http",
            "path": "/admin/qarm/ready",
            "method": "GET",
            "headers": [(b"host", host.encode())],
            "server": ("127.0.0.1", 8000),
            "client": (client, 4242),
            "scheme": "http",
        }
    )


def test_readiness_is_protected_and_passive_get_only(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    assert {route.path: route.methods for route in router.routes} == {
        "/admin/qarm/ready": {"GET"}
    }
    response = qarm_readiness_page(_request())
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "connect-src 'self'" in response.headers["Content-Security-Policy"]
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    with pytest.raises(HTTPException) as exc:
        qarm_readiness_page(_request(host="public.example", client="192.0.2.30"))
    assert exc.value.status_code == 403


def test_readiness_reads_only_existing_owner_status_without_secret_exposure(
    monkeypatch,
):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    html = qarm_readiness_page(_request()).body.decode("utf-8")
    for path in (
        "/admin/api/providers/openai/auth",
        "/admin/api/code/bootstrap",
        "/admin/api/models",
        "/admin/code",
    ):
        assert path in html
    assert 'credentials:"same-origin"' in html
    assert 'Promise.allSettled(paths.map(getJson))' in html
    assert 'info.connected===true' in html
    assert 'info.available===true' in html
    assert "لا يعني وجود API مجاني غير محدود" in html
    assert 'refresh.addEventListener("click",inspect)' in html
    assert 'fetch(path,{credentials:"same-origin",cache:"no-store"})' in html
    assert '"POST"' not in html
    assert 'auth/login' not in html
    assert "TAVILY_API_KEY" not in html


def test_readiness_inline_javascript_is_valid(monkeypatch):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js not installed for script syntax check")
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    html = qarm_readiness_page(_request()).body.decode("utf-8")

    class Scripts(HTMLParser):
        def __init__(self):
            super().__init__()
            self._is_script = False
            self.scripts = []

        def handle_starttag(self, tag, attrs):
            if tag == "script" and not dict(attrs).get("src"):
                self._is_script = True
                self.scripts.append("")

        def handle_endtag(self, tag):
            if tag == "script":
                self._is_script = False

        def handle_data(self, data):
            if self._is_script:
                self.scripts[-1] += data

    parser = Scripts()
    parser.feed(html)
    assert len(parser.scripts) == 1
    result = subprocess.run(
        [node, "--check", "-"],
        input=parser.scripts[0],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
