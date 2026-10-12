"""Codespaces owner-login bootstrap regression checks: no network or model calls."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException, Response
from starlette.requests import Request

from free_claude_code.api.admin_routes import QarmLoginPayload, qarm_login
from free_claude_code.api.admin_security import require_loopback_admin
from free_claude_code.cli import commands
from free_claude_code.cli.qarm_codespaces_access import (
    _get_or_create_owner_password,
    owner_password_file,
    prepare_codespaces_owner_login,
)



@pytest.fixture(autouse=True)
def isolate_owner_login_process_environment():
    """The bootstrap intentionally sets os.environ; never leak it across tests."""
    keys = (
        "QARM_ADMIN_PASSWORD",
        "QARM_ADMIN_PUBLIC_ORIGIN",
        "CODESPACES",
        "CODESPACE_NAME",
        "HOME",
    )
    original = {key: os.environ.get(key) for key in keys}
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _setup(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CODESPACES", "true")
    monkeypatch.setenv("CODESPACE_NAME", "friendly-qarm-abcdef")
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("QARM_ADMIN_PUBLIC_ORIGIN", raising=False)
    return "https://friendly-qarm-abcdef-8082.app.github.dev"


def _http_request(origin: str, path: str, method: str, cookie: str = ""):
    headers = [
        (b"host", origin.removeprefix("https://").encode()),
        (b"x-forwarded-proto", b"https"),
    ]
    if method == "POST":
        headers.append((b"origin", origin.encode()))
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "client": ("10.1.2.3", 51111),
            "server": ("127.0.0.1", 8082),
            "scheme": "http",
        }
    )


def test_codespaces_first_launch_generates_persistent_private_secret(
    monkeypatch, tmp_path
):
    origin = _setup(monkeypatch, tmp_path)
    assert prepare_codespaces_owner_login(8082) == origin + "/admin/login"
    password = os.environ["QARM_ADMIN_PASSWORD"]
    assert len(password) >= 40
    assert os.environ["QARM_ADMIN_PUBLIC_ORIGIN"] == origin
    path = owner_password_file()
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert path.read_text().strip() == password
    assert not str(path).startswith(str(Path.cwd()))
    assert _get_or_create_owner_password(path) == password

    monkeypatch.delenv("QARM_ADMIN_PASSWORD")
    monkeypatch.delenv("QARM_ADMIN_PUBLIC_ORIGIN")
    assert prepare_codespaces_owner_login(8082) == origin + "/admin/login"
    assert os.environ["QARM_ADMIN_PASSWORD"] == password


def test_remote_login_is_protected_even_when_port_is_public(monkeypatch, tmp_path):
    origin = _setup(monkeypatch, tmp_path)
    prepare_codespaces_owner_login(8082)
    password = os.environ["QARM_ADMIN_PASSWORD"]

    with pytest.raises(HTTPException) as unauthenticated:
        require_loopback_admin(_http_request(origin, "/admin", "GET"))
    assert unauthenticated.value.status_code == 307
    assert unauthenticated.value.headers["Location"] == "/admin/login"

    response = Response()
    payload = QarmLoginPayload(password=password)
    assert qarm_login(
        payload, _http_request(origin, "/admin/api/qarm-login", "POST"), response
    ) == {"ok": True}
    cookie = response.headers["set-cookie"].split(";", 1)[0]
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "secure" in response.headers["set-cookie"].lower()
    require_loopback_admin(_http_request(origin, "/admin", "GET", cookie))

    with pytest.raises(HTTPException) as wrong_password:
        qarm_login(
            QarmLoginPayload(password="incorrect-secret"),
            _http_request(origin, "/admin/api/qarm-login", "POST"),
            Response(),
        )
    assert wrong_password.value.status_code == 401

    foreign = "https://attacker-8082.app.github.dev"
    with pytest.raises(HTTPException) as foreign_origin:
        qarm_login(
            payload, _http_request(foreign, "/admin/api/qarm-login", "POST"), Response()
        )
    assert foreign_origin.value.status_code == 403
    with pytest.raises(HTTPException) as foreign_write:
        require_loopback_admin(
            _http_request(foreign, "/admin/api/config", "POST", cookie)
        )
    assert foreign_write.value.status_code == 401


def test_non_codespaces_never_creates_a_secret_or_modifies_environment(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CODESPACES", raising=False)
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("QARM_ADMIN_PUBLIC_ORIGIN", raising=False)
    assert prepare_codespaces_owner_login(8082) is None
    assert not owner_password_file().exists()
    assert "QARM_ADMIN_PASSWORD" not in os.environ
    assert "QARM_ADMIN_PUBLIC_ORIGIN" not in os.environ


@pytest.mark.parametrize(
    ("name", "port"),
    [
        ("", 8082),
        ("name.not.allowed", 8082),
        ("name/other", 8082),
        ("-bad", 8082),
        ("friendly-qarm", 0),
        ("friendly-qarm", 65536),
    ],
)
def test_invalid_codespaces_identity_does_not_create_credentials(
    monkeypatch, tmp_path, name, port
):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("CODESPACE_NAME", name)
    with pytest.raises(ValueError):
        prepare_codespaces_owner_login(port)
    assert not owner_password_file().exists()


def test_secret_symlink_and_weak_permissions_fail_closed(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    path = owner_password_file()
    path.parent.mkdir(mode=0o700, parents=True)
    outside = tmp_path / "unrelated.txt"
    outside.write_text("do-not-touch", encoding="utf-8")
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        prepare_codespaces_owner_login(8082)
    assert outside.read_text(encoding="utf-8") == "do-not-touch"
    path.unlink()
    path.write_text("stronger-than-20-character-test-password", encoding="utf-8")
    path.chmod(0o644)
    with pytest.raises(ValueError):
        prepare_codespaces_owner_login(8082)


def test_explicit_operator_credentials_are_preserved(monkeypatch, tmp_path):
    origin = _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "operator-created-password-at-least-20")
    monkeypatch.setenv("QARM_ADMIN_PUBLIC_ORIGIN", origin)
    assert prepare_codespaces_owner_login(8082) == origin + "/admin/login"
    assert os.environ["QARM_ADMIN_PASSWORD"] == "operator-created-password-at-least-20"
    assert not owner_password_file().exists()
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "short")
    with pytest.raises(ValueError):
        prepare_codespaces_owner_login(8082)
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "operator-created-password-at-least-20")
    monkeypatch.setenv("QARM_ADMIN_PUBLIC_ORIGIN", "http://unsafe.example")
    with pytest.raises(ValueError):
        prepare_codespaces_owner_login(8082)


def test_server_entrypoint_invokes_codespaces_bootstrap_once(monkeypatch, tmp_path):
    origin = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(commands, "get_settings", lambda: SimpleNamespace(port=8082))
    run_calls = []
    monkeypatch.setattr(
        commands.ServerSupervisor, "run", lambda self: run_calls.append(True)
    )
    commands.serve()
    assert run_calls == [True]
    assert os.environ["QARM_ADMIN_PUBLIC_ORIGIN"] == origin
    assert owner_password_file().is_file()
