"""Owner-only Groq chat using the existing runtime and private credentials."""

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from free_claude_code.core.anthropic import Message, MessagesRequest, get_token_count

from .admin_security import require_loopback_admin
from .dependencies import get_services
from .handlers import MessagesHandler
from .ports import ApiServices
from .qarm_codex_local_routes import _csrf_token, require_codex_write
from .request_ids import get_request_id
from .response_streams import bind_response_lifetime
from .routes import _provider_resolver

router = APIRouter()
_PAGE = Path(__file__).parent / "admin_static" / "qarm_chat.html"
_CHAT_LOCK = asyncio.Lock()
_SYSTEM = (
    "أنت قرم، مساعد شخصي ومبرمج. أجب بالعربية ما لم يُطلب غير ذلك. "
    "قدم خطوات عملية وكودًا واضحًا. لا تدّع تنفيذ أوامر أو بحث أو تذكّر معلومات "
    "لم تُزوّد بها. هذه محادثة نصية؛ تنفيذ المشاريع متاح في جلسات البرمجة المنفصلة."
)


class ChatTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=24000)


class QarmChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: Literal["groq/openai/gpt-oss-120b", "groq/openai/gpt-oss-20b"] = (
        "groq/openai/gpt-oss-120b"
    )
    messages: list[ChatTurn] = Field(min_length=1)
    stream: bool = False
    max_tokens: int = Field(default=1024, ge=256, le=8192, strict=True)

    @model_validator(mode="after")
    def validate_turns(self):
        for index, turn in enumerate(self.messages):
            expected = "user" if index % 2 == 0 else "assistant"
            if turn.role != expected or not turn.content.strip():
                raise ValueError("Messages must alternate, starting with a user")
        if self.messages[-1].role != "user":
            raise ValueError("The last message must be from the user")
        if sum(len(turn.content) for turn in self.messages) > 60000:
            raise ValueError("Conversation is too large")
        return self


def prepare_chat(payload: QarmChatRequest) -> MessagesRequest:
    messages = [
        Message(role=turn.role, content=turn.content) for turn in payload.messages
    ]
    estimated = get_token_count(messages, _SYSTEM)
    # The provider enforces its authoritative TPM budget; token estimates are
    # approximate. Do not reserve an arbitrary portion of the free allowance.
    available = 8000 - estimated
    if available < 256:
        raise HTTPException(
            status_code=413,
            detail="المحادثة طويلة للحصة المجانية. احفظها وابدأ محادثة جديدة أو اختصر النص؛ لم تُحذف أي رسالة.",
        )
    return MessagesRequest(
        model=payload.model,
        system=_SYSTEM,
        messages=messages,
        max_tokens=min(payload.max_tokens, available),
        stream=payload.stream,
    )


@router.get("/admin/qarm/chat", response_class=HTMLResponse, include_in_schema=False)
def chat_page(request: Request):
    require_loopback_admin(request)
    return HTMLResponse(
        _PAGE.read_text(encoding="utf-8"),
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; frame-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get(
    "/admin/api/qarm/chat/bootstrap",
    include_in_schema=False,
    dependencies=[Depends(require_loopback_admin)],
)
def chat_bootstrap(request: Request):
    return {"csrf_token": _csrf_token(request)}


def require_chat_write(request: Request) -> None:
    if request.headers.get("x-qarm-csrf"):
        require_codex_write(request)
    else:
        require_loopback_admin(request)


@router.post(
    "/admin/api/qarm/chat",
    include_in_schema=False,
    dependencies=[Depends(require_chat_write)],
)
async def chat(
    payload: QarmChatRequest,
    request: Request,
    services: ApiServices = Depends(get_services),
):
    prepared = prepare_chat(payload)
    if _CHAT_LOCK.locked():
        raise HTTPException(status_code=429, detail="قرم يجيب الآن. انتظر اكتمال الرد.")
    await _CHAT_LOCK.acquire()
    lease = None
    try:
        lease = await services.requests.acquire()
        await lease.wait_for_token_estimation()
        settings = lease.settings.model_copy(update={"model_fallbacks": None})
        handler = MessagesHandler(
            settings,
            web_tools=services.web_tools,
            provider_resolver=_provider_resolver(lease),
            token_counter=get_token_count,
            generation_id=lease.generation_id,
            model_info_lookup=lease.model_info,
        )
        response = await handler.create(prepared, request_id=get_request_id(request))

        async def release():
            try:
                await lease.release()
            finally:
                if _CHAT_LOCK.locked():
                    _CHAT_LOCK.release()

        return await bind_response_lifetime(response, release)
    except BaseException:
        try:
            if lease is not None:
                await lease.release()
        finally:
            if _CHAT_LOCK.locked():
                _CHAT_LOCK.release()
        raise
