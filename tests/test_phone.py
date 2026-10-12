"""The phone remote: names only, everyday controls only, and only with the pairing token."""

import asyncio
import json

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import phone
import server
import store
from test_ac import online_session

NEVER_ON_A_PHONE = ("settings", "schedules", "events", "health", "sleep_curve", "price_per_kwh", "clean_hours",
                    "filter_hours", "power_w", "today_kwh", "month_kwh", "hourly_kwh", "token", "key", "ip", "id",
                    "compressor_hz", "coil", "fault")


def test_the_phone_view_holds_names_only():
    view = phone.phone_view(online_session().message())
    assert set(view) <= set(phone.PHONE_KEYS)
    assert not set(view) & set(NEVER_ON_A_PHONE)
    assert view["target"] == 16.0 and view["modes"] == ["auto", "cool", "dry", "fan"]


class Socket:
    def __init__(self):
        self.sent = []

    async def send_json(self, message):
        self.sent.append(message)


def phone_says(session, payload):
    ws = Socket()
    asyncio.run(server.handle_message(session, ws, json.dumps(payload), server.PHONE_HANDLERS))
    return ws.sent


def phone_session():
    session = server.Session()
    session.ac = online_session()
    session.ac._kick = lambda: None
    return session


def test_a_phone_cannot_reach_settings_schedules_or_the_phone_access():
    session = phone_session()
    for kind in ("ac_setting", "ac_schedules", "ac_sleep_curve", "ac_restore", "ac_filter_cleaned", "ac_display",
                 "ac_phone", "ac_phone_set", "ac_phone_reset"):
        assert phone_says(session, {"type": kind, "enabled": True})[0]["message"] == server.BAD_MESSAGE


def test_a_phone_may_only_use_the_everyday_controls():
    session = phone_session()
    assert phone_says(session, {"type": "ac_set", "changes": {"louver_v": "1"}})[0]["message"] == server.BAD_MESSAGE
    assert phone_says(session, {"type": "ac_set", "changes": {}})[0]["message"] == server.BAD_MESSAGE
    assert phone_says(session, {"type": "ac_set", "changes": {"target": 20}}) == []
    assert session.ac._pending == {"target": 20.0}


def test_a_broadcast_reaches_a_phone_as_its_view():
    session = phone_session()
    mac, handset = Socket(), Socket()
    session.clients.add(mac)
    session.phones.add(handset)
    message = session.ac.message()
    asyncio.run(session.broadcast(message))
    assert mac.sent == [message]
    assert handset.sent == [phone.phone_view(message)] and "settings" not in handset.sent[0]


def test_turning_it_on_makes_a_new_code_and_off_closes_phones(monkeypatch):
    closed = []

    async def close():
        closed.append(True)

    async def run():
        access = phone.PhoneAccess(run_socket=None, close_phones=close)
        monkeypatch.setattr(access, "start", lambda: asyncio.sleep(0))
        await access.set_enabled(True)
        first = access.token
        await access.set_enabled(False)
        await access.set_enabled(True)
        return first, access.token, store.read_json_dict(store.PHONE_FILE)
    first, second, saved = asyncio.run(run())
    assert first and second and first != second and saved == {"enabled": True, "token": second}
    assert closed == [True]


def gate(path, host_ok=True, origin=None):
    async def run():
        access = phone.PhoneAccess(run_socket=None, close_phones=lambda: asyncio.sleep(0))
        access.token = "pairing-code"
        app = web.Application(middlewares=[access._guard])
        app.router.add_get("/check", access._check)
        async with TestClient(TestServer(app, host="127.0.0.1")) as client:
            port = client.server.port
            allowed = {f"127.0.0.1:{port}"} if host_ok else {"elsewhere:1"}
            access._allowed_hosts = lambda: allowed
            headers = {"Origin": origin} if origin else {}
            response = await client.get(path, headers=headers)
            return response.status, response.headers.get("Content-Security-Policy")
    return asyncio.run(run())


def test_the_pairing_code_host_and_origin_are_checked():
    assert gate("/check?t=pairing-code")[0] == 204
    assert gate("/check?t=wrong")[0] == 403
    assert gate("/check")[0] == 403
    assert gate("/check?t=pairing-code", host_ok=False)[0] == 403
    assert gate("/check?t=pairing-code", origin="https://evil.example")[0] == 403
    assert "frame-ancestors 'none'" in gate("/check?t=wrong")[1]  # hardened even when refused


def test_a_bad_phone_file_means_off():
    store.write_private(store.PHONE_FILE, {"enabled": True, "token": 5})
    access = phone.PhoneAccess(run_socket=None, close_phones=None)
    assert access.enabled is False and access.token is None
