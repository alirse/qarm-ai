#!/usr/bin/env python3
"""Read only public Gradio component defaults/choices for three Qarm Spaces.

Never submits prompts, never POSTs, never calls GPU endpoints, and never reads
credentials. Intended for a single limited metadata audit in GitHub Actions.
"""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

SPACES = (
    ("black-forest-labs/FLUX.1-schnell", "infer"),
    ("seawolf2357/REALVISXL-V5", "generate"),
    ("artificialguybr/JUGGERNAUT-XL-FREE-DEMO", "run"),
)


def fetch(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Qarm-public-contract-discovery/1.0"})
    with urlopen(request, timeout=12) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ValueError("Expected JSON object")
    return data


def safe_host(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    url = urlsplit(value if "://" in value else "https://" + value)
    if (
        url.scheme != "https"
        or not url.hostname
        or not url.hostname.endswith(".hf.space")
        or url.port is not None
        or url.username is not None
        or url.password is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        return None
    return url.hostname


def clipped(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)[:230]


def main() -> None:
    print("Qarm Gradio public choice discovery — GET ONLY / no generation")
    for space_id, function_name in SPACES:
        print("\nSPACE", space_id, "endpoint", function_name)
        try:
            meta = fetch(
                "https://huggingface.co/api/spaces/" + quote(space_id, safe="/")
            )
            runtime = meta.get("runtime") or {}
            if not isinstance(runtime, dict):
                runtime = {}
            host = safe_host(meta.get("host") or runtime.get("host"))
            if host is None:
                print("  No safe host")
                continue
            config = fetch("https://" + host + "/config")
            components = {
                comp["id"]: comp
                for comp in config.get("components", [])
                if isinstance(comp, dict) and isinstance(comp.get("id"), int)
            }
            matches = [
                dep
                for dep in config.get("dependencies", [])
                if isinstance(dep, dict)
                and str(dep.get("api_name", "")).lstrip("/") == function_name
            ]
            if not matches:
                print("  No matching dependency")
                continue
            ids = matches[0].get("inputs", [])
            if not isinstance(ids, list):
                print("  Invalid input metadata")
                continue
            for index, ident in enumerate(ids, 1):
                component = components.get(ident, {})
                props = component.get("props", {})
                if not isinstance(props, dict):
                    props = {}
                print(
                    " ", index, component.get("type", "unknown"),
                    "label:", clipped(props.get("label", "")),
                    "value:", clipped(props.get("value")),
                    "choices:", clipped(props.get("choices")),
                    "min:", clipped(props.get("minimum")),
                    "max:", clipped(props.get("maximum")),
                    "step:", clipped(props.get("step")),
                )
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            print("  Metadata unavailable:", type(exc).__name__)
    print("\nCompleted without POST, queue, token or image generation.")


if __name__ == "__main__":
    main()
