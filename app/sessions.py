"""Signed-cookie session middleware with per-session lifetime.

Same idea as Starlette's SessionMiddleware, but the cookie is a browser-session cookie
unless the session contains ``remember=True`` ("Keep me signed in"), in which case it
persists for ``remember_max_age`` seconds.
"""
import json
from base64 import b64decode, b64encode

import itsdangerous
from itsdangerous.exc import BadSignature
from starlette.datastructures import MutableHeaders
from starlette.requests import HTTPConnection
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class SessionMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        secret_key: str,
        session_cookie: str = "sp_session",
        remember_max_age: int = 30 * 24 * 3600,
        https_only: bool = False,
        same_site: str = "lax",
    ) -> None:
        self.app = app
        self.signer = itsdangerous.TimestampSigner(str(secret_key))
        self.session_cookie = session_cookie
        self.remember_max_age = remember_max_age
        self.security_flags = "httponly; samesite=" + same_site + ("; secure" if https_only else "")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        connection = HTTPConnection(scope)
        initial_session_was_empty = True
        scope["session"] = {}
        if self.session_cookie in connection.cookies:
            data = connection.cookies[self.session_cookie].encode("utf-8")
            try:
                data = self.signer.unsign(data, max_age=self.remember_max_age)
                scope["session"] = json.loads(b64decode(data))
                initial_session_was_empty = False
            except (BadSignature, ValueError):
                scope["session"] = {}

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                session = scope["session"]
                headers = MutableHeaders(scope=message)
                if session:
                    data = b64encode(json.dumps(session).encode("utf-8"))
                    data = self.signer.sign(data)
                    max_age = f"Max-Age={self.remember_max_age}; " if session.get("remember") else ""
                    headers.append(
                        "Set-Cookie",
                        f"{self.session_cookie}={data.decode('utf-8')}; path=/; {max_age}{self.security_flags}",
                    )
                elif not initial_session_was_empty:
                    headers.append(
                        "Set-Cookie",
                        f"{self.session_cookie}=null; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; "
                        f"{self.security_flags}",
                    )
            await send(message)

        await self.app(scope, receive, send_wrapper)
