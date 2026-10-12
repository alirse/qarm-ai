"""Prepare an image provider request without executing it.

The plan is deliberately inert: no HTTP client is created, no secret is read,
no provider job is submitted, and no model weight/GPU is loaded. A public API
schema does not prove zero-cost access or permission to reuse a Space.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

FLUX_MODEL_ID = "black-forest-labs/FLUX.1-schnell"
REALVIS_MODEL_ID = "SG161222/RealVisXL_V5.0"
JUGGERNAUT_MODEL_ID = "RunDiffusion/Juggernaut-XL-v9"

_SUPPORTED = frozenset({FLUX_MODEL_ID, REALVIS_MODEL_ID, JUGGERNAUT_MODEL_ID})


class QarmImagePlanRequest(BaseModel):
    """Strict offline contract. No credentials or billable overrides."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=1200)
    width: int = Field(default=768, ge=512, le=1024, multiple_of=64)
    height: int = Field(default=768, ge=512, le=1024, multiple_of=64)
    steps: int = Field(default=4, ge=1, le=8)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must contain non-whitespace text")
        return value


def prepare_image_plan(payload: QarmImagePlanRequest) -> dict:
    """Build known positional Gradio arguments, but NEVER invoke the endpoint."""

    if payload.model_id not in _SUPPORTED:
        raise ValueError("Unknown Qarm image model")

    if payload.model_id == FLUX_MODEL_ID:
        space_id = "black-forest-labs/FLUX.1-schnell"
        api_name = "/infer"
        args = [
            payload.prompt,
            payload.seed,
            False,
            payload.width,
            payload.height,
            payload.steps,
        ]
        ready = True
        note = (
            "Six positional inputs identified via public Gradio config. "
            "A real call still requires user approval and verified free access."
        )
    elif payload.model_id == REALVIS_MODEL_ID:
        space_id = "seawolf2357/REALVISXL-V5"
        api_name = "/generate"
        args = None
        ready = False
        note = (
            "Model Selection and Quality Style choices need validation before "
            "forming the 12-argument Gradio payload. No values invented."
        )
    else:
        space_id = "artificialguybr/JUGGERNAUT-XL-FREE-DEMO"
        api_name = "/run"
        args = None
        ready = False
        note = (
            "Unnamed dropdown/radio and Sampler choices need validation before "
            "forming the 10-argument Gradio payload. No values invented."
        )

    return {
        "status": "prepared_offline",
        "model_id": payload.model_id,
        "space_id": space_id,
        "api_name": api_name,
        "args": args,
        "contract_complete": ready,
        "generation_allowed": False,
        "submitted": False,
        "external_requests": 0,
        "billing_enabled": False,
        "maximum_spend_usd": 0,
        "quota_verified": False,
        "note": note,
    }
