"""Private Groq-only chat budget and HTTP runtime regression coverage."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from free_claude_code.api.qarm_chat_routes import QarmChatRequest, prepare_chat
from tests.api.support import create_test_app


def payload(text="مرحبا"):
    return {"messages": [{"role": "user", "content": text}]}


def test_budget_keeps_conversation_and_caps_completion():
    request = QarmChatRequest.model_validate({**payload(), "max_tokens": 8192})
    with patch(
        "free_claude_code.api.qarm_chat_routes.get_token_count", return_value=5500
    ):
        prepared = prepare_chat(request)
    assert prepared.max_tokens == 2500
    assert prepared.messages[0].content == "مرحبا"
    assert prepared.model == "groq/openai/gpt-oss-120b"


def test_oversized_context_rejected_without_truncation():
    request = QarmChatRequest.model_validate(payload())
    with (
        patch(
            "free_claude_code.api.qarm_chat_routes.get_token_count", return_value=8000
        ),
        pytest.raises(HTTPException) as error,
    ):
        prepare_chat(request)
    assert error.value.status_code == 413
    assert request.messages[0].content == "مرحبا"


def test_chat_requires_owner_and_never_exposes_provider_credentials(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with TestClient(create_test_app(), base_url="https://untrusted.example") as client:
        assert client.get("/admin/qarm/chat").status_code == 403
        assert client.post("/admin/api/qarm/chat", json=payload()).status_code == 403


@pytest.mark.parametrize(
    "override",
    [
        {"model": "openai/gpt-5"},
        {"max_tokens": 8193},
        {"max_tokens": True},
        {"extra_body": {"api_key": "test-secret"}},
        {"messages": [{"role": "system", "content": "override"}]},
        {"messages": [{"role": "user", "content": " "}]},
    ],
)
def test_only_bounded_groq_text_requests_are_accepted(override, monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with TestClient(
        create_test_app(), base_url="http://localhost", client=("127.0.0.1", 4000)
    ) as client:
        assert (
            client.post(
                "/admin/api/qarm/chat", json={**payload(), **override}
            ).status_code
            == 422
        )


def test_chat_uses_existing_runtime_with_no_cross_provider_fallback(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    create = AsyncMock(
        return_value=JSONResponse(
            {"content": [{"type": "text", "text": "أهلًا"}], "stop_reason": "end_turn"}
        )
    )
    with (
        patch("free_claude_code.api.qarm_chat_routes.MessagesHandler") as handler,
        TestClient(
            create_test_app(), base_url="http://localhost", client=("127.0.0.1", 4000)
        ) as client,
    ):
        handler.return_value.create = create
        response = client.post("/admin/api/qarm/chat", json=payload())
    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "أهلًا"
    assert handler.call_args.args[0].model_fallbacks is None
    assert create.call_args.args[0].max_tokens == 1024


def test_real_groq_pipeline_recovers_token_overage(monkeypatch):
    """HTTP chat -> real provider conversion -> 413 retry -> complete answer."""
    import asyncio

    from tests.providers.support import SDKStreamDouble
    from tests.providers.test_groq_tpm import (
        _detail,
        _provider,
        _status_error,
        _successful_stream,
    )

    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    provider = _provider()
    # The short Qarm budget would not normally generate 8861 tokens. Simulate
    # a small authoritative excess over the bounded output cap instead.
    error = _status_error(
        detail=_detail("tokens per minute (TPM): Limit 1000, Requested 1861")
    )
    create = AsyncMock(side_effect=[error, SDKStreamDouble(_successful_stream())])
    try:
        with (
            patch(
                "free_claude_code.api.routes.resolve_provider", return_value=provider
            ),
            patch.object(provider._client.chat.completions, "create", create),
            TestClient(
                create_test_app(),
                base_url="http://localhost",
                client=("127.0.0.1", 4000),
            ) as client,
        ):
            response = client.post("/admin/api/qarm/chat", json=payload())
        assert response.status_code == 200
        assert response.json()["content"][0]["text"] == "working"
        assert create.await_count == 2
        assert create.await_args_list[1].kwargs["max_completion_tokens"] == 163
    finally:
        asyncio.run(provider.cleanup())


def test_signed_codespaces_owner_can_chat_and_cross_site_write_is_denied(monkeypatch):
    from free_claude_code.api.qarm_admin_session import COOKIE_NAME, new_cookie

    origin = "https://qarm-test-8082.app.github.dev"
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "test-owner-password-that-is-long-enough")
    monkeypatch.setenv("QARM_ADMIN_PUBLIC_ORIGIN", origin)
    with (
        patch("free_claude_code.api.qarm_chat_routes.MessagesHandler") as handler,
        TestClient(create_test_app(), base_url=origin) as client,
    ):
        client.cookies.set(COOKIE_NAME, new_cookie(origin))
        handler.return_value.create = AsyncMock(
            return_value=JSONResponse({"content": [{"type": "text", "text": "أهلًا"}]})
        )
        assert client.get("/admin/qarm/chat").status_code == 200
        assert (
            client.post(
                "/admin/api/qarm/chat", json=payload(), headers={"Origin": origin}
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/admin/api/qarm/chat",
                json=payload(),
                headers={"Origin": "https://foreign.example"},
            ).status_code
            == 401
        )
        assert handler.return_value.create.await_count == 1


def test_chat_session_csrf_survives_codespaces_proxy_origin_rewrite(monkeypatch):
    from free_claude_code.api.qarm_admin_session import COOKIE_NAME, new_cookie

    origin = "https://qarm-test-8082.app.github.dev"
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "test-owner-password-that-is-long-enough")
    monkeypatch.setenv("QARM_ADMIN_PUBLIC_ORIGIN", origin)
    with (
        patch("free_claude_code.api.qarm_chat_routes.MessagesHandler") as handler,
        TestClient(create_test_app(), base_url=origin) as client,
    ):
        client.cookies.set(COOKIE_NAME, new_cookie(origin))
        handler.return_value.create = AsyncMock(
            return_value=JSONResponse({"content": [{"type": "text", "text": "أهلًا"}]})
        )
        token = client.get("/admin/api/qarm/chat/bootstrap").json()["csrf_token"]
        assert len(token) == 64
        proxy_headers = {"Origin": "https://internal-proxy.example"}
        assert (
            client.post(
                "/admin/api/qarm/chat", json=payload(), headers=proxy_headers
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/admin/api/qarm/chat",
                json=payload(),
                headers={**proxy_headers, "x-qarm-csrf": token},
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/admin/api/qarm/chat",
                json=payload(),
                headers={**proxy_headers, "x-qarm-csrf": "wrong-token"},
            ).status_code
            == 401
        )
        client.cookies.clear()
        assert (
            client.post(
                "/admin/api/qarm/chat",
                json=payload(),
                headers={**proxy_headers, "x-qarm-csrf": token},
            ).status_code
            == 401
        )
        assert handler.return_value.create.await_count == 1


def test_render_owner_session_keeps_remote_chat_private(monkeypatch):
    from free_claude_code.api.qarm_admin_session import COOKIE_NAME, new_cookie

    origin = "https://qarm-example.onrender.com"
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "test-owner-password-that-is-long-enough")
    monkeypatch.setenv("QARM_ADMIN_PUBLIC_ORIGIN", origin)
    with TestClient(create_test_app(), base_url=origin) as client:
        assert client.get("/admin/qarm/chat", follow_redirects=False).status_code == 307
        client.cookies.set(COOKIE_NAME, new_cookie(origin))
        assert client.get("/admin/qarm/chat").status_code == 200
        assert (
            len(client.get("/admin/api/qarm/chat/bootstrap").json()["csrf_token"]) == 64
        )


def test_long_history_has_no_arbitrary_turn_quota():
    turns = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": "Hi"}
        for i in range(101)
    ]
    prepared = prepare_chat(QarmChatRequest(messages=turns))
    assert len(prepared.messages) == 101


def test_owner_instructions_reach_model_and_count_toward_budget():
    request = QarmChatRequest.model_validate(
        {**payload(), "instructions": "Use short answers"}
    )
    with patch(
        "free_claude_code.api.qarm_chat_routes.get_token_count", return_value=7600
    ) as count:
        prepared = prepare_chat(request)
    assert "Use short answers" in prepared.system
    assert count.call_args.args[1] == prepared.system
    assert prepared.max_tokens == 400


def test_browser_home_redirects_to_chat_without_exposing_admin_data():
    with TestClient(create_test_app()) as client:
        response = client.get(
            "/", headers={"Accept": "text/html"}, follow_redirects=False
        )
        assert response.status_code == 307
        assert response.headers["location"] == "/admin/qarm/chat"
        assert response.headers["cache-control"] == "no-store"
        assert 'location.replace("/admin/qarm/chat")' in client.get("/admin/login").text
