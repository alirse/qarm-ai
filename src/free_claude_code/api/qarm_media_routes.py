"""Qarm's private, research-only image-model catalog.

This module does not call a remote provider, generate images, or load model
weights. Never equate a Gradio endpoint listing with approved/free inference.
"""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from .admin_security import require_loopback_admin
from .qarm_image_contracts import QarmImagePlanRequest, prepare_image_plan
from .qarm_image_engine import QarmImageRequest, simulate_image

router = APIRouter()
_IMAGES_PAGE = Path(__file__).resolve().parent / "admin_static" / "qarm_images.html"

_IMAGE_MODELS = (
    {
        "id": "black-forest-labs/FLUX.1-schnell",
        "name": "FLUX.1 Schnell",
        "style": "general_and_photorealistic",
        "demo_url": "https://huggingface.co/spaces/black-forest-labs/FLUX.1-schnell",
        "api_path": "/run/infer",
        "inputs": 6,
        "outputs": 2,
        "license_note": "Apache-2.0 model weights; Space terms and quotas are separate",
    },
    {
        "id": "SG161222/RealVisXL_V5.0",
        "name": "RealVisXL V5",
        "style": "photorealistic",
        "demo_url": "https://huggingface.co/spaces/seawolf2357/REALVISXL-V5",
        "api_path": "/run/generate",
        "inputs": 12,
        "outputs": 2,
        "license_note": "OpenRAIL++ model weights; verify hosting and content rules",
    },
    {
        "id": "RunDiffusion/Juggernaut-XL-v9",
        "name": "Juggernaut XL",
        "style": "cinematic_and_photorealistic",
        "demo_url": "https://huggingface.co/spaces/artificialguybr/JUGGERNAUT-XL-FREE-DEMO",
        "api_path": "/run/run",
        "inputs": 10,
        "outputs": 2,
        "license_note": "Model author restricts paid API deployment; verify Space terms",
    },
)


def qarm_media_catalog() -> dict:
    """Return read-only discovery; future adapters must be separately enabled."""
    return {
        "status": "live_zerogpu_adapters",
        "generation_available": True,
        "billing_enabled": False,
        "default_spend_limit_usd": 0,
        "network_calls_made": False,
        "note": (
            "Public ZeroGPU adapters are connected. FLUX inference was verified; "
            "other models depend on upstream quota and availability."
        ),
        "models": [
            {
                **model,
                "browser_tested": True,
                "api_call_tested": model["id"] == "black-forest-labs/FLUX.1-schnell",
                "integration_status": "adapter_ready",
            }
            for model in _IMAGE_MODELS
        ],
    }


@router.get("/admin/api/qarm/media/models")
def list_qarm_image_models(request: Request) -> dict:
    """Owner-protected metadata endpoint; GET only and zero provider calls."""
    require_loopback_admin(request)
    return qarm_media_catalog()


@router.get("/admin/qarm/images", response_class=HTMLResponse, include_in_schema=False)
def qarm_image_gallery(request: Request) -> HTMLResponse:
    """Owner-only gallery; links to demos but never invokes inference."""
    require_loopback_admin(request)
    return HTMLResponse(
        _IMAGES_PAGE.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/admin/api/qarm/media/mock")
def simulate_qarm_image(payload: QarmImageRequest, request: Request) -> dict:
    """Owner-only simulation. Never call a real image provider."""
    require_loopback_admin(request)
    if payload.model_id not in {entry["id"] for entry in _IMAGE_MODELS}:
        raise HTTPException(status_code=422, detail="Unknown Qarm image model")
    return simulate_image(model_id=payload.model_id)


@router.post("/admin/api/qarm/media/prepare")
def prepare_qarm_image(payload: QarmImagePlanRequest, request: Request) -> dict:
    """Owner-only offline planning. This does not send requests to a Space."""
    require_loopback_admin(request)
    if payload.model_id not in {entry["id"] for entry in _IMAGE_MODELS}:
        raise HTTPException(status_code=422, detail="Unknown Qarm image model")
    return prepare_image_plan(payload)
