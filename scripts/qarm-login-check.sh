#!/usr/bin/env bash
# Quick offline checks before trying Qarm ChatGPT device sign-in.
set -euo pipefail
cd "$(dirname "$0")/.."

if ! command -v uv >/dev/null 2>&1; then
  echo "Missing uv; Qarm was not changed." >&2
  exit 1
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Missing Node.js; Qarm was not changed." >&2
  exit 1
fi

echo "Checking browser code syntax..."
node --check src/free_claude_code/api/admin_static/admin.js

echo "Checking model login and private admin session tests..."
uv run --no-sync pytest -q -o addopts='' \
  tests/providers/test_openai_codex_auth.py \
  tests/api/test_qarm_admin_session.py \
  tests/api/test_qarm_remote_admin.py

echo "Qarm offline login checks passed. Live device auth has NOT been tested yet."
