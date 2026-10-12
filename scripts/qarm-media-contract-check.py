#!/usr/bin/env python3
"""Inspect three public Gradio API input/output contracts for Qarm.

GET requests only. No prompts sent, no inference, no POST requests, no auth
tokens, no GPU tasks, no billing endpoints, and no changes to existing models.
"""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

SPACES = (
    ("FLUX.1 Schnell", "black-forest-labs/FLUX.1-schnell", "infer"),
    ("RealVisXL V5", "seawolf2357/REALVISXL-V5", "generate"),
    ("Juggernaut XL", "artificialguybr/JUGGERNAUT-XL-FREE-DEMO", "run"),
)
TIMEOUT = 12


def fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Qarm-read-only-contract-review/1.0"})
    with urlopen(request, timeout=TIMEOUT) as response:
        value = json.load(response)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def space_host(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    url = urlsplit(value if "://" in value else "https://" + value)
    hostname = url.hostname
    if (
        url.scheme != "https"
        or hostname is None
        or not hostname.endswith(".hf.space")
        or url.username is not None
        or url.password is not None
        or url.port is not None
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        return None
    return hostname


def show_components(config: dict, name: str) -> bool:
    components = config.get("components", [])
    dependencies = config.get("dependencies", [])
    if not isinstance(components, list) or not isinstance(dependencies, list):
        return False
    comp_by_id = {
        c["id"]: c
        for c in components
        if isinstance(c, dict) and isinstance(c.get("id"), int)
    }
    matches = [
        dep for dep in dependencies
        if isinstance(dep, dict) and str(dep.get("api_name", "")).lstrip("/") == name
    ]
    if not matches:
        return False
    for dep in matches[:2]:
        print(f"  Gradio function: {name}")
        print(f"  API visibility flag: {dep.get('show_api', 'unspecified')}")
        for direction in ("inputs", "outputs"):
            ids = dep.get(direction, [])
            if not isinstance(ids, list):
                ids = []
            print(f"  {direction.title()} ({len(ids)}):")
            for index, component_id in enumerate(ids[:24], 1):
                comp = comp_by_id.get(component_id, {})
                props = comp.get("props", {})
                if not isinstance(props, dict):
                    props = {}
                label = props.get("label") or props.get("placeholder") or "(unlabeled)"
                kind = comp.get("type", "unknown")
                print(f"    {index}. {str(label)[:75]} [{kind}]")
            if len(ids) > 24:
                print(f"    ... {len(ids) - 24} more")
    return True


def check(title: str, space_id: str, fn_name: str) -> None:
    print(f"\n{title} — {space_id}")
    try:
        meta = fetch_json("https://huggingface.co/api/spaces/" + quote(space_id, safe="/"))
        runtime = meta.get("runtime") or {}
        if not isinstance(runtime, dict):
            runtime = {}
        print("  Status:", runtime.get("stage", "unknown"))
        host = space_host(meta.get("host") or runtime.get("host"))
        if host is None:
            print("  No verified public hf.space host; no remote request attempted.")
            return
        print("  Expected POST path (NOT CALLED): /run/" + fn_name)
        config = fetch_json("https://" + host + "/config")
        if not show_components(config, fn_name):
            print("  Exact inputs not exposed by the public Gradio config.")
            print("  Manual API verification required before building adapter.")
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        print("  Could not read public contract:", type(exc).__name__)
    print("  This does NOT validate free quotas, remote inference or model licensing.")


def main() -> None:
    print("Qarm image API contracts — GET-only, no generation or GPU usage.")
    for title, space_id, fn_name in SPACES:
        check(title, space_id, fn_name)
    print("\nFinished: no image-generation request was sent.")


if __name__ == "__main__":
    main()
