#!/usr/bin/env bash
# Qarm Codespaces setup: use the project's pinned Python version and lockfile.
set -euo pipefail
cd "$(dirname "$0")/.."
echo "Qarm: checking required tools..."
if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not installed. Stop here; no remote installer was executed." >&2
  exit 1
fi
echo "Qarm: installing the Python version requested by pyproject.toml..."
uv python install 3.14.7
echo "Qarm: installing locked project dependencies (no optional dev or voice extras)..."
uv sync --locked --no-dev --python 3.14.7
echo "Qarm: verifying the command without starting a server..."
uv run --no-sync fcc-server --version
echo "Qarm setup complete. No AI provider or paid API was configured."
