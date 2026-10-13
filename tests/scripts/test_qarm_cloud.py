"""Free deployment must require owner secrets and protect the public proxy."""

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    "qarm_cloud", ROOT / "scripts/qarm-cloud-start.py"
)
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


@pytest.mark.parametrize(
    "origin",
    [
        "",
        "http://qarm.onrender.com",
        "https://evil.example",
        "https://user@qarm.onrender.com",
        "https://qarm.onrender.com/path",
    ],
)
def test_cloud_refuses_unapproved_origin(monkeypatch, origin):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", origin)
    with pytest.raises(SystemExit):
        cloud.main()


def test_cloud_requires_credentials_and_enables_proxy_auth(monkeypatch):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://qarm.onrender.com")
    monkeypatch.delenv("QARM_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        cloud.main()
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", "test-pass-12")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-credential")
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    # Keep launch-time process changes isolated from later tests.
    for key in (
        "QARM_ADMIN_PUBLIC_ORIGIN",
        "HOST",
        "PORT",
        "MODEL",
        "PROXY_AUTH_ENABLED",
        "ANTHROPIC_AUTH_TOKEN",
        "FCC_OPEN_BROWSER",
    ):
        monkeypatch.setenv(key, "")
    monkeypatch.setenv("PORT", "10000")
    called = []
    monkeypatch.setattr(cloud, "serve", lambda: called.append(True))
    cloud.main()
    import os

    assert called == [True]
    assert os.environ["PROXY_AUTH_ENABLED"] == "true"
    assert len(os.environ["ANTHROPIC_AUTH_TOKEN"]) >= 12
    assert os.environ["MODEL"].startswith("groq/")


def test_deployment_blueprint_requests_only_free_compute():
    data = yaml.safe_load((ROOT / "render.yaml").read_text())
    assert "databases" not in data
    assert len(data["services"]) == 1
    assert data["services"][0]["plan"] == "free"
    assert all(
        entry.get("sync") is False
        for entry in data["services"][0]["envVars"]
        if entry["key"] in {"GROQ_API_KEY", "QARM_ADMIN_PASSWORD"}
    )


@pytest.mark.parametrize(
    "key,password,expected",
    [
        ("", "test-owner-password-long-enough", "GROQ_API_KEY is missing"),
        ("   ", "test-owner-password-long-enough", "GROQ_API_KEY is missing"),
        ("private-test-key", "", "QARM_ADMIN_PASSWORD is missing"),
        ("private-test-key", "short-pass", "at least 12 characters"),
    ],
)
def test_configuration_error_identifies_field_without_revealing_secrets(
    monkeypatch, key, password, expected
):
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://qarm.onrender.com")
    monkeypatch.setenv("GROQ_API_KEY", key)
    monkeypatch.setenv("QARM_ADMIN_PASSWORD", password)
    with pytest.raises(SystemExit) as error:
        cloud.main()
    message = str(error.value)
    assert expected in message
    if key.strip():
        assert key not in message
    if password:
        assert password not in message
