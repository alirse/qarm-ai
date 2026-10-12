"""Offline-only image pipeline simulator for Qarm.

This is NOT image generation: it never opens sockets, imports inference clients,
calls third-party providers, or consumes tokens, quota, or GPU. Real providers
must go through a future independent explicit-consent and quota review.
"""

import base64

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QarmImageRequest(BaseModel):
    """Strict typed input: no hidden live/paid/provider flags accepted."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=1200)

    @field_validator("prompt")
    @classmethod
    def nonempty_prompt(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Prompt must contain non-whitespace text")
        return value


_MOCK_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="720" height="460" viewBox="0 0 720 460">
<rect width="720" height="460" fill="#f6eee0"/>
<circle cx="590" cy="110" r="75" fill="#f2bb4e"/>
<path d="M0 350 Q170 230 380 335 T720 300 V460 H0Z" fill="#d7c6eb"/>
<path d="M0 400 Q290 260 530 380 T720 350 V460 H0Z" fill="#a899c8"/>
<rect x="140" y="175" width="440" height="105" rx="18" fill="#1e1733"/>
<text x="360" y="221" fill="#f6eee0" font-size="36" text-anchor="middle" font-family="sans-serif">QARM MOCK</text>
<text x="360" y="251" fill="#f2bb4e" font-size="18" text-anchor="middle" font-family="sans-serif">NO REAL IMAGE GENERATED</text>
</svg>"""


def simulate_image(*, model_id: str) -> dict:
    """Produce a static, unmistakable placeholder without external work."""

    uri = "data:image/svg+xml;base64," + base64.b64encode(
        _MOCK_SVG.encode("utf-8")
    ).decode("ascii")
    return {
        "status": "mock_completed",
        "model_id": model_id,
        "result_data_uri": uri,
        "actual_generation": False,
        "external_requests": 0,
        "gpu_minutes_consumed": 0,
        "estimated_cost_usd": 0,
        "notice": "Simulation only. No model was run, and no real image was made.",
    }
