"""Phone remote: the everyday air conditioner controls as a web page for phones on the same Wi-Fi.

Off until the user turns it on in the Mac app. Then a second server listens on the LAN port and
serves the page. Every request that does anything must carry the pairing token, which only the
QR code in the Mac app shows. Host and Origin are checked, so a website cannot reach it through
the phone's browser by DNS rebinding. Plain HTTP on the home network: the token travels
unencrypted on the Wi-Fi, which is the same trust the AC's own protocol gets there.

Phones get a short list of names (see PHONE_KEYS), never Breeze's settings, schedules, energy,
events or anything about the link to the AC, and may only use the everyday controls.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import secrets
import socket
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiohttp import web

import store

PHONE_PORT = 8768  # one above the helper's own port (8767, see build-app.sh), clear of it
PAGE_DIR = Path(__file__).parent / "phone"
TOKEN_BYTES = 24
# The LAN address is looked up again after this long, in case the Mac moved networks.
ADDRESS_CACHE_SECONDS = 30
SHUTDOWN_SECONDS = 2.0
# The Mac's Wi-Fi and Ethernet ports, asked first: the default route may be a VPN a phone cannot reach.
LAN_INTERFACES = ("en0", "en1")

# All a phone ever sees.
PHONE_KEYS = ("type", "status", "notice", "notice_id", "power", "mode", "target", "indoor", "outdoor", "fan", "swing",
              "eco", "turbo", "sleep", "cleaning", "phase", "min", "max", "modes", "fans", "swings", "has_eco",
              "has_turbo", "timer_choices", "off_in")
# All a phone may change.
PHONE_CHANGES = frozenset({"power", "target", "mode", "fan", "swing", "eco", "turbo", "sleep"})

log = logging.getLogger("breeze.phone")

SocketRunner = Callable[[web.Request], Awaitable[web.WebSocketResponse]]


def phone_view(message: dict[str, Any]) -> dict[str, Any]:
    """The phone's copy of an AC message: only the names in PHONE_KEYS."""
    return {key: message[key] for key in PHONE_KEYS if key in message}


def interface_addresses() -> list[str]:
    """IPv4 addresses of the Mac's Wi-Fi and Ethernet ports, in LAN_INTERFACES order."""
    found = []
    for name in LAN_INTERFACES:
        try:
            out = subprocess.run(["/usr/sbin/ipconfig", "getifaddr", name], capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            continue
        address = out.stdout.strip()
        if out.returncode == 0 and address and address not in found:
            found.append(address)
    return found


def lan_address() -> str | None:
    """The Mac's address on the local network (the interface that would reach the internet)."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # TEST-NET address: picks a route, sends nothing
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


class PhoneAccess:
    """Turns the phone server on and off and owns its pairing token."""

    def __init__(self, run_socket: SocketRunner, close_phones: Callable[[], Awaitable[None]]) -> None:
        self._run_socket = run_socket
        self._close_phones = close_phones
        self._runner: web.AppRunner | None = None
        self._addresses: list[str] = []  # the first goes in the QR code
        self._address_checked = 0.0
        # Turning on, off and forgetting run one at a time, so the server never outlives "off".
        self._switching = asyncio.Lock()
        settings = store.read_json_dict(store.PHONE_FILE)
        token = settings.get("token")
        self.token: str | None = token if isinstance(token, str) and token else None
        self.enabled = settings.get("enabled") is True and self.token is not None

    def _save(self) -> None:
        store.write_private(store.PHONE_FILE, {"enabled": self.enabled, "token": self.token})

    # ------------------------------------------------------------ control

    async def set_enabled(self, enabled: bool) -> None:
        async with self._switching:
            if enabled and not self.enabled:
                # A fresh code every time it is turned on, so turning it off really locks old phones out.
                self.token = secrets.token_urlsafe(TOKEN_BYTES)
            self.enabled = enabled
            self._save()
            if enabled:
                await self._start()
            else:
                await self._stop()

    async def reset_token(self) -> None:
        """Forget every paired phone: a new token, and open phone pages drop off."""
        async with self._switching:
            self.token = secrets.token_urlsafe(TOKEN_BYTES)
            self._save()
            if self._runner:
                await self._stop()
                await self._start()

    async def start(self) -> None:
        async with self._switching:
            await self._start()

    async def stop(self) -> None:
        async with self._switching:
            await self._stop()

    def info(self) -> dict[str, Any]:
        """For the Mac app only: never sent to phones, since it holds the token."""
        addresses = self._current_addresses()
        address = addresses[0] if addresses else None
        # The token stays in the address: Home Screen apps keep their own storage, the address survives.
        url = f"http://{address}:{PHONE_PORT}/?t={self.token}" if self.enabled and address and self.token else None
        return {"type": "phone", "enabled": self.enabled, "running": self._runner is not None, "url": url}

    async def _start(self) -> None:
        if self._runner or not self.enabled:
            return
        app = web.Application(middlewares=[self._guard])
        app.router.add_get("/", self._page("index.html", "text/html"))
        app.router.add_get("/app.js", self._page("app.js", "text/javascript"))
        app.router.add_get("/style.css", self._page("style.css", "text/css"))
        app.router.add_get("/manifest.webmanifest", self._manifest)
        app.router.add_get("/ws", self._socket)
        app.router.add_get("/check", self._check)
        runner = web.AppRunner(app, access_log=None, shutdown_timeout=SHUTDOWN_SECONDS)
        await runner.setup()
        try:
            # All interfaces, so a changed Wi-Fi address keeps working; the Host check and token gate it.
            await web.TCPSite(runner, "0.0.0.0", PHONE_PORT).start()
        except OSError as exc:
            log.warning("phone remote could not listen on port %s: %s", PHONE_PORT, type(exc).__name__)
            await runner.cleanup()
            return
        self._runner = runner
        log.info("phone remote on port %s", PHONE_PORT)

    async def _stop(self) -> None:
        # Close open phone pages first: a revoked phone must lose control now.
        await self._close_phones()
        if self._runner:
            await self._runner.cleanup()
            self._runner = None

    # ------------------------------------------------------------ requests

    def _current_addresses(self) -> list[str]:
        if time.monotonic() - self._address_checked > ADDRESS_CACHE_SECONDS:
            found = interface_addresses()
            routed = lan_address()
            if routed and routed not in found:
                found.append(routed)
            self._addresses = found
            self._address_checked = time.monotonic()
        return self._addresses

    def _allowed_hosts(self) -> set[str]:
        local = socket.gethostname()
        hosts = {f"{local}:{PHONE_PORT}"}
        if not local.endswith(".local"):
            hosts.add(f"{local}.local:{PHONE_PORT}")
        for address in self._current_addresses():
            hosts.add(f"{address}:{PHONE_PORT}")
        return {host.lower() for host in hosts}

    @web.middleware
    async def _guard(self, request: web.Request, handler):
        try:
            hosts = self._allowed_hosts()
            if (request.host or "").lower() not in hosts:
                raise web.HTTPForbidden()
            origin = request.headers.get("Origin")
            if origin is not None and origin.lower() not in {f"http://{host}" for host in hosts}:
                raise web.HTTPForbidden()
            response = await handler(request)
        except web.HTTPException as error:
            self._harden(error)
            raise
        self._harden(response)
        return response

    @staticmethod
    def _harden(response: web.StreamResponse) -> None:
        if response.prepared:
            return  # a WebSocket upgrade has already sent its headers
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'")

    @staticmethod
    def _page(name: str, content_type: str):
        path = PAGE_DIR / name

        async def handler(_request: web.Request) -> web.StreamResponse:
            if not path.is_file():
                raise web.HTTPNotFound()
            return web.FileResponse(path, headers={"Content-Type": content_type})

        return handler

    def token_ok(self, offered: str) -> bool:
        # Bytes, so a non-ASCII value is a plain mismatch instead of a TypeError.
        return bool(self.token) and hmac.compare_digest(offered.encode(), (self.token or "").encode())

    async def _manifest(self, request: web.Request) -> web.Response:
        """The Home Screen app starts at the manifest's start_url, so that has to carry the token."""
        offered = request.query.get("t", "")
        start = f"/?t={offered}" if self.token_ok(offered) else "/"
        manifest = {"name": "Breeze", "short_name": "Breeze", "description": "Air conditioner remote",
                    "start_url": start, "scope": "/", "display": "standalone", "orientation": "portrait",
                    "background_color": "#0d1428", "theme_color": "#0d1428"}
        return web.json_response(manifest, content_type="application/manifest+json")

    async def _check(self, request: web.Request) -> web.Response:
        """Lets the page tell a forgotten phone (403) from a Mac that is asleep (no answer)."""
        return web.Response(status=204 if self.token_ok(request.query.get("t", "")) else 403)

    async def _socket(self, request: web.Request) -> web.WebSocketResponse:
        if not self.token_ok(request.query.get("t", "")):
            raise web.HTTPForbidden()
        return await self._run_socket(request)
