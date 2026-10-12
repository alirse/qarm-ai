#!/usr/bin/env python3
"""Read-only Hugging Face Space discovery for Qarm image candidates.

Sends GET requests only. No image generation, GPU jobs, model downloads, tokens,
billing endpoints, or changes to existing chat/coding integrations.
"""
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

SPACES = (
    ("FLUX.1 Schnell", "black-forest-labs/FLUX.1-schnell"),
    ("RealVisXL V5", "seawolf2357/REALVISXL-V5"),
    ("Juggernaut XL", "artificialguybr/JUGGERNAUT-XL-FREE-DEMO"),
)
TIMEOUT_SECONDS = 12


def read_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "qarm-read-only-api-audit/1.0"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def safe_hf_space_host(value: object) -> str | None:
    """Reject redirects or unexpected domains before fetching API metadata."""
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value if "://" in value else "https://" + value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".hf.space")
        or parsed.username
        or parsed.password
        or parsed.port is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return parsed.hostname


def check_space(title: str, space_id: str) -> None:
    print(f"\n{title} ({space_id})")
    url = "https://huggingface.co/api/spaces/" + quote(space_id, safe="/")
    try:
        metadata = read_json(url)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        print(f"  Public Space metadata unavailable: {type(error).__name__}")
        return

    runtime = metadata.get("runtime")
    if not isinstance(runtime, dict):
        runtime = {}
    print(f"  Runtime: {runtime.get('stage') or 'unknown'}")
    print(f"  SDK: {metadata.get('sdk') or 'unknown'}")
    host = safe_hf_space_host(metadata.get("host") or runtime.get("host"))
    if host is None:
        print("  API host: not advertised in metadata; no endpoint assumed")
        return

    api_url = f"https://{host}/gradio_api/openapi.json"
    try:
        schema = read_json(api_url)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as error:
        print(f"  Public API description unavailable: {type(error).__name__}")
        return

    paths = schema.get("paths")
    if not isinstance(paths, dict):
        print("  API description contains no paths")
        return
    callable_paths = [
        name for name, methods in paths.items()
        if isinstance(name, str) and isinstance(methods, dict) and "post" in methods
    ]
    print(f"  Public API description found; POST paths: {len(callable_paths)}")
    for name in callable_paths[:8]:
        print(f"    {name}")
    print("  IMPORTANT: no generation/API invocation attempted; free quota not validated.")


def main() -> int:
    print("Qarm media Space discovery — GET requests only; no GPU inference.")
    for title, space_id in SPACES:
        check_space(title, space_id)
    print("\nNo paid or generation requests were made by this script.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
