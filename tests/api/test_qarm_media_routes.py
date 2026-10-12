"""Private Qarm media gallery tests: no remote GPU, keys or network calls."""

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from free_claude_code.api.qarm_media_routes import (
    list_qarm_image_models,
    qarm_image_gallery,
    qarm_media_catalog,
    router,
)


def _request(host: str, client: str, path: str = "/admin/api/qarm/media/models") -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [(b"host", host.encode())],
            "server": ("127.0.0.1", 8000),
            "client": (client, 12345),
            "scheme": "http",
        }
    )


def test_catalog_never_enables_generation_or_billing():
    data = qarm_media_catalog()
    assert data["generation_available"] is False
    assert data["billing_enabled"] is False
    assert data["default_spend_limit_usd"] == 0
    assert data["network_calls_made"] is False
    assert len(data["models"]) == 3
    assert {item["api_path"] for item in data["models"]} == {
        "/run/infer",
        "/run/generate",
        "/run/run",
    }
    assert all(item["integration_status"] == "not_connected" for item in data["models"])
    assert all(item["api_call_tested"] is False for item in data["models"])


def test_routes_are_get_only_without_generation_or_write_operations():
    assert len(router.routes) == 2
    assert {
        route.path: route.methods
        for route in router.routes
    } == {
        "/admin/api/qarm/media/models": {"GET"},
        "/admin/qarm/images": {"GET"},
    }


def test_catalog_allows_existing_loopback_owner_only(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    result = list_qarm_image_models(_request("127.0.0.1:8000", "127.0.0.1"))
    assert len(result["models"]) == 3


def test_catalog_denies_untrusted_client(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc:
        list_qarm_image_models(_request("public.example", "192.0.2.10"))
    assert exc.value.status_code == 403


def test_gallery_has_clear_zero_cost_no_inference_messaging(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    page = qarm_image_gallery(
        _request("127.0.0.1:8000", "127.0.0.1", path="/admin/qarm/images")
    )
    content = page.body.decode("utf-8")
    assert "قرم" in content
    assert "/admin/api/qarm/media/models" in content
    assert "generation_available" in content
    assert "billing_enabled" in content
    assert "0 دولار" in content
    assert page.headers["Cache-Control"] == "no-store"
    assert page.headers["Referrer-Policy"] == "no-referrer"


def test_gallery_denies_untrusted_client(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc:
        qarm_image_gallery(
            _request("public.example", "192.0.2.10", path="/admin/qarm/images")
        )
    assert exc.value.status_code == 403
