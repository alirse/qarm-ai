"""Browser landing redirect that preserves streaming and disconnect ownership."""

from starlette.datastructures import Headers
from starlette.responses import RedirectResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class QarmBrowserHomeMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope.get("method") == "GET"
            and scope.get("path") == "/"
            and "text/html" in Headers(scope=scope).get("accept", "")
        ):
            response = RedirectResponse(
                "/admin/qarm/chat", headers={"Cache-Control": "no-store"}
            )
            await response(scope, receive, send)
            return
        await self._app(scope, receive, send)
