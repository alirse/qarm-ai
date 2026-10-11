# Qarm — Codespaces setup

This is a small, reversible setup layer for the existing Free Claude Code project. It does **not** change the available AI models, provider integrations, model behavior, or content policies.

## What changed
- `.python-version` declares Python 3.14.7, matching `pyproject.toml`.
- `scripts/qarm-codespaces-setup.sh` installs that Python version with an existing `uv` installation, installs the project's locked dependencies, and verifies the CLI version.
- No third-party shell installer is downloaded or piped to a shell by this script.
- No credentials, paid providers, Telegram bots, or public ports are configured.

## Run inside the Codespaces terminal
First ensure you are on the `qarm/python-version-setup` branch (the default `main` branch does not contain these changes).

```bash
bash scripts/qarm-codespaces-setup.sh
```

This may download Python and Python packages and use Codespaces compute/storage quota. It does not establish a free, permanent server.

## Before exposing a web UI
Review the server bind address, authentication and GitHub forwarded-port visibility. Do not make an unauthenticated admin panel public. This protects account credentials and project files; it is not a restriction on which models or prompts can be used.

## Status
Prepared in GitHub only. Not executed in the user's Codespace; installation, runtime behavior, external provider quotas and billing remain unverified.
