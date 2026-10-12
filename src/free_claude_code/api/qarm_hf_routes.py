"""Owner-initiated image generation through fixed public ZeroGPU Spaces only."""

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import Field

from free_claude_code.config.paths import config_dir_path

from .admin_security import require_loopback_admin
from .qarm_chat_routes import require_chat_write
from .qarm_image_contracts import QarmImagePlanRequest, prepare_image_plan

router = APIRouter()
_SPACES = {
    "black-forest-labs/FLUX.1-schnell": "black-forest-labs-flux-1-schnell.hf.space",
    "SG161222/RealVisXL_V5.0": "seawolf2357-realvisxl-v5.hf.space",
    "RunDiffusion/Juggernaut-XL-v9": "artificialguybr-juggernaut-xl-free-demo.hf.space",
}
_lock = asyncio.Lock()
# Prevent duplicate submissions in this process, including failed/timeout jobs.
_requests: dict[UUID, dict | None] = {}


class LiveImageRequest(QarmImagePlanRequest):
    request_id: UUID = Field(default_factory=uuid4)
    width: int = Field(default=512, ge=512, le=1024, multiple_of=64)
    height: int = Field(default=512, ge=512, le=1024, multiple_of=64)


def _root() -> Path:
    return config_dir_path() / "qarm-media"


async def _read(client: httpx.AsyncClient, url: str, *, limit: int, payload=None):
    async with client.stream(
        "POST" if payload is not None else "GET", url, json=payload
    ) as response:
        if response.status_code == 429:
            raise HTTPException(
                429, "انتهت الحصة المؤقتة للنموذج. جرّب لاحقًا؛ لا يوجد بديل مدفوع."
            )
        if response.status_code >= 400:
            raise HTTPException(
                502, "خدمة الصور غير متاحة حاليًا. لم ننتقل إلى خدمة مدفوعة."
            )
        if response.is_redirect:
            raise HTTPException(502, "تغير عنوان خدمة الصور؛ توقف الطلب.")
        data = bytearray()
        async for chunk in response.aiter_bytes():
            data.extend(chunk)
            if len(data) > limit:
                raise HTTPException(502, "تجاوزت نتيجة خدمة الصور الحجم المسموح.")
        return bytes(data)


def _result(data: bytes):
    for block in data.decode().replace("\r\n", "\n").split("\n\n"):
        event = ""
        lines = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            if line.startswith("data:"):
                lines.append(line[5:].strip())
        if event == "error":
            raise HTTPException(
                429,
                "لم يكتمل التوليد: قد تكون حصة ZeroGPU انتهت أو الخدمة مزدحمة. حاول لاحقًا.",
            )
        if event == "complete":
            return json.loads("\n".join(lines))
    raise HTTPException(502, "لم تصل صورة مكتملة من النموذج.")


def _download_url(result, host: str):
    if isinstance(result, dict):
        result = result.get("data")
    if not isinstance(result, list) or not result:
        raise ValueError("Missing image result")
    first = result[0]
    # Gallery components return a list of {image: FileData, caption: ...}.
    if isinstance(first, list) and first:
        first = first[0]
    if isinstance(first, dict) and "image" in first:
        first = first["image"]
    if not isinstance(first, dict) or not isinstance(first.get("url"), str):
        raise ValueError("Missing image URL")
    url = first["url"]
    parsed = urlsplit(url)
    if not (
        parsed.scheme == "https"
        and parsed.hostname == host
        and parsed.port is None
        and parsed.username is None
        and parsed.password is None
        and parsed.path.startswith(("/gradio_api/file=", "/file="))
        and not parsed.fragment
    ):
        raise ValueError("Untrusted image origin")
    return url


async def generate_free_image(payload: LiveImageRequest, client: httpx.AsyncClient):
    host = _SPACES.get(payload.model_id)
    if not host:
        raise HTTPException(422, "نموذج الصور غير مدعوم.")
    plan = prepare_image_plan(payload)
    if not plan["contract_complete"]:
        raise HTTPException(422, "اختر مقاس 1024 x 1024 لهذا النموذج.")
    meta = json.loads(
        await _read(
            client,
            "https://huggingface.co/api/spaces/" + plan["space_id"],
            limit=2_000_000,
        )
    )
    runtime = meta.get("runtime", {})
    hardware = runtime.get("hardware", {}).get("current", "")
    # Refuse paid GPU hosting or a changed public origin before inference.
    if (
        meta.get("host") != "https://" + host
        or runtime.get("stage") != "RUNNING"
        or not hardware.startswith("zero-")
    ):
        raise HTTPException(503, "النموذج غير جاهز على ZeroGPU المجاني حاليًا.")
    config = json.loads(
        await _read(client, "https://" + host + "/config", limit=2_000_000)
    )
    api = plan["api_name"].lstrip("/")
    if not any(
        (d.get("api_name") or "").lstrip("/") == api
        and len(d.get("inputs", [])) == len(plan["args"])
        for d in config.get("dependencies", [])
        if isinstance(d, dict)
    ):
        raise HTTPException(503, "تغيرت واجهة النموذج؛ توقف الطلب قبل التوليد.")
    base = "https://" + host + "/gradio_api/call/" + api
    event = json.loads(
        await _read(client, base, limit=10000, payload={"data": plan["args"]})
    ).get("event_id")
    if not isinstance(event, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", event):
        raise ValueError("Invalid event identifier")
    result = _result(await _read(client, base + "/" + event, limit=2_000_000))
    image = await _read(client, _download_url(result, host), limit=12_000_000)
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        extension = "png"
    elif image.startswith(b"\xff\xd8\xff"):
        extension = "jpg"
    elif image.startswith(b"RIFF") and image[8:12] == b"WEBP":
        extension = "webp"
    else:
        raise ValueError("Unsupported image format")
    root = _root()
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    filename = str(uuid4()) + "." + extension
    (root / filename).write_bytes(image)
    return {
        "status": "completed",
        "actual_generation": True,
        "model_id": payload.model_id,
        "image_url": "/admin/api/qarm/images/files/" + filename,
        "billing_enabled": False,
        "provider": "Hugging Face ZeroGPU",
    }


@router.post(
    "/admin/api/qarm/images/generate", dependencies=[Depends(require_chat_write)]
)
async def create_image(payload: LiveImageRequest):
    if payload.request_id in _requests:
        previous = _requests[payload.request_id]
        if previous:
            return previous
        raise HTTPException(409, "أُرسل هذا الطلب سابقًا؛ لن نكرره تلقائيًا.")
    if _lock.locked():
        raise HTTPException(429, "يوجد طلب صور جارٍ. انتظر اكتماله.")
    if len(_requests) >= 256:
        raise HTTPException(429, "وصلت هذه الجلسة لحد طلبات الصور. توقف التوليد.")
    _requests[payload.request_id] = None
    async with _lock:
        try:
            async with (
                asyncio.timeout(190),
                httpx.AsyncClient(
                    timeout=180, follow_redirects=False, trust_env=True
                ) as client,
            ):
                result = await generate_free_image(payload, client)
        except HTTPException:
            raise
        except TimeoutError:
            raise HTTPException(
                504, "انتهت مهلة انتظار الصورة. لم نُعد إرسال طلب التوليد."
            ) from None
        except httpx.HTTPError, ValueError, KeyError, TypeError:
            raise HTTPException(
                502,
                "تعذر توليد الصورة عبر العرض المجاني. لا توجد إعادة تلقائية أو رسوم.",
            ) from None
        _requests[payload.request_id] = result
        return result


@router.get(
    "/admin/api/qarm/images/files/{filename}",
    dependencies=[Depends(require_loopback_admin)],
)
def image_file(filename: str):
    if not re.fullmatch(r"[a-f0-9-]{36}\.(?:png|jpg|webp)", filename):
        raise HTTPException(404)
    path = _root() / filename
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(
        path, headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    )
