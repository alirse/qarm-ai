"""Prepare image provider requests without executing them.

All Gradio component choices below were read from public Space configuration on
2026-10-12. They can change. These payloads have NOT been tested in live
inference. No HTTP clients, tokens, credentials, jobs or GPU use exist here.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FLUX_MODEL_ID = "black-forest-labs/FLUX.1-schnell"
REALVIS_MODEL_ID = "SG161222/RealVisXL_V5.0"
JUGGERNAUT_MODEL_ID = "RunDiffusion/Juggernaut-XL-v9"

_SUPPORTED = frozenset({FLUX_MODEL_ID, REALVIS_MODEL_ID, JUGGERNAUT_MODEL_ID})

RealvisQuality = Literal["3840 x 2160", "2560 x 1440", "HD+", "Style Zero"]
JuggernautSampler = Literal[
    "DPM++ 2M Karras",
    "DPM++ SDE Karras",
    "DPM++ 2M SDE Karras",
    "Euler",
    "Euler a",
    "DDIM",
]


class QarmImagePlanRequest(BaseModel):
    """Strict offline contract. No keys, URLs or billable overrides allowed."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=1200)
    negative_prompt: str = Field(default="", max_length=500)
    width: int = Field(default=1024, ge=512, le=1024, multiple_of=64)
    height: int = Field(default=1024, ge=512, le=1024, multiple_of=64)
    steps: int | None = Field(default=None, ge=1, le=50)
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    realvis_quality: RealvisQuality = "Style Zero"
    juggernaut_sampler: JuggernautSampler = "DPM++ 2M SDE Karras"

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must contain non-whitespace text")
        return value


def prepare_image_plan(payload: QarmImagePlanRequest) -> dict:
    """Prepare known positional Gradio inputs, but NEVER invoke the endpoint."""

    if payload.model_id not in _SUPPORTED:
        raise ValueError("Unknown Qarm image model")

    ready = True
    if payload.model_id == FLUX_MODEL_ID:
        space_id = "black-forest-labs/FLUX.1-schnell"
        api_name = "/infer"
        args = [
            payload.prompt,
            payload.seed,
            False,
            payload.width,
            payload.height,
            payload.steps if payload.steps is not None else 4,
        ]
        note = "Six inputs match the public FLUX Gradio configuration."
    elif payload.model_id == REALVIS_MODEL_ID:
        space_id = "seawolf2357/REALVISXL-V5"
        api_name = "/generate"
        args = [
            "REALVISXL V5.0",
            payload.prompt,
            payload.negative_prompt,
            bool(payload.negative_prompt.strip()),
            payload.realvis_quality,
            payload.seed,
            payload.width,
            payload.height,
            3.0,
            payload.steps if payload.steps is not None else 28,
            False,
            1,
        ]
        note = (
            "Twelve inputs use observed RealVisXL model and quality choices. "
            "The request is not proof of successful live inference."
        )
    else:
        space_id = "artificialguybr/JUGGERNAUT-XL-FREE-DEMO"
        api_name = "/run"
        # The Space uses a preset size radio plus separate sliders. Never
        # invent which mismatched pair would take precedence remotely.
        ready = payload.width == 1024 and payload.height == 1024
        args = (
            [
                JUGGERNAUT_MODEL_ID,
                payload.prompt,
                payload.negative_prompt,
                payload.seed,
                1024,
                1024,
                7.0,
                payload.steps if payload.steps is not None else 30,
                payload.juggernaut_sampler,
                "1024 x 1024",
            ]
            if ready
            else None
        )
        note = (
            "Ten inputs use observed Juggernaut model/sampler/preset choices. "
            "Only 1024 x 1024 was verified as a matching preset."
            if ready
            else "Choose 1024 x 1024 for this Space; no mismatched size sent."
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
