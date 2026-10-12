"""Fixed-origin ZeroGPU generation, download limits and no paid fallback."""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from free_claude_code.api import qarm_hf_routes as hf
from tests.api.support import create_test_app

MODEL = "black-forest-labs/FLUX.1-schnell"
HOST = "black-forest-labs-flux-1-schnell.hf.space"
IMAGE = b"RIFF" + bytes(4) + b"WEBP" + b"test-image"


def mock_space(request, *, hardware="zero-a10g", output_host=HOST):
    path = request.url.path
    if path.startswith("/api/spaces/"):
        return httpx.Response(
            200,
            json={
                "host": "https://" + HOST,
                "runtime": {"stage": "RUNNING", "hardware": {"current": hardware}},
            },
        )
    if path == "/config":
        return httpx.Response(
            200,
            json={"dependencies": [{"api_name": "infer", "inputs": list(range(6))}]},
        )
    if request.method == "POST":
        assert set(json.loads(request.content)) == {"data"}
        assert "authorization" not in request.headers
        return httpx.Response(200, json={"event_id": "evt_test"})
    if path.endswith("evt_test"):
        data = [
            {"url": "https://" + output_host + "/gradio_api/file=/tmp/test.webp"},
            0,
        ]
        return httpx.Response(
            200, content="event: complete\ndata: " + json.dumps(data) + "\n\n"
        )
    return httpx.Response(200, content=IMAGE)


@pytest.mark.asyncio
async def test_one_post_generates_real_file_at_authenticated_local_url(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(hf, "_root", lambda: tmp_path)
    calls = []

    def handle(request):
        calls.append(request)
        return mock_space(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        result = await hf.generate_free_image(
            hf.LiveImageRequest(model_id=MODEL, prompt="A sunny garden"), client
        )
    assert result["actual_generation"] is True
    assert result["billing_enabled"] is False
    assert sum(r.method == "POST" for r in calls) == 1
    assert (tmp_path / result["image_url"].split("/")[-1]).read_bytes() == IMAGE


@pytest.mark.asyncio
@pytest.mark.parametrize("hardware", ["a10g-small", "cpu-basic", "", "t4-small"])
async def test_no_generation_post_when_zerogpu_is_not_verified(hardware):
    calls = []

    def handle(request):
        calls.append(request)
        return mock_space(request, hardware=hardware)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(HTTPException) as error:
            await hf.generate_free_image(
                hf.LiveImageRequest(model_id=MODEL, prompt="Test"), client
            )
    assert error.value.status_code == 503
    assert all(r.method == "GET" for r in calls)


@pytest.mark.asyncio
async def test_untrusted_result_url_is_never_downloaded():
    calls = []

    def handle(request):
        calls.append(request)
        return mock_space(request, output_host="127.0.0.1")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
        with pytest.raises(ValueError):
            await hf.generate_free_image(
                hf.LiveImageRequest(model_id=MODEL, prompt="Test"), client
            )
    assert all(r.url.host in {"huggingface.co", HOST} for r in calls)


def test_owner_auth_and_duplicate_generation_request(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    identifier = str(uuid4())
    payload = {"model_id": MODEL, "prompt": "Test", "request_id": identifier}
    with TestClient(create_test_app(), base_url="https://untrusted.example") as client:
        assert (
            client.post("/admin/api/qarm/images/generate", json=payload).status_code
            == 403
        )
        assert (
            client.get(
                "/admin/api/qarm/images/files/" + str(uuid4()) + ".webp"
            ).status_code
            == 403
        )
    with (
        patch.object(
            hf,
            "generate_free_image",
            AsyncMock(return_value={"actual_generation": True, "status": "completed"}),
        ) as generate,
        TestClient(
            create_test_app(), base_url="http://localhost", client=("127.0.0.1", 4000)
        ) as client,
    ):
        assert (
            client.post("/admin/api/qarm/images/generate", json=payload).status_code
            == 200
        )
        assert (
            client.post("/admin/api/qarm/images/generate", json=payload).status_code
            == 200
        )
        assert generate.await_count == 1


@pytest.mark.asyncio
async def test_gallery_result_shape_is_supported():
    result = [
        [
            {
                "image": {"url": "https://" + HOST + "/gradio_api/file=/tmp/test.webp"},
                "caption": None,
            }
        ],
        0,
    ]
    assert hf._download_url(result, HOST).startswith("https://" + HOST)


@pytest.mark.asyncio
async def test_duplicate_cache_is_not_a_generation_quota(monkeypatch):
    cache = {uuid4(): {"status": "completed"} for _ in range(256)}
    monkeypatch.setattr(hf, "_requests", cache)
    generate = AsyncMock(return_value={"actual_generation": True})
    monkeypatch.setattr(hf, "generate_free_image", generate)
    payload = hf.LiveImageRequest(model_id=MODEL, prompt="A new image")
    result = await hf.create_image(payload)
    assert result["actual_generation"] is True
    assert generate.await_count == 1
    assert len(cache) == 256
    assert payload.request_id in cache
