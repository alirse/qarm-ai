"""Owner-only native Codex CLI bridge.

Reuse the user's existing Codex CLI ChatGPT sign-in, not FCC's separate
OAuth credential store. No token import, refresh or paid API-key fallback.
Status performs only `codex login status`; inference requires a separate
explicitly confirmed POST by the owner.
"""

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

from .admin_security import require_loopback_admin
from .qarm_admin_session import COOKIE_NAME, valid_cookie

router = APIRouter()


def _csrf_token(request: Request) -> str:
    """Unpredictable session-bound HMAC; never return or log the cookie itself."""
    cookie = request.cookies.get(COOKIE_NAME, "")
    secret = os.environ.get("QARM_ADMIN_PASSWORD", "")
    if len(secret) < 12 or not cookie or not valid_cookie(request, check_write_origin=False):
        return ""
    key = hashlib.sha256(("qarm-codex-csrf-v1:" + secret).encode()).digest()
    return hmac.new(key, cookie.encode(), hashlib.sha256).hexdigest()


def require_codex_write(request: Request) -> None:
    """Signed owner cookie + per-session CSRF token, independent of proxy headers."""
    supplied = request.headers.get("x-qarm-csrf", "")
    expected = _csrf_token(request)
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Qarm owner login required")



_CODEX_PAGE = Path(__file__).resolve().parent / "admin_static" / "qarm_codex_local.html"
_MAX_OUTPUT_BYTES = 1_500_000
_MAX_RESPONSE_CHARS = 14000
_RUN_TIMEOUT_SECONDS = 90
_run_lock = asyncio.Lock()


class NativeCodexPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=4000)
    confirm_plan_usage: Literal[True]


def _binary() -> str | None:
    return shutil.which("codex")


def native_codex_login_status() -> str:
    """Return only a coarse local CLI login type; never reveal CLI output."""
    binary = _binary()
    if not binary:
        return "not_installed"
    try:
        result = subprocess.run(
            [binary, "login", "status"],
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except OSError, subprocess.TimeoutExpired:
        return "unavailable"
    if result.returncode != 0:
        return "disconnected"
    output = (result.stdout + "\n" + result.stderr).strip().lower()
    if "logged in using chatgpt" in output:
        return "chatgpt"
    if "api key" in output or "apikey" in output:
        return "api_key"
    return "unknown"


@router.get("/admin/api/qarm/codex-local", include_in_schema=False, dependencies=[Depends(require_loopback_admin)])
def native_codex_status(request: Request) -> dict[str, str | bool]:
    """No network inference, no credential reads, no model usage."""
    login = native_codex_login_status()
    return {
        "login": login,
        "ready_for_native_chat": login == "chatgpt",
        "qarm_oauth_is_separate": True,
        "inference_performed": False,
        "csrf_token": _csrf_token(request),
    }


@router.get(
    "/admin/qarm/codex-local", response_class=HTMLResponse, include_in_schema=False,
    dependencies=[Depends(require_loopback_admin)],
)
def native_codex_page() -> HTMLResponse:
    return HTMLResponse(
        _CODEX_PAGE.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": (
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; connect-src 'self'; "
                "img-src 'none'; base-uri 'none'; form-action 'none'; "
                "frame-ancestors 'none'"
            ),
        },
    )


def _native_only_environment() -> dict[str, str]:
    """Prevent accidental fallback to paid API-key and custom endpoint auth."""
    env = dict(os.environ)
    for key in (
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_ORG_ID",
        "OPENAI_ORGANIZATION",
        "CODEX_API_KEY",
        "CODEX_ACCESS_TOKEN",
    ):
        env.pop(key, None)
    return env


def _last_agent_message(output: bytes) -> str | None:
    """Accept only Codex's structured final agent messages, not raw log output."""
    text = output.decode("utf-8", errors="replace")
    answer = None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict) or event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            candidate = item.get("text")
            if isinstance(candidate, str) and candidate.strip():
                answer = candidate.strip()
    return answer[:_MAX_RESPONSE_CHARS] if answer else None


@router.post("/admin/api/qarm/codex-local/preflight", include_in_schema=False, dependencies=[Depends(require_codex_write)])
def native_codex_owner_write_preflight() -> dict[str, bool]:
    """Verify owner cookie and CSRF protection for writes without model usage."""
    return {"owner_write_authorized": True, "inference_performed": False}


@router.post("/admin/api/qarm/codex-local/chat", include_in_schema=False, dependencies=[Depends(require_codex_write)])
async def native_codex_chat(payload: NativeCodexPrompt) -> dict[str, str]:
    """One owner-initiated native ChatGPT-plan turn; never use paid API keys."""
    if native_codex_login_status() != "chatgpt":
        raise HTTPException(
            status_code=409,
            detail="Codex CLI is not logged in using ChatGPT. No request was sent.",
        )
    if _run_lock.locked():
        raise HTTPException(
            status_code=409, detail="A native Codex request is already running."
        )
    binary = _binary()
    if not binary:
        raise HTTPException(status_code=503, detail="Codex CLI is not installed.")
    async with _run_lock:
        with tempfile.TemporaryDirectory(prefix="qarm-codex-") as scratch:
            # Explicitly override any FCC proxy configuration. Temporary
            # working directory prevents implicit access to the user's repo.
            command = [
                binary,
                "exec",
                "--json",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "-C",
                scratch,
                "-c",
                'model_provider="openai"',
                "-",
            ]
            process = None
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_native_only_environment(),
                )
                stdout, _stderr = await asyncio.wait_for(
                    process.communicate(payload.prompt.encode("utf-8")),
                    timeout=_RUN_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                if process is not None and process.returncode is None:
                    process.kill()
                    await process.communicate()
                raise HTTPException(
                    status_code=504,
                    detail="Codex timed out. The request was not retried.",
                ) from None
            except OSError:
                raise HTTPException(
                    status_code=503, detail="Could not start local Codex CLI."
                ) from None
            except asyncio.CancelledError:
                if process is not None and process.returncode is None:
                    process.kill()
                    await process.communicate()
                raise
            if len(stdout) > _MAX_OUTPUT_BYTES:
                raise HTTPException(
                    status_code=502, detail="Codex output exceeded the safe size limit."
                )
            if process.returncode != 0:
                raise HTTPException(
                    status_code=502,
                    detail="Codex did not complete. Verify the ChatGPT plan limits in Codex.",
                )
            answer = _last_agent_message(stdout)
            if not answer:
                raise HTTPException(
                    status_code=502, detail="Codex returned no completed agent message."
                )
            return {"answer": answer, "provider": "native_codex_chatgpt"}
