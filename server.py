"""Local helper behind the Breeze Mac app.

Holds the link to the air conditioner and talks to the app over a WebSocket. Binds to
127.0.0.1 only and checks Host and Origin, so neither other devices on the Wi-Fi nor websites
open in a browser can reach it. The app starts it with BREEZE_TOKEN set, and every request
must carry that token, so other local programs cannot drive the AC either.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
from collections.abc import Awaitable, Callable
from typing import Any

from aiohttp import WSMsgType, web

from ac import ACError, ACSession
from phone import PHONE_CHANGES, PhoneAccess, phone_view

TOKEN_HEADER = "X-Breeze-Token"
MAX_MESSAGE_BYTES = 4096
# WebSocket pings, so a vanished client (a Mac app gone, a phone off the Wi-Fi) is noticed.
HEARTBEAT_SECONDS = 20
# How long closing a phone's socket may wait for the phone to answer; a vanished one never does.
PHONE_CLOSE_SECONDS = 1.0
PARENT_CHECK_SECONDS = 5.0
BAD_MESSAGE = "Bad message."

log = logging.getLogger("breeze.server")


class UserError(Exception):
    """A problem the app can show as is. Never wraps internal error text."""


class Session:
    def __init__(self) -> None:
        self.clients: set[web.WebSocketResponse] = set()
        self.phones: set[web.WebSocketResponse] = set()  # get phone_view only
        self._background: set[asyncio.Task[Any]] = set()
        self.ac = ACSession(on_change=lambda: self.spawn(self.broadcast(self.ac.message())))
        self.phone = PhoneAccess(self.run_phone_socket, self.close_phones)

    def spawn(self, coro: Awaitable[Any]) -> None:
        task = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    async def broadcast(self, message: dict[str, Any]) -> None:
        for ws in list(self.clients):
            await reply(ws, message)
        if self.phones:
            view = phone_view(message)
            for ws in list(self.phones):
                await reply(ws, view)

    async def run_phone_socket(self, request: web.Request) -> web.WebSocketResponse:
        # timeout: how long a close waits for the phone's answer.
        ws = web.WebSocketResponse(heartbeat=HEARTBEAT_SECONDS, max_msg_size=MAX_MESSAGE_BYTES,
                                   timeout=PHONE_CLOSE_SECONDS)
        await ws.prepare(request)
        self.phones.add(ws)
        await reply(ws, phone_view(self.ac.message()))
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await handle_message(self, ws, msg.data, PHONE_HANDLERS)
        finally:
            self.phones.discard(ws)
        return ws

    async def close_phones(self) -> None:
        """All at once, each waiting at most PHONE_CLOSE_SECONDS, so dead phones never hold up the Mac."""
        phones, self.phones = list(self.phones), set()
        await asyncio.gather(*(ws.close() for ws in phones), return_exceptions=True)


async def reply(ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    """Send to one client that may have closed meanwhile (aiohttp raises ConnectionError, or
    RuntimeError for a socket already closing)."""
    try:
        await ws.send_json(message)
    except (ConnectionError, RuntimeError):
        pass


Handler = Callable[[Session, web.WebSocketResponse, dict[str, Any]], Awaitable[None]]


async def _ac_get(session: Session, ws: web.WebSocketResponse, _message: dict[str, Any]) -> None:
    """A panel opened: send what is known now and read the AC again."""
    await reply(ws, session.ac.message())
    session.ac.refresh_soon()


async def _ac_set(session: Session, _ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    changes = message.get("changes")
    if not isinstance(changes, dict):
        raise UserError(BAD_MESSAGE)
    session.ac.change(changes)


async def _ac_display(session: Session, _ws: web.WebSocketResponse, _message: dict[str, Any]) -> None:
    await session.ac.toggle_display()


async def _ac_timer(session: Session, _ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    session.ac.set_off_timer(message.get("minutes"))


async def _ac_restore(session: Session, _ws: web.WebSocketResponse, _message: dict[str, Any]) -> None:
    session.ac.restore()


async def _ac_setting(session: Session, _ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    session.ac.set_setting(message.get("name"), message.get("value"))


async def _ac_filter_cleaned(session: Session, _ws: web.WebSocketResponse, _message: dict[str, Any]) -> None:
    session.ac.filter_cleaned()


async def _ac_schedules(session: Session, _ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    session.ac.set_schedules(message.get("entries"))


async def _ac_sleep_curve(session: Session, _ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    session.ac.start_sleep_curve(message.get("minutes"))


async def _ac_phone(session: Session, ws: web.WebSocketResponse, _message: dict[str, Any]) -> None:
    await reply(ws, session.phone.info())


async def _ac_phone_set(session: Session, ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    enabled = message.get("enabled")
    if not isinstance(enabled, bool):
        raise UserError(BAD_MESSAGE)
    await session.phone.set_enabled(enabled)
    await reply(ws, session.phone.info())


async def _ac_phone_reset(session: Session, ws: web.WebSocketResponse, _message: dict[str, Any]) -> None:
    await session.phone.reset_token()
    await reply(ws, session.phone.info())


async def _phone_get(session: Session, ws: web.WebSocketResponse, _message: dict[str, Any]) -> None:
    await reply(ws, phone_view(session.ac.message()))
    session.ac.refresh_soon()


async def _phone_set(session: Session, ws: web.WebSocketResponse, message: dict[str, Any]) -> None:
    """Only the everyday controls, from a phone."""
    changes = message.get("changes")
    if not isinstance(changes, dict) or not changes or not set(changes) <= PHONE_CHANGES:
        raise UserError(BAD_MESSAGE)
    session.ac.change(changes)


HANDLERS: dict[str, Handler] = {
    "ac_get": _ac_get,
    "ac_set": _ac_set,
    "ac_display": _ac_display,
    "ac_timer": _ac_timer,
    "ac_setting": _ac_setting,
    "ac_restore": _ac_restore,
    "ac_filter_cleaned": _ac_filter_cleaned,
    "ac_schedules": _ac_schedules,
    "ac_sleep_curve": _ac_sleep_curve,
    "ac_phone": _ac_phone,
    "ac_phone_set": _ac_phone_set,
    "ac_phone_reset": _ac_phone_reset,
}
# What a phone may ask. Nothing about Breeze's settings, schedules or the phone access itself.
PHONE_HANDLERS: dict[str, Handler] = {
    "ac_get": _phone_get,
    "ac_set": _phone_set,
    "ac_timer": _ac_timer,
}
# These wait on the AC; run them beside the read loop so other buttons keep working.
BACKGROUND_HANDLERS = frozenset({"ac_display"})


async def handle_message(session: Session, ws: web.WebSocketResponse, data: str,
                         handlers: dict[str, Handler] = HANDLERS) -> None:
    try:
        message = json.loads(data)
    except json.JSONDecodeError:
        await reply(ws, {"type": "error", "message": BAD_MESSAGE})
        return
    kind = message.get("type") if isinstance(message, dict) else None
    handler = handlers.get(kind) if isinstance(kind, str) else None
    if handler is None:
        await reply(ws, {"type": "error", "message": BAD_MESSAGE})
        return
    run = run_handler(session, handler, ws, message, kind)
    if kind in BACKGROUND_HANDLERS:
        session.spawn(run)
    else:
        await run


async def run_handler(session: Session, handler: Handler, ws: web.WebSocketResponse,
                      message: dict[str, Any], kind: str) -> None:
    try:
        await handler(session, ws, message)
    except (UserError, ACError) as exc:
        await reply(ws, {"type": "error", "message": str(exc), "for": kind})
    except Exception:
        log.exception("failed to handle a %r message", kind)
        await reply(ws, {"type": "error", "message": "Something went wrong. Try again."})


# ---------------------------------------------------------------- web app

SESSION = web.AppKey("session", Session)
ALLOWED_HOSTS = web.AppKey("allowed_hosts", frozenset)
ALLOWED_ORIGINS = web.AppKey("allowed_origins", frozenset)
TOKEN = web.AppKey("token", str)


@web.middleware
async def local_only(request: web.Request, handler):
    """Reject requests whose Host, Origin or token is not this app's."""
    if request.host not in request.app[ALLOWED_HOSTS]:
        raise web.HTTPForbidden()
    origin = request.headers.get("Origin")
    if origin is not None and origin not in request.app[ALLOWED_ORIGINS]:
        raise web.HTTPForbidden()
    token = request.app[TOKEN]
    # Bytes, so a non-ASCII header is a plain mismatch instead of a TypeError.
    if not token or not hmac.compare_digest(request.headers.get(TOKEN_HEADER, "").encode(), token.encode()):
        raise web.HTTPForbidden()
    return await handler(request)


async def health(_request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def websocket(request: web.Request) -> web.WebSocketResponse:
    session = request.app[SESSION]
    ws = web.WebSocketResponse(heartbeat=HEARTBEAT_SECONDS, max_msg_size=MAX_MESSAGE_BYTES)
    await ws.prepare(request)
    session.clients.add(ws)
    await reply(ws, session.ac.message())
    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                await handle_message(session, ws, msg.data)
    finally:
        session.clients.discard(ws)
    return ws


async def exit_when_parent_dies(parent_pid: int, shutdown: asyncio.Event) -> None:
    """Stop when the Mac app that started us is gone, so no orphan keeps driving the AC."""
    while not shutdown.is_set():
        try:
            os.kill(parent_pid, 0)
        except ProcessLookupError:
            log.info("parent app %s exited, shutting down", parent_pid)
            shutdown.set()
            return
        except PermissionError:
            pass
        await asyncio.sleep(PARENT_CHECK_SECONDS)


async def serve(port: int, token: str, parent_pid: int | None = None) -> None:
    session = Session()
    shutdown = asyncio.Event()
    app = web.Application(middlewares=[local_only])
    app[SESSION] = session
    app[ALLOWED_HOSTS] = frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
    app[ALLOWED_ORIGINS] = frozenset({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})
    app[TOKEN] = token
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", port).start()
    log.info("Breeze helper listening on 127.0.0.1:%s", port)
    session.ac.start()
    await session.phone.start()  # only if the user turned it on
    watchdog = asyncio.create_task(exit_when_parent_dies(parent_pid, shutdown)) if parent_pid else None
    try:
        await shutdown.wait()
    finally:
        if watchdog:
            watchdog.cancel()
        await session.phone.stop()
        await session.ac.close()
        await runner.cleanup()
