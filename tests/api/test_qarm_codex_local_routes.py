"""Offline, no-inference safety checks for native Codex CLI bridge."""

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from free_claude_code.api import qarm_codex_local_routes as bridge


def _request(host="127.0.0.1:8082", client="127.0.0.1"):
    return Request(
        {
            "type": "http",
            "path": "/admin/qarm/codex-local",
            "method": "GET",
            "headers": [(b"host", host.encode())],
            "server": ("127.0.0.1", 8082),
            "client": (client, 4444),
            "scheme": "http",
        }
    )


def test_login_status_only_executes_local_codex_status_and_never_reads_tokens(
    monkeypatch,
):
    monkeypatch.setattr(bridge, "_binary", lambda: "/usr/local/bin/codex")
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(
            returncode=0, stdout="", stderr="Logged in using ChatGPT\n"
        )

    monkeypatch.setattr(bridge.subprocess, "run", fake_run)
    result = bridge.native_codex_status()
    assert result == {
        "login": "chatgpt",
        "ready_for_native_chat": True,
        "qarm_oauth_is_separate": True,
        "inference_performed": False,
    }
    assert len(calls) == 1
    assert calls[0][0] == ["/usr/local/bin/codex", "login", "status"]
    assert calls[0][1]["timeout"] == 8
    assert calls[0][1]["check"] is False


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Logged in using ChatGPT", "chatgpt"),
        ("Logged in using an API key", "api_key"),
        ("gibberish", "unknown"),
    ],
)
def test_status_recognizes_chatgpt_without_api_key_fallback(
    monkeypatch, message, expected
):
    monkeypatch.setattr(bridge, "_binary", lambda: "/mock/codex")
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout=message, stderr=""
        ),
    )
    assert bridge.native_codex_login_status() == expected


def test_no_cli_or_failed_cli_never_triggers_inference(monkeypatch):
    monkeypatch.setattr(bridge, "_binary", lambda: None)
    assert bridge.native_codex_login_status() == "not_installed"
    monkeypatch.setattr(bridge, "_binary", lambda: "/mock/codex")
    monkeypatch.setattr(
        bridge.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout="", stderr="not authenticated"
        ),
    )
    assert bridge.native_codex_status()["ready_for_native_chat"] is False


def test_page_is_protected_and_mentions_quota_not_unlimited(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as remote:
        bridge.require_loopback_admin(
            _request(host="public.example", client="192.0.2.40")
        )
    assert remote.value.status_code == 403

    response = bridge.native_codex_page()
    assert response.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    text = response.body.decode("utf-8")
    assert "/admin/api/qarm/codex-local/chat" in text
    assert "/admin/api/qarm/codex-local" in text
    assert "confirm_plan_usage:true" in text
    assert "confirmUsage.checked" in text
    assert "/admin/api/qarm/codex-local/preflight" in text
    assert "لا يستخدم هذا المسار مفاتيح API المدفوعة" in text
    assert "answer.textContent" in text


def test_explicit_consent_required_at_api_boundary():
    with pytest.raises(ValidationError):
        bridge.NativeCodexPrompt.model_validate({"prompt": "Hello"})
    with pytest.raises(ValidationError):
        bridge.NativeCodexPrompt.model_validate(
            {"prompt": "Hello", "confirm_plan_usage": False}
        )
    assert (
        bridge.NativeCodexPrompt(prompt="Hello", confirm_plan_usage=True).prompt
        == "Hello"
    )


@pytest.mark.asyncio
async def test_chat_uses_native_chatgpt_login_no_api_key_and_read_only(monkeypatch):
    monkeypatch.setattr(bridge, "native_codex_login_status", lambda: "chatgpt")
    monkeypatch.setattr(bridge, "_binary", lambda: "/mock/codex")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_ACCESS_TOKEN", "must-not-leak")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://paid.example")
    calls = []

    class FakeProcess:
        returncode = 0

        async def communicate(self, message):
            calls.append(("prompt", message))
            return (
                (
                    json.dumps(
                        {
                            "type": "item.completed",
                            "item": {"type": "agent_message", "text": "تم الرد"},
                        }
                    )
                    + "\n"
                ).encode(),
                b"",
            )

    async def fake_spawn(*args, **kwargs):
        calls.append(("spawn", args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(bridge.asyncio, "create_subprocess_exec", fake_spawn)
    result = await bridge.native_codex_chat(
        bridge.NativeCodexPrompt(prompt="مرحبا", confirm_plan_usage=True)
    )
    assert result == {"answer": "تم الرد", "provider": "native_codex_chatgpt"}
    cmd = calls[0][1]
    env = calls[0][2]["env"]
    assert cmd[:4] == ("/mock/codex", "exec", "--json", "--sandbox")
    assert "read-only" in cmd
    assert 'model_provider="openai"' in cmd
    assert "--full-auto" not in cmd
    assert "workspace-write" not in cmd
    assert "-C" in cmd
    assert "-c" in cmd
    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env
    assert "CODEX_ACCESS_TOKEN" not in env
    assert "OPENAI_BASE_URL" not in env
    assert ("prompt", "مرحبا".encode()) in calls


@pytest.mark.asyncio
async def test_no_request_when_api_key_login_or_not_connected(monkeypatch):
    monkeypatch.setattr(bridge, "native_codex_login_status", lambda: "api_key")

    async def must_not_spawn(*a, **kw):
        pytest.fail("No model call permitted for paid API-key login")

    monkeypatch.setattr(bridge.asyncio, "create_subprocess_exec", must_not_spawn)
    with pytest.raises(HTTPException) as exc:
        await bridge.native_codex_chat(
            bridge.NativeCodexPrompt(prompt="Hello", confirm_plan_usage=True)
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_failure_does_not_expose_native_stderr_or_api_tokens(monkeypatch):
    monkeypatch.setattr(bridge, "native_codex_login_status", lambda: "chatgpt")
    monkeypatch.setattr(bridge, "_binary", lambda: "/mock/codex")

    class FakeProcess:
        returncode = 1

        async def communicate(self, prompt):
            return b"", b"SECRET-LIVE-TOKEN"

    async def fake_spawn(*a, **kw):
        return FakeProcess()

    monkeypatch.setattr(bridge.asyncio, "create_subprocess_exec", fake_spawn)
    with pytest.raises(HTTPException) as exc:
        await bridge.native_codex_chat(
            bridge.NativeCodexPrompt(prompt="Hello", confirm_plan_usage=True)
        )
    assert exc.value.status_code == 502
    assert "SECRET-LIVE-TOKEN" not in str(exc.value.detail)


def test_app_registers_native_codex_owner_routes():
    from free_claude_code.api import qarm_codex_local_routes

    assert {
        route.path: route.methods for route in qarm_codex_local_routes.router.routes
    } == {
        "/admin/api/qarm/codex-local": {"GET"},
        "/admin/qarm/codex-local": {"GET"},
        "/admin/api/qarm/codex-local/chat": {"POST"},
        "/admin/api/qarm/codex-local/preflight": {"POST"},
    }


def test_readiness_has_native_codex_link():
    from free_claude_code.api.qarm_ready_routes import _READY_PAGE

    assert "/admin/qarm/codex-local" in _READY_PAGE.read_text(encoding="utf-8")


def test_owner_write_preflight_never_calls_codex(monkeypatch):
    monkeypatch.setattr(
        bridge, "native_codex_login_status",
        lambda: pytest.fail("No Codex status or inference during owner preflight"),
    )
    assert bridge.native_codex_owner_write_preflight() == {
        "owner_write_authorized": True,
        "inference_performed": False,
    }
