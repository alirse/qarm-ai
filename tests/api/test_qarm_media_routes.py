"""Private Qarm media gallery tests: no remote GPU, keys or network calls."""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.requests import Request

from free_claude_code.api.qarm_image_contracts import (
    FLUX_MODEL_ID,
    JUGGERNAUT_MODEL_ID,
    REALVIS_MODEL_ID,
    QarmImagePlanRequest,
)
from free_claude_code.api.qarm_image_engine import QarmImageRequest
from free_claude_code.api.qarm_media_routes import (
    list_qarm_image_models,
    prepare_qarm_image,
    qarm_image_gallery,
    qarm_media_catalog,
    router,
    simulate_qarm_image,
)


def _request(
    host: str, client: str, path: str = "/admin/api/qarm/media/models"
) -> Request:
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
    assert len(router.routes) == 4
    assert {route.path: route.methods for route in router.routes} == {
        "/admin/api/qarm/media/models": {"GET"},
        "/admin/qarm/images": {"GET"},
        "/admin/api/qarm/media/mock": {"POST"},
        "/admin/api/qarm/media/prepare": {"POST"},
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


def test_mock_pipeline_works_offline_with_unmistakable_watermark(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    model = qarm_media_catalog()["models"][0]["id"]
    request = _request("127.0.0.1:8000", "127.0.0.1")
    result = simulate_qarm_image(
        QarmImageRequest(model_id=model, prompt="A sunny garden"), request
    )
    assert result["status"] == "mock_completed"
    assert result["model_id"] == model
    assert result["actual_generation"] is False
    assert result["external_requests"] == 0
    assert result["gpu_minutes_consumed"] == 0
    assert result["estimated_cost_usd"] == 0
    import base64

    svg = base64.b64decode(result["result_data_uri"].split(",", 1)[1])
    assert b"QARM MOCK" in svg
    assert b"NO REAL IMAGE GENERATED" in svg
    assert b"A sunny garden" not in svg


def test_mock_blocks_unknown_model_and_extra_paid_flags(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    request = _request("127.0.0.1:8000", "127.0.0.1")
    with pytest.raises(HTTPException) as exc:
        simulate_qarm_image(
            QarmImageRequest(model_id="paid/provider", prompt="Test"), request
        )
    assert exc.value.status_code == 422

    with pytest.raises(ValidationError):
        QarmImageRequest(
            model_id=qarm_media_catalog()["models"][0]["id"], prompt="Test", paid=True
        )
    with pytest.raises(ValidationError):
        QarmImageRequest(model_id=qarm_media_catalog()["models"][0]["id"], prompt="  ")


def test_mock_rejects_untrusted_client(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    request = _request("public.example", "192.0.2.10")
    with pytest.raises(HTTPException) as exc:
        simulate_qarm_image(
            QarmImageRequest(
                model_id=qarm_media_catalog()["models"][0]["id"], prompt="Test"
            ),
            request,
        )
    assert exc.value.status_code == 403


def test_prepare_flux_positional_api_without_any_inference(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    payload = QarmImagePlanRequest(
        model_id=FLUX_MODEL_ID,
        prompt="Golden desert sunrise",
        width=768,
        height=512,
        steps=4,
        seed=42,
    )
    plan = prepare_qarm_image(payload, _request("127.0.0.1:8000", "127.0.0.1"))
    assert plan["space_id"] == "black-forest-labs/FLUX.1-schnell"
    assert plan["api_name"] == "/infer"
    assert plan["args"] == ["Golden desert sunrise", 42, False, 768, 512, 4]
    assert plan["contract_complete"] is True
    assert plan["generation_allowed"] is False
    assert plan["submitted"] is False
    assert plan["quota_verified"] is False
    assert plan["external_requests"] == 0
    assert plan["billing_enabled"] is False
    assert plan["maximum_spend_usd"] == 0


@pytest.mark.parametrize("model_id", [REALVIS_MODEL_ID, JUGGERNAUT_MODEL_ID])
def test_prepare_does_not_invent_unknown_dropdown_choices(model_id, monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    plan = prepare_qarm_image(
        QarmImagePlanRequest(model_id=model_id, prompt="A studio portrait"),
        _request("127.0.0.1:8000", "127.0.0.1"),
    )
    assert plan["contract_complete"] is False
    assert plan["args"] is None
    assert plan["submitted"] is False
    assert plan["external_requests"] == 0


def test_prepare_blocks_paid_overrides_invalid_dimensions_and_unknown_models(
    monkeypatch,
):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        QarmImagePlanRequest(model_id=FLUX_MODEL_ID, prompt="Test", paid=True)
    with pytest.raises(ValidationError):
        QarmImagePlanRequest(model_id=FLUX_MODEL_ID, prompt="Test", width=769)
    with pytest.raises(ValidationError):
        QarmImagePlanRequest(model_id=FLUX_MODEL_ID, prompt=" ", steps=0)

    with pytest.raises(HTTPException) as exc:
        prepare_qarm_image(
            QarmImagePlanRequest(model_id="untrusted/model", prompt="Test"),
            _request("127.0.0.1:8000", "127.0.0.1"),
        )
    assert exc.value.status_code == 422


def test_prepare_denies_untrusted_client(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    with pytest.raises(HTTPException) as exc:
        prepare_qarm_image(
            QarmImagePlanRequest(model_id=FLUX_MODEL_ID, prompt="Test"),
            _request("public.example", "192.0.2.10"),
        )
    assert exc.value.status_code == 403


def test_gallery_displays_non_sending_preflight_ui(monkeypatch):
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    page = qarm_image_gallery(
        _request("127.0.0.1:8000", "127.0.0.1", path="/admin/qarm/images")
    )
    html = page.body.decode("utf-8")
    assert 'id="prepareButton"' in html
    assert "/admin/api/qarm/media/prepare" in html
    assert "plan.submitted !== false" in html
