#!/usr/bin/env python3
"""One authorized anonymous FLUX.1 Schnell ZeroGPU trial, max ONE generation POST.

Only runs in the explicit one-shot GitHub workflow. No API keys, payments,
account tokens, fallback provider, retry, deployment, or model downloads.
The submitted prompt is synthetic, public and contains no user information.
"""
import json
import os
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

SPACE_ID = "black-forest-labs/FLUX.1-schnell"
PROMPT = "A cozy sunlit courtyard with a brass lantern, cream walls and a small green palm tree, photorealistic"
OUTPUT = Path("qarm-flux-one-shot")
MAX_IMAGE_BYTES = 12 * 1024 * 1024
MAX_META_BYTES = 2 * 1024 * 1024
MAX_EVENT_BYTES = 2 * 1024 * 1024
TIMEOUT_SECONDS = 180


class NoRedirects(HTTPRedirectHandler):
    """Reject redirects, especially any redirect after the single POST."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Redirect rejected")


OPENER = build_opener(NoRedirects)


def request(url: str, *, payload: bytes | None = None, limit: int = MAX_META_BYTES, timeout: int = 20) -> bytes:
    headers = {"User-Agent": "Qarm-public-ZeroGPU-one-shot/1.0"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=payload, headers=headers, method="POST" if payload is not None else "GET")
    with OPENER.open(req, timeout=timeout) as resp:
        if resp.status not in (200, 201, 202):
            raise ValueError("Unexpected HTTP status")
        body = resp.read(limit + 1)
        if len(body) > limit:
            raise ValueError("Response exceeded fixed safety limit")
        return body


def as_json(data: bytes) -> dict:
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON dictionary")
    return value


def safe_space_host(meta: dict) -> str:
    runtime = meta.get("runtime") or {}
    if not isinstance(runtime, dict):
        runtime = {}
    if runtime.get("stage") != "RUNNING" or meta.get("sdk") != "gradio":
        raise ValueError("Public Space not running Gradio")
    value = meta.get("host") or runtime.get("host")
    if not isinstance(value, str):
        raise ValueError("No verified Space host")
    u = urlsplit(value if "://" in value else "https://" + value)
    if (
        u.scheme != "https"
        or not u.hostname
        or not u.hostname.endswith(".hf.space")
        or u.username is not None
        or u.password is not None
        or u.port is not None
        or u.path not in ("", "/")
        or u.query
        or u.fragment
    ):
        raise ValueError("Refusing untrusted host")
    return u.hostname


def sse_complete(body: bytes) -> object:
    events = body.decode("utf-8").replace("\r\n", "\n").split("\n\n")
    for block in events:
        event = ""
        data = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        if event == "error":
            raise ValueError("ZeroGPU queue returned an error (no retry)")
        if event == "complete":
            return json.loads("\n".join(data))
    raise ValueError("No completed generation event in response")


def image_url(response_data: object, host: str) -> str:
    candidate = response_data
    if isinstance(candidate, dict):
        candidate = candidate.get("data")
    if not isinstance(candidate, list) or not candidate:
        raise ValueError("Generation did not return outputs")
    first = candidate[0]
    if not isinstance(first, dict) or not isinstance(first.get("url"), str):
        raise ValueError("No download URL in image output")
    url = first["url"]
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname != host
        or p.username is not None
        or p.password is not None
        or p.port is not None
        or not p.path.startswith("/gradio_api/file=")
    ):
        raise ValueError("Image URL outside trusted Space origin")
    return url


def main() -> int:
    OUTPUT.mkdir(exist_ok=True)
    if os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
        raise ValueError("HF tokens are forbidden in anonymous one-shot trial")
    print("Qarm one-shot: public FLUX Gradio Space, no token, no paid API.")
    print("Limit: exactly one POST to generation, no retries.")
    meta = as_json(request("https://huggingface.co/api/spaces/" + quote(SPACE_ID, safe="/")))
    host = safe_space_host(meta)
    config = as_json(request("https://" + host + "/config"))
    deps = config.get("dependencies") or []
    if not any(
        isinstance(d, dict) and str(d.get("api_name", "")).lstrip("/") == "infer"
        and len(d.get("inputs", [])) == 6
        for d in deps
    ):
        raise ValueError("FLUX Space API inputs no longer match preflight; no POST")
    print("Preflight verified. One free anonymous GPU request now.")
    data = json.dumps({"data": [PROMPT, 0, False, 512, 512, 4]}).encode("utf-8")
    response = as_json(
        request(
            "https://" + host + "/gradio_api/call/infer",
            payload=data,
            timeout=35,
        )
    )
    event = response.get("event_id")
    if not isinstance(event, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", event):
        raise ValueError("No valid event id returned (no retry)")
    print("Generation submitted once; reading existing event output.")
    result = sse_complete(
        request(
            "https://" + host + "/gradio_api/call/infer/" + quote(event, safe=""),
            limit=MAX_EVENT_BYTES,
            timeout=TIMEOUT_SECONDS,
        )
    )
    url = image_url(result, host)
    image = request(url, limit=MAX_IMAGE_BYTES, timeout=40)
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        name = "qarm-flux-free-test.png"
    elif image.startswith(b"\xff\xd8\xff"):
        name = "qarm-flux-free-test.jpg"
    elif image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        name = "qarm-flux-free-test.webp"
    else:
        raise ValueError("Image output is not a supported format")
    (OUTPUT / name).write_bytes(image)
    (OUTPUT / "result.json").write_text(
        json.dumps(
            {
                "model": SPACE_ID,
                "prompt": PROMPT,
                "status": "generated_one_image",
                "image_file": name,
                "image_size_bytes": len(image),
                "authenticated": False,
                "paid_inference_api_used": False,
                "gpu_generation_post_count": 1,
            },
            indent=2,
            ensure_ascii=False,
        ) + "\n",
        encoding="utf-8",
    )
    print(f"SUCCESS: Generated image verified and saved in artifact. Bytes: {len(image)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (HTTPError, URLError, TimeoutError, ValueError, OSError, json.JSONDecodeError) as exc:
        # Deliberately no second POST on any failure (including quota or timeout).
        print(f"ONE-SHOT STOPPED: {type(exc).__name__}. No retry or billable fallback.")
        sys.exit(1)
